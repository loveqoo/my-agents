"""스펙 041 통합 검증 — /chat 전 경로의 HIL 글루(실 HTTP·실 DB·실 체크포인터).

verify_041은 게이트 *시맨틱*(interrupt 전 무부수효과, approve→1회 실행, reject→무실행)을
실 build_tools로 증명했다. 이 프로브는 그 위의 **chat.py 통합 글루**를 증명한다:
  POST /agents/{pk}/chat → event_stream의 stream_mode 튜플 파싱 + __interrupt__ 감지
    → _create_approval(런타임 Approval pending row) → "⏸ 승인 대기" 프레임(정상 영속 안 함)
  POST /approvals/{apid}/resolve(admin) → 원자적 status 가드 → resume_approval
    → 같은 thread_id 체크포인트에서 그래프 재구축·재개 → 최종 답변 원 세션 영속.

모델만 결정적 스텁(api.chat.build_agent를 monkeypatch). **체크포인터는 실 AsyncPostgresSaver**
(durable 경로 그대로). 시드 에이전트 agt_rvw_2b91c4(mcps=github → merge_pr 게이트)를 태운다.

**스펙 046 이후**: 순수 웹 에이전트 플랫폼으로 정리하며 github/kubernetes MCP와
agt_rvw_2b91c4(Code Reviewer)를 카탈로그에서 제거했다. 따라서 이 통합 시나리오는 더 이상
*시드되지 않는다* — HIL 게이트 메커니즘은 runtime 정책(_APPROVAL_ACTIONS)으로 보존되나,
이를 발화시킬 빌딩블록(위험 도구)이 카탈로그에 없다. 단위 게이트 시맨틱은 tests/verify_041이
계속 green으로 지킨다. 이 프로브는 트리거 빌딩블록(github MCP + 그를 wiring한 에이전트)이
존재하는 DB(046 이전, 또는 미래에 admin 승인이 필요한 웹 액션이 추가된 상태)에서만 동작하며,
없으면 크래시 대신 SKIP한다.

ScriptedModel: 메시지에 ToolMessage가 있으면 최종답, 없으면 merge_pr 호출 — 재개 시 새 모델
인스턴스여도 도구 재호출 무한루프를 피하고 실 LLM 행동을 모사한다(글루 검증의 핵심 안전장치).

실행: uv run python .dev/probe_041_chat_integration.py
"""

import asyncio
import json
import os
import sys

os.environ["ADMIN_EMAIL"] = "admin041i@example.com"
os.environ["ADMIN_PASSWORD"] = "Admin041i!pw"
os.environ["AUTH_COOKIE_SECURE"] = "false"  # 평문 ASGITransport에서 쿠키 흐르게(하니스 한정)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))
sys.path.insert(0, os.path.join(ROOT, "packages", "agent", "src"))

import httpx  # noqa: E402
from httpx import ASGITransport  # noqa: E402
from langchain_core.messages import AIMessage, ToolMessage  # noqa: E402
from langchain_core.language_models.chat_models import BaseChatModel  # noqa: E402
from langchain_core.outputs import ChatGeneration, ChatResult  # noqa: E402
from langgraph.prebuilt import create_react_agent  # noqa: E402
from sqlalchemy import select  # noqa: E402

from api import chat as chat_mod  # noqa: E402
from api import runtime  # noqa: E402
from api.db import SessionLocal  # noqa: E402
from api.main import app, lifespan  # noqa: E402
from api.models import Agent, Approval, McpServer, Message, Session  # noqa: E402

_fails: list[str] = []
MERGE = runtime._safe_name("github", "merge_pr")


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


class ScriptedModel(BaseChatModel):
    """ToolMessage 있으면 최종답, 없으면 merge_pr 호출. 재개(새 인스턴스)에도 안전."""

    @property
    def _llm_type(self):
        return "scripted-int"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        has_tool_result = any(isinstance(m, ToolMessage) for m in messages)
        if has_tool_result:
            msg = AIMessage(content="머지를 완료했습니다.")
        else:
            msg = AIMessage(
                content="", tool_calls=[{"name": MERGE, "args": {"query": "merge PR"}, "id": "ci1"}]
            )
        return ChatResult(generations=[ChatGeneration(message=msg)])


class MultiGatedModel(BaseChatModel):
    """한 AIMessage에 merge_pr를 두 번 호출 — 다중 pending interrupt 유발(Finding 1 floor 검증)."""

    @property
    def _llm_type(self):
        return "scripted-multi"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        if any(isinstance(m, ToolMessage) for m in messages):
            msg = AIMessage(content="끝.")
        else:
            msg = AIMessage(
                content="",
                tool_calls=[
                    {"name": MERGE, "args": {"query": "merge A"}, "id": "m1"},
                    {"name": MERGE, "args": {"query": "merge B"}, "id": "m2"},
                ],
            )
        return ChatResult(generations=[ChatGeneration(message=msg)])


def _fake_build_agent(persona, params, tools, model_cfg, checkpointer=None):
    return create_react_agent(
        ScriptedModel(), tools=tools or [], prompt=persona, checkpointer=checkpointer
    )


def _multi_build_agent(persona, params, tools, model_cfg, checkpointer=None):
    return create_react_agent(
        MultiGatedModel(), tools=tools or [], prompt=persona, checkpointer=checkpointer
    )


async def _sse_post(client, url, payload):
    """SSE 응답 본문을 모아 data 프레임 리스트로 파싱."""
    frames = []
    async with client.stream("POST", url, json=payload) as resp:
        status = resp.status_code
        async for line in resp.aiter_lines():
            if line.startswith("data:"):
                body = line[5:].lstrip()
                if body == "[DONE]":
                    continue
                try:
                    frames.append(json.loads(body))
                except json.JSONDecodeError:
                    pass
    return status, frames


async def _ensure_gated_tools_wired():
    """게이트 도구(merge_pr·scale)를 github/kubernetes enabled_tools에 가산(없을 때만).

    dev DB가 seed.py에 위험도구가 추가되기 전 상태로 시드돼 있으면 게이트가 발동하지 않는다
    (seed는 _empty일 때만 적용 — 기존 DB 미반영). 의도된 시드와 일치시키는 비파괴 가산이며,
    이 자체가 '기존 DB는 재시드/마이그레이션 필요'(스펙 041 §7 빚)를 드러낸다."""
    want = {"github": "merge_pr", "kubernetes": "scale"}
    async with SessionLocal() as db:
        rows = (
            await db.execute(select(McpServer).where(McpServer.name.in_(list(want))))
        ).scalars().all()
        for r in rows:
            tool = want[r.name]
            changed = False
            if tool not in (r.tools or []):
                r.tools = [*(r.tools or []), tool]
                changed = True
            if tool not in (r.enabled_tools or []):
                r.enabled_tools = [*(r.enabled_tools or []), tool]
                changed = True
            if changed:
                print(f"  setup: {r.name}.enabled_tools += {tool} (stale 시드 보정)")
        await db.commit()


async def _count_approvals():
    async with SessionLocal() as db:
        from sqlalchemy import func
        return await db.scalar(select(func.count()).select_from(Approval))


async def _agent_pk():
    """트리거 에이전트 pk 또는 None(046 이후 제거됐을 수 있음 → 호출부가 SKIP)."""
    async with SessionLocal() as db:
        a = (
            await db.execute(select(Agent).where(Agent.agent_id == "agt_rvw_2b91c4"))
        ).scalar_one_or_none()
        return a.id if a else None


async def _github_merge_wired() -> bool:
    """github MCP가 카탈로그에 있고 merge_pr를 노출하는가(게이트 트리거 가능 조건)."""
    async with SessionLocal() as db:
        r = (
            await db.execute(select(McpServer).where(McpServer.name == "github"))
        ).scalar_one_or_none()
        return bool(r and "merge_pr" in (r.enabled_tools or []))


async def _approval(apid):
    async with SessionLocal() as db:
        return (
            await db.execute(select(Approval).where(Approval.approval_id == apid))
        ).scalar_one_or_none()


async def _session_msgs(session_str_id):
    async with SessionLocal() as db:
        s = (
            await db.execute(select(Session).where(Session.session_id == session_str_id))
        ).scalar_one_or_none()
        if s is None:
            return []
        rows = (
            await db.execute(select(Message).where(Message.session_pk == s.id))
        ).scalars().all()
        return [(m.role, m.content) for m in rows]


async def chat_until_pause(client, pk):
    """chat → interrupt(approval). resolve는 하지 않음(pause 시점 상태 검사용). (apid, sid, pause, cstat)."""
    cstat, frames = await _sse_post(
        client, f"/agents/{pk}/chat", {"messages": [{"role": "user", "content": "PR 482 머지해줘"}]}
    )
    sid = next((f["session"] for f in frames if "session" in f), None)
    apid = next((f["approval"] for f in frames if "approval" in f), None)
    pause = " ".join(f.get("text", "") for f in frames)
    return apid, sid, pause, cstat


async def main():
    chat_mod.build_agent = _fake_build_agent  # 모델만 결정적 스텁(체크포인터·도구·글루는 실코드)
    async with lifespan(app):
        ckpt = chat_mod.checkpointer.get_checkpointer()
        check(ckpt is not None, "전제: 실 AsyncPostgresSaver 체크포인터 활성(durable 경로)")
        await _ensure_gated_tools_wired()
        pk = await _agent_pk()
        if pk is None or not await _github_merge_wired():
            print(
                "SKIP: 스펙 046 이후 github MCP·agt_rvw_2b91c4(위험도구 트리거)가 카탈로그에서\n"
                "      제거되어 이 라이브-DB HIL 통합 시나리오는 더 이상 시드되지 않습니다.\n"
                "      게이트 메커니즘은 runtime._APPROVAL_ACTIONS 정책으로 보존되며, 단위\n"
                "      시맨틱은 tests/verify_041_hil_approval_gating.py가 계속 검증합니다."
            )
            return
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            sc = await ac.post(
                "/auth/login",
                data={"username": "admin041i@example.com", "password": "Admin041i!pw"},
            )
            check(sc.status_code == 204, f"admin 로그인 204 (got {sc.status_code})")

            # --- approve 경로: pause 시점 상태를 resolve 전에 정확히 검사 ---
            apid, sid, pause, cstat = await chat_until_pause(ac, pk)
            check(cstat == 200, f"chat 200 (got {cstat})")
            check(apid is not None, "chat: 위험도구 호출 → __interrupt__ 감지 → approval id 발급")
            check("승인 대기" in pause, "chat: '⏸ 승인 대기' 프레임 emit")
            ap = await _approval(apid) if apid else None
            check(
                ap is not None and ap.status == "pending" and ap.permission == "repo.merge",
                "pause: 런타임 Approval(pending, repo.merge) row 생성",
            )
            check(
                ap is not None and ap.checkpoint and ":" in ap.checkpoint,
                "pause: checkpoint=thread_id 재개키 박힘",
            )
            # pause 시점엔 정상 영속 안 함(이 턴 최종답변 미영속 — interrupt 전 무부수효과).
            msgs_at_pause = await _session_msgs(sid)
            check(
                all("머지를 완료" not in c for _, c in msgs_at_pause),
                "pause: 승인 전 최종답변 미영속(interrupt 전 무부수효과)",
            )
            # 이제 resolve(approve) → 재개·영속.
            r = await ac.post(f"/approvals/{apid}/resolve", json={"decision": "approve"})
            check(r.status_code == 200, f"resolve(approve) admin 200 (got {r.status_code})")
            ap2 = await _approval(apid)
            check(ap2 is not None and ap2.status == "approved", "resolve: status=approved")
            msgs_after = await _session_msgs(sid)
            check(
                any("머지를 완료" in c for role, c in msgs_after if role == "assistant"),
                "resume: 재개 그래프가 도구 실행 후 최종답변을 원 세션에 영속",
            )

            # --- reject 경로(글루: 재개가 status=rejected에서도 깨지지 않음) ---
            apid_r, sid_r, pause_r, _ = await chat_until_pause(ac, pk)
            check(apid_r is not None, "reject: 두번째 chat도 interrupt → approval 발급")
            rr = await ac.post(f"/approvals/{apid_r}/resolve", json={"decision": "reject"})
            check(rr.status_code == 200, f"resolve(reject) admin 200 (got {rr.status_code})")
            apr = await _approval(apid_r)
            check(apr is not None and apr.status == "rejected", "reject: status=rejected")

            # --- 이중 resolve 가드(원자적): 같은 approval 재처리는 409 ---
            r2 = await ac.post(f"/approvals/{apid}/resolve", json={"decision": "approve"})
            check(r2.status_code == 409, f"이중 resolve → 409 가드 (got {r2.status_code})")

            # --- Finding 1 floor: 한 턴 다중 게이트 도구 → 에러 종료 + approval 미생성(오도 row 0) ---
            chat_mod.build_agent = _multi_build_agent
            before = await _count_approvals()
            _, frames_m = await _sse_post(
                ac, f"/agents/{pk}/chat", {"messages": [{"role": "user", "content": "둘 다 머지"}]}
            )
            after = await _count_approvals()
            err_m = " ".join(f.get("error", "") for f in frames_m)
            has_approval_frame = any("approval" in f for f in frames_m)
            check("둘 이상" in err_m, "Finding1: 다중 게이트 → 명시적 에러 프레임")
            check(not has_approval_frame, "Finding1: 다중 게이트 → approval 프레임 미emit")
            check(after == before, f"Finding1: 다중 게이트 → Approval row 미생성(오도 approved 방지) ({before}→{after})")
            chat_mod.build_agent = _fake_build_agent

    print()
    if _fails:
        print(f"❌ {len(_fails)} FAIL")
        for f in _fails:
            print("   -", f)
        sys.exit(1)
    print("✅ 스펙 041 chat 통합 글루 전부 통과(interrupt 감지·approval·재개·영속·이중가드)")


asyncio.run(main())

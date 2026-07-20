"""verify_415 — 첨부 후속 경화(스펙 415: 404 codex 잔여 3축).

  E1 전역 body limit(P1): 3MB JSON → 413(Content-Length 선검사) · chunked(무 Content-Length)
     3MB → 413(raw 누적 실측) · 정상 요청 무영향 · 업로드 라우트는 6MB 상한(5MB 파일 통과).
  E2 턴 예산(P2): messages 201개 → 422 · content 15만자 초과 → 422 · 현재 턴 유저 입력 5만자
     초과 → 422(스키마 아닌 chat 입구) · 경계값(5만자 정확) 통과.
  E3 업로드 rate limit(P3): 분당 10회 — 11회째 429 · 한국어 사유.
  E4 첨부 유래 승인 강제(P4) 단위: 강제 payload 형태 · 그래프 지문이 attachment_context로 갈라짐
     (캐시 분리) · 브로커 _gate가 정책 없는 MCP/agent cap에 payload 합성(RAG는 면제) ·
     Approval args에 _attachment_context 스탬프.
  E5 첨부 컨텍스트 판정: 이번 턴 첨부 or 대화 펜스 마커(재생 구멍 폐쇄).

실행: uv run python tests/_throwaway_server.py tests/verify_415_attachment_hardening.py
"""

import asyncio
import json
import os
import pathlib
import sys
import uuid

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "packages" / "api" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "agent" / "src"))

import httpx  # noqa: E402

BASE = os.environ.get("VERIFY_BASE", "http://127.0.0.1:8000")

_fails: list[str] = []
passed = 0


def check(cond: bool, msg: str) -> None:
    global passed
    print(("  ok  " if cond else " FAIL ") + msg)
    if cond:
        passed += 1
    else:
        _fails.append(msg)


def _auth() -> dict:
    from api.auth import _token

    return {"Authorization": f"Bearer {_token()}"}


async def _e1_body_limit(c: httpx.AsyncClient) -> None:
    print("== E1 전역 body limit(P1) ==")
    big = "x" * (3 * 1024 * 1024)
    # (a) Content-Length 선검사 — httpx는 CL을 자동 설정.
    r = await c.post("/agents", json={"name": "v415", "config": {"note": big}})
    check(r.status_code == 413, f"E1a 3MB JSON → 413 (got {r.status_code})")
    check("본문이 너무" in r.text, "E1b 한국어 사유(2MB 상한 안내)")

    # (b) chunked(무 Content-Length) — raw 누적 실측 경로.
    async def _gen():  # noqa: ANN202
        chunk = b"y" * 65536
        for _ in range(3 * 1024 * 1024 // 65536 + 1):
            yield chunk

    try:
        # httpx는 제너레이터 content면 Content-Length 없이 chunked로 보낸다(수동 헤더 지정 금지 —
        # 자동 chunked와 충돌해 서버 400). 선검사가 못 보는 경로 → raw 누적 실측이 잡아야 한다.
        r = await c.post(
            "/agents", content=_gen(), headers={"content-type": "application/json"}
        )
        check(r.status_code == 413, f"E1c chunked 3MB → 413(실측) (got {r.status_code})")
    except (httpx.WriteError, httpx.RemoteProtocolError):
        # 서버가 수신 중단(캡 초과 즉시 응답) 시 클라이언트 write가 끊길 수 있음 — 캡 동작의 방증.
        check(True, "E1c chunked 3MB → 서버 수신 중단(캡 동작)")

    # (c) 정상 요청 무영향.
    r = await c.get("/agents")
    check(r.status_code == 200, f"E1d 정상 요청 무영향 (got {r.status_code})")

    # (d) 업로드 라우트 상한 6MB — 5MB 파일이 미들웨어를 통과(엔드포인트 캡이 관할).
    five = b"z" * (5 * 1024 * 1024 - 1024)
    r = await c.post("/chat/attachments", files={"file": ("big.txt", five, "text/plain")})
    check(
        r.status_code == 200,
        f"E1e 업로드 5MB는 미들웨어 통과(6MB 상한) → 추출 200 (got {r.status_code})",
    )
    seven = b"z" * (6 * 1024 * 1024 + 1024)
    r = await c.post("/chat/attachments", files={"file": ("huge.txt", seven, "text/plain")})
    check(r.status_code == 413, f"E1f 업로드 6MB 초과 → 413 (got {r.status_code})")


async def _e2_turn_budget(c: httpx.AsyncClient, aid: str) -> None:
    print("== E2 턴 예산(P2) ==")
    msgs = [{"role": "user", "content": f"m{i}"} for i in range(201)]
    r = await c.post(f"/agents/{aid}/chat", json={"messages": msgs})
    check(r.status_code == 422, f"E2a messages 201개 → 422 (got {r.status_code})")

    r = await c.post(
        f"/agents/{aid}/chat",
        json={"messages": [{"role": "user", "content": "y" * 150_001}]},
    )
    check(r.status_code == 422, f"E2b content 15만자 초과 → 422(스키마) (got {r.status_code})")

    r = await c.post(
        f"/agents/{aid}/chat",
        json={"messages": [{"role": "user", "content": "y" * 50_001}]},
    )
    check(r.status_code == 422, f"E2c 현재 턴 유저 입력 5만자 초과 → 422 (got {r.status_code})")
    check("5만자" in r.text, "E2d 한국어 사유(5만자 안내)")

    body = {"messages": [{"role": "user", "content": "y" * 50_000}]}
    async with c.stream("POST", f"/agents/{aid}/chat", json=body) as resp:
        check(resp.status_code == 200, f"E2e 경계값 5만자 정확 → 200 (got {resp.status_code})")
        async for _line in resp.aiter_lines():
            pass  # 스트림 소진(연결 정리)

    # E2f(codex P2): 끝에 assistant를 붙여 "마지막 위치" 검사를 우회하던 구멍 — 마지막 user로 검사.
    r = await c.post(
        f"/agents/{aid}/chat",
        json={
            "messages": [
                {"role": "user", "content": "y" * 50_001},
                {"role": "assistant", "content": "x"},
            ]
        },
    )
    check(
        r.status_code == 422,
        f"E2f assistant-last 뒤 user 5만자 초과 → 422(우회 봉합) (got {r.status_code})",
    )


async def _e3_rate_limit(c: httpx.AsyncClient) -> None:
    print("== E3 업로드 rate limit(P3) ==")
    # E1에서 이미 2회 사용 — 남은 윈도를 소진해 11회째 429 확인.
    last = None
    got_429 = False
    for _i in range(12):
        r = await c.post(
            "/chat/attachments", files={"file": ("r.txt", b"rate probe", "text/plain")}
        )
        last = r.status_code
        if r.status_code == 429:
            got_429 = True
            check("업로드가 너무" in r.text, "E3b 한국어 사유(분당 10회 안내)")
            break
    check(got_429, f"E3a 연속 업로드 → 429 도달 (last {last})")


def _e4_unit() -> None:
    print("== E4 승인 강제(P4) 단위 ==")
    from api.chat_context_types import ChatContext
    from api.chat_graph_build import _graph_fingerprint
    from api.runtime_mcp import forced_attachment_approval

    fa = forced_attachment_approval("mcp.srv.tool")
    check(
        fa["approver"] == "self" and fa["forced"] == "attachment" and fa["permission"],
        f"E4a 강제 payload 형태(self·forced=attachment) (got {fa})",
    )

    # 그래프 지문 분리 — 첨부 턴/비첨부 턴이 같은 캐시를 쓰면 강제가 조용히 우회된다.
    base = {
        "agent_pk": uuid.uuid4(),
        "model_cfg": {"base_url": "http://x", "model_id": "m", "api_key": ""},
    }
    c1 = ChatContext(**base)
    c2 = ChatContext(**base)
    c2.attachment_context = True
    f1, f2 = _graph_fingerprint(c1), _graph_fingerprint(c2)
    check(
        f1 is not None and f2 is not None and f1 != f2,
        "E4b 그래프 지문이 attachment_context로 갈라짐(캐시 분리)",
    )

    # 브로커 _gate 합성 — 정책 없는 MCP/agent cap은 payload 합성, RAG(읽기 전용)는 면제.
    import api.broker.core as core

    class _FakeProvider:
        def __init__(self, kind: str) -> None:
            self.kind = kind

        def approval_for(self, _row, _cap, _args, _tp=None):  # noqa: ANN001, ANN202
            return None  # 정책 없음(즉시 실행 상태)

    captured: list[dict] = []

    def _fake_interrupt(payload):  # noqa: ANN001, ANN202
        captured.append(payload)
        return {"decision": "approve"}  # 승인으로 재개된 셈 — _gate는 None(전송 진행) 반환

    import langgraph.types as lg_types

    orig = lg_types.interrupt
    lg_types.interrupt = _fake_interrupt
    try:
        broker = core.PolicyScopedBroker(
            ["mcp:srv"], lambda *_a: True, [], force_approval=True
        )
        res = broker._gate(_FakeProvider("mcp"), object(), "mcp:srv/tool", {"x": 1})
        check(
            res is None and len(captured) == 1 and captured[0].get("forced") == "attachment",
            f"E4c MCP cap 정책 없음+강제 → 승인 interrupt 발생 (captured {len(captured)})",
        )
        # codex P1③: 강제 payload에 마스킹된 인자가 실려야("정보에 근거한 승인") — args:{}면 승인자가
        # 무엇을 승인하는지 못 본다. redact를 거치되 구조(키)는 남아야 한다.
        check(
            captured[0].get("args") not in ({}, None) and "x" in (captured[0].get("args") or {}),
            f"E4c' 강제 payload에 마스킹 인자 노출(빈 dict 아님) (got {captured[0].get('args')})",
        )
        res = broker._gate(_FakeProvider("agent"), object(), "agent:sub-agent", {})
        check(len(captured) == 2, "E4d agent 위임 cap도 강제")
        res = broker._gate(_FakeProvider("rag"), object(), "rag:kb", {})
        check(
            res is None and len(captured) == 2,
            "E4e RAG(읽기 전용) cap은 면제(interrupt 미발생)",
        )
        # 강제 꺼짐(비첨부 턴) — 종전 동작.
        broker_off = core.PolicyScopedBroker(["mcp:srv"], lambda *_a: True, [])
        res = broker_off._gate(_FakeProvider("mcp"), object(), "mcp:srv/tool", {})
        check(
            res is None and len(captured) == 2,
            "E4f 비첨부 턴은 종전 동작(정책 없으면 즉시 실행)",
        )
    finally:
        lg_types.interrupt = orig


async def _e4_approval_stamp() -> None:
    print("== E4g Approval 스탬프 ==")
    from sqlalchemy import delete, select

    from api.chat_approval import _create_approval
    from api.chat_context_types import ChatContext
    from api.db import SessionLocal
    from api.models import Agent, Approval

    async with SessionLocal() as s:
        agent_pk = (await s.execute(select(Agent.id).limit(1))).scalar_one()
    ctx = ChatContext(agent_pk=agent_pk)
    ctx.session_id = None
    ctx.attachment_context = True
    apid = await _create_approval(
        ctx, f"v415-{uuid.uuid4().hex[:8]}", {"permission": "p", "args": {"a": 1}}, None
    )
    try:
        async with SessionLocal() as s:
            row = (
                await s.execute(select(Approval).where(Approval.approval_id == apid))
            ).scalar_one()
            check(
                row.args.get("_attachment_context") is True and row.args.get("a") == 1,
                f"E4g 첨부 턴 Approval args 스탬프+원 args 보존 (got {row.args})",
            )
    finally:
        async with SessionLocal() as s:
            await s.execute(delete(Approval).where(Approval.approval_id == apid))
            await s.commit()


async def _e5_context_detection(c: httpx.AsyncClient, aid: str) -> str | None:
    print("== E5 첨부 컨텍스트 판정(재생 구멍) ==")
    # 첨부와 함께 1턴 → 세션에 주입본 영속. 다음 턴(첨부 없음)에 펜스 마커가 히스토리로 재생됨을
    # 서버 영속 메시지로 확인(판정식 "⟦첨부 "가 대화에 존재 → 강제 유지의 근거 데이터).
    body = {
        "messages": [{"role": "user", "content": "첨부 요약"}],
        "attachments": [{"filename": "doc.txt", "text": "V415-MARK 본문"}],
    }
    session_id = None
    async with c.stream("POST", f"/agents/{aid}/chat", json=body) as resp:
        async for line in resp.aiter_lines():
            if line.startswith("data: ") and session_id is None:
                try:
                    obj = json.loads(line[6:])
                    if isinstance(obj, dict) and "session" in obj:
                        session_id = obj["session"]
                except json.JSONDecodeError:
                    pass
    check(session_id is not None, f"E5a 첨부 턴 세션 생성 (got {session_id})")
    from sqlalchemy import select

    from api.chat_history import _load_session_conversation
    from api.db import SessionLocal
    from api.models import Agent

    async with SessionLocal() as s:
        agent_pk = (
            await s.execute(select(Agent.id).where(Agent.id == uuid.UUID(aid)))
        ).scalar_one()
    conv = await _load_session_conversation(session_id, agent_pk)
    has_marker = any("⟦첨부 " in (m.get("content") or "") for m in conv)
    check(has_marker, "E5b 영속 대화에 펜스 마커 — 후속 턴 재생 시 판정식이 참(강제 유지)")
    return session_id


async def _e7_a2a_replay_force(aid: str, session_id: str | None) -> None:
    """codex P1① — A2A 서빙이 영속 첨부(펜스 마커)를 재생할 때 force_approval을 도구 빌드에 넘기나.
    build_mcp_tools를 몽키패치해 force_approval 인자를 포착한다(MCP 서버 불요 — 배선만 검증)."""
    print("== E7 A2A 서빙 재생 승인 강제 배선(codex P1①) ==")
    if session_id is None:
        check(False, "E7 선행 세션(E5) 부재 — 스킵")
        return
    import api.chat_a2a_serve as serve
    import api.runtime as runtime

    captured: dict = {}
    orig = runtime.build_mcp_tools

    async def _spy(servers, calls_sink, tool_policy=None, selected_tools=None, force_approval=False):  # noqa: ANN001, ANN202
        captured["force"] = force_approval
        return await orig(servers, calls_sink, tool_policy, selected_tools, force_approval)

    serve.runtime.build_mcp_tools = _spy  # type: ignore[attr-defined]
    try:
        # 첨부 없는 후속 A2A 턴 — 재생된 세션 대화의 펜스 마커만으로 강제가 켜져야 한다.
        await serve.prepare_serve_turn(
            uuid.UUID(aid), "이전 문서 기반으로 실행해", user_id=None, context_id=session_id
        )
        check(
            captured.get("force") is True,
            f"E7 재생 마커 → A2A 서빙 도구 빌드에 force_approval=True (got {captured.get('force')})",
        )
    finally:
        serve.runtime.build_mcp_tools = orig  # type: ignore[attr-defined]


async def main() -> None:
    async with httpx.AsyncClient(base_url=BASE, headers=_auth(), timeout=180) as c:
        ag = (
            await c.post(
                "/agents",
                json={"name": f"v415-{uuid.uuid4().hex[:6]}", "config": {"model": "mock-llm"}},
            )
        ).json()
        aid = ag["id"]
        try:
            await _e1_body_limit(c)
            await _e2_turn_budget(c, aid)
            await _e3_rate_limit(c)
            _e4_unit()
            await _e4_approval_stamp()
            sid = await _e5_context_detection(c, aid)
            await _e7_a2a_replay_force(aid, sid)
        finally:
            await c.delete(f"/agents/{aid}")

    print()
    if _fails:
        print(f"FAILED: {len(_fails)}건")
        for f in _fails:
            print("  -", f)
        sys.exit(1)
    print(f"VERIFY415_OK — {passed}건 전부 통과")


if __name__ == "__main__":
    asyncio.run(main())

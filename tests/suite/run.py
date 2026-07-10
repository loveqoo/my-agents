"""기능 조합 시나리오 스위트 러너 (스펙 288) — 실모델 전제.

실행: cd packages/api && uv run python ../../tests/suite/run.py [--only 부분키] [--list] [--bootstrap-only]
종료코드: 0=전부 통과 / 1=실패 있음 / 2=사전조건 미충족(실모델·DB·mem0).

원칙(스펙 288): 단언은 기록으로만(trace mcp/toolDiag/brokerCalls/graph·recall·DB 행 실측),
시나리오 독립(각자 새 세션), 실패는 재시도(기본 2회, --retries — 통과 시 flaky로 정직 표기).
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import pathlib
import sys
import time
import uuid

import httpx

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))  # tests/

from suite import fixtures  # noqa: E402
from suite._sse import parse_sse  # noqa: E402
from suite.scenarios import (  # noqa: E402
    NODE_OVERRIDE_ECHO_PROMPT,
    NODE_OVERRIDE_TOKEN,
    SCENARIOS,
)

from api.auth import _token, current_principal  # noqa: E402
from api.main import app  # noqa: E402


class _SuitePrincipal:
    """스위트 principal — user_id(기억 스코프)·세션 소유권이 이 id로 흐른다(fixtures.SUITE_USER와 동일)."""

    id = fixtures.SUITE_USER
    is_superuser = True
    is_active = True
    is_verified = True
    email = "suite-288@local"


app.dependency_overrides[current_principal] = lambda: _SuitePrincipal()

CHAT_TIMEOUT = httpx.Timeout(300.0, connect=10.0)  # 로컬 실모델(수십 B)은 노드형 다턴이 느릴 수 있다


class PreflightError(RuntimeError):
    pass


# ── 단언 어휘 — (res, trace, *args) -> (ok, detail). 전부 기록 기반. ──────────────────────────

def _mcp(trace: dict) -> list[dict]:
    return trace.get("mcp") or []


def _non_rag(trace: dict) -> list[dict]:
    return [e for e in _mcp(trace) if e.get("server") != "rag"]


ASSERTS = {
    "tool_called": lambda res, t, sub, n=1: (
        len([e for e in _non_rag(t) if sub in (e.get("tool") or "")]) >= n,
        f"mcp={[(e.get('server'), e.get('tool')) for e in _mcp(t)]}",
    ),
    "tool_not_called": lambda res, t, sub: (
        not any(sub in (e.get("tool") or "") for e in _non_rag(t)),
        f"mcp={[(e.get('server'), e.get('tool')) for e in _mcp(t)]}",
    ),
    "tools_called_zero": lambda res, t: (
        len(_non_rag(t)) == 0,
        f"mcp={[(e.get('server'), e.get('tool')) for e in _mcp(t)]}",
    ),
    "rag_called": lambda res, t: (
        any(e.get("server") == "rag" for e in _mcp(t)),
        f"mcp={[(e.get('server'), e.get('tool')) for e in _mcp(t)]}",
    ),
    "rag_not_called": lambda res, t: (
        not any(e.get("server") == "rag" for e in _mcp(t)),
        f"mcp={[(e.get('server'), e.get('tool')) for e in _mcp(t)]}",
    ),
    "memory_hit": lambda res, t, token: (
        any(token in str(h) for h in (t.get("memories") or [])),
        f"memories={[str(h)[:80] for h in (t.get('memories') or [])]}",
    ),
    # 노드형 회상(스펙 268 P2) — 노드별 프록시 조회가 trace["memoryRecalls"]({node,query,hits,cached})로
    # 표면화된다(내용 아닌 건수 — 243 마스킹 규약). 비노드형의 memories와 다른 표면.
    "memory_recall_min": lambda res, t, n: (
        any((r.get("hits") or 0) >= n for r in (t.get("memoryRecalls") or [])),
        f"memoryRecalls={t.get('memoryRecalls')}",
    ),
    "memory_absent": lambda res, t: (
        not (t.get("memories") or []) and not t.get("memoryQuery"),
        f"memories={t.get('memories')}, memoryQuery={t.get('memoryQuery')!r}",
    ),
    "broker_min": lambda res, t, n: (
        len(t.get("brokerCalls") or []) >= n,
        f"brokerCalls={t.get('brokerCalls')}",
    ),
    "broker_zero": lambda res, t: (
        not (t.get("brokerCalls") or []),
        f"brokerCalls={t.get('brokerCalls')}",
    ),
    "override_key": lambda res, t, k: (
        k in (t.get("overrides") or {}),
        f"overrides={t.get('overrides')}",
    ),
    "override_absent": lambda res, t: (
        not t.get("overrides"),
        f"overrides={t.get('overrides')}",
    ),
    "graph_node": lambda res, t, name: (
        any(g.get("node") == name for g in (t.get("graph") or [])),
        f"graph={[g.get('node') for g in (t.get('graph') or [])]}",
    ),
    "graph_node_absent": lambda res, t, name: (
        not any(g.get("node") == name for g in (t.get("graph") or [])),
        f"graph={[g.get('node') for g in (t.get('graph') or [])]}",
    ),
    # 히스토리 서버 재구성(스펙 289 P1) — trace.historyRestore {mode, restored, ms}.
    "history_restored_min": lambda res, t, n: (
        (t.get("historyRestore") or {}).get("restored", 0) >= n,
        f"historyRestore={t.get('historyRestore')}",
    ),
    "history_restore_absent": lambda res, t: (
        not t.get("historyRestore"),
        f"historyRestore={t.get('historyRestore')}",
    ),
    # 노드형 대화 창(스펙 270) — 노드가 실제 본 이전 대화 건수(historyWindows[].count).
    "history_window_min": lambda res, t, n: (
        any((w.get("count") or 0) >= n for w in (t.get("historyWindows") or [])),
        f"historyWindows={t.get('historyWindows')}",
    ),
    # 위임 사유(스펙 289 P3) — plan 노드 타임라인 요약(delegationNote)에 "왜 위임 0건"이 남는다.
    "graph_summary_contains": lambda res, t, tok: (
        any(tok in (g.get("summary") or "") for g in (t.get("graph") or [])),
        f"summaries={[(g.get('node'), (g.get('summary') or '')[:60]) for g in (t.get('graph') or []) if g.get('summary')]}",
    ),
    "text_contains": lambda res, t, tok: (tok in res["text"], f"text={res['text'][:160]!r}"),
    "text_not_contains": lambda res, t, tok: (tok not in res["text"], f"text={res['text'][:160]!r}"),
    "text_nonempty": lambda res, t: (
        bool(res["text"].strip()) and not res["error"],
        f"text={res['text'][:80]!r}, error={res['error']!r}",
    ),
}


# ── 프리플라이트 (완료 기준 2 — 미충족이면 무엇이 없는지 말하고 exit 2) ─────────────────────

async def preflight(c: httpx.AsyncClient) -> tuple[dict, dict]:
    r = await c.get("/agents")
    if r.status_code != 200:
        raise PreflightError(f"API/DB 미가용 — GET /agents {r.status_code}")
    try:
        chat_m, embed_m = fixtures.pick_from((await c.get("/models")).json())
    except RuntimeError as e:
        raise PreflightError(str(e)) from e
    # 실모델 서버 생존 핑 — 어떤 HTTP 응답이든(401 포함) 살아있음, 연결 실패만 미가용.
    for base in {chat_m["base_url"], embed_m["base_url"]}:
        try:
            async with httpx.AsyncClient(timeout=5) as h:
                await h.get(base.rstrip("/") + "/models")
        except Exception as e:  # noqa: BLE001
            raise PreflightError(f"실모델 서버 응답 없음: {base} ({type(e).__name__}: {e})") from e
    # mem0 백엔드(회상 시나리오 전제) — recall_diag가 미가용 사유를 구조화해 준다(스펙 125).
    d = (await c.post(f"/memory/user/{fixtures.SUITE_USER}/search", json={"query": "ping"})).json()
    diag = d.get("diag") or {}
    if not (diag.get("configured") and diag.get("backendReady")):
        raise PreflightError(f"기억(mem0) 백엔드 미가용 — diag={diag}")
    return chat_m, embed_m


# ── 데이터 시나리오 실행 ─────────────────────────────────────────────────────────────────

async def run_turns(
    c: httpx.AsyncClient, agent_id: str, turns: list[str], overrides: dict | None,
    history: str = "client",
) -> dict:
    """턴들을 같은 세션으로 잇고 마지막 턴의 파싱 결과를 돌려준다(시나리오 독립 — 세션은 여기서 시작).

    history 모드(스펙 289 P1 양 계약):
    - "client"(기본): 플레이그라운드처럼 **대화 전체를 body.messages로 누적 전송**(assistant 포함
      → 서버는 클라 관리 모드로 판정, 무회귀 축).
    - "server": 외부 연동 클라이언트처럼 **sessionId + 새 메시지만** 전송 — 서버가 DB에서 이전
      대화를 이어붙인다(trace.historyRestore로 실증)."""
    sid: str | None = None
    convo: list[dict] = []
    res: dict = {}
    for turn in turns:
        convo.append({"role": "user", "content": turn})
        body: dict = {"messages": ([{"role": "user", "content": turn}] if history == "server" else convo)}
        if sid:
            body["sessionId"] = sid
        if overrides is not None:
            body["overrides"] = overrides
        r = await c.post(f"/agents/{agent_id}/chat", json=body)
        if r.status_code != 200:
            raise AssertionError(f"HTTP {r.status_code}: {r.text[:200]}")
        res = parse_sse(r.text)
        res["_session"] = sid = res["session"] or sid
        convo.append({"role": "assistant", "content": res["text"]})
    return res


def check_expects(res: dict, expects: list[tuple]) -> list[str]:
    # trace 필수 게이트(codex 288 #1) — trace 프레임이 아예 없으면 부재(absence) 단언들이
    # "관측 없음"을 "안 불렸음"으로 오독해 공허히 통과한다. 부재 단언은 관측 존재가 전제.
    if res.get("trace") is None:
        return [f"trace 프레임 없음 — 단언 불가(공허한 통과 방지). error={res.get('error')!r}"]
    trace = res["trace"]
    fails: list[str] = []
    for exp in expects:
        name, *args = exp
        ok, detail = ASSERTS[name](res, trace, *args)
        if not ok:
            fails.append(f"{name}{tuple(args)} — {detail}")
    return fails


async def run_data_scenario(c: httpx.AsyncClient, fx: dict, sc: dict) -> list[str]:
    agent = fx["agents"][sc["agent"]]
    res = await run_turns(c, agent["id"], sc["turns"], sc.get("overrides"), history=sc.get("history", "client"))
    return check_expects(res, sc["expect"])


# ── 커스텀 시나리오 (데이터 선언로 안 담기는 왕복들) ─────────────────────────────────────

async def custom_approval_roundtrip(c: httpx.AsyncClient, fx: dict) -> list[str]:
    """승인 도구 발동 → Approval 생성 → approve → 재개 턴이 도구를 실제 실행(기록)."""
    agent = fx["agents"]["direct"]
    res = await run_turns(c, agent["id"], ["반드시 delete_record 도구로 레코드 rec-288 을 삭제해줘."], None)
    apid = res.get("approval")
    if isinstance(apid, dict):
        apid = apid.get("id")
    if not apid:
        return [f"approval 프레임 없음 — text={res['text'][:120]!r}, error={res['error']!r}"]
    r = await c.post(f"/approvals/{apid}/resolve", json={"decision": "approve"})
    if r.status_code != 200:
        return [f"resolve HTTP {r.status_code}: {r.text[:200]}"]
    # 재개는 서버가 수행(resume_approval) — 재개 턴의 도구 실행 기록이 세션 메시지 trace에 남는다.
    sid = res.get("_session")
    for _ in range(30):
        msgs = (await c.get(f"/sessions/{sid}/messages")).json()
        for m in msgs:
            t = m.get("trace") or {}
            if any("delete_record" in (e.get("tool") or "") for e in (t.get("mcp") or [])):
                return []
        await asyncio.sleep(1)
    return ["재개 후 delete_record 실행 기록을 세션 메시지 trace에서 찾지 못함(30s)"]


async def custom_ephemeral_db_invariant(c: httpx.AsyncClient, fx: dict) -> list[str]:
    """비영속 채팅 1턴 전후 쓰기 대상 테이블 행 수 불변(verify_235 패턴 — 실측)."""
    from sqlalchemy import text as sql_text

    from api.db import SessionLocal

    tables = ["sessions", "messages", "checkpoints", "checkpoint_writes", "checkpoint_blobs", "approvals"]

    async def counts() -> dict[str, int]:
        async with SessionLocal() as db:
            out = {}
            for t in tables:
                out[t] = int((await db.execute(sql_text(f"SELECT COUNT(*) FROM {t}"))).scalar_one())
            return out

    before = await counts()
    res = await run_turns(c, fx["agents"]["ephemeral"]["id"], ["1 더하기 1은? 숫자만 답해."], None)
    if not res["text"].strip():
        return [f"비영속 응답 없음 — error={res['error']!r}"]
    after = await counts()
    diff = {t: after[t] - before[t] for t in tables if after[t] != before[t]}
    return [f"비영속인데 DB 행 증가: {diff}"] if diff else []


async def custom_ephemeral_approval_refused(c: httpx.AsyncClient, fx: dict) -> list[str]:
    """비영속 + 승인 필요 도구(오버라이드로 배선) → 승인 대기 대신 명시 거부(스펙 237 게이트)."""
    ov = {"tools": [fixtures.TOOL_DELETE, fixtures.TOOL_ECHO], "mcps": ["local-tools"]}
    res = await run_turns(
        c, fx["agents"]["ephemeral"]["id"],
        ["반드시 delete_record 도구로 레코드 rec-1 을 삭제해줘."], ov,
    )
    fails = []
    if res.get("approval"):
        fails.append(f"비영속인데 승인 대기 생성됨: {res['approval']}")
    if not (res.get("error") and "비영속" in str(res["error"])):
        fails.append(f"명시 거부 안내 없음 — error={res['error']!r}, text={res['text'][:120]!r}")
    return fails


async def _stored_nodes(c: httpx.AsyncClient, agent_id: str) -> list[dict]:
    a = (await c.get(f"/agents/{agent_id}")).json()
    nodes = a.get("nodes") or []
    if not nodes:
        raise AssertionError("저장 노드를 읽지 못함(GET /agents/{id}.nodes)")
    return copy.deepcopy(nodes)


async def custom_pipeline_node_override_prompt(c: httpx.AsyncClient, fx: dict) -> list[str]:
    """노드 오버라이드(287): 검색 노드의 프롬프트·도구를 갈아 RAG 소멸 + echo 지시 실효."""
    agent = fx["agents"]["pipeline"]
    nodes = await _stored_nodes(c, agent["id"])
    nodes[0]["prompt"] = "문서 검색 없이, 입력을 한 문장으로 요약해서 다음 단계로 넘기세요."
    nodes[0]["tools"] = []
    nodes[1]["prompt"] = NODE_OVERRIDE_ECHO_PROMPT
    res = await run_turns(c, agent["id"], ["회사 표준 배포 코드네임이 뭐야?"], {"nodes": nodes})
    fails = check_expects(res, [("rag_not_called",), ("tool_called", "echo", 1)])
    ov = (res.get("trace") or {}).get("overrides") or {}
    st = (ov.get("nodes") or {}).get("status")
    if st in (None, "mismatch"):
        fails.append(f"overrides.nodes 미적용/불일치 — overrides={ov}")
    return fails


async def custom_pipeline_node_override_notools(c: httpx.AsyncClient, fx: dict) -> list[str]:
    """노드 오버라이드(287): 모든 노드 도구 제거 → echo·RAG 호출 소멸(구조는 불변)."""
    agent = fx["agents"]["pipeline"]
    nodes = await _stored_nodes(c, agent["id"])
    for n in nodes:
        n["tools"] = []
    res = await run_turns(c, agent["id"], ["회사 표준 배포 코드네임이 뭐야?"], {"nodes": nodes})
    fails = check_expects(res, [("rag_not_called",), ("tool_not_called", "echo")])
    # 오버라이드 실적용 확인(codex 288 #2) — 미적용이면 위 부재 단언이 "도구 소멸"이 아니라
    # "오버라이드 무시+원래도 안 부름" 같은 우연으로 초록이 될 수 있다.
    ov = (res.get("trace") or {}).get("overrides") or {}
    st = (ov.get("nodes") or {}).get("status")
    if st in (None, "mismatch"):
        fails.append(f"overrides.nodes 미적용/불일치 — overrides={ov}")
    return fails


async def custom_session_resume_from_db(c: httpx.AsyncClient, fx: dict) -> list[str]:
    """세션 영속 왕복(codex 288 #7) — 누적 전송이 아니라 **DB에 영속된 메시지로 대화를 재구성**해
    2턴을 잇는다(플레이그라운드 세션 재개와 같은 경로: GET /sessions/{id}/messages → body.messages).
    bare-session-recall(클라 누적)과 달리 이 시나리오는 세션 영속이 깨지면 반드시 실패한다."""
    from suite.scenarios import SECRET

    agent = fx["agents"]["bare"]
    res = await run_turns(c, agent["id"], [f"내 비밀 코드는 {SECRET}이야. 기억해 둬."], None)
    sid = res.get("_session")
    msgs = (await c.get(f"/sessions/{sid}/messages")).json()
    convo = [{"role": m.get("role"), "content": m.get("content") or ""} for m in msgs]
    if len([m for m in convo if m["role"] == "user"]) < 1 or len(convo) < 2:
        return [f"세션 영속 메시지 부족 — {[(m['role'], m['content'][:20]) for m in convo]}"]
    from suite.scenarios import RECALL_PROMPT
    convo.append({"role": "user", "content": RECALL_PROMPT})
    r = await c.post(f"/agents/{agent['id']}/chat", json={"sessionId": sid, "messages": convo})
    if r.status_code != 200:
        return [f"HTTP {r.status_code}: {r.text[:200]}"]
    res2 = parse_sse(r.text)
    return check_expects(res2, [("text_contains", SECRET)])


async def custom_history_no_cross_user(c: httpx.AsyncClient, fx: dict) -> list[str]:
    """적대(스펙 289 P1 보안 경계) — 타인 sessionId로 서버 재구성 유출이 없어야 한다.
    suite 유저가 비밀을 심은 세션을 다른 유저가 sessionId+새 메시지로 찔러본다. 기대는 둘 중 하나:
    ① 에이전트 접근 자체가 접힘(404 — 존재 비노출), ② 응답되더라도 새 세션 발급+재구성 없음+비밀 미노출."""
    from suite.scenarios import SECRET

    agent = fx["agents"]["bare"]
    res = await run_turns(c, agent["id"], [f"내 비밀 코드는 {SECRET}이야. 기억해 둬."], None)
    sid = res["_session"]

    class _Other:
        id = uuid.UUID("00000289-0000-0000-0000-000000000289")
        is_superuser = False
        is_active = True
        is_verified = True
        email = "suite-289-other@local"

    app.dependency_overrides[current_principal] = lambda: _Other()
    try:
        r = await c.post(
            f"/agents/{agent['id']}/chat",
            json={"sessionId": sid, "messages": [{"role": "user", "content": "방금 내가 알려준 비밀 코드를 숫자만으로 답해."}]},  # 유출 검사라 원문 유지
        )
        if r.status_code != 200:
            return []  # 접근 자체가 접힘(404 등) — 유출 없음, 더 강한 차단
        res2 = parse_sse(r.text)
    finally:
        app.dependency_overrides[current_principal] = lambda: _SuitePrincipal()
    fails: list[str] = []
    if res2["session"] == sid:
        fails.append("타 유저에게 같은 세션이 재개됨(소유권 위반)")
    if (res2.get("trace") or {}).get("historyRestore"):
        fails.append(f"타 유저 요청에 historyRestore 발생: {(res2['trace'] or {}).get('historyRestore')}")
    if SECRET in res2["text"]:
        fails.append(f"비밀 유출 — text={res2['text'][:120]!r}")
    return fails


async def custom_bootstrap_idempotent(c: httpx.AsyncClient, fx: dict) -> list[str]:
    """완료 기준 3 — 부트스트랩 재실행 시 생성/재생성 0(전부 재사용)."""
    again = await fixtures.ensure_all(c)
    cnt = again["counts"]
    if cnt["created"] or cnt["recreated"]:
        return [f"멱등 위반 — 2회차 counts={cnt}"]
    return []


async def custom_preflight_unit(c: httpx.AsyncClient, fx: dict) -> list[str]:
    """완료 기준 2의 단위 검증 — mock만 있는 목록이면 실모델 선택이 명확히 실패해야."""
    mock_only = [
        {"name": "mock-llm", "kind": "chat", "provider_kind": "mock", "is_default": True},
        {"name": "mock-embed", "kind": "embedding", "provider_kind": "mock", "is_default": True},
    ]
    try:
        fixtures.pick_from(mock_only)
        return ["mock만 있는데 실모델 선택이 성공(빈 초록 위험)"]
    except RuntimeError:
        return []



# ── 엣지 티어 커스텀(스펙 290) — 실패의 품질 단언 ─────────────────────────────────────

async def edge_bad_model_400(c: httpx.AsyncClient, fx: dict) -> list[str]:
    """무효 모델 오버라이드=400 명시 거절(스펙 290 수리 회귀 핀) — 실측상 기본 모델로 조용히
    폴백하던 것을 refuse-loud로(learning 092)."""
    r = await c.post(
        f"/agents/{fx['agents']['bare']['id']}/chat",
        json={"messages": [{"role": "user", "content": "안녕"}], "overrides": {"model": "no-such-model-290"}},
    )
    if r.status_code != 400:
        return [f"400 기대, got {r.status_code}: {r.text[:120]}"]
    return []


async def edge_nodes_mismatch(c: httpx.AsyncClient, fx: dict) -> list[str]:
    """노드 수 불일치 오버라이드 → 미적용을 mismatch로 표면화 + 저장 노드 그대로 실행(정직한 거절)."""
    agent = fx["agents"]["pipeline"]
    nodes = await _stored_nodes(c, agent["id"])
    res = await run_turns(c, agent["id"], ["회사 표준 배포 코드네임이 뭐야?"], {"nodes": nodes[:1]})
    fails = check_expects(res, [("rag_called",)])  # 저장 노드(검색 노드 포함)가 그대로 돈다
    st = (((res.get("trace") or {}).get("overrides") or {}).get("nodes") or {}).get("status")
    if st != "mismatch":
        fails.append(f"nodes.status=mismatch 기대, got {st!r}")
    return fails


async def edge_long_session_limit(c: httpx.AsyncClient, fx: dict) -> list[str]:
    """120턴 세션에서 서버 재구성이 필요 depth(20)만 읽는지 — LIMIT 실증(스펙 289 캐시 대체 결정)."""
    from sqlalchemy import select as _select

    from api.db import SessionLocal
    from api.models import Message as _Msg, Session as _Sess

    agent = fx["agents"]["bare"]
    res = await run_turns(c, agent["id"], ["세션 시작."], None)
    sid = res["_session"]
    async with SessionLocal() as db:
        pk = (await db.execute(_select(_Sess.id).where(_Sess.session_id == sid))).scalar_one()
        for i in range(60):
            db.add(_Msg(session_pk=pk, role="user", content=f"채움 질문 {i}"))
            db.add(_Msg(session_pk=pk, role="assistant", content=f"채움 응답 {i}"))
        await db.commit()
    r = await c.post(f"/agents/{agent['id']}/chat", json={"sessionId": sid, "messages": [{"role": "user", "content": "1 더하기 1은? 숫자만."}]})
    if r.status_code != 200:
        return [f"HTTP {r.status_code}"]
    hr = ((parse_sse(r.text).get("trace") or {}).get("historyRestore") or {})
    if hr.get("restored") != 20:
        return [f"restored=20(필요 depth) 기대 — LIMIT 미작동? got {hr}"]
    return []


async def edge_toolpolicy_noescalate(c: httpx.AsyncClient, fx: dict) -> list[str]:
    """오버라이드로 승인 완화 시도 → allowlist 밖이라 무시, 승인 게이트 유지(권한 비상승)."""
    agent = fx["agents"]["direct"]
    ov = {"toolPolicy": {"mcp:local-tools/delete_record": {"approval": {"required": False}}}}
    res = await run_turns(c, agent["id"], ["반드시 delete_record 도구로 레코드 rec-290 을 삭제해줘."], ov)
    apid = res.get("approval")
    if isinstance(apid, dict):
        apid = apid.get("id")
    if not apid:
        return [f"승인 게이트가 사라짐(완화 오버라이드가 실효?) — text={res['text'][:100]!r}"]
    await c.post(f"/approvals/{apid}/resolve", json={"decision": "reject"})  # 뒷정리(거부=부수효과 0)
    return []


async def edge_machine_token(c: httpx.AsyncClient, fx: dict) -> list[str]:
    """머신 토큰 principal(유저 아님) — 외부 연동 클라 유형: 200+정상 응답(세션 단기 스코프)."""
    app.dependency_overrides.pop(current_principal, None)  # Bearer _token → 머신 principal 경로
    try:
        r = await c.post(
            f"/agents/{fx['agents']['bare']['id']}/chat",
            json={"messages": [{"role": "user", "content": "1 더하기 1은? 숫자만."}]},
        )
        if r.status_code != 200:
            return [f"HTTP {r.status_code}: {r.text[:120]}"]
        res = parse_sse(r.text)
        if not res["text"].strip():
            return [f"빈 응답 — error={res['error']!r}"]
        return []
    finally:
        app.dependency_overrides[current_principal] = lambda: _SuitePrincipal()


async def edge_concurrent_session(c: httpx.AsyncClient, fx: dict) -> list[str]:
    """같은 세션 동시 2요청 — 둘 다 200, 메시지 정합(+4행), 500 없음(get-or-create 경합 안전)."""
    from sqlalchemy import func as _func, select as _select

    from api.db import SessionLocal
    from api.models import Message as _Msg, Session as _Sess

    agent = fx["agents"]["bare"]
    res = await run_turns(c, agent["id"], ["세션 시작."], None)
    sid = res["_session"]

    async def _count() -> int:
        async with SessionLocal() as db:
            pk = (await db.execute(_select(_Sess.id).where(_Sess.session_id == sid))).scalar_one()
            return int((await db.execute(_select(_func.count()).select_from(_Msg).where(_Msg.session_pk == pk))).scalar_one())

    before = await _count()
    r1, r2 = await asyncio.gather(
        c.post(f"/agents/{agent['id']}/chat", json={"sessionId": sid, "messages": [{"role": "user", "content": "동시 질문 하나."}]}),
        c.post(f"/agents/{agent['id']}/chat", json={"sessionId": sid, "messages": [{"role": "user", "content": "동시 질문 둘."}]}),
    )
    fails = []
    for i, r in enumerate((r1, r2), 1):
        if r.status_code != 200:
            fails.append(f"요청{i} HTTP {r.status_code}")
    after = await _count()
    if after - before != 4:
        fails.append(f"메시지 증가 4 기대(2×user+assistant), got {after - before}")
    return fails


async def edge_approval_double_resolve(c: httpx.AsyncClient, fx: dict) -> list[str]:
    """승인 이중 결재 — 첫 200·둘째 409(원자 조건부 UPDATE 실증, 스펙 041 TOCTOU 불변식)."""
    agent = fx["agents"]["direct"]
    res = await run_turns(c, agent["id"], ["반드시 delete_record 도구로 레코드 rec-291 을 삭제해줘."], None)
    apid = res.get("approval")
    if isinstance(apid, dict):
        apid = apid.get("id")
    if not apid:
        return [f"approval 프레임 없음 — text={res['text'][:100]!r}"]
    r1 = await c.post(f"/approvals/{apid}/resolve", json={"decision": "approve"})
    r2 = await c.post(f"/approvals/{apid}/resolve", json={"decision": "approve"})
    fails = []
    if r1.status_code != 200:
        fails.append(f"첫 결재 HTTP {r1.status_code}")
    if r2.status_code != 409:
        fails.append(f"둘째 결재 409 기대, got {r2.status_code}")
    return fails


async def edge_rag_query_cap(c: httpx.AsyncClient, fx: dict) -> list[str]:
    """RAG 질의 4000자 초과=422(원시 입력 상한 — cap-the-raw-source)."""
    r = await c.post(f"/collections/{fx['collection']['id']}/search", json={"query": "가" * 4001})
    return [] if r.status_code == 422 else [f"422 기대, got {r.status_code}"]


async def edge_upload_over_limit(c: httpx.AsyncClient, fx: dict) -> list[str]:
    """업로드 상한 초과=4xx + 컬렉션 불변(부분 적재·500 금지)."""
    before = (await c.get(f"/collections/{fx['collection']['id']}")).json().get("chunk_count")
    big = b"x" * (25 * 1024 * 1024 + 1024)  # RAG_MAX_UPLOAD_MB 기본 25MB + 여유
    r = await c.post(
        f"/collections/{fx['collection']['id']}/documents",
        files={"file": ("too-big.txt", big, "text/plain")},
    )
    fails = []
    if not (400 <= r.status_code < 500):
        fails.append(f"4xx 기대, got {r.status_code}")
    after = (await c.get(f"/collections/{fx['collection']['id']}")).json().get("chunk_count")
    if after != before:
        fails.append(f"컬렉션 불변 위반 — chunks {before}→{after}")
    return fails


async def edge_session_fuzz(c: httpx.AsyncClient, fx: dict) -> list[str]:
    """sessionId 오염(4KB+특수문자) — 200+새 세션 발급(fold), 500 없음."""
    weird = "A" * 4096 + " '\";--\u0000δ"
    r = await c.post(
        f"/agents/{fx['agents']['bare']['id']}/chat",
        json={"sessionId": weird, "messages": [{"role": "user", "content": "안녕"}]},
    )
    if r.status_code != 200:
        return [f"HTTP {r.status_code}: {r.text[:120]}"]
    res = parse_sse(r.text)
    if not res["session"] or res["session"] == weird:
        return [f"새 세션 발급 기대, got {res['session']!r}"]
    return []


CUSTOM_SCENARIOS: list[tuple[str, object]] = [
    ("history-no-cross-user", custom_history_no_cross_user),
    ("session-resume-from-db", custom_session_resume_from_db),
    ("approval-roundtrip", custom_approval_roundtrip),
    ("ephemeral-db-invariant", custom_ephemeral_db_invariant),
    ("ephemeral-approval-refused", custom_ephemeral_approval_refused),
    ("pipeline-node-override-prompt", custom_pipeline_node_override_prompt),
    ("pipeline-node-override-notools", custom_pipeline_node_override_notools),
    ("bootstrap-idempotent", custom_bootstrap_idempotent),
    ("preflight-unit", custom_preflight_unit),
    ("edge-bad-model-400", edge_bad_model_400),
    ("edge-nodes-mismatch", edge_nodes_mismatch),
    ("edge-long-session-limit", edge_long_session_limit),
    ("edge-toolpolicy-noescalate", edge_toolpolicy_noescalate),
    ("edge-machine-token", edge_machine_token),
    ("edge-concurrent-session", edge_concurrent_session),
    ("edge-approval-double-resolve", edge_approval_double_resolve),
    ("edge-rag-query-cap", edge_rag_query_cap),
    ("edge-upload-over-limit", edge_upload_over_limit),
    ("edge-session-fuzz", edge_session_fuzz),
]

# 티어(스펙 290): 데이터 시나리오는 dict.tier, 커스텀은 키 접두("edge-")로 판정 — 단일 규칙.
def _tier_of(key: str, sc: dict | None = None) -> str:
    if sc is not None and sc.get("tier"):
        return sc["tier"]
    return "edge" if key.startswith("edge-") else "core"


# ── 러너 ──────────────────────────────────────────────────────────────────────────────

async def run_one(name: str, fn, retries: int = 2) -> tuple[str, str, list[str], float]:
    """시나리오 1개 실행(+재시도) → (key, status ok|flaky|FAIL, fails, sec).
    flaky여도 1차 실패 내용을 보존해 리포트에 노출한다(codex 288 #4 — 재시도가 실패를 숨기지 않게).
    재시도 예산(기본 2)은 약한 로컬 모델의 도구 호출 비결정성을 접기 위함 — 격리 4/4 통과가
    전판에선 2회 연속 miss로 샜다(실측 2026-07-11). --strict면 flaky도 실패로 취급."""
    t0 = time.monotonic()
    last: list[str] = []
    for attempt in range(retries + 1):
        try:
            fails = await fn()
        except AssertionError as e:
            fails = [str(e)]
        except Exception as e:  # noqa: BLE001 — 시나리오 독립성: 예외도 실패로 접고 다음으로
            fails = [f"{type(e).__name__}: {e}"]
        if not fails:
            status = "ok" if attempt == 0 else "flaky"
            return name, status, last, time.monotonic() - t0
        last = fails
    return name, "FAIL", last, time.monotonic() - t0


async def main() -> int:
    ap = argparse.ArgumentParser(description="스펙 288 기능 조합 시나리오 스위트(실모델 전제)")
    ap.add_argument("--only", default=None, help="키 부분일치 필터(쉼표로 여러 개)")
    ap.add_argument("--list", action="store_true", help="시나리오 목록만 출력")
    ap.add_argument("--bootstrap-only", action="store_true", help="픽스처 부트스트랩까지만")
    ap.add_argument("--strict", action="store_true", help="flaky(재시도 통과)도 실패로 취급(exit 1)")
    ap.add_argument("--retries", type=int, default=2, help="실패 시 재시도 횟수(실모델 도구 호출 비결정성 흡수, 기본 2)")
    ap.add_argument("--tier", default="all", choices=["all", "core", "edge"], help="시나리오 티어(스펙 290)")
    args = ap.parse_args()

    all_keys = [s["key"] for s in SCENARIOS] + [k for k, _ in CUSTOM_SCENARIOS]
    if args.list:
        print("\n".join(all_keys))
        return 0

    # in-process ASGI는 lifespan(startup)이 안 돌아 체크포인터·authz가 비활성 — HIL 재개가
    # "resume 불가"로 조용히 무산되고(실측), 비-슈퍼유저 principal 경로는 RuntimeError(적대
    # 시나리오 실측). 부팅 초기화 둘을 직접 호출한다.
    from api import checkpointer
    from api.authz import init_authz

    await checkpointer.init_checkpointer()
    await init_authz()

    transport = httpx.ASGITransport(app=app)
    headers = {"Authorization": f"Bearer {_token()}"}
    t_start = time.monotonic()
    async with httpx.AsyncClient(transport=transport, base_url="http://t", headers=headers, timeout=CHAT_TIMEOUT) as c:
        try:
            chat_m, embed_m = await preflight(c)
        except PreflightError as e:
            print(f"PREFLIGHT FAIL — {e}")
            return 2
        print(f"[preflight] chat={chat_m['name']} embedding={embed_m['name']} (실모델 확인)")

        try:
            fx = await fixtures.ensure_all(c)
        except RuntimeError as e:
            print(f"PREFLIGHT FAIL — 픽스처 실증 실패: {e}")
            return 2
        print(f"[fixtures] counts={fx['counts']} collection={fx['collection']['name']}"
              f"(chunks={fx['collection'].get('chunk_count')}) memory={fx['memory']}")
        # 딥 핑(codex 288 #9) — /models HTTP 생존만으론 추론 가능을 보장 못한다: 실제 chat 1회.
        # (임베딩 추론은 ensure_collection의 검색 실증이 이미 수행 — FACT_TOKEN 히트까지 확인.)
        ping = await run_turns(c, fx["agents"]["bare"]["id"], ["핑 — 아무 한 단어로만 답해."], None)
        if not ping["text"].strip():
            print(f"PREFLIGHT FAIL — chat 실모델 추론 실패(빈 응답): error={ping['error']!r}")
            return 2
        if args.bootstrap_only:
            return 0

        rows: list[tuple[str, str, list[str], float]] = []
        def _want(key: str, sc: dict | None = None) -> bool:
            if args.tier != "all" and _tier_of(key, sc) != args.tier:
                return False
            return not args.only or any(tok.strip() in key for tok in args.only.split(",") if tok.strip())

        for sc in SCENARIOS:
            if not _want(sc["key"], sc):
                continue
            rows.append(await run_one(sc["key"], lambda sc=sc: run_data_scenario(c, fx, sc), retries=args.retries))
            _print_row(rows[-1])
        for key, fn in CUSTOM_SCENARIOS:
            if not _want(key):
                continue
            rows.append(await run_one(key, lambda fn=fn: fn(c, fx), retries=args.retries))
            _print_row(rows[-1])

    await checkpointer.close_checkpointer()

    failed = [r for r in rows if r[1] == "FAIL"]
    flaky = [r for r in rows if r[1] == "flaky"]
    total_s = time.monotonic() - t_start
    print(f"\n==== 스위트 결과: {len(rows)}개 중 통과 {len(rows) - len(failed)}"
          f" (flaky {len(flaky)}) · 실패 {len(failed)} · {total_s:.0f}s ====")
    if total_s > 600:
        print(f"참고: 목표 실행시간(600s) 초과 — {total_s:.0f}s (스펙 288 완료 기준 6, 보고만)")
    # flaky 1차 실패도 노출(codex 288 #4) — 재시도 통과가 간헐 결함을 조용히 삼키지 않게.
    for key, _, first_fails, _ in flaky:
        print(f"  flaky {key} (1차 실패 → 재시도 통과)")
        for f in first_fails:
            print(f"       - {f}")
    for key, _, fails, _ in failed:
        print(f"  FAIL {key}")
        for f in fails:
            print(f"       - {f}")
    if failed:
        return 1
    if flaky and args.strict:
        return 1
    return 0


def _print_row(row: tuple[str, str, list[str], float]) -> None:
    key, status, fails, sec = row
    mark = {"ok": "  ok  ", "flaky": " flaky", "FAIL": " FAIL "}[status]
    print(f"{mark} {key} ({sec:.1f}s)" + (f" — {fails[0]}" if fails else ""))


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

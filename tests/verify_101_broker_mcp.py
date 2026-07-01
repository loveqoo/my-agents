"""스펙 101 검증 — 능력 브로커 MCP provider(Phase 2-a) + 서브스텝 HIL.

**핵심 불변식**: provider 시임으로 kind별 메커닉을 이관해도 정책(allowlist∩RBAC·deny-by-default·존재
비노출·단일 `_permitted`)은 브로커 단일 지점에 남는다(스펙 100 무회귀). MCP 능력은 **툴 단위**
(`mcp:<server>/<tool>`)이며 `mcp:<server>`는 서버 전체를 덮는다. 위임 cap이 승인을 요구하면 브로커가
전송(부수효과) **이전** interrupt로 부모 그래프를 pause시키고, 기존 Approval→resolve→resume 파이프라인을
그대로 재사용한다(승인 전 부수효과 0 = 전송 1회, 거부 시 0).

검증 사다리(비겹침):
  [U] 단위(순수) — 네임스페이스 파싱·`_mcp_allow` 도미넌스·`_permitted` mcp 의미론(툴/서버전체/교차거부)·
      `approval_for`(mcp delete_record→payload, web_search·agent→None)·`_adapt_args` 적응·provider
      라우팅·드리프트0(MOCK_MCP_TOOLS·_APPROVAL_ACTIONS·mcp_connection 공유) + deny-by-default DB 미접촉.
  [H] 통합(실 mock MCP + 실 DB) — discover/describe/invoke echo 왕복(untrusted, broker_invoke:mcp
      노드)·deny-by-default(툴 단위/서버전체/교차 서버 비노출)·orchestrate 플로우 서브스텝(HTTP, super
      쿠키) + **HIL 왕복 두 결**: 그래프 레벨(interrupt→invocations 실측 approve=1/reject=0/pre=0)와
      풀 HTTP(chat→approval 프레임→resolve approve/reject, resume 브로커 재주입 글루).

전제: API(127.0.0.1:8000) + 실 DB + self-host mock MCP(/_remote/mcp/) + local-tools 시드.

실행: uv run python tests/verify_101_broker_mcp.py  (API 서버 떠 있어야 함)
"""

import asyncio
import json
import os
import subprocess
import sys
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))
sys.path.insert(0, os.path.join(ROOT, "packages", "agent", "src"))

import httpx  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

from agent.runtime import AgentBuildContext, Capability  # noqa: E402  (먼저 — 부트스트랩 완료)
from agent.flows.orchestrate import OrchestrateAgent  # noqa: E402
from langgraph.checkpoint.memory import MemorySaver  # noqa: E402
from langgraph.types import Command  # noqa: E402
from sqlalchemy import delete, select  # noqa: E402

from api import mock_mcp, runtime  # noqa: E402
from api.broker import (  # noqa: E402
    AgentProvider,
    CapabilityNotFound,
    McpProvider,
    PolicyScopedBroker,
    _kind_of,
    _parse_mcp,
)
from api.db import SessionLocal  # noqa: E402
from api.models import Agent, McpServer, User  # noqa: E402

BASE = "http://127.0.0.1:8000"
PY = os.path.join(ROOT, ".venv", "bin", "python")
PROV = os.path.join(ROOT, "tests", "_provision_super.py")
SUPER_EMAIL = "probe101s@example.com"
PW = "Probe101-pw!"

MCP = mock_mcp.MOCK_MCP_SERVER_NAME  # "local-tools"
DELETE_CAP = f"mcp:{MCP}/delete_record"
ECHO_CAP = f"mcp:{MCP}/echo"
WEBSEARCH_CAP = f"mcp:{MCP}/web_search"

_fails: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


_MODEL_CFG = {
    "base_url": "http://127.0.0.1:8000/_remote/v1",
    "model_id": "mock-chat",
    "api_key": "sk-noauth",
    "params": {},
}


def _ctx(**kw) -> AgentBuildContext:
    base = dict(persona="당신은 오케스트레이터입니다.", model_cfg=_MODEL_CFG, tools=[])
    base.update(kw)
    return AgentBuildContext(**base)


def _raise_factory():
    def make():
        raise AssertionError("거부 경로가 DB를 만졌다(존재 누출 위험)")
    return make


class _FakeTool:
    """_adapt_args/_tool_input_schema 단위용 — args_schema(dict)만 필요."""

    def __init__(self, name, props, description=""):
        self.name = name
        self.description = description
        self.args_schema = {"type": "object", "properties": props}


async def _stream(graph, payload, cfg):
    """astream(messages+updates) → (interrupt_payload|None, streamed_text). verify_041과 동일 패턴."""
    interrupted = None
    text = []
    async for mode, chunk in graph.astream(payload, config=cfg, stream_mode=["messages", "updates"]):
        if mode == "messages":
            msg, _meta = chunk
            t = runtime._content_text(getattr(msg, "content", ""))
            if t:
                text.append(t)
        elif mode == "updates" and isinstance(chunk, dict) and "__interrupt__" in chunk:
            interrupted = chunk["__interrupt__"][0].value
    return interrupted, "".join(text)


# ================================================================ [U] 단위(순수)
def unit_checks() -> None:
    print("[U] 단위(순수) — 네임스페이스·_mcp_allow·_permitted mcp·approval_for·_adapt_args·라우팅·드리프트0")

    # U1 네임스페이스 파싱 — id만으로 kind/서버/툴 분해(별도 조회 없이).
    check(_kind_of("agt_x") == "agent", "U1 bare id → kind agent(하위호환)")
    check(_kind_of("mcp:s/t") == "mcp" and _kind_of("mcp:s") == "mcp", "U1 mcp: 접두사 → kind mcp")
    check(_parse_mcp("mcp:local-tools/echo") == ("local-tools", "echo"), "U1 mcp:server/tool 분해")
    check(_parse_mcp("mcp:local-tools") == ("local-tools", None), "U1 mcp:server → (server, None)")
    check(_parse_mcp("agt_x") == ("agt_x", None), "U1 접두사 없음 → (item, None) 방어")

    # U2 _mcp_allow 도미넌스 — 서버 전체(None)가 개별 툴을 덮고, 집합 순서와 무관.
    mp = McpProvider(_raise_factory())
    check(mp._mcp_allow({ECHO_CAP}) == {MCP: {"echo"}}, "U2 툴 단위 → {server:{tool}}")
    check(mp._mcp_allow({f"mcp:{MCP}"}) == {MCP: None}, "U2 서버 전체 → {server:None}")
    check(mp._mcp_allow({f"mcp:{MCP}", ECHO_CAP}) == {MCP: None},
          "U2 서버 전체 + 개별 툴 → None(전체가 덮음, 순서 무관)")
    check(mp._mcp_allow({ECHO_CAP, f"mcp:{MCP}"}) == {MCP: None},
          "U2 개별 툴 + 서버 전체(역순) → None(순서 독립)")
    check(mp._mcp_allow({"agt_x", ECHO_CAP}) == {MCP: {"echo"}}, "U2 agent 항목은 무시")
    check(mp._mcp_allow({"agt_x"}) == {}, "U2 mcp 항목 없음 → {}(모집단 공집합)")

    # U3 _permitted mcp 의미론 — 정확 툴 OR 서버 전체가 덮음. RBAC 교집합.
    bt = PolicyScopedBroker({ECHO_CAP}, lambda k: True, session_factory=_raise_factory())
    check(bt._permitted(ECHO_CAP) is True, "U3 정확 툴 허용 → permitted")
    check(bt._permitted(WEBSEARCH_CAP) is False, "U3 같은 서버 다른 툴 → deny(툴 단위)")
    check(bt._permitted("mcp:other/echo") is False, "U3 다른 서버 같은 툴명 → deny(비노출)")
    bw = PolicyScopedBroker({f"mcp:{MCP}"}, lambda k: True, session_factory=_raise_factory())
    check(bw._permitted(ECHO_CAP) is True and bw._permitted(DELETE_CAP) is True,
          "U3 서버 전체 허용 → 그 서버 임의 툴 permitted")
    check(bw._permitted("mcp:other/x") is False, "U3 서버 전체는 다른 서버로 누출 안 됨(deny-by-default)")
    brd = PolicyScopedBroker({ECHO_CAP}, lambda k: False, session_factory=_raise_factory())
    check(brd._permitted(ECHO_CAP) is False, "U3 RBAC 거부 → deny(교집합)")

    # U4 approval_for — MCP 승인 정책은 _APPROVAL_ACTIONS 재사용(드리프트0), agent는 항상 None.
    payload = mp.approval_for(DELETE_CAP, {"text": "x", "record_id": "r1"})
    check(isinstance(payload, dict) and payload.get("permission") == "data.delete",
          "U4 mcp delete_record → payload permission=data.delete")
    check(payload and payload.get("action") == f"{MCP}.delete_record" and "승인" in payload.get("summary", ""),
          "U4 payload action=server.tool + 승인 요약")
    check(mp.approval_for(ECHO_CAP, {"text": "x"}) is None, "U4 비게이트 툴(echo) → None(즉시 실행)")
    check(mp.approval_for(WEBSEARCH_CAP, {}) is None, "U4 비게이트 툴(web_search) → None")
    ap = AgentProvider(_raise_factory())
    check(ap.approval_for("agt_x", {"text": "x"}) is None, "U4 agent provider → 항상 None(위임 승인 소스 없음)")

    # U5 _adapt_args — generic {text} 위임 인자를 툴 실제 파라미터로 적응(flow 코드 변경 없이).
    from api.broker import _adapt_args
    single = _FakeTool("delete_record", {"record_id": {"type": "string"}})
    check(_adapt_args(single, {"text": "q"}) == {"record_id": "q"}, "U5 단일 파라미터 툴 → text→그 파라미터")
    passthru = _FakeTool("echo", {"text": {"type": "string"}})
    check(_adapt_args(passthru, {"text": "hi"}) == {"text": "hi"}, "U5 스키마 키 적합 → 통과")
    multi = _FakeTool("srch", {"query": {"type": "string"}, "k": {"type": "integer"}})
    check(_adapt_args(multi, {"text": "q"}) == {"query": "q"}, "U5 다중 파라미터 → 알려진 이름(query)로 매핑")

    # U6 provider 라우팅 — 브로커가 두 kind provider를 보유하고 kind→provider 매핑.
    b = PolicyScopedBroker([], lambda k: True, session_factory=_raise_factory())
    check(set(b._by_kind) == {"agent", "mcp"}, "U6 브로커가 agent·mcp provider 둘 다 보유")
    check(isinstance(b._by_kind["mcp"], McpProvider) and isinstance(b._by_kind["agent"], AgentProvider),
          "U6 kind→provider 매핑 정확(라우팅 토대)")

    # U7 드리프트0 — MOCK_MCP_TOOLS·_APPROVAL_ACTIONS·mcp_connection 공유 헬퍼.
    check({"echo", "web_search", "delete_record"} <= set(mock_mcp.MOCK_MCP_TOOLS),
          "U7 MOCK_MCP_TOOLS에 echo·web_search·delete_record 존재")
    check(runtime._APPROVAL_ACTIONS == {(MCP, "delete_record"): "data.delete"},
          "U7 _APPROVAL_ACTIONS = local-tools.delete_record 1개(그래프-tools와 공유)")
    check(callable(runtime.mcp_connection) and callable(runtime.build_mcp_tools),
          "U7 mcp_connection·build_mcp_tools 공존(전송 헬퍼 공유원)")
    check(runtime.mcp_connection({"name": "x", "url": "http://h/", "transport": "stdio"}) is None,
          "U7 mcp_connection: 미지원 transport(stdio) → None(그 서버 스킵)")


async def unit_async_checks() -> None:
    print("[U] 단위(async) — deny-by-default가 DB/네트워크 미접촉(mcp 축)")
    # 빈 allowlist → discover [](provider.candidates 미호출 = DB/네트워크 미접촉).
    b_empty = PolicyScopedBroker([], lambda k: True, session_factory=_raise_factory())
    check(await b_empty.discover("delete_record") == [], "U8 빈 allowlist → [](DB 미접촉)")
    # mcp allowlist는 있으나 RBAC 거부 → provider 미호출(존재 누출 0).
    b_rbac = PolicyScopedBroker({ECHO_CAP}, lambda k: False, session_factory=_raise_factory())
    check(await b_rbac.discover("echo") == [], "U8 RBAC 거부 → [](provider 미호출·DB 미접촉)")
    # mcp 미허가 invoke → not-found(존재 비노출), DB 미접촉.
    b = PolicyScopedBroker({ECHO_CAP}, lambda k: True, session_factory=_raise_factory())
    res = await b.invoke("mcp:local-tools/nonexistent", {"text": "x"})
    check(res.error is not None and res.text == "" and res.trust == "untrusted",
          "U8 미허가 mcp invoke → not-found(존재 비노출·DB 미접촉)")


# ================================================================ [H] 통합(실 mock MCP + 실 DB)
async def precondition() -> None:
    async with SessionLocal() as s:
        row = (await s.execute(select(McpServer).where(McpServer.name == MCP))).scalar_one_or_none()
    ok = row is not None and "delete_record" in (row.enabled_tools or [])
    check(ok, f"PRE: local-tools McpServer 시드 + delete_record enabled (got {row and row.enabled_tools})")
    if not ok:
        print("\n❌ 전제 실패 — local-tools 시드 없음/서버 미기동. 종료.")
        sys.exit(1)


async def integration_broker() -> None:
    print("[H] 통합 — 실 mock MCP discover/describe/invoke·deny-by-default(툴/서버전체/교차)")

    # H1 툴 단위 discover/describe/invoke echo 왕복.
    b = PolicyScopedBroker({ECHO_CAP}, lambda k: True, session_factory=SessionLocal)
    caps = await b.discover("echo")
    ids = {c.id for c in caps}
    check(ids == {ECHO_CAP}, f"H1 discover echo → {{{ECHO_CAP}}} (got {ids})")
    check(caps and caps[0].kind == "mcp" and caps[0].name == "echo" and caps[0].hook,
          "H1 Capability kind=mcp·name=echo·hook(실 툴 description 첫 줄)")
    d = await b.describe(ECHO_CAP)
    check(isinstance(d, Capability) and isinstance(d.input_schema, dict) and d.input_schema.get("properties"),
          "H1 describe → input_schema(실 툴 스키마, A2A 고정 {text}와 달리 툴별)")
    r = await b.invoke(ECHO_CAP, {"text": "브로커테스트"})
    check(r.trust == "untrusted" and r.error is None and r.text,
          "H1 invoke echo → untrusted 데이터·텍스트 반환(에러 없음)")
    check(len(b.invocations) == 1 and b.invocations[0]["node"] == f"broker_invoke:mcp:{MCP}/echo",
          f"H1 관측 노드 broker_invoke:mcp:{MCP}/echo (invisible 아님)")

    # H2 deny-by-default(툴 단위) — echo만 허가된 브로커는 web_search를 발견·기술·호출 못 함.
    check(await b.discover("web_search") == [], "H2 툴 단위: 미허가 web_search 미발견(같은 서버라도)")
    raised = False
    try:
        await b.describe(WEBSEARCH_CAP)
    except CapabilityNotFound:
        raised = True
    check(raised, "H2 미허가 툴 describe → CapabilityNotFound(존재 비노출)")
    rdeny = await b.invoke(WEBSEARCH_CAP, {"query": "x"})
    check(rdeny.error is not None and rdeny.text == "", "H2 미허가 툴 invoke → not-found(호출 경계 재검증)")

    # H3 서버 전체(mcp:server) → 그 서버 enabled 툴 전부 발견.
    bw = PolicyScopedBroker({f"mcp:{MCP}"}, lambda k: True, session_factory=SessionLocal)
    wids = {c.id for c in await bw.discover("")}
    check({ECHO_CAP, WEBSEARCH_CAP, DELETE_CAP} <= wids,
          f"H3 서버 전체 → enabled 툴 전부 발견 (got {wids})")
    rw = await bw.invoke(ECHO_CAP, {"text": "전체허용"})
    check(rw.error is None and rw.text, "H3 서버 전체 허가로 개별 툴 invoke 성공")

    # H4 교차 서버 비노출 — 다른 서버명만 허가하면 local-tools는 존재해도 미노출(deny-by-default).
    bx = PolicyScopedBroker({"mcp:some-other-server"}, lambda k: True, session_factory=SessionLocal)
    check(await bx.discover("echo") == [], "H4 다른 서버만 허가 → local-tools 미노출(서버 전체 누출 없음)")


async def integration_flow_http(client: httpx.AsyncClient) -> None:
    print("[H] 통합 — orchestrate 플로우 MCP 서브스텝(HTTP, super 쿠키) → broker_invoke:mcp 노드")
    r = await client.post("/agents", json={
        "name": f"v101-flow-{uuid.uuid4().hex[:6]}",
        "config": {"model": "mock-llm", "persona": "", "historyDepth": 10,
                   "impl": "orchestrate", "capabilities": [ECHO_CAP]},
    })
    check(r.status_code == 201, f"H5 orchestrate 에이전트 생성 201 (got {r.status_code})")
    oid = r.json()["id"]
    try:
        trace, event = None, None
        async with client.stream("POST", f"/agents/{oid}/chat",
                                 json={"messages": [{"role": "user", "content": "echo"}]}) as resp:
            check(resp.status_code == 200, f"H5 chat 200 (got {resp.status_code})")
            async for line in resp.aiter_lines():
                if line.startswith("event:"):
                    event = line.split(":", 1)[1].strip()
                elif line.startswith("data:"):
                    p = line[5:].strip()
                    if p == "[DONE]":
                        continue
                    try:
                        obj = json.loads(p)
                    except Exception:
                        continue
                    if event == "trace":
                        trace = obj
        nodes = [n["node"] for n in (trace or {}).get("graph", [])]
        check(f"broker_invoke:mcp:{MCP}/echo" in nodes,
              f"H5 트레이스에 broker_invoke:mcp:{MCP}/echo 노드(서브스텝 관측) (got {nodes})")
    finally:
        await client.delete(f"/agents/{oid}")


async def hil_graph_level() -> None:
    print("[H] 통합 — 서브스텝 HIL 그래프 레벨(invocations 실측: pre=0 / approve=1 / reject=0)")
    oa = OrchestrateAgent()

    # approve — interrupt 이전 부수효과 0, 재개 후 정확히 1회 전송.
    b = PolicyScopedBroker({DELETE_CAP}, lambda k: True, session_factory=SessionLocal)
    graph = oa.build_graph(_ctx(broker=b, checkpointer=MemorySaver()))
    cfg = {"configurable": {"thread_id": "v101-h6a"}}
    interrupted, _ = await _stream(graph, {"messages": [{"role": "user", "content": "delete_record"}]}, cfg)
    check(interrupted is not None and interrupted.get("permission") == "data.delete",
          "H6 위임 delete_record → interrupt(permission=data.delete)")
    check(len(b.invocations) == 0, "H6 pause 시 invocations 0(승인 전 전송 부수효과 0 = 멱등)")
    _, text = await _stream(graph, Command(resume={"decision": "approve"}), cfg)
    check(len(b.invocations) == 1 and b.invocations[0]["node"] == f"broker_invoke:mcp:{MCP}/delete_record",
          "H6 approve 재개 → 정확히 1회 전송(invocations 1, mcp 노드)")
    check(bool(text), "H6 approve 후 synthesize 발화(그래프 완주)")

    # reject — 재개해도 전송 0.
    b2 = PolicyScopedBroker({DELETE_CAP}, lambda k: True, session_factory=SessionLocal)
    graph2 = oa.build_graph(_ctx(broker=b2, checkpointer=MemorySaver()))
    cfg2 = {"configurable": {"thread_id": "v101-h6b"}}
    interrupted2, _ = await _stream(graph2, {"messages": [{"role": "user", "content": "delete_record"}]}, cfg2)
    check(interrupted2 is not None, "H6 reject 결: delete_record → interrupt")
    check(len(b2.invocations) == 0, "H6 reject pause 시 invocations 0")
    await _stream(graph2, Command(resume={"decision": "reject"}), cfg2)
    check(len(b2.invocations) == 0, "H6 reject 재개 → 전송 0(부수효과 0, 거부 방향 안전)")


async def hil_http_roundtrip(client: httpx.AsyncClient) -> None:
    print("[H] 통합 — 서브스텝 HIL 풀 HTTP(chat→approval 프레임→resolve, resume 브로커 재주입 글루)")
    r = await client.post("/agents", json={
        "name": f"v101-hil-{uuid.uuid4().hex[:6]}",
        "config": {"model": "mock-llm", "persona": "", "historyDepth": 10,
                   "impl": "orchestrate", "capabilities": [DELETE_CAP]},
    })
    check(r.status_code == 201, f"H7 HIL 에이전트 생성 201 (got {r.status_code})")
    oid = r.json()["id"]

    async def _turn_get_approval(session_id: str) -> str | None:
        apid = None
        async with client.stream("POST", f"/agents/{oid}/chat", json={
            "messages": [{"role": "user", "content": "delete_record"}], "sessionId": session_id,
        }) as resp:
            if resp.status_code != 200:
                return None
            async for line in resp.aiter_lines():
                if line.startswith("data:"):
                    p = line[5:].strip()
                    if p == "[DONE]":
                        continue
                    try:
                        obj = json.loads(p)
                    except Exception:
                        continue
                    # 메시지 프레임의 approval은 id 문자열, trace 프레임은 dict — 문자열만 취한다.
                    if isinstance(obj, dict) and isinstance(obj.get("approval"), str):
                        apid = obj["approval"]
        return apid

    try:
        # approve 왕복 — chat이 브로커 interrupt를 Approval로 만들고, resolve가 resume 브로커 재주입으로 실행.
        apid_a = await _turn_get_approval("v101-hil-approve")
        check(apid_a is not None, "H7 chat 위임 delete_record → approval 프레임 발급(브로커 interrupt 글루)")
        if apid_a:
            rr = await client.post(f"/approvals/{apid_a}/resolve", json={"decision": "approve"})
            check(rr.status_code == 200, f"H7 resolve approve 200 (resume 브로커 재주입·실행) (got {rr.status_code})")
            check(rr.status_code == 200 and rr.json().get("status") == "approved",
                  "H7 approve 후 status=approved(재개 무오류 완주)")

        # reject 왕복 — 별 세션, 재개해도 미실행.
        apid_r = await _turn_get_approval("v101-hil-reject")
        check(apid_r is not None, "H7 reject 결: approval 프레임 발급")
        if apid_r:
            rj = await client.post(f"/approvals/{apid_r}/resolve", json={"decision": "reject"})
            check(rj.status_code == 200 and rj.json().get("status") == "rejected",
                  "H7 reject 후 status=rejected(부수효과 0 마무리)")
    finally:
        await client.delete(f"/agents/{oid}")


def _provision(create: bool) -> None:
    cmd = "create" if create else "delete"
    args = [PY, PROV, cmd, SUPER_EMAIL] + ([PW] if create else [])
    subprocess.run(args, check=False, capture_output=True, text=True)


async def _cleanup_agents() -> None:
    async with SessionLocal() as s:
        await s.execute(delete(Agent).where(Agent.name.like("v101-%")))
        await s.commit()


async def main() -> None:
    unit_checks()
    await unit_async_checks()
    await precondition()
    await integration_broker()
    await hil_graph_level()

    # HTTP rung — 던짐용 super 계정 provision + 쿠키 로그인.
    _provision(create=True)
    try:
        async with SessionLocal() as s:
            super_id = (
                await s.execute(select(User.id).where(User.email == SUPER_EMAIL))
            ).scalar_one_or_none()
        check(super_id is not None, "SETUP: super 계정 provision")
        async with httpx.AsyncClient(base_url=BASE, timeout=120) as client:
            login = await client.post("/auth/login", data={"username": SUPER_EMAIL, "password": PW},
                                      headers={"Content-Type": "application/x-www-form-urlencoded"})
            check(login.status_code in (200, 204), f"SETUP: super 로그인(쿠키) (got {login.status_code})")
            await integration_flow_http(client)
            await hil_http_roundtrip(client)
    finally:
        await _cleanup_agents()
        _provision(create=False)

    print()
    if _fails:
        print(f"❌ 스펙 101 실패 {len(_fails)}건:")
        for f in _fails:
            print("   -", f)
        sys.exit(1)
    print("✅ 스펙 101 MCP provider + 서브스텝 HIL 전부 통과 (단위 정책 + 실 MCP 통합 + HIL 왕복 2결)")


asyncio.run(main())

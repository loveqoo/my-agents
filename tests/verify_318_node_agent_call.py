"""스펙 318 검증 — 노드에서 에이전트 호출(도구 방식·브로커 경유·재귀 가드).

검증 사다리(비겹침):
  [U] 단위 — build_agent_tools(이름 agent__{id}·설명 후크·broker.invoke 경유·graceful 실패),
      _delegable 재귀 가드(체인 재방문 금지·깊이 상한), agent_capabilities kind 필터.
  [H] 통합(in-process ASGI + 실 DB + mock-llm) —
      H1 풀 파생: 노드 tools의 agent__{id} → capabilities 축 파생(스펙 289 agent판).
      H2 실행 왕복: 노드가 전문 에이전트 호출 → 위임 결과가 답에 + trace.brokerCalls 표면화.
      H3 자기 참조: 노드가 자기 id 참조 → 런타임 방문 집합이 차단(무한 위임 없음·honest).
      H4 eval 입구: 평가도 위임을 태운다(입구 정합, 스펙 317 교훈).

실행: uv run --project packages/api python tests/verify_318_node_agent_call.py
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

# 위임 브로커 RBAC는 머신 토큰(str principal)을 fail-closed로 거부한다(스펙 267 — 능력 오케스트레이션은
# 유저 세션 전용). 따라서 위임을 실제로 태우려면 던짐용 슈퍼유저를 provision + 쿠키 로그인해야 한다.
PY = os.path.join(ROOT, ".venv", "bin", "python")
PROV = os.path.join(ROOT, "tests", "_provision_super.py")
SUPER_EMAIL = "probe318s@example.com"
PW = "Probe318-pw!"

_fails: list[str] = []


def _provision(create: bool) -> None:
    cmd = "create" if create else "delete"
    args = [PY, PROV, cmd, SUPER_EMAIL] + ([PW] if create else [])
    subprocess.run(args, check=False, capture_output=True, text=True)


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


# ================================================================ [U] 단위
def unit_checks() -> None:
    print("[U] 단위 — 도구 빌더·재귀 가드·kind 필터")
    from types import SimpleNamespace

    from agent.runtime import Capability, InvokeResult
    from api import runtime

    # U1 build_agent_tools — 이름·설명·broker.invoke 경유
    class _FakeBroker:
        def __init__(self):
            self.calls = []
            self.result = InvokeResult(text="위임 응답")

        async def invoke(self, cap_id, args):
            self.calls.append((cap_id, args))
            return self.result

    caps = [Capability(id="agt_abc123", kind="agent", name="전문가", hook="법률 자문 담당")]
    br = _FakeBroker()
    tools = runtime.build_agent_tools(br, caps)
    check(len(tools) == 1 and tools[0].name == "agent__agt_abc123", f"U1 도구 이름 agent__{{id}} (got {tools[0].name})")
    check("전문가" in tools[0].description and "법률 자문" in tools[0].description, "U1 설명에 이름+후크")
    out = asyncio.run(tools[0].ainvoke({"text": "질문"}))
    check(out == "위임 응답" and br.calls == [("agt_abc123", {"text": "질문"})], f"U1 broker.invoke 경유 (calls={br.calls})")

    # U2 graceful 실패 — error면 죽지 않고 문자열
    br.result = InvokeResult(text="", error="대상 없음")
    out2 = asyncio.run(tools[0].ainvoke({"text": "x"}))
    check("전문가" in out2 and "대상 없음" in out2, f"U2 실패=graceful 문자열 (got {out2})")

    # U3 재귀 가드 — _delegable: 체인 재방문 금지 + 깊이 상한
    from api.broker.providers.agent import DELEGATION_MAX_DEPTH, AgentProvider

    prov = AgentProvider(session_factory=None, principal="machine", delegation_chain=("agt_self",))
    visited = SimpleNamespace(source="ui", active_version="v1", agent_id="agt_self", owner_id=None)
    fresh = SimpleNamespace(source="ui", active_version="v1", agent_id="agt_other", owner_id=None)
    check(prov._delegable(visited) is False, "U3 체인 내 재방문 id는 비위임(순환 차단)")
    check(prov._delegable(fresh) is True, "U3 새 id는 위임 가능")
    deep = AgentProvider(
        session_factory=None, principal="machine",
        delegation_chain=tuple(f"agt_{i}" for i in range(DELEGATION_MAX_DEPTH)),
    )
    check(deep._delegable(fresh) is False, f"U3 깊이 상한({DELEGATION_MAX_DEPTH}) 초과는 비위임")

    # U4 안전 불변식(적대 리뷰 P1 — 참조만으론 권한 안 열림). 노드가 `agent__{id}`를 참조하면
    # derive_pipeline_pool이 그 id를 config `capabilities`(=브로커 allowlist)에 넣는다. 하지만
    # allowlist는 _permitted의 **필요조건일 뿐**(allowlist ∩ RBAC) — RBAC 미허가 주체는 그 도구를
    # 못 만들고 못 부른다. 머신 토큰(str)은 RBAC deny-by-default라 이 공동 게이트를 실증한다
    # (MCP/RAG 풀 파생과 동일 posture — 참조가 정책 게이트를 우회하지 않음).
    from api.broker import build_broker

    denied = build_broker("machine", ["agt_victim"])  # allowlist엔 있으나 RBAC deny
    caps_denied = asyncio.run(denied.agent_capabilities())
    check(caps_denied == [], f"U4 RBAC 미허가면 allowlist에 있어도 agent cap 0 (got {caps_denied})")
    check(
        runtime.build_agent_tools(denied, caps_denied) == [],
        "U4 미허가 주체 → agent 도구 0(참조만으론 권한 안 열림 — allowlist∩RBAC)",
    )


# ================================================================ [H] 통합
async def http_checks() -> None:
    print("[H] 통합 — 풀 파생·실행 왕복·자기참조·eval 입구")
    import httpx
    from sqlalchemy import select

    from api.chat import derive_pipeline_pool
    from api.db import SessionLocal
    from api.main import app
    from api.models import User

    transport = httpx.ASGITransport(app=app)
    created: list[str] = []

    async def _chat(client, aid, text):
        acc, trace, error = [], None, None
        async with client.stream(
            "POST", f"/agents/{aid}/chat", json={"messages": [{"role": "user", "content": text}]}
        ) as resp:
            if resp.status_code != 200:
                return resp.status_code, "", None, None
            event = None
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
                    elif isinstance(obj, dict) and obj.get("error"):
                        error = obj["error"]
                    elif isinstance(obj, dict) and obj.get("text"):
                        acc.append(obj["text"])
        return 200, "".join(acc), trace, error

    async with httpx.AsyncClient(transport=transport, base_url="http://t", timeout=120) as c:
        # 슈퍼유저 쿠키 로그인 — 위임 브로커가 실 유저 principal에만 능력을 허가(머신 토큰 deny).
        login = await c.post(
            "/auth/login", data={"username": SUPER_EMAIL, "password": PW},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        check(login.status_code in (200, 204), f"SETUP 슈퍼유저 로그인(쿠키) (got {login.status_code})")
        async with SessionLocal() as s:
            super_user = (
                await s.execute(select(User).where(User.email == SUPER_EMAIL))
            ).scalar_one_or_none()
        check(super_user is not None, "SETUP 슈퍼유저 principal 확보")

        # 전문가(위임 대상) — 로컬 ui, 활성 버전 보유(위임 자격). mock-llm이 평문 답.
        r = await c.post("/agents", json={
            "name": f"v318-expert-{uuid.uuid4().hex[:6]}",
            "config": {"model": "mock-llm", "prompt": "너는 전문가다. 받은 질문에 답한다."},
        })
        check(r.status_code == 201, f"H0 전문가 생성 201 (got {r.status_code})")
        expert = r.json()
        expert_id = expert["agentId"]  # agt_...
        created.append(expert["id"])
        # 전문가 활성화(로컬 위임은 활성 버전 필수 — _delegable)
        g = (await c.get(f"/agents/{expert['id']}")).json()
        draft = next((v["version"] for v in g.get("versions", []) if v.get("status") == "draft"), None)
        if draft:
            await c.post(f"/agents/{expert['id']}/activate", json={"version": draft})

        # H1 풀 파생 — 노드 tools의 agent__{id} → capabilities 파생(저장 시 derive_pipeline_pool)
        agent_tool = f"agent__{expert_id}"
        cfg = {
            "model": "mock-llm", "prompt": "", "impl": "pipeline",
            "nodes": [{"name": "위임노드", "prompt": "전문가에게 물어라", "model": "mock-llm", "tools": [agent_tool]}],
        }
        derived = dict(cfg)
        await derive_pipeline_pool(derived)
        check(derived.get("capabilities") == [expert_id], f"H1 capabilities 파생 (got {derived.get('capabilities')})")

        # H2 실행 왕복 — 노드가 전문가 호출(mock-llm은 도구 base=agent_id 언급 시 호출).
        r = await c.post("/agents", json={"name": f"v318-pipe-{uuid.uuid4().hex[:6]}", "config": cfg})
        check(r.status_code == 201, f"H2 파이프라인 생성 201 (got {r.status_code}: {r.text[:200]})")
        pid = r.json()["id"]
        created.append(pid)
        status, text, tr, _e = await _chat(c, pid, f"{expert_id} 에게 위임해줘")
        check(status == 200, f"H2 채팅 200 (status={status})")
        broker_calls = (tr or {}).get("brokerCalls", [])
        check(len(broker_calls) > 0, f"H2 위임이 brokerCalls로 표면화 (got {broker_calls})")
        check(any(expert_id in json.dumps(bc, ensure_ascii=False) for bc in broker_calls),
              f"H2 brokerCalls에 전문가 id (got {broker_calls})")

        # H3 자기 참조 — 노드가 자기 id를 참조해도 무한 위임 없음(방문 집합 차단). 자기 id는 저장 후에야
        # 알 수 있으므로, 파이프라인 자신을 참조하도록 수정 저장 → 채팅이 무한루프 없이 종료.
        self_id = r.json()["agentId"]
        cfg_self = dict(cfg)
        cfg_self["nodes"] = [{"name": "자기위임", "prompt": "자신에게 물어라", "model": "mock-llm", "tools": [f"agent__{self_id}"]}]
        r = await c.put(f"/agents/{pid}", json={"name": None, "description": None, "config": cfg_self})
        check(r.status_code == 200, f"H3 자기참조 저장 200 (got {r.status_code})")
        status, _t, _tr, _e = await asyncio.wait_for(_chat(c, pid, f"{self_id} 에게 위임"), timeout=60)
        check(status == 200, "H3 자기참조도 무한루프 없이 200 종료(방문 집합 차단)")

        # H4 eval 입구 — 평가도 위임을 태운다(기본 노드 퇴화 아님). 전문가 참조 파이프라인으로 복원.
        from api.eval_runner import eval_run_agent

        r = await c.put(f"/agents/{pid}", json={"name": None, "description": None, "config": cfg})
        check(r.status_code == 200, "H4 전문가참조 복원 저장")
        obs = await eval_run_agent(uuid.UUID(pid), f"{expert_id} 에게 위임해줘", principal=super_user)
        check(not obs.get("error"), f"H4 eval 위임 실행 성공(error 0) (got {obs.get('detail')})")
        check(expert_id in json.dumps(obs.get("trace_nodes", []), ensure_ascii=False)
              or any("agent" in str(n) for n in obs.get("trace_nodes", [])),
              f"H4 eval 트레이스에 위임 흔적 (got {obs.get('trace_nodes')})")

        for a in created:
            await c.delete(f"/agents/{a}")


def main() -> None:
    unit_checks()
    _provision(create=True)
    try:
        asyncio.run(http_checks())
    finally:
        _provision(create=False)
    print(f"\n{len(_fails)} failed")
    if _fails:
        for f in _fails:
            print("  FAILED:", f)
        sys.exit(1)
    print("VERIFY318_OK — 노드 에이전트-호출(도구·브로커 경유·재귀 가드·입구 정합) 정착")


if __name__ == "__main__":
    main()

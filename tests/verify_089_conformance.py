"""스펙 089 검증 — 커스텀 에이전트 공통 인터페이스 준수 3상태 분류(순수 단위).

핵심 불변식:
  1) classify_runtime 매트릭스 — conforming / non_conforming(A2A) / config_error 3상태.
  2) get_agent_impl isinstance 게이트 — 등록만 되고 부적합/생성던짐이면 None(085 갭 봉합, fail-closed).
  3) resolve_agent_runtime 폴백 교정(교정3) — impl-없음→DefaultUiAgent, 선언한 미해결→AgentConfigError
     (DefaultUiAgent로 *만회 안 함* — 이게 089의 핵심 핀).
  4) 디스패치(resolve)와 분류(classify)가 *같은 게이트* — 모든 입력에서 일관(술어 단일 출처).

실행: python tests/verify_089_conformance.py
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))
sys.path.insert(0, os.path.join(ROOT, "packages", "agent", "src"))

from agent import runtime as agent_rt  # noqa: E402
from agent.runtime import (  # noqa: E402
    AgentConfigError,
    CustomAgent,
    DefaultUiAgent,
    classify_runtime,
    get_agent_impl,
    register_agent,
)
from agent.examples.plan_execute import PlanExecuteAgent  # noqa: E402

from api import chat as chat_mod  # noqa: E402

_fails: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


# 적대 픽스처: 등록은 되지만 공통 인터페이스에 부적합한 구현들(085 갭이 통과시키던 부류).
class _BadStub:
    """describe()/build_graph()가 없다 → CustomAgent 부적합(isinstance 실패)."""


class _ThrowingAgent:
    def __init__(self) -> None:
        raise RuntimeError("의도적 생성 실패")  # fail-closed 경로 핀

    def describe(self):  # pragma: no cover - 생성이 먼저 던진다
        ...

    def build_graph(self, ctx):  # pragma: no cover
        ...


def _resolve(source, impl):
    """chat.resolve_agent_runtime를 (raise | None | 인스턴스) 셋 중 하나로 정규화."""
    try:
        return chat_mod.resolve_agent_runtime({"source": source, "impl": impl})
    except AgentConfigError:
        return "RAISE"


def run() -> None:
    print("[089] 커스텀 에이전트 준수 3상태 분류")

    register_agent("bad_stub_089", _BadStub)
    register_agent("throws_089", _ThrowingAgent)

    # ---------------------------------------------------------------- C: classify_runtime 매트릭스
    print("\n[C] classify_runtime — 3상태")
    check(classify_runtime("ui", None) == "conforming", "C1 ui+impl없음 → conforming(default)")
    check(classify_runtime("ui", "") == "conforming", "C2 ui+빈impl → conforming(default)")
    check(classify_runtime("ui", "plan_execute") == "conforming", "C3 ui+적합 impl → conforming")
    check(classify_runtime("code", None) == "non_conforming", "C4 code(A2A) → non_conforming")
    check(classify_runtime("external", None) == "non_conforming", "C5 external(A2A) → non_conforming")
    # A2A는 impl 값과 무관하게 non_conforming(원격이 우선 — 인터페이스 미대상).
    check(classify_runtime("code", "plan_execute") == "non_conforming", "C6 code는 impl 무관 non_conforming")
    check(classify_runtime("ui", "does_not_exist") == "config_error", "C7 ui+미등록 키 → config_error")
    check(classify_runtime("ui", "bad_stub_089") == "config_error", "C8 ui+등록됐으나 부적합 → config_error(갭 봉합)")
    check(classify_runtime("ui", "throws_089") == "config_error", "C9 ui+생성던짐 → config_error(fail-closed)")

    # ---------------------------------------------------------------- G: get_agent_impl isinstance 게이트
    print("\n[G] get_agent_impl — isinstance 게이트(fail-closed)")
    check(get_agent_impl(None) is None, "G1 None 키 → None")
    check(get_agent_impl("does_not_exist") is None, "G2 미등록 키 → None")
    pe = get_agent_impl("plan_execute")
    check(isinstance(pe, PlanExecuteAgent) and isinstance(pe, CustomAgent), "G3 적합 키 → 적합 인스턴스")
    check(get_agent_impl("bad_stub_089") is None, "G4 등록됐으나 Protocol 부적합 → None(085 갭 봉합)")
    check(get_agent_impl("throws_089") is None, "G5 생성이 던짐 → None(fail-closed, 만회 없음)")

    # ---------------------------------------------------------------- R: resolve 폴백 교정(교정3 핵심 핀)
    print("\n[R] resolve_agent_runtime — 폴백 교정")
    check(isinstance(_resolve("ui", None), DefaultUiAgent), "R1 ui+impl없음 → DefaultUiAgent(default 유지)")
    check(isinstance(_resolve("ui", "plan_execute"), PlanExecuteAgent), "R2 ui+적합 impl → 커스텀")
    check(_resolve("code", None) is None, "R3 code(A2A) → None(원격 fallback)")
    check(_resolve("external", None) is None, "R4 external(A2A) → None(원격 fallback)")
    # 핵심: 선언한 미해결 impl은 DefaultUiAgent로 *만회하지 않는다* — raise.
    check(_resolve("ui", "does_not_exist") == "RAISE", "R5 ui+미등록 키 → AgentConfigError(default 만회 안 함)")
    check(_resolve("ui", "bad_stub_089") == "RAISE", "R6 ui+부적합 등록 → AgentConfigError(폴백 마스킹 없음)")
    check(_resolve("ui", "throws_089") == "RAISE", "R7 ui+생성던짐 → AgentConfigError")
    # AgentConfigError 메시지는 impl 키만(비밀 아님) — 누출 0.
    try:
        chat_mod.resolve_agent_runtime({"source": "ui", "impl": "does_not_exist"})
    except AgentConfigError as e:
        check(str(e) == "does_not_exist", "R8 에러 인자=impl 키(비밀 없음)")

    # ---------------------------------------------------------------- S: 디스패치 ↔ 분류 단일 게이트
    print("\n[S] resolve ↔ classify — 같은 게이트(술어 단일 출처)")
    cases = [
        ("ui", None), ("ui", ""), ("ui", "plan_execute"),
        ("code", None), ("external", None), ("code", "plan_execute"),
        ("ui", "does_not_exist"), ("ui", "bad_stub_089"), ("ui", "throws_089"),
    ]
    for source, impl in cases:
        cls = classify_runtime(source, impl)
        res = _resolve(source, impl)
        if cls == "conforming":
            ok = isinstance(res, CustomAgent)
        elif cls == "non_conforming":
            ok = res is None
        else:  # config_error
            ok = res == "RAISE"
        check(ok, f"S ({source},{impl!r}) classify={cls} ↔ resolve 일관")

    # 픽스처 정리(전역 레지스트리 오염 방지 — 다른 테스트 무영향).
    agent_rt._REGISTRY.pop("bad_stub_089", None)
    agent_rt._REGISTRY.pop("throws_089", None)


# ================================================================ [H] 실인프라 통합(ASGI + 실 DB)
async def http_checks() -> None:
    """rung ② — in-process ASGI + 실 DB seed: GET /agents conformance가 표대로이고, 미해결 impl
    에이전트로 채팅하면 설정-실패 SSE(default 응답 *아님*)가 나옴을 단언(폴백 마스킹 제거 증명)."""
    import json
    import uuid

    import httpx
    from api.auth import _token
    from api.main import app

    print("\n[H] 실인프라 통합 — GET /agents conformance + config_error 채팅 거부")
    auth = {"Authorization": f"Bearer {_token()}"}
    transport = httpx.ASGITransport(app=app)
    created: list[str] = []

    async with httpx.AsyncClient(
        transport=transport, base_url="http://t", headers=auth, timeout=120
    ) as c:
        # H1 ui(impl 없음) → conforming.
        r_ui = await c.post("/agents", json={
            "name": f"v089-ui-{uuid.uuid4().hex[:6]}",
            "config": {"model": "mock-llm", "persona": "", "historyDepth": 10},
        })
        check(r_ui.status_code == 201, f"H1 ui 생성 201 (got {r_ui.status_code})")
        ui_id = r_ui.json()["id"]
        created.append(ui_id)
        check(r_ui.json().get("conformance") == "conforming", "H1 ui+impl없음 → conformance=conforming")

        # H2 ui + 미해결 impl(저장 허용=합의 B) → config_error. 생성 응답·GET 둘 다 표대로.
        r_bad = await c.post("/agents", json={
            "name": f"v089-bad-{uuid.uuid4().hex[:6]}",
            "config": {"model": "mock-llm", "persona": "", "historyDepth": 10,
                       "impl": "does_not_exist_089"},
        })
        check(r_bad.status_code == 201, f"H2 미해결 impl 저장 허용 201(합의 B) (got {r_bad.status_code})")
        bad_id = r_bad.json()["id"]
        created.append(bad_id)
        check(r_bad.json().get("conformance") == "config_error",
              "H2 ui+미해결 impl → conformance=config_error(저장 응답)")
        r_get = await c.get(f"/agents/{bad_id}")
        check(r_get.json().get("conformance") == "config_error",
              "H2 GET /{id} 도 config_error(단일 헬퍼 파생, 입구 일관)")

        # H3 config_error 에이전트로 채팅 → 설정-실패 SSE(error 프레임), default 응답 *아님*.
        acc, err = [], None
        async with c.stream("POST", f"/agents/{bad_id}/chat",
                            json={"messages": [{"role": "user", "content": "안녕하세요"}]}) as resp:
            check(resp.status_code == 200, f"H3 config_error 채팅 status 200(SSE) (got {resp.status_code})")
            async for line in resp.aiter_lines():
                if line.startswith("data:"):
                    payload = line[5:].strip()
                    if payload in ("", "[DONE]"):
                        continue
                    try:
                        obj = json.loads(payload)
                    except Exception:
                        continue
                    if isinstance(obj, dict) and obj.get("error"):
                        err = obj["error"]
                    elif isinstance(obj, dict) and obj.get("text"):
                        acc.append(obj["text"])
        check(err is not None, "H3 채팅이 설정-실패 error 프레임을 냄(폴백 마스킹 제거)")
        check(not acc, f"H3 default 텍스트 응답이 *없음*(만회 안 함) (got {''.join(acc)[:40]!r})")
        # 089-F1(codex): config["impl"]은 관리자 임의 저장값 → 클라이언트 메시지에 *미반영*(서버 로그만).
        check(err is not None and "does_not_exist_089" not in err,
              f"H3 클라이언트 에러에 impl 원문 미노출(정보노출 0) (got {err!r})")

        # H4 시드 code/external 에이전트(있으면) → non_conforming. 원격은 in-process 인터페이스 미대상.
        r_list = await c.get("/agents")
        remotes = [a for a in r_list.json() if a.get("source") in ("code", "external")]
        if remotes:
            bad_remote = [a for a in remotes if a.get("conformance") != "non_conforming"]
            check(not bad_remote,
                  f"H4 모든 code/external 에이전트 → non_conforming (위반 {len(bad_remote)}개)")
        else:
            print("  ..  H4 시드에 code/external 에이전트 없음 — 단위 C4/C5가 분류를 핀")

        # 정리.
        for aid in created:
            await c.delete(f"/agents/{aid}")


async def main() -> None:
    run()
    await http_checks()
    if _fails:
        print(f"\nFAILED ({len(_fails)})")
        for m in _fails:
            print("  - " + m)
        sys.exit(1)
    print("\nALL GREEN (089 conformance — 단위 + 실인프라 통합)")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())

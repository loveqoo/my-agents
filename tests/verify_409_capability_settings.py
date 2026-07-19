"""verify_409 — 능력→설정 파생 단일화(스펙 409, 408 재구조화).

  U1 파생 파리티: 백엔드 화이트리스트·노드 정규화가 서술자 목록(SETTING_KEYS)에서 나온다
     (하드코딩 0 — 설정 추가=서술자 한 줄). 화이트리스트 밖 키는 저장/적용에서 드롭.
  U2 유효값 게이트(능력 AND 설정): thinking도 능력 게이트(408은 미게이트). streaming/thinking
     능력 false면 어느 층도 못 켠다.
  U3 노드 캐스케이드: 모델 → 에이전트 → **노드**. 노드 modelParams가 에이전트 위를 덮고, 노드
     미명시는 상속.
  H1 서술자 엔드포인트: GET /models/capabilities/descriptors == 정본 목록(FE 사본 없음).
  H2 노드별 오버라이드 저장/로드 왕복: 노드 modelParams가 config.nodes로 살아 폼 재로드에 실림.

실행: uv run --project packages/api python tests/_throwaway_server.py tests/verify_409_capability_settings.py
"""

import asyncio
import os
import sys
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))
sys.path.insert(0, os.path.join(ROOT, "packages", "agent", "src"))

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


async def unit_checks() -> None:
    from agent.capabilities import SETTING_KEYS, resolve_effective
    from api.chat_context_models import MODEL_PARAM_OVERRIDE_KEYS, _resolve_node_models
    from api.schemas.agents import AgentConfig

    # U1 파생 파리티 — 화이트리스트가 서술자에서 나온다(별도 하드코딩 아님).
    check(tuple(MODEL_PARAM_OVERRIDE_KEYS) == tuple(SETTING_KEYS), "U1a 화이트리스트=SETTING_KEYS 파생")
    check("stream" in SETTING_KEYS and "enable_thinking" in SETTING_KEYS, "U1b 설정 키 목록 존재")
    # U1c 노드 정규화가 화이트리스트만 보존(evil/temperature 드롭 — 설정 아님).
    cfg = AgentConfig(
        nodes=[{"prompt": "p", "modelParams": {"stream": False, "enable_thinking": True, "evil": 1, "temperature": 0.9}}]
    )
    check(
        cfg.nodes[0].get("modelParams") == {"stream": False, "enable_thinking": True},
        f"U1c 노드 modelParams 화이트리스트만 (got {cfg.nodes[0].get('modelParams')})",
    )

    # U2 유효값 게이트 — 능력 AND 설정. 능력 false면 어느 층도 못 켬.
    check(resolve_effective("streaming", {"streaming": True}, {}, {}) is True, "U2a streaming 능력 true 기본 켬")
    check(resolve_effective("streaming", {"streaming": False}, {"stream": True}, {}) is False, "U2b streaming 능력 false→못 켬")
    check(resolve_effective("thinking", {"thinking": True}, {"enable_thinking": True}, {}) is True, "U2c thinking 능력 true+want→켬")
    check(resolve_effective("thinking", {"thinking": False}, {"enable_thinking": True}, {}) is False, "U2d thinking 능력 false→못 켬(408은 미게이트였음)")
    check(resolve_effective("thinking", {}, {"enable_thinking": True}, {}) is False, "U2e thinking 능력 미선언(기본 false)→못 켬")

    # U3 노드 캐스케이드 — DB 미접촉(노드에 명시 모델 없음 → 상속 default_cfg에 노드 층만 덮음).
    # default_cfg는 **에이전트 해석본**(프로덕션에선 _resolve_model이 에이전트 modelParams를 이미 병합).
    # 여기선 에이전트가 enable_thinking=on을 켠 상태로 가정(default_cfg params에 반영).
    default_cfg = {"base_url": "b", "model_id": "m", "params": {"stream": True, "enable_thinking": True}}
    nodes = [
        {"prompt": "A", "modelParams": {"stream": False}},  # 노드가 에이전트 위 stream만 덮음
        {"prompt": "B"},  # 미명시 → 상속
    ]
    resolved = await _resolve_node_models(None, nodes, default_cfg, None, agent_cfg=None)
    a_params = resolved[0]["model_cfg"]["params"]
    b_params = resolved[1]["model_cfg"]["params"]
    check(a_params.get("stream") is False, f"U3a 노드A stream=off(노드가 덮음) (got {a_params.get('stream')})")
    check(a_params.get("enable_thinking") is True, f"U3b 노드A enable_thinking=on(에이전트 상속 — 노드 미덮음) (got {a_params.get('enable_thinking')})")
    check(b_params.get("stream") is True, f"U3c 노드B stream=on(에이전트 상속 — 노드 미명시) (got {b_params.get('stream')})")

    # U4 세션 > 노드(codex P1① — 세션이 노드 층 뒤에 재적용돼 이긴다). 노드 stream=off + 세션 stream=on → on.
    resolved2 = await _resolve_node_models(
        None,
        [{"prompt": "A", "modelParams": {"stream": False}}],
        {"base_url": "b", "model_id": "m", "params": {"stream": True}},
        None,
        agent_cfg=None,
        session_mp={"stream": True},
    )
    check(
        resolved2[0]["model_cfg"]["params"].get("stream") is True,
        f"U4 세션 stream=on이 노드 stream=off를 이김(최상위 층) (got {resolved2[0]['model_cfg']['params'].get('stream')})",
    )

    # U5 문자열 "false" 게이트 우회 차단(codex P1②) — clean_* 드롭 + resolve_effective _as_bool.
    from agent.capabilities import clean_capabilities, clean_setting_params

    check(clean_capabilities({"streaming": "false", "thinking": "false"}) == {}, "U5a 비-bool 능력 드롭")
    check(clean_setting_params({"stream": "false", "enable_thinking": "true", "evil": True}) == {}, "U5b 비-bool/미지 설정 드롭")
    check(
        resolve_effective("thinking", {"thinking": "false"}, {"enable_thinking": True}) is False,
        "U5c 문자열 능력('false')은 thinking 못 켬(bool('false')==True 함정 봉인)",
    )


async def main() -> None:
    await unit_checks()
    from agent.capabilities import SETTING_KEYS

    tag = f"v409-{uuid.uuid4().hex[:6]}"
    async with httpx.AsyncClient(base_url=BASE, headers=_auth(), timeout=120) as c:
        # H1 서술자 엔드포인트 = 정본
        r = await c.get("/models/capabilities/descriptors")
        check(r.status_code == 200, f"H1a 서술자 200 (got {r.status_code})")
        descs = r.json()
        caps = {d["cap"] for d in descs}
        check({"streaming", "thinking", "vision"} <= caps, f"H1b 능력 3종 노출 (got {caps})")
        tunable = {d["setting"] for d in descs if d["setting"]}
        check(tunable == set(SETTING_KEYS), f"H1c 튜닝 설정=SETTING_KEYS 파리티 (got {tunable})")
        vis = next(d for d in descs if d["cap"] == "vision")
        check(vis["setting"] is None, "H1d vision은 능력만(setting=None)")

        # H2 노드별 오버라이드 저장/로드 왕복
        ag = (
            await c.post(
                "/agents",
                json={
                    "name": f"{tag}-pipe",
                    "config": {
                        "impl": "pipeline",
                        "nodes": [
                            {"prompt": "분석해", "model": "mock-llm", "modelParams": {"stream": False}},
                            {"prompt": "정리해", "model": "mock-llm"},
                        ],
                    },
                },
            )
        ).json()
        try:
            got = (await c.get(f"/agents/{ag['id']}")).json()
            nodes = got.get("config", {}).get("nodes") or got.get("nodes") or []
            n0mp = nodes[0].get("modelParams") if nodes else None
            check(n0mp == {"stream": False}, f"H2a 노드0 modelParams 저장/로드 왕복 (got {n0mp})")
            check("modelParams" not in (nodes[1] if len(nodes) > 1 else {}), "H2b 노드1 미명시=키 없음(상속)")
        finally:
            await c.delete(f"/agents/{ag['id']}")

    print(f"\n{passed} passed, {len(_fails)} failed")
    if _fails:
        sys.exit(1)
    print("VERIFY409_OK")


if __name__ == "__main__":
    asyncio.run(main())

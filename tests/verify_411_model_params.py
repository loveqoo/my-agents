"""verify_411 — 모델 튜닝 파라미터 N-확장 단일화(스펙 411).

대부분 서버 불필요(결정적 단위) — 서술자 파생·유효값·클램프·wire 배선·temperature 흡수.
H1만 엔드포인트(throwaway) 필요.

  U1 서술자: PARAM_KEYS·descriptors_public {capabilities,params} 형태.
  U2 유효값: resolve_effective(bool 게이트)·resolve_number(클램프).
  U3 clean_model_params: bool·number 타입·범위 검증(미지/타입불일치 드롭).
  U4 build_chat_openai wire: top(temperature/top_p/max_tokens)·extra_body(enable_thinking/repetition_penalty)·disable_streaming.
  U5 temperature 흡수: _fold_temperature 이관(legacy→modelParams·None 제외·modelParams 우선).
  U6 캐스케이드: _apply_agent_model_params가 number 파라미터 병합.
  H1 엔드포인트: GET /models/capabilities/descriptors == {capabilities,params}.

실행: uv run --project packages/api python tests/_throwaway_server.py tests/verify_411_model_params.py
"""

import os
import sys

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


def unit_checks() -> None:
    from agent.capabilities import (
        PARAM_KEYS,
        clean_model_params,
        descriptors_public,
        resolve_effective,
        resolve_number,
    )

    # U1 서술자
    check(
        {"stream", "enable_thinking", "temperature", "top_p", "max_tokens", "repetition_penalty"} <= set(PARAM_KEYS),
        f"U1a PARAM_KEYS 6종 (got {PARAM_KEYS})",
    )
    d = descriptors_public()
    check(set(d.keys()) == {"capabilities", "params"}, f"U1b descriptors {{capabilities,params}} (got {list(d.keys())})")
    keys = {p["key"] for p in d["params"]}
    check("temperature" in keys and "repetition_penalty" in keys, "U1c params에 temperature·repetition_penalty")

    # U2 유효값
    check(resolve_effective("stream", {"streaming": True}, {}, {}) is True, "U2a stream 능력 true")
    check(resolve_effective("enable_thinking", {"thinking": False}, {"enable_thinking": True}, {}) is False, "U2b thinking 능력 false→못켬")
    check(resolve_number("temperature", {}, {}) == 0.7, f"U2c temperature 기본 0.7 (got {resolve_number('temperature', {}, {})})")
    check(resolve_number("temperature", {"temperature": 1.5}, {"temperature": 0.3}) == 1.5, "U2d 세션>모델 우선")
    check(resolve_number("top_p", {"top_p": 2.0}, {}) == 1.0, "U2e top_p 클램프 2.0→1.0")
    check(resolve_number("max_tokens", {}, {}) == 0, "U2f max_tokens 기본 0(미설정)")

    # U3 clean
    c = clean_model_params({"temperature": 3.0, "stream": False, "repetition_penalty": 1.2, "evil": 1, "top_p": "x"})
    check(c == {"temperature": 2.0, "stream": False, "repetition_penalty": 1.2}, f"U3 clean 타입·범위·드롭 (got {c})")

    # U4 build_chat_openai wire
    from agent.model import build_chat_openai

    cli = build_chat_openai(
        {
            "base_url": "http://x/v1",
            "api_key": "k",
            "model_id": "m",
            "capabilities": {"streaming": True, "thinking": True},
            # max_tokens는 사고 바닥(8192, 스펙 427) 위 값으로 둔다 — 그래야 wire 경로만 검증되고
            # bump가 개입 안 한다(bump 자체는 U4e에서 검증). 사고 ON + 바닥 미만은 U4e가 다룬다.
            "params": {"temperature": 0.9, "top_p": 0.8, "max_tokens": 16384, "repetition_penalty": 1.15, "enable_thinking": True},
        }
    )
    check(cli.temperature == 0.9, f"U4a temperature=top-level (got {cli.temperature})")
    check(getattr(cli, "top_p", None) == 0.8 and getattr(cli, "max_tokens", None) == 16384, "U4b top_p·max_tokens=top-level")
    eb = cli.extra_body or {}
    check(eb.get("repetition_penalty") == 1.15, f"U4c repetition_penalty=extra_body (got {eb.get('repetition_penalty')})")
    check(eb.get("chat_template_kwargs", {}).get("enable_thinking") is True, "U4d enable_thinking=extra_body chat_template_kwargs")
    # U4e 사고 바닥(스펙 427) — 사고 ON + 명시적으로 작은 max_tokens(512)면 바닥값(8192)으로 대체해
    # 답 굶김을 막는다. 사고 OFF면 그대로, 미설정(0)이면 미개입(서버 기본)은 thinking_budget_applied 단위로.
    cli_bump = build_chat_openai(
        {"base_url": "http://x/v1", "api_key": "k", "model_id": "m",
         "capabilities": {"thinking": True},
         "params": {"max_tokens": 512, "enable_thinking": True}}
    )
    check(getattr(cli_bump, "max_tokens", None) == 8192, f"U4e 사고 바닥 512→8192 (got {getattr(cli_bump, 'max_tokens', None)})")
    from agent.model import thinking_budget_applied
    check(thinking_budget_applied({"thinking": True}, {}, {"enable_thinking": True, "max_tokens": 512}) == 8192, "U4e-2 bump 값 8192")
    check(thinking_budget_applied({"thinking": True}, {}, {"enable_thinking": True, "max_tokens": 0}) is None, "U4e-3 미설정(0)은 미개입")
    check(thinking_budget_applied({"thinking": True}, {}, {"enable_thinking": False, "max_tokens": 512}) is None, "U4e-4 사고 OFF 미개입")

    # U5 temperature 흡수
    from api.chat_context_loader import _fold_temperature

    cfg = {"model": "m", "temperature": 0.3}
    _fold_temperature(cfg)
    check(cfg.get("modelParams") == {"temperature": 0.3} and "temperature" not in cfg, "U5a legacy→modelParams 이관·특례키 제거")
    cfg2 = {"temperature": 0.3, "modelParams": {"temperature": 0.9}}
    _fold_temperature(cfg2)
    check(cfg2["modelParams"]["temperature"] == 0.9, "U5b modelParams 우선(신규 저장 보존)")
    cfg3 = {"temperature": None}
    _fold_temperature(cfg3)
    check("temperature" not in (cfg3.get("modelParams") or {}), "U5c None(자동)은 이관 안 함")

    # U6 캐스케이드
    from api.chat_context_models import _apply_agent_model_params

    mc = _apply_agent_model_params(
        {"base_url": "b", "model_id": "m", "params": {}},
        {"modelParams": {"temperature": 0.4, "top_p": 0.8, "repetition_penalty": 1.1}},
    )
    check(
        mc["params"] == {"temperature": 0.4, "top_p": 0.8, "repetition_penalty": 1.1},
        f"U6 modelParams→model_cfg.params 병합 (got {mc['params']})",
    )

    # U7 세션 최상위(codex P1) — 세션 overrides.modelParams.temperature가 에이전트 modelParams.temperature를
    # 이긴다(per-key 병합). 레거시 overrides.temperature 특례 키는 은퇴(허용목록 밖 — 드롭).
    from api.chat_context_loader import _OVERRIDE_ALLOWED
    from api.chat_context_overrides import _apply_overrides

    class _FakeAgent:
        source = "ui"

    check("temperature" not in _OVERRIDE_ALLOWED, "U7a 레거시 temperature 세션 특례 키 은퇴(허용목록 밖)")
    cfg7 = {"model": "m", "modelParams": {"temperature": 0.9}}
    out7, _p, _n, _pt = _apply_overrides(
        cfg7, "", {"modelParams": {"temperature": 0.2}}, _FakeAgent(), _OVERRIDE_ALLOWED
    )
    check(
        out7["modelParams"].get("temperature") == 0.2,
        f"U7b 세션 modelParams.temperature가 저장값을 이김 (got {out7['modelParams'].get('temperature')})",
    )

    # U8 유한수 거부(codex P2③) — NaN/Infinity는 clean/resolve에서 드롭(int() 예외·무의미 클램프 차단).
    check(clean_model_params({"temperature": float("nan"), "max_tokens": float("inf")}) == {}, "U8a NaN/Inf 드롭(clean)")
    check(resolve_number("temperature", {"temperature": float("inf")}, {}) == 0.7, "U8b Inf 무시→기본값(resolve)")


def main() -> None:
    unit_checks()
    try:
        with httpx.Client(base_url=BASE, headers=_auth(), timeout=30) as c:
            r = c.get("/models/capabilities/descriptors")
            check(r.status_code == 200, f"H1a 엔드포인트 200 (got {r.status_code})")
            body = r.json()
            check(
                isinstance(body, dict) and "capabilities" in body and "params" in body,
                f"H1b {{capabilities,params}} 형태 (got {list(body) if isinstance(body, dict) else type(body)})",
            )
    except Exception as e:  # noqa: BLE001
        check(False, f"H1 엔드포인트 예외: {e}")

    print(f"\n{passed} passed, {len(_fails)} failed")
    if _fails:
        sys.exit(1)
    print("VERIFY411_OK")


if __name__ == "__main__":
    main()

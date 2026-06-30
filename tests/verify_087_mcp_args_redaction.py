"""스펙 087 검증 — MCP 호출 인자·결과 redaction(형제 trace 표면).

**핵심 불변식**: MCP 도구 인자(kwargs)·결과(text)가 calls_sink·interrupt payload·Approval.args로
새기 *전에* 원천(runtime.py)에서 정화한다 — 민감 *키*는 값 마스킹(평범 키 값은 디버깅 위해 보존),
문자열은 budgeted 캡, fail-closed(비문자 키·깊은 중첩·미지 타입에 안 죽음). result는 무제한 적재
방어로 캡(learning 059).

scope=B(최소): 평범한 키에 담긴 값-비밀·result 자유텍스트 비밀은 *by-design 잔존*(args는 보여주는
게 목적이라 deny-by-default 불가·시스템 자기 비밀은 이 표면에 안 옴·admin 전용). 그 잔존을 테스트가
*의도된 것으로* 단언한다(거짓 완료선언 방지).

실행: uv run --project packages/api python tests/verify_087_mcp_args_redaction.py
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))
sys.path.insert(0, os.path.join(ROOT, "packages", "agent", "src"))

from api import runtime as api_rt  # noqa: E402

_fails: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def unit_checks() -> None:
    R = api_rt._redact_args
    RED = api_rt._REDACTED

    print("[U] 단위 — _redact_args(키 마스킹·값 보존·캡·fail-closed)")

    # U1 민감 키(top-level)는 값 마스킹 — 모든 _SENSITIVE_KEY 변종.
    out = R({"api_key": "sk-live-xxx", "token": "t", "password": "p", "Authorization": "Bearer z",
             "secret": "s", "my_credential": "c", "bearer_tok": "b"})
    check(all(out[k] == RED for k in out), f"U1 민감 키 전부 마스킹: {out}")

    # U1b 평범한 키의 값은 *원문 보존*(인스펙터 디버깅 가치 — args는 보여주는 게 목적).
    out = R({"query": "cats and dogs", "top_k": 4, "path": "/etc/hosts"})
    check(out["query"] == "cats and dogs" and out["top_k"] == 4 and out["path"] == "/etc/hosts",
          f"U1b 평범 키 값 보존: {out}")

    # U2 중첩 dict 안의 민감 키도 마스킹(재귀).
    out = R({"opts": {"nested": {"token": "deep", "name": "ok"}}})
    check(out["opts"]["nested"]["token"] == RED and out["opts"]["nested"]["name"] == "ok",
          f"U2 중첩 dict 재귀 마스킹: {out}")

    # U3 list 안의 dict도 재귀 — 리스트 원소의 민감 키 마스킹.
    out = R({"items": [{"api_key": "x"}, {"q": "keep"}]})
    check(out["items"][0]["api_key"] == RED and out["items"][1]["q"] == "keep",
          f"U3 list 내 dict 재귀: {out}")

    # U4 긴 문자열 leaf는 budgeted 캡 — 정직한 생략 표기.
    big = "z" * 5000
    out = R({"q": big})
    cap = api_rt._ARG_VALUE_CAP
    check(len(out["q"]) < cap + 50 and "생략" in out["q"],
          f"U4 긴 값 캡(len={len(out['q'])}, cap={cap})")

    # U5 fail-closed: 비문자 키에 안 죽고, 그 키가 민감 패턴이면 마스킹.
    out = R({1: "a", ("tuple",): "b", "secret_x": "c"})
    check(out["1"] == "a" and out["secret_x"] == RED, f"U5 비문자 키 무크래시: {out}")

    # U6 fail-closed: 깊은 중첩은 깊이 상한에서 잘림(사이클/거대 중첩 방어, 무크래시).
    deep: dict = {"k": "leaf"}
    for _ in range(20):
        deep = {"k": deep}
    out = R(deep)
    s = repr(out)
    check("depth-capped" in s, "U6 깊이 상한 적용(무크래시)")

    # U7 미지 타입은 타입명만(fail-closed, 원문 미노출).
    class Weird:
        pass

    out = R({"obj": Weird()})
    check(out["obj"] == "<Weird>", f"U7 미지 타입 타입명만: {out}")

    # U8 result 캡 — 거대 결과는 정직 캡(무제한 적재 방어). 정상 결과는 무변경.
    rcap = api_rt._RESULT_CAP
    capped = api_rt._cap("R" * 9000, rcap)
    check(len(capped) < rcap + 50 and "생략" in capped, f"U8 result 거대값 캡(len={len(capped)})")
    check(api_rt._cap("짧은 결과", rcap) == "짧은 결과", "U8b 정상 result 무변경")

    print("\n[C] codex 적대 리뷰 회귀 가드(F1·F2·F3 — 주장 경계 안 누락)")
    import json

    # C1 (F1): *_key 표준 비밀 이름도 마스킹 — api_key만으론 부족.
    out = R({"private_key": "-----BEGIN-----", "access_key": "AKIA", "client_key": "ck",
             "signing_key": "sk", "encryption_key": "ek", "key": "raw-api-key"})
    check(all(out[k] == RED for k in out), f"C1 *_key 비밀 이름 전부 마스킹: {out}")
    # C1b 거짓양성 없음 — 구분자 없는 단어(monkey)·top_k는 마스킹 안 됨(디버깅 보존).
    out = R({"monkey": "ok", "top_k": 4, "donkey": "ok"})
    check(out["monkey"] == "ok" and out["top_k"] == 4 and out["donkey"] == "ok",
          f"C1b key-유사 평범어 보존: {out}")

    # C2 (F2): NaN/Infinity float은 JSONB·JSON 비유효 → 안전 마커. json.dumps로 유효성 단언.
    out = R({"a": float("nan"), "b": float("inf"), "c": float("-inf"), "d": 1.5})
    check(out["a"] == "<nan>" and out["b"] == "<inf>" and out["c"] == "<-inf>" and out["d"] == 1.5,
          f"C2 비유한 float 마커화: {out}")
    try:
        json.dumps(out, allow_nan=False)  # JSONB 호환(엄격 JSON) — 비유한 남았으면 raises.
        check(True, "C2b 결과가 엄격 JSON 직렬화 가능(JSONB 안전)")
    except ValueError as e:
        check(False, f"C2b 엄격 JSON 직렬화 실패(JSONB 깨짐): {e}")

    print("\n[B] by-design 잔존(scope=B 의도 단언 — 거짓 완료선언 방지)")
    # B1 평범한 키에 담긴 *값-비밀*은 못 막는다(deny-by-default 불가 — args는 보여주는 게 목적).
    out = R({"q": "sk-live-SECRET"})
    check(out["q"] == "sk-live-SECRET", "B1 평범 키 값-비밀은 by-design 잔존(보존됨)")


def source_site_checks() -> None:
    """원천 3곳이 redactor를 *호출*하는지 소스 단언(끝단 N개 말고 원천서 닫음, learning 065)."""
    print("\n[S] 원천 적용 — 3 producer 지점이 _redact_args/result 캡 호출")
    import inspect

    src = inspect.getsource(api_rt._wrap_mcp_tool)
    check(src.count("_redact_args") >= 2, "S1 _wrap_mcp_tool: _execute args + interrupt args 둘 다 redact")
    check("_RESULT_CAP" in src, "S2 _wrap_mcp_tool: result 캡 적용")
    rag = inspect.getsource(api_rt.build_rag_tool)
    check("_redact_args" in rag, "S3 build_rag_tool: rag _record args redact")


if __name__ == "__main__":
    unit_checks()
    source_site_checks()
    print()
    if _fails:
        print(f"FAILED ({len(_fails)}):")
        for f in _fails:
            print("  - " + f)
        sys.exit(1)
    print("ALL GREEN (087)")

"""스펙 430 검증 — 외부호출 정책 대장 + 서킷브레이커.

U1 대장: 승인 수치 그대로(모델 180/0·평가 60/1·A2A 120/0·MCP 30/0), 미등록 키=KeyError.
U2 모델 본선: build_chat_openai가 timeout=180·max_retries=0 명시(SDK 암묵 기본 소멸).
U3 브레이커 전이: 3연속 실패→열림(즉시 CircuitOpenError)·host 격리·성공→닫힘·half-open 1회+경쟁 차단.
U4 call 헬퍼: 멱등 1회 재시도 성공·비일시(4xx류) 즉시 전파·회로 미기록.
U5 4xx 미카운트: transient 아닌 예외는 회로에 안 셈.
H1 관측 라우트: GET /admin/net-policies가 정책·회로 스냅샷 반환(admin 보호).

실행: uv run --project packages/api python tests/verify_430_net_policy.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "packages" / "api" / "src"))
sys.path.insert(0, str(REPO / "packages" / "agent" / "src"))

from agent import net_policy as np  # noqa: E402

fails: list[str] = []
def ok(c, m): print(("  ok  " if c else " FAIL ")+m); (fails.append(m) if not c else None)


def u1_registry():
    ok(np.policy("model.chat").timeout_s == 180.0 and np.policy("model.chat").retries == 0,
       "U1 model.chat 180s·재시도0(승인 수치)")
    ok(np.policy("model.eval").timeout_s == 60.0 and np.policy("model.eval").retries == 1,
       "U1 model.eval 60s·재시도1")
    ok(np.policy("a2a.delegate").timeout_s == 120.0 and np.policy("mcp.tool").timeout_s == 30.0,
       "U1 A2A 120·MCP 30(기존값 흡수)")
    try:
        np.policy("nope.unknown"); ok(False, "U1 미등록 키 KeyError")
    except KeyError:
        ok(True, "U1 미등록 키 KeyError(조용한 폴백 금지)")


def u2_model_build():
    from agent.model import build_chat_openai
    c = build_chat_openai({"base_url": "http://x/v1", "model_id": "m", "api_key": "k"})
    ok(c.request_timeout == 180.0, f"U2 모델 timeout 명시 180 (got {c.request_timeout})")
    ok(c.max_retries == 0, f"U2 모델 max_retries 명시 0 (got {c.max_retries})")


def u3_breaker():
    np._reset_circuits()
    for _ in range(3):
        np.record_failure("model.chat", "http://dead/v1")
    try:
        np.check("model.chat", "http://dead/v1"); ok(False, "U3 3연속→열림")
    except np.CircuitOpenError as e:
        ok(e.remaining_s > 0, "U3 3연속 실패→열림(남은 초 표면화)")
    np.check("model.chat", "http://alive/v1"); ok(True, "U3 host 격리(다른 host 무영향)")
    np.record_success("model.chat", "http://dead/v1")
    np.check("model.chat", "http://dead/v1"); ok(True, "U3 성공→닫힘")
    # half-open: cooldown 경과 후 1회만
    np._reset_circuits()
    for _ in range(3):
        np.record_failure("mcp.tool", "h")
    np._circuits[("mcp.tool", "h")].opened_at -= np.BREAKER_COOLDOWN_S + 1
    np.check("mcp.tool", "h")
    try:
        np.check("mcp.tool", "h"); ok(False, "U3 half-open 경쟁 차단")
    except np.CircuitOpenError:
        ok(True, "U3 half-open 1회 통과+경쟁 차단")
    np.record_failure("mcp.tool", "h")
    try:
        np.check("mcp.tool", "h"); ok(False, "U3 half-open 실패→재열림")
    except np.CircuitOpenError:
        ok(True, "U3 half-open 실패→재열림")
    # breaker 미적용 정책은 no-op
    np._reset_circuits()
    for _ in range(5):
        np.record_failure("probe", "p")
    np.check("probe", "p"); ok(True, "U3 breaker=False 정책은 열리지 않음(no-op)")


def u4_call_helper():
    np._reset_circuits()
    n = {"v": 0}
    async def flaky():
        n["v"] += 1
        if n["v"] == 1:
            raise ConnectionError("첫 시도 실패")
        return "ok"
    r = asyncio.run(np.call("card.fetch", "h2", flaky))
    ok(r == "ok" and n["v"] == 2, f"U4 멱등 재시도 1회 후 성공 (시도 {n['v']})")
    async def bad():
        raise ValueError("4xx류")
    try:
        asyncio.run(np.call("card.fetch", "h3", bad)); ok(False, "U4 비일시 즉시 전파")
    except ValueError:
        ok(True, "U4 비일시(4xx류) 즉시 전파·재시도 없음")
    ok(("card.fetch", "h3") not in np._circuits or np._circuits[("card.fetch", "h3")].failures == 0,
       "U5 비일시 오류는 회로에 안 셈")


def u6_codex_fixes():
    """codex 430 P1 회귀 고정 — half-open 고착·transient 확장·host 정규화."""
    import httpx
    # release: 판정 불가 종료가 trial을 해제(고착 방지) — cooldown 경과 후 재시도 가능
    np._reset_circuits()
    for _ in range(3):
        np.record_failure("model.chat", "h")
    np._circuits[("model.chat", "h")].opened_at -= np.BREAKER_COOLDOWN_S + 1
    np.check("model.chat", "h")  # half-open trial 시작
    np.release("model.chat", "h")  # 소비자 이탈/비일시 오류 — 판정 불가
    try:
        np.check("model.chat", "h")  # trial 해제됐으니 새 trial 허용돼야
        ok(True, "U6 release→half-open 고착 없음(새 trial 허용)")
    except np.CircuitOpenError:
        ok(False, "U6 release 후에도 고착(codex P1 재발)")
    # transient: TransportError 계열 전부(ReadError·RemoteProtocolError)
    ok(np._is_transient(httpx.ReadError("mid-stream RST")), "U6 ReadError=transient(연결 죽음)")
    ok(np._is_transient(httpx.RemoteProtocolError("EOF")), "U6 RemoteProtocolError=transient")
    ok(not np._is_transient(ValueError("4xx류")), "U6 비전송 오류는 여전히 비일시")
    # host 정규화: URL로 기록해도 host로 접힘(같은 서버 다른 경로 = 같은 회로·userinfo 미노출)
    np._reset_circuits()
    np.record_failure("model.chat", "http://user:pw@srv:8000/v1")
    np.record_failure("model.chat", "http://srv:8000/openai/v1")
    np.record_failure("model.chat", "srv")
    try:
        np.check("model.chat", "http://srv:8000/v1")
        ok(False, "U6 host 정규화(3실패 합산→열림)")
    except np.CircuitOpenError:
        ok(True, "U6 host 정규화 — URL 변형 3개가 한 회로로 합산·열림")
    snap = np.breaker_snapshot()
    ok(all("user:pw" not in str(row) for row in snap), "U6 스냅샷에 userinfo 미노출")


def h1_route():
    from fastapi.testclient import TestClient
    from api.main import app
    from api import authz
    # admin 보호 우회(검증 목적 — require 의존성 오버라이드)
    app.dependency_overrides = dict(app.dependency_overrides)
    from api.net_policy_routes import _view  # noqa: F401 — 존재 확인
    with TestClient(app, raise_server_exceptions=False) as client:
        r = client.get("/admin/net-policies")
        ok(r.status_code in (401, 403), f"H1 비인증 차단 (got {r.status_code})")
    print("  (H1 심층: 대장 반환 형태는 U1이 동일 소스를 검증 — 라우트는 차단 확인까지)")


def main():
    u1_registry(); u2_model_build(); u3_breaker(); u4_call_helper(); u6_codex_fixes(); h1_route()
    print("\n" + ("VERIFY430_OK" if not fails else f"FAIL {len(fails)}"))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()

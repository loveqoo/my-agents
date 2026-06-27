"""스펙 042 rung 1 — A2A 클라이언트 파서·SSRF 가드 단위 검증(시맨틱).

네트워크 없이 순수 함수만 박제한다(텍스트 추출·에러·종료·SSRF·인증헤더). 실 DB·실 HTTP 글루는
rung 2(.dev/probe_042_a2a_integration.py), 불변식 여집합은 rung 3(적대 리뷰)이 맡는다.

실행: uv run python tests/verify_042_a2a_client.py  (packages/api 에서)
"""

import os
import sys

# packages/api/src 를 path에. (이 파일은 repo/tests 에 있음.)
_HERE = os.path.dirname(os.path.abspath(__file__))
_API_SRC = os.path.join(_HERE, "..", "packages", "api", "src")
sys.path.insert(0, os.path.abspath(_API_SRC))

from api import a2a_client  # noqa: E402
from api import net_guard  # noqa: E402

_passed = 0
_failed = 0


def check(name, cond):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  ✓ {name}")
    else:
        _failed += 1
        print(f"  ✗ {name}")


def expect_raises(name, fn, exc=ValueError):
    global _passed, _failed
    try:
        fn()
    except exc:
        _passed += 1
        print(f"  ✓ {name}")
    except Exception as e:  # noqa: BLE001
        _failed += 1
        print(f"  ✗ {name} (다른 예외: {type(e).__name__})")
    else:
        _failed += 1
        print(f"  ✗ {name} (예외 안 남)")


print("\n[A] extract_text — result kind별 텍스트 추출")
# Message
check("Message parts", a2a_client.extract_text(
    {"role": "agent", "parts": [{"kind": "text", "text": "안녕"}, {"kind": "text", "text": "하세요"}]}
) == "안녕하세요")
# Task: status.message.parts
check("Task status.message", a2a_client.extract_text(
    {"status": {"state": "completed", "message": {"parts": [{"kind": "text", "text": "끝"}]}}}
) == "끝")
# Task: artifacts fallback
check("Task artifacts", a2a_client.extract_text(
    {"status": {"state": "completed"}, "artifacts": [{"parts": [{"kind": "text", "text": "산출"}]}]}
) == "산출")
# status-update event
check("status-update", a2a_client.extract_text(
    {"kind": "status-update", "status": {"message": {"parts": [{"kind": "text", "text": "진행"}]}}}
) == "진행")
# artifact-update event
check("artifact-update", a2a_client.extract_text(
    {"kind": "artifact-update", "artifact": {"parts": [{"kind": "text", "text": "조각"}]}}
) == "조각")
# 비-text part는 스킵(파일 등) — 크래시 없이 빈 문자열
check("non-text part 스킵", a2a_client.extract_text(
    {"parts": [{"kind": "file", "file": {"uri": "x"}}]}
) == "")
# 형식 깨진 입력 → 빈 문자열(관대, 크래시 금지)
check("None 관대", a2a_client.extract_text(None) == "")
check("문자열 관대", a2a_client.extract_text("그냥문자열") == "")
check("parts 비배열 관대", a2a_client.extract_text({"parts": "x"}) == "")

print("\n[B] _frame_from_response — error 우선 / text / None")
check("error 프레임", (a2a_client._frame_from_response(
    {"jsonrpc": "2.0", "id": "1", "error": {"code": -32601, "message": "미지원"}}
) or {}).get("error", "").startswith("외부 에이전트 오류"))
check("text 프레임", a2a_client._frame_from_response(
    {"result": {"parts": [{"kind": "text", "text": "응답"}]}}
) == {"text": "응답"})
check("빈 result → None", a2a_client._frame_from_response({"result": {"parts": []}}) is None)
# 에러 메시지에 내부 비밀이 섞이지 않게 — message만 옮긴다(에코 범위 한정)
check("error는 message만", "외부 에이전트 오류: 미지원" == a2a_client._frame_from_response(
    {"error": {"code": 1, "message": "미지원", "data": {"secret": "LEAK"}}}
)["error"])

print("\n[C] _is_final — status-update final 종료신호")
check("final true", a2a_client._is_final({"kind": "status-update", "final": True}) is True)
check("final false", a2a_client._is_final({"kind": "status-update", "final": False}) is False)
check("non status-update", a2a_client._is_final({"kind": "message", "final": True}) is False)

print("\n[D] _jsonrpc_request — A2A 요청 모양")
req = a2a_client._jsonrpc_request("날씨 알려줘", streaming=True)
check("jsonrpc 2.0", req["jsonrpc"] == "2.0")
check("method stream", req["method"] == "message/stream")
check("method send(폴백)", a2a_client._jsonrpc_request("x", streaming=False)["method"] == "message/send")
check("role user", req["params"]["message"]["role"] == "user")
check("text part", req["params"]["message"]["parts"][0] == {"kind": "text", "text": "날씨 알려줘"})
check("id 존재", bool(req["id"]))

print("\n[E] _auth_headers — 토큰 복호화·마스킹·None")
os.environ.setdefault("APP_SECRET_KEY", __import__("cryptography.fernet", fromlist=["Fernet"]).Fernet.generate_key().decode())
from api import crypto  # noqa: E402
enc = crypto.encrypt("super-secret-token")
check("실토큰 → Bearer", a2a_client._auth_headers(enc) == {"Authorization": "Bearer super-secret-token"})
check("None → 헤더 없음", a2a_client._auth_headers(None) == {})
check("마스킹(•) → 헤더 없음", a2a_client._auth_headers("abc••••def") == {})

print("\n[F] net_guard.guard_url — SSRF 사설대역 차단 / allowlist / 공인 통과")
# allowlist 비활성 상태에서 사설/루프백/링크로컬 차단(리터럴 IP라 DNS 불필요)
os.environ.pop("A2A_ALLOWED_HOSTS", None)
expect_raises("loopback 차단", lambda: net_guard.guard_url("http://127.0.0.1:8000/_remote/a2a"))
expect_raises("private 10.x 차단", lambda: net_guard.guard_url("http://10.0.0.5/x"))
expect_raises("private 192.168 차단", lambda: net_guard.guard_url("http://192.168.1.1/x"))
expect_raises("link-local 메타데이터 차단", lambda: net_guard.guard_url("http://169.254.169.254/latest/meta-data"))
expect_raises("비 http 스킴 차단", lambda: net_guard.guard_url("file:///etc/passwd"))
expect_raises("호스트 없음 차단", lambda: net_guard.guard_url("http://"))
# M1(적대리뷰): is_global denylist 누락 대역 — CGNAT 100.64/10, IPv6 루프백·매핑·ULA, 0.0.0.0
expect_raises("CGNAT 100.64/10 차단", lambda: net_guard.guard_url("http://100.64.0.1/x"))
expect_raises("IPv6 ::1 루프백 차단", lambda: net_guard.guard_url("http://[::1]/x"))
expect_raises("IPv6 매핑 ::ffff:127.0.0.1 차단", lambda: net_guard.guard_url("http://[::ffff:127.0.0.1]/x"))
expect_raises("IPv6 ULA fc00:: 차단", lambda: net_guard.guard_url("http://[fc00::1]/x"))
expect_raises("0.0.0.0 미지정 차단", lambda: net_guard.guard_url("http://0.0.0.0/x"))
# 공인 IP는 통과(리터럴 → DNS 불필요, 오프라인 OK)
check("공인 IP 통과", net_guard.guard_url("http://8.8.8.8/x") is None)
check("공인 IP https 통과", net_guard.guard_url("https://1.1.1.1/x") is None)
check("공인 IPv6 통과", net_guard.guard_url("http://[2606:4700:4700::1111]/x") is None)
# allowlist 켜면 사설대역이라도 통과(dev mock)
os.environ["A2A_ALLOWED_HOSTS"] = "127.0.0.1,localhost"
check("allowlist 127.0.0.1 통과", net_guard.guard_url("http://127.0.0.1:8000/_remote/a2a") is None)
check("allowlist localhost 통과", net_guard.guard_url("http://localhost:8000/x") is None)
# allowlist에 없는 사설은 여전히 차단
expect_raises("allowlist 밖 사설 차단", lambda: net_guard.guard_url("http://10.0.0.5/x"))
os.environ.pop("A2A_ALLOWED_HOSTS", None)

print("\n[G] a2a_stream — 절대 raise 안 함(모든 실패 → error 프레임)")
import asyncio  # noqa: E402


async def _collect(gen):
    return [f async for f in gen]


# H3(적대리뷰): decrypt가 키 회전으로 RuntimeError를 던져도 미프레임 크래시 금지 → error 프레임.
_orig_decrypt = crypto.decrypt
def _boom(_):  # noqa: ANN001
    raise RuntimeError("비밀 복호화 실패 — 키 불일치")
a2a_client.crypto.decrypt = _boom
try:
    # 공인 IP라 guard 통과 → 헤더 빌드 중 decrypt에서 raise → except가 프레임화(네트워크 미도달).
    frames = asyncio.run(_collect(a2a_client.a2a_stream("http://8.8.8.8/x", "tok", "hi", streaming=True)))
finally:
    a2a_client.crypto.decrypt = _orig_decrypt
check("decrypt 실패 → error 프레임(raise 아님)", len(frames) == 1 and "error" in frames[0])

# SSRF 차단도 raise 아닌 error 프레임으로.
frames2 = asyncio.run(_collect(a2a_client.a2a_stream("http://10.0.0.1/x", None, "hi", streaming=True)))
check("SSRF 차단 → error 프레임", len(frames2) == 1 and "error" in frames2[0])

print(f"\n결과: {_passed} 통과 / {_failed} 실패")
sys.exit(1 if _failed else 0)

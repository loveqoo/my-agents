"""스펙 070 검증(단위 시맨틱) — 세션 읽기 가시성을 *쿼리에 융합* (인프라 불요).

067은 item 가시성을 `_visible_or_404`(행 로드 후 사후 거부)로 처리해 타인-존재행과 부재행이 다른
코드 경로를 타는 타이밍 측면채널(retro 056 [P3-1])을 남겼다. 070은 owner 스코프를 `_get_session_or_404`
의 SELECT WHERE에 융합해 **거부행을 로드조차 안 함** → 타인행·NULL-owner·부재가 *동일한 단일 쿼리*
에서 None으로 떨어져 동일 404 경로가 된다(069 체크리스트 2(a) 첫 적용).

이 단위는 실 DB 없이 *쿼리가 어떻게 빌드되는지*를 본다: FakeSession이 execute에 전달된 select를
캡처해, own이 주어질 때만 `user_id` 필터가 융합되는지, None 결과가 단일 404 경로로 가는지 검증한다.
실제 필터링·404 응답코드·admin 무회귀는 verify_067_live.py(라이브, 행동 등가)에서 확인.

검증:
  U1. own=None(admin/머신): 쿼리에 user_id 필터 없음(전체), 존재행 그대로 반환
  U2. own=member: 쿼리에 user_id 필터 *융합*(거부행을 WHERE로 걸러 로드 안 함)
  U3. 결과 None(타인행·NULL·부재 무차별): 단일 404 경로 — 그리고 그 쿼리엔 user_id 필터 존재
  U4. own=None + 부재(None): 404 (admin도 부재는 404)

실행: .venv/bin/python tests/verify_070_scope.py
"""
import asyncio
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))

from fastapi import HTTPException  # noqa: E402

from api import sessions as S  # noqa: E402

_fails: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


class FakeResult:
    def __init__(self, obj):
        self._obj = obj

    def scalar_one_or_none(self):
        return self._obj


class FakeSession:
    """execute에 전달된 쿼리를 캡처하고 미리 정한 행을 돌려준다(실 DB 무관)."""

    def __init__(self, obj):
        self._obj = obj
        self.last_q = None

    async def execute(self, q):
        self.last_q = q
        return FakeResult(self._obj)


def _where_binds(q) -> dict:
    """WHERE 절 바인드 파라미터(=필터 조건). SELECT 컬럼 목록엔 바인드가 없으므로, 여기에
    user_id가 있으면 *WHERE user_id 필터가 융합됐다*는 확증이다(str(q) substring은 SELECT의
    user_id 컬럼에 거짓양성)."""
    return q.compile().params


def _has_user_filter(binds: dict) -> bool:
    return any("user_id" in k for k in binds)


def _run(obj, session_id, own):
    fs = FakeSession(obj)
    try:
        s = asyncio.run(S._get_session_or_404(fs, session_id, own))
        return s, _where_binds(fs.last_q), None
    except HTTPException as e:
        return None, _where_binds(fs.last_q), e.status_code


SENTINEL = object()  # "행 존재"의 불투명 표식 — 헬퍼는 객체를 그대로 반환만 함

# ---- U1. admin/머신(own=None): 무스코프, 존재행 반환 ----
s, binds, code = _run(SENTINEL, "sess-x", None)
check(not _has_user_filter(binds), "U1: own=None → WHERE에 user_id 필터 없음(admin 전체)")
check(any("session_id" in k for k in binds), "U1: session_id 필터는 있음")
check(s is SENTINEL and code is None, "U1: 존재행 그대로 반환")

# ---- U2. member(own): user_id 필터 융합 ----
s, binds, code = _run(SENTINEL, "sess-x", "owner-1")
check(_has_user_filter(binds), "U2: own 주면 user_id 필터를 WHERE에 융합(거부행 로드 안 함)")
check("owner-1" in binds.values(), "U2: 융합된 user_id 값 = 본인 스코프")
check(any("session_id" in k for k in binds), "U2: session_id 필터도 함께(둘 다 WHERE)")
check(s is SENTINEL, "U2: 본인행은 반환")

# ---- U3. 결과 None(타인/NULL/부재 무차별) → 단일 404, WHERE엔 user_id 필터 ----
s, binds, code = _run(None, "sess-x", "owner-1")
check(code == 404, "U3: 스코프 불일치/부재 → 404(타인-존재행과 부재행 동일 경로)")
check(_has_user_filter(binds), "U3: 거부행은 WHERE user_id로 걸러짐 = 로드조차 안 함(타이밍 오라클 봉합)")
check(s is None, "U3: 반환 없음")

# ---- U4. admin + 부재 → 404 ----
s, binds, code = _run(None, "nope", None)
check(code == 404, "U4: admin도 부재 세션은 404")
check(not _has_user_filter(binds), "U4: admin 부재 경로에도 user_id 스코프 없음(무회귀)")

print()
if _fails:
    print(f"FAILED ({len(_fails)})")
    for m in _fails:
        print("  - " + m)
    sys.exit(1)
print("ALL PASS — 스펙 070 세션 읽기 가시성 쿼리 융합(거부행 미로드) 시맨틱 통과")

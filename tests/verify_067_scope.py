"""스펙 067 검증(단위 시맨틱) — 세션 유저 스코핑 분기 (인프라 불요).

sessions의 스코핑 헬퍼를 라이브 Postgres/casbin/쿠키 없이 격리 검증한다. casbin enforce는
FakeEnforcer로 주입(get_enforcer 패치) — 분기 로직만 본다. 실 DB 스코핑 글루·쿠키 라운드트립·
404 응답코드는 verify_067_live.py(라이브 통합 rung)에서 별도 확인.

검증(정본 authz, 스펙 298 — 옛 sessions._is_admin/_own_scope는 authz.is_admin_for/own_scope로 이관,
호출부가 ("sessions","read") 튜플 명시 = 라우터 독립 보존):
  M1. is_admin_for(·,"sessions","read"): 머신·superuser·casbin(sessions:read) = True / member = False
  M2. own_scope(·,"sessions","read"): admin/머신=None(전체) / member=str(id)(본인만)
  M3. own_scope_write (스펙 299): 머신/superuser=None(전체) / sessions:read 운영자·member=str(id)
      (읽기 권한이 쓰기를 넓히면 안 됨 — end_session·feedback이 read-scope 쓰던 버그 정정)

NOTE(스펙 070): 067은 item 가시성을 `_visible_or_404`(fetch-then-check)로 사후 거부했으나, 070이
그 가시성을 `_get_session_or_404`의 쿼리에 융합해 거부행을 로드조차 안 하게 바꿨다(타이밍 오라클
봉합). 그 가시성 단위 검증은 verify_070_scope.py로 이관됐다.

실행: .venv/bin/python tests/verify_067_scope.py
"""
import os
import sys
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))

from api import authz  # noqa: E402

_fails: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


class P:
    """fastapi-users User 모사 — principal 최소 필드(id·is_superuser)."""

    def __init__(self, is_superuser=False):
        self.id = uuid.uuid4()
        self.is_superuser = is_superuser


class FakeEnforcer:
    def __init__(self, allow):
        self.allow = allow

    def enforce(self, sub, obj, act):
        return (sub, obj, act) in self.allow


# ---- 주체 ----
machine = "machine"
superuser = P(is_superuser=True)
operator = P(is_superuser=False)   # casbin sessions:read 보유(전체 열람 운영자 훅)
member = P(is_superuser=False)     # 정책 전무
m1 = str(member.id)

authz.get_enforcer = lambda: FakeEnforcer({
    (str(operator.id), "sessions", "read"),
})

# ---- M1. is_admin_for(·, "sessions", "read") ----
check(authz.is_admin_for(machine, "sessions", "read") is True, "M1: 머신 토큰 = 전체 열람")
check(authz.is_admin_for(superuser, "sessions", "read") is True, "M1: superuser = 전체(우회)")
check(authz.is_admin_for(operator, "sessions", "read") is True, "M1: casbin sessions:read = 전체 열람 운영자")
check(authz.is_admin_for(member, "sessions", "read") is False, "M1: member = 비-admin(자기 것만)")

# ---- M2. own_scope(·, "sessions", "read") ----
check(authz.own_scope(machine, "sessions", "read") is None, "M2: 머신 → 전체(스코프 None)")
check(authz.own_scope(superuser, "sessions", "read") is None, "M2: superuser → 전체")
check(authz.own_scope(operator, "sessions", "read") is None, "M2: sessions:read 운영자 → 전체")
check(authz.own_scope(member, "sessions", "read") == m1, "M2: member → 본인 user_id로 스코핑")

# ---- M3. own_scope_write (스펙 299 — 읽기 권한이 쓰기를 넓히면 안 됨) ----
# end_session·feedback 같은 mutating route용. **핵심 대비**: sessions:read 운영자는 M2(read)에선
# 무스코프(전체)지만 여기선 스코프됨 → 타인 세션 종료/피드백 차단. machine/superuser만 전체.
op1 = str(operator.id)
check(authz.own_scope_write(machine) is None, "M3: 머신 → 전체(쓰기도, 011/031)")
check(authz.own_scope_write(superuser) is None, "M3: superuser → 전체(쓰기)")
check(
    authz.own_scope_write(operator) == op1,
    "M3: sessions:read 운영자 → 자기 것만(read는 전체지만 write는 스코프 = 299 정정)",
)
check(authz.own_scope_write(member) == m1, "M3: member → 본인 user_id로 스코핑(쓰기)")

print()
if _fails:
    print(f"FAILED ({len(_fails)})")
    for m in _fails:
        print("  - " + m)
    sys.exit(1)
print("ALL PASS — 스펙 067/299 세션 스코핑 시맨틱(M1/M2 읽기·M3 쓰기) 통과 (가시성은 verify_070_scope.py)")

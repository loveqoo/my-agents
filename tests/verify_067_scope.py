"""스펙 067 검증(단위 시맨틱) — 세션 유저 스코핑 분기 (인프라 불요).

sessions의 스코핑 헬퍼 3종을 라이브 Postgres/casbin/쿠키 없이 격리 검증한다. casbin enforce는
FakeEnforcer로 주입(get_enforcer 패치) — 분기 로직만 본다. 실 DB 스코핑 글루·쿠키 라운드트립·
404 응답코드는 verify_067_live.py(라이브 통합 rung)에서 별도 확인.

검증:
  M1. _is_admin: 머신·superuser·casbin(sessions:read) = True / member = False
  M2. _own_scope: admin/머신=None(전체) / member=str(id)(본인만)
  M3. _visible_or_404:
      - admin/머신(own=None) → 어떤 세션도 통과(예외 없음)
      - member + 본인 세션(user_id==own) → 통과
      - member + 타인 세션(user_id≠own) → 404 (T2 존재 은폐)
      - member + NULL-owner 세션(user_id=None) → 404 (T3)

실행: .venv/bin/python tests/verify_067_scope.py
"""
import os
import sys
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))

from fastapi import HTTPException  # noqa: E402

from api import authz  # noqa: E402
from api import sessions as S  # noqa: E402

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


class Sess:
    """Session 모사 — 스코핑에 쓰는 user_id만."""

    def __init__(self, user_id):
        self.user_id = user_id


class FakeEnforcer:
    def __init__(self, allow):
        self.allow = allow

    def enforce(self, sub, obj, act):
        return (sub, obj, act) in self.allow


def _raises_404(fn) -> bool:
    try:
        fn()
        return False
    except HTTPException as e:
        return e.status_code == 404


# ---- 주체 ----
machine = "machine"
superuser = P(is_superuser=True)
operator = P(is_superuser=False)   # casbin sessions:read 보유(전체 열람 운영자 훅)
member = P(is_superuser=False)     # 정책 전무
m1 = str(member.id)

authz.get_enforcer = lambda: FakeEnforcer({
    (str(operator.id), "sessions", "read"),
})

# ---- M1. _is_admin ----
check(S._is_admin(machine) is True, "M1: 머신 토큰 = 전체 열람")
check(S._is_admin(superuser) is True, "M1: superuser = 전체(우회)")
check(S._is_admin(operator) is True, "M1: casbin sessions:read = 전체 열람 운영자")
check(S._is_admin(member) is False, "M1: member = 비-admin(자기 것만)")

# ---- M2. _own_scope ----
check(S._own_scope(machine) is None, "M2: 머신 → 전체(스코프 None)")
check(S._own_scope(superuser) is None, "M2: superuser → 전체")
check(S._own_scope(operator) is None, "M2: sessions:read 운영자 → 전체")
check(S._own_scope(member) == m1, "M2: member → 본인 user_id로 스코핑")

# ---- M3. _visible_or_404 ----
own = Sess(m1)
others = Sess(str(superuser.id))
null_owner = Sess(None)

# admin/머신(own=None): 무게이트 — 어떤 세션도 통과
for name, pr in [("머신", machine), ("superuser", superuser), ("운영자", operator)]:
    o = S._own_scope(pr)
    check(S._visible_or_404(others, o) is None, f"M3: {name} → 타인 세션도 통과(전체)")
    check(S._visible_or_404(null_owner, o) is None, f"M3: {name} → NULL-owner 세션도 통과")

# member(own=m1): 본인만 통과, 타인·NULL → 404
mo = S._own_scope(member)
check(S._visible_or_404(own, mo) is None, "M3: member + 본인 세션 → 통과")
check(_raises_404(lambda: S._visible_or_404(others, mo)),
      "M3(T2): member + 타인 세션 → 404(존재 은폐, 403 아님)")
check(_raises_404(lambda: S._visible_or_404(null_owner, mo)),
      "M3(T3): member + NULL-owner 세션 → 404")

print()
if _fails:
    print(f"FAILED ({len(_fails)})")
    for m in _fails:
        print("  - " + m)
    sys.exit(1)
print("ALL PASS — 스펙 067 세션 스코핑 시맨틱 전부 통과")

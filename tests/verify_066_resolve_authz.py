"""스펙 066 검증(단위 시맨틱) — 승인 resolve 인가 3-way + list 스코핑 (인프라 불요).

permission RBAC 3-way의 핵심 불변식을 라이브 Postgres/casbin/쿠키 없이 격리 검증한다.
casbin enforce는 FakeEnforcer로 주입(get_enforcer 패치) — 분기 로직만 본다. 실 casbin 그룹핑
해석·DB 스코핑 글루·쿠키 라운드트립은 verify_066_live.py(라이브 통합 rung)에서 별도 확인.

검증:
  M1. _is_admin: 머신·superuser·casbin(approvals:resolve) = True / member = False
  M2. _may_resolve 3-way:
      - 머신/superuser/admin → 무엇이든 True
      - owner(본인) + self_approve 정책 perm → True
      - owner + 민감 perm(data.delete, 정책無) → False (민감도 구분)
      - owner + 빈 perm → False (T6 알 수 없는 권한)
      - 타인 것(user_id≠본인) → False (T1)
      - user_id=None(머신/레거시 발) → False (T2 NULL-owner)
      - owner지만 self_approve 정책 없는 member → False (T7 정책 부재 = 거부)
  M3. _own_scope: admin/머신=None(전체) / member=str(id)(본인만)
  M4. can_self_approve: 빈 perm=False(무 enforce) / 정책 있으면 True / 없으면 False

실행: .venv/bin/python tests/verify_066_resolve_authz.py
"""
import os
import sys
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))

from api import approvals as AP  # noqa: E402
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


class A:
    """Approval 모사 — 인가에 쓰는 필드(user_id·permission)만."""

    def __init__(self, user_id, permission):
        self.user_id = user_id
        self.permission = permission


class FakeEnforcer:
    """주어진 (sub, obj, act) 집합에만 True. 나머지 False(실 casbin 그룹핑 해석은 라이브 rung)."""

    def __init__(self, allow):
        self.allow = allow

    def enforce(self, sub, obj, act):
        return (sub, obj, act) in self.allow


# ---- 주체 ----
machine = "machine"
superuser = P(is_superuser=True)
admin = P(is_superuser=False)       # casbin approvals:resolve 보유
member = P(is_superuser=False)      # data.read만 self_approve 보유
member2 = P(is_superuser=False)     # self_approve 정책 전무(T7)

m1 = str(member.id)
# casbin: admin은 approvals:resolve, member(m1)은 data.read self_approve. 그 외 전부 deny.
authz.get_enforcer = lambda: FakeEnforcer({
    (str(admin.id), "approvals", "resolve"),
    (m1, "data.read", "self_approve"),
})

# ---- M1. _is_admin ----
check(AP._is_admin(machine) is True, "M1: 머신 토큰 = admin 등가(전체 승인)")
check(AP._is_admin(superuser) is True, "M1: superuser = admin(우회)")
check(AP._is_admin(admin) is True, "M1: casbin approvals:resolve = admin")
check(AP._is_admin(member) is False, "M1: member = 비-admin")

# ---- M2. _may_resolve 3-way ----
own_read = A(m1, "data.read")        # owner + self_approve 정책 있음
own_delete = A(m1, "data.delete")    # owner + 민감(정책 없음)
own_empty = A(m1, "")                # owner + 빈 perm
others = A(str(member2.id), "data.read")  # 타인 것(perm은 self지만 소유자 아님)
null_owner = A(None, "data.read")    # 머신/레거시 발

# admin 3종 + 머신: 무엇이든 True (민감 perm여도)
for name, pr in [("머신", machine), ("superuser", superuser), ("casbin-admin", admin)]:
    check(AP._may_resolve(own_delete, pr) is True, f"M2: {name} → 민감 perm(data.delete)도 승인 허용")
    check(AP._may_resolve(null_owner, pr) is True, f"M2: {name} → NULL-owner 행도 승인 허용(전체)")

# owner + self_approve 정책 → True
check(AP._may_resolve(own_read, member) is True, "M2: owner + self_approve perm(data.read) → 허용")
# owner + 민감 perm(정책 없음) → False
check(AP._may_resolve(own_delete, member) is False, "M2: owner + 민감 perm(data.delete) → 거부(admin 필수)")
# owner + 빈 perm → False (T6)
check(AP._may_resolve(own_empty, member) is False, "M2(T6): owner + 빈 permission → 거부(알 수 없는 권한)")
# 타인 것 → False (T1) — perm이 self-허용이라도 소유자 불일치
check(AP._may_resolve(others, member) is False, "M2(T1): 타인 소유 행 → 거부(교차 유저 차단)")
# NULL-owner → False (T2)
check(AP._may_resolve(null_owner, member) is False, "M2(T2): user_id=None 행 → 거부(레거시/머신 탈취 차단)")
# self_approve 정책 없는 member가 자기 것 → False (T7)
check(
    AP._may_resolve(A(str(member2.id), "data.read"), member2) is False,
    "M2(T7): 정책 없는 member가 자기 data.read → 거부(정책 부재=fail-closed)",
)

# ---- M3. _own_scope ----
check(AP._own_scope(machine) is None, "M3: 머신 → 전체(스코프 None)")
check(AP._own_scope(superuser) is None, "M3: superuser → 전체")
check(AP._own_scope(admin) is None, "M3: casbin-admin → 전체")
check(AP._own_scope(member) == m1, "M3: member → 본인 user_id로 스코핑")

# ---- M4. can_self_approve ----
check(authz.can_self_approve(m1, "") is False, "M4: 빈 permission → False(무 enforce)")
check(authz.can_self_approve(m1, "data.read") is True, "M4: 정책 있는 perm → True")
check(authz.can_self_approve(m1, "data.delete") is False, "M4: 정책 없는 민감 perm → False")
check(authz.can_self_approve(str(member2.id), "data.read") is False, "M4: 정책 없는 sub → False")

print()
if _fails:
    print(f"FAILED ({len(_fails)})")
    for m in _fails:
        print("  - " + m)
    sys.exit(1)
print("ALL PASS — 스펙 066 resolve 인가 3-way 시맨틱 전부 통과")

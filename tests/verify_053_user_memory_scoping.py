"""스펙 053 검증 — 유저 메모리 역할 기반 스코핑 (인프라 불요).

라이브 Postgres/casbin/쿠키 없이 권한 게이트의 핵심 불변식을 격리 검증한다:
  1. _can_curate_others: 머신·superuser·casbin-admin = True / member = False
  2. _assert_principal_may_access: 비-어드민은 자기 user_id만(타인 → 403),
     어드민(머신/superuser/casbin)은 임의 user_id 허용
  3. _principal_identity: 머신=None, 유저=MemoryUserOut(str(id))
  4. 누출-안전: MemoryUserOut 필드가 정확히 {user_id,email,display_name}(스펙 052 회귀)
  5. MemoryUserList 형상: {can_curate_others, me, users}

casbin enforce는 FakeEnforcer로 주입 — get_enforcer를 패치해 라이브 인가 불요.
라이브 쿠키 라운드트립(member 로그인→403)은 브라우저샷/사용자 브랜치 통합에서 확인.
실행: .venv/bin/python tests/verify_053_user_memory_scoping.py
"""
import os
import sys
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))

from fastapi import HTTPException  # noqa: E402

from api import memory_routes as MR  # noqa: E402

_fails: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


class P:
    """fastapi-users User 모사 — principal로 쓰일 최소 필드."""

    def __init__(self, is_superuser=False, email="u@example.com", display_name=None):
        self.id = uuid.uuid4()
        self.is_superuser = is_superuser
        self.email = email
        self.display_name = display_name


class FakeEnforcer:
    """주어진 (sub, obj, act) 집합에만 True. 나머지 False."""

    def __init__(self, allow: set[tuple[str, str, str]]):
        self.allow = allow

    def enforce(self, sub, obj, act):
        return (sub, obj, act) in self.allow


def raised_403(fn) -> bool:
    try:
        fn()
        return False
    except HTTPException as e:
        return e.status_code == 403


# ---- 주체 준비 ----
machine = "machine"
superuser = P(is_superuser=True, email="root@example.com")
member = P(is_superuser=False, email="member@example.com")
admin = P(is_superuser=False, email="admin-role@example.com")

# casbin: admin.id만 memory:manage 통과(superuser·member는 enforce 안 탐/실패해야 함)
MR.get_enforcer = lambda: FakeEnforcer({(str(admin.id), "memory", "manage")})

# ---- 1. _can_curate_others ----
check(MR._can_curate_others(machine) is True, "머신 토큰 = 어드민 등가(can_curate_others)")
check(MR._can_curate_others(superuser) is True, "superuser = can_curate_others(우회)")
check(MR._can_curate_others(admin) is True, "casbin admin 역할 = can_curate_others(enforce)")
check(MR._can_curate_others(member) is False, "member = 타인 큐레이션 불가")

# ---- 2. _assert_principal_may_access ----
other = str(uuid.uuid4())
# 어드민 3종: 타인 허용(no raise)
for name, pr in [("머신", machine), ("superuser", superuser), ("casbin-admin", admin)]:
    check(
        not raised_403(lambda pr=pr: MR._assert_principal_may_access(pr, other)),
        f"{name}: 타 유저 메모리 접근 허용",
    )
# member: 자기 것 허용, 타인 403
check(
    not raised_403(lambda: MR._assert_principal_may_access(member, str(member.id))),
    "member: 본인 user_id 접근 허용",
)
check(
    raised_403(lambda: MR._assert_principal_may_access(member, other)),
    "member: 타 user_id 접근 403(프라이버시 경계)",
)

# ---- 3. _principal_identity ----
check(MR._principal_identity(machine) is None, "머신 신원 = None(유저신원 없음)")
ident = MR._principal_identity(member)
check(
    ident is not None and ident.user_id == str(member.id) and ident.email == member.email,
    "유저 신원 = MemoryUserOut(str(id)·email)",
)

# ---- 4. 누출-안전: MemoryUserOut 필드 ----
check(
    set(MR.MemoryUserOut.model_fields) == {"user_id", "email", "display_name"},
    "MemoryUserOut 필드 정확히 3개(누출-안전, 052 회귀)",
)

# ---- 5. MemoryUserList 형상 ----
check(
    set(MR.MemoryUserList.model_fields) == {"can_curate_others", "me", "users"},
    "MemoryUserList 형상 {can_curate_others, me, users}",
)
# 비-어드민 응답 구성 재현: users=[me]
ml = MR.MemoryUserList(can_curate_others=False, me=ident, users=[ident])
check(
    ml.can_curate_others is False and len(ml.users) == 1 and ml.users[0].user_id == str(member.id),
    "비-어드민 응답: can_curate_others=False·users=[me]",
)

print()
if _fails:
    print(f"FAILED ({len(_fails)})")
    for m in _fails:
        print("  - " + m)
    sys.exit(1)
print("ALL PASS")

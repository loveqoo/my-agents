"""스펙 177 P3 검증 — 능력 부여(정책) + 보안 경계.

능력(capability:*)을 역할/유저에 여는 부여 UI의 백엔드. member는 deny-by-default라 부여 없인
능력을 못 쓴다(스펙). 이 표면이 **권한 상승 도구가 되지 않도록** 경계를 강제하는지 검증한다.

  G1-G4 보안 경계(_assert_grantable): 비-capability 객체·와일드카드·비-invoke 거부 / 정상 통과.
  G5-G6 grant/revoke 라운드트립(실 casbin enforcer): 부여 전 deny → add 후 allow → remove 후 deny.
  G7 subject 검증: 비-역할·비-uuid → 400 / 역할명 통과.

실행: (packages/api서) uv run python ../../tests/verify_177_p3_capability_grant.py
"""

import asyncio
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))

from fastapi import HTTPException  # noqa: E402

from api import authz  # noqa: E402
from api.db import SessionLocal  # noqa: E402
from api.user_admin import _assert_grantable, _assert_valid_subject  # noqa: E402

_fails: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def _expect_400(obj: str, act: str, label: str) -> None:
    try:
        _assert_grantable(obj, act)
        check(False, f"{label} → 400이어야 (통과됨)")
    except HTTPException as ex:
        check(ex.status_code == 400, f"{label} 400 (got {ex.status_code})")


async def main() -> None:
    await authz.init_authz()  # 실 enforcer 로드 + 역할 카탈로그 시드(멱등)
    e = authz.get_enforcer()

    # ---- 보안 경계 ----
    _expect_400("users", "manage", "G1 비-capability 객체(리소스 권한) 거부")
    _expect_400("*", "*", "G1b (*,*) 상승 거부")
    _expect_400("capability:mcp:*", "invoke", "G2 와일드카드 능력 거부")
    _expect_400("capability:mcp", "manage", "G3 비-invoke action 거부")
    try:
        _assert_grantable("capability:mcp:local-tools", "invoke")
        check(True, "G4 정상 capability:mcp:local-tools invoke 통과")
    except HTTPException:
        check(False, "G4 정상 capability는 통과해야")

    # ---- grant/revoke 라운드트립(실 casbin) ----
    SUB, OBJ = "test_p3_role_zzz", "capability:test:probe"
    await authz.remove_policy(SUB, OBJ, "invoke")  # 클린 시작(이전 실패 잔재 제거)
    check(not e.enforce(SUB, OBJ, "invoke"), "G5 부여 전 enforce False(deny-by-default)")
    added = await authz.add_policy(SUB, OBJ, "invoke")
    check(added and e.enforce(SUB, OBJ, "invoke"), "G6a add_policy 후 enforce True(멱등 신규)")
    again = await authz.add_policy(SUB, OBJ, "invoke")
    check(again is False, "G6b 중복 add는 False(멱등)")
    removed = await authz.remove_policy(SUB, OBJ, "invoke")
    check(removed and not e.enforce(SUB, OBJ, "invoke"), "G6c remove_policy 후 enforce False")

    # ---- subject 검증 ----
    async with SessionLocal() as s:
        try:
            await _assert_valid_subject("not-a-role-or-uuid", s)
            check(False, "G7 비-역할·비-uuid subject → 400이어야")
        except HTTPException as ex:
            check(ex.status_code == 400, f"G7 잘못된 subject 400 (got {ex.status_code})")
        try:
            await _assert_valid_subject("member", s)
            check(True, "G7b 역할명(member) subject 통과")
        except HTTPException:
            check(False, "G7b 역할명은 통과해야(카탈로그 시드)")

    print()
    if _fails:
        print(f"검증 실패 {len(_fails)}건:")
        for f in _fails:
            print(f"  - {f}")
        sys.exit(1)
    print("스펙 177 P3 능력 부여 검증 — 전부 통과.")


if __name__ == "__main__":
    asyncio.run(main())

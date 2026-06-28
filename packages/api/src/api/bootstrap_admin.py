"""첫 관리자(superuser) 부트스트랩 / 락아웃 회복 — 1급 콘솔 경로 (스펙 058).

언제: 프로젝트를 처음 받아 띄웠는데 ADMIN_EMAIL/ADMIN_PASSWORD env를 안 줘서 `seed_admin`이
fail-closed로 관리자를 안 만든 경우(유저 0 → 로그인 불가). 또는 어드민 계정을 잃은 경우.
공개 등록 라우터는 의도적으로 막혀 있으므로(스펙 031), 이 커맨드가 *유일하고 명시적인* 회복 경로다.

escalation 방지(learning 050): **신규 생성만** 한다. 이미 존재하는 이메일은 *승격하지 않고 거부*한다 —
운영자가 평범한 member 계정을 이 커맨드로 슬쩍 superuser로 올리는 길을 닫는다(실수·악용 모두). 새 관리자가
필요하면 *새 이메일*로 만든다.

  python -m api.bootstrap_admin <email> <password>
  python -m api.bootstrap_admin            # 인자 없으면 env ADMIN_EMAIL/ADMIN_PASSWORD 사용

종료 코드: 0 생성/이미 super(무동작), 2 입력 누락, 3 기존 계정 승격 거부.
"""

import asyncio
import logging
import os
import sys

log = logging.getLogger("api.bootstrap_admin")

_MIN_PASSWORD_LEN = 8


async def bootstrap_admin(email: str, password: str) -> int:
    """superuser 신규 생성(+admin role). 기존 이메일은 승격 거부. 반환=종료코드."""
    from fastapi_users.db import SQLAlchemyUserDatabase

    from .authz import assign_role
    from .db import SessionLocal
    from .models import User
    from .schemas import UserCreate
    from .users import UserManager

    email = (email or "").strip().lower()
    password = password or ""
    if not email or "@" not in email:
        print("BOOTSTRAP_REFUSED 유효한 이메일이 필요합니다.")
        return 2
    if len(password) < _MIN_PASSWORD_LEN:
        print(f"BOOTSTRAP_REFUSED 비밀번호는 최소 {_MIN_PASSWORD_LEN}자 이상이어야 합니다.")
        return 2

    async with SessionLocal() as session:
        user_db = SQLAlchemyUserDatabase(session, User)
        manager = UserManager(user_db)
        existing = await user_db.get_by_email(email)
        if existing is not None:
            # escalation 방지(050): 기존 계정은 절대 승격하지 않는다.
            if existing.is_superuser:
                print(f"BOOTSTRAP_EXISTS {email} — 이미 superuser입니다(무동작).")
                return 0
            print(
                f"BOOTSTRAP_REFUSED {email} — 이미 존재하는 일반 계정입니다. 승격하지 않습니다"
                "(escalation 방지). 새 관리자는 다른 이메일로 만드세요."
            )
            return 3
        user = await manager.create(
            UserCreate(email=email, password=password, is_superuser=True, is_verified=True),
            safe=False,
        )
        await assign_role(str(user.id), "admin")
        print(f"BOOTSTRAP_OK {email} — superuser 생성 완료. 이 계정으로 로그인하세요.")
        return 0


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    args = sys.argv[1:]
    if len(args) >= 2:
        email, password = args[0], args[1]
    elif len(args) == 0:
        email = os.environ.get("ADMIN_EMAIL", "")
        password = os.environ.get("ADMIN_PASSWORD", "")
        if not email or not password:
            print(
                "사용법: python -m api.bootstrap_admin <email> <password>\n"
                "  (또는 ADMIN_EMAIL/ADMIN_PASSWORD env 설정 후 인자 없이)"
            )
            sys.exit(2)
    else:
        print("사용법: python -m api.bootstrap_admin <email> <password>")
        sys.exit(2)
    sys.exit(asyncio.run(bootstrap_admin(email, password)))


if __name__ == "__main__":
    main()

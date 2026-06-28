"""테스트 super 계정 self-fixture provisioner (스펙 050 Phase 3).

브라우저 샷·통합 프로브가 *영속 계정에 의존하지 않도록* 던져버릴 super를 즉석 생성/삭제한다.
실행 중인 admin 서버는 별 프로세스라 casbin enforcer를 reload 못 하지만, authz.require가
`is_superuser`를 우회 경로로 두므로(서버가 매 요청 DB에서 읽음) is_superuser=True만 박으면
casbin grant 없이도 admin 라우트가 통과한다 — 그래서 g-policy를 만들지도, reload하지도 않는다.

바닥(learning 037, 적대 리뷰 반영): **생성·삭제 둘 다** keep-list(admin@·alice@)와
던짐용 prefix(`shotfix_`/`probe`/`verify`/`shottmp`) + **`@example.com`(RFC 예약 테스트 도메인)**
조건을 강제해, 헬퍼가 실계정·부트스트랩 admin을 절대 못 지우고(삭제), 실계정을 super로
승격시키지도(생성) 못한다. 이메일은 양쪽에서 `.strip().lower()`로 정규화해 대소문자 비대칭을 없앤다.

  uv run python tests/_provision_super.py create <email> <password>
  uv run python tests/_provision_super.py delete <email>
"""

import asyncio
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))

# 주의: api.models를 fastapi_users 하위모듈보다 *먼저* 임포트해야 한다 — fastapi_users_db_sqlalchemy를
# 직접 선임포트하면 fastapi_users.db 재익스포트가 부분초기화로 깨진다(SQLAlchemyBaseUserTableUUID 미해석).
from api.db import SessionLocal  # noqa: E402
from api.models import User  # noqa: E402
from api.schemas import UserCreate  # noqa: E402
from api.users import UserManager  # noqa: E402
from fastapi_users.db import SQLAlchemyUserDatabase  # noqa: E402
from sqlalchemy import delete, select, text  # noqa: E402

# 헬퍼가 지울 수 있는 이메일 — 던짐용 prefix만(실계정 보호). delete가 이 화이트리스트로 한 번 더 막는다.
_DISPOSABLE_PREFIXES = ("shotfix_", "shottmp_", "probe", "verify")
_KEEP = frozenset({"admin@example.com", "alice@example.com"})


def _disposable(email: str) -> bool:
    e = (email or "").strip().lower()
    if e in _KEEP or not e.endswith("@example.com"):  # 예약 테스트 도메인만(실 corp 도메인 차단)
        return False
    local = e.split("@", 1)[0]  # prefix는 local-part 기준(도메인 오염 방지)
    return any(local.startswith(p) for p in _DISPOSABLE_PREFIXES)


async def _create(email: str, password: str) -> None:
    email = (email or "").strip().lower()  # delete와 동일 정규화 — 대소문자 비대칭 제거
    if not _disposable(email):  # 적대 리뷰 H1: 실계정 super 승격 금지(create도 던짐용만)
        print("PROVISION_REFUSED(비-던짐 이메일은 생성 거부 — 실계정 super 승격 방지):", email)
        sys.exit(2)
    async with SessionLocal() as session:
        user_db = SQLAlchemyUserDatabase(session, User)
        manager = UserManager(user_db)
        existing = await user_db.get_by_email(email)
        if existing is not None:
            if not existing.is_superuser:  # 멱등 — 이미 있으면 super만 보장
                existing.is_superuser = True
                await session.commit()
            print("PROVISION_EXISTS", email)
            return
        await manager.create(
            UserCreate(email=email, password=password, is_superuser=True, is_verified=True),
            safe=False,
        )
    print("PROVISION_OK", email)


async def _delete(email: str) -> None:
    email = (email or "").strip().lower()  # create와 동일 정규화 — 저장값(소문자)과 매칭 보장
    if not _disposable(email):
        print("PROVISION_REFUSED(비-던짐 이메일은 삭제 거부):", email)
        sys.exit(2)
    async with SessionLocal() as session:
        uid = (
            await session.execute(select(User.id).where(User.email == email))
        ).scalar_one_or_none()
        if uid is None:
            print("PROVISION_DELETE_NOOP(없음)", email)
            return
        # casbin은 안 만들지만(is_superuser 우회) dangling 방지 위해 방어적으로 제거.
        await session.execute(
            text("DELETE FROM casbin_rule WHERE ptype IN ('g','p') AND v0 = :u"), {"u": str(uid)}
        )
        await session.execute(delete(User).where(User.id == uid))  # accesstoken은 FK CASCADE
        await session.commit()
    print("PROVISION_DELETED", email)


def main() -> None:
    if len(sys.argv) < 3:
        print("usage: _provision_super.py {create <email> <password> | delete <email>}")
        sys.exit(1)
    cmd, email = sys.argv[1], sys.argv[2]
    if cmd == "create":
        if len(sys.argv) < 4:
            print("create는 password가 필요합니다")
            sys.exit(1)
        asyncio.run(_create(email, sys.argv[3]))
    elif cmd == "delete":
        asyncio.run(_delete(email))
    else:
        print("미지의 명령:", cmd)
        sys.exit(1)


if __name__ == "__main__":
    main()

"""감사 컬럼 계층 (스펙 343) — created_at/updated_at/created_by/updated_by.

**앱 계층으로 채운다**(DB 트리거는 사용자 기각 — 로직이 DB에 숨는 방식은 쓰지 않는다).
핵심은 SQLAlchemy **컬럼 default/onupdate가 ORM뿐 아니라 Core `insert()`/`update()`에도 적용**된다는
점 — rag_ingest의 청크 대량 삽입, 좀비 스윕의 Core update 같은 비-ORM 경로도 자동으로 채워진다
(ORM 이벤트 훅으로 짰다면 조용히 샜을 자리).

주체(actor)는 contextvar로 흐른다:
- 사람: 이메일의 `@` **앞 로컬파트**(`admin@example.com` → `admin`). 실명·전체 이메일은 담지 않는다.
- 사람 아님(머신 토큰·시드·마이그레이션·배치·백그라운드 잡): `system` 예약어.
- 과거 행(백필): `unknown`.

정직 경계(트리거를 뺀 대가): raw `text()` 쓰기와 `created_by`를 명시로 덮어쓰는 Core 문은 DB가
막지 못한다 — 전자는 "코드에 그런 쓰기가 없음"을 상주 테스트로, 후자는 ORM 경로에 한해 아래
before_flush 가드로 되돌린다.
"""

from contextvars import ContextVar, Token
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, String, event, func, inspect
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.orm import Session as OrmSession

SYSTEM_ACTOR = "system"  # 사람 아닌 주체
UNKNOWN_ACTOR = "unknown"  # 감사 도입(343) 이전 행의 백필값

# 기본값이 SYSTEM_ACTOR — actor를 못 정한 경로(배치·시드·부팅)는 자동으로 system이 된다.
# 요청 스코프: Starlette는 요청마다 새 태스크 → 컨텍스트가 분리되므로 요청 간 누출이 없다.
_actor_var: ContextVar[str] = ContextVar("audit_actor", default=SYSTEM_ACTOR)


def actor_of(principal: Any) -> str:
    """인증 주체 → 감사 actor 문자열. 이메일이면 `@` 앞만, 그 외는 system."""
    email = getattr(principal, "email", None)
    if isinstance(email, str) and "@" in email:
        local = email.split("@", 1)[0].strip()
        if local:
            return local[:80]
    return SYSTEM_ACTOR


def set_actor(actor: str) -> Token[str]:
    """현재 컨텍스트의 actor 설정(인증 의존성이 호출). 반환 토큰으로 되돌릴 수 있다."""
    return _actor_var.set(actor or SYSTEM_ACTOR)


def current_actor() -> str:
    """지금 이 실행 컨텍스트의 actor — 컬럼 default/onupdate가 **실행 시점에** 호출한다."""
    return _actor_var.get()


def _now() -> datetime:
    return datetime.now(UTC)


class AuditMixin:
    """감사 4컬럼. 우리 소유 전 테이블이 상속한다(외부 라이브러리 소유 테이블은 제외 — 스펙 343 §1).

    최초 삽입 시 4개가 모두 채워진다(created == updated). `created_*`는 이후 불변.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_now,
        onupdate=_now,
        server_default=func.now(),
        nullable=False,
    )
    created_by: Mapped[str] = mapped_column(String(80), default=current_actor, nullable=False)
    updated_by: Mapped[str] = mapped_column(
        String(80), default=current_actor, onupdate=current_actor, nullable=False
    )


@event.listens_for(OrmSession, "before_flush")
def _freeze_created(session: OrmSession, _ctx: Any, _instances: Any) -> None:
    """생성 정보 불변 — UPDATE에서 created_at/created_by를 바꾸려 하면 옛 값으로 되돌린다.

    (DB 트리거였다면 DB가 봉했을 자리. ORM 경로 한정이라는 것이 이 설계의 정직한 한계 — Core
    update().values(created_by=…) 같은 직접 덮어쓰기는 테스트가 잡는 선까지다.)
    """
    for obj in session.dirty:
        if not isinstance(obj, AuditMixin):
            continue
        state = inspect(obj)
        for col in ("created_at", "created_by"):
            hist = state.attrs[col].history
            if hist.deleted:  # 이전 값이 밀려났다 = 변경 시도
                setattr(obj, col, hist.deleted[0])

"""models.sessions — 도메인 테이블(스펙 379 분할·verbatim 이관)."""

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..audit import AuditMixin
from .base import Base, _pk


class Session(AuditMixin, Base):
    __tablename__ = "sessions"
    # owner-선두 복합 인덱스(스펙 073, 070 P2 봉합) — member 읽기 `WHERE user_id=:own AND ...`에서
    # 타인-존재행을 인덱스 진입 단계에서 부재행과 동일하게 미스시켜 heap-fetch 타이밍 델타를 제거.
    # session_id 단독 unique는 전역 uniqueness 보장용으로 유지(get-or-create flush 의존). 플래너가
    # 실제로 이 복합을 선택하는지는 EXPLAIN으로 측정(verify_073_explain) — 선언만으론 봉합 미완.
    __table_args__ = (
        Index("ix_sessions_user_id_session_id", "user_id", "session_id"),
        Index("ix_sessions_user_id_agent_pk_session_id", "user_id", "agent_pk", "session_id"),
    )
    id: Mapped[uuid.UUID] = _pk()
    session_id: Mapped[str] = mapped_column(String(80), unique=True)  # sess_...
    agent_pk: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), index=True
    )
    agent_name: Mapped[str] = mapped_column(String(200), default="")
    channel: Mapped[str] = mapped_column(String(80), default="debug-console")
    # 이 세션에서 마지막으로 쓰인 non-empty userId(mem0 user_id 축). distinct 목록 출처 — 스펙 021.
    # 세션당 1값이라 도중 변경 시 마지막 값만 남는다(목록 생성엔 충분, 합의된 한계).
    user_id: Mapped[str | None] = mapped_column(String(80), index=True, default=None)
    status: Mapped[str] = mapped_column(String(20), default="active")
    turns: Mapped[int] = mapped_column(Integer, default=0)
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_activity: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    messages: Mapped[list["Message"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="Message.created_at"
    )


class Message(AuditMixin, Base):
    __tablename__ = "messages"
    id: Mapped[uuid.UUID] = _pk()
    session_pk: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20))  # user | assistant
    content: Mapped[str] = mapped_column(Text, default="")
    trace: Mapped[dict | None] = mapped_column(JSONB, default=None)  # 인스펙터용 트레이스
    # 턴 id(스펙 364) — 한 턴의 user+assistant 두 행에 같은 값(=런타임 thread_id). 이력을 턴 단위로
    # 묶어 분석 가능케 한다(예전엔 세션+시간순만이라 턴 경계 소실). HIL/폼 재개가 얽혀도 한 턴 1 id.
    # 과거 행은 null(소급 안 함 — thread_id 이미 소실). index로 turn 그룹핑 조회.
    turn_id: Mapped[str | None] = mapped_column(String(200), index=True, default=None)
    # 프롬프트(프롬프트) 출처(스펙 364, 옵션 b) — 이 턴에 실제 쓰인 프롬프트. assistant 행에만 스탬프
    # (user 행은 프롬프트 무관). 라이브러리 참조면 id·name 有, 인라인/오버라이드면 null(정직). FK 아님
    # (provenance는 프롬프트 삭제 후에도 살아남아야 — 역사 기록). body 스냅샷은 trace.promptSnapshot.
    prompt_id: Mapped[str | None] = mapped_column(String(80), index=True, default=None)
    prompt_name: Mapped[str | None] = mapped_column(String(200), default=None)

    session: Mapped[Session] = relationship(back_populates="messages")


class MessageFeedback(AuditMixin, Base):
    """응답 피드백(스펙 209) — assistant 메시지에 대한 👍/👎 + 이유. 평가 케이스 수확의 원천.

    소유권: `owner_id`=서버 도출 auth User UUID str(위조 불가, 세션 소유 스코프로 게이트). 한 사용자가
    한 메시지에 1건(재클릭=upsert). session_pk는 소유 스코프 조회·수확 집계용(에이전트 세션 묶음)."""

    __tablename__ = "message_feedback"
    __table_args__ = (
        # 사용자당 메시지당 1건(upsert 키). 소유 스코프·수확 집계용 인덱스는 컬럼 index=True로.
        Index("uq_message_feedback_msg_user", "message_pk", "owner_id", unique=True),
    )
    id: Mapped[uuid.UUID] = _pk()
    message_pk: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), index=True
    )
    session_pk: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    rating: Mapped[str] = mapped_column(String(8))  # 'up' | 'down'
    reason: Mapped[str] = mapped_column(Text, default="")
    # 피드백 작성자(스펙 209) — auth User UUID str. **감사용 created_by(스펙 343, 이메일 로컬파트)와는
    # 별개 개념**이라 343에서 owner_id로 개명(다른 테이블의 소유자 컬럼과 같은 이름·같은 값 형식).
    owner_id: Mapped[str] = mapped_column(String(80), index=True)
    # 수확 링크(스펙 209 Phase 2) — 이 피드백에서 만든 평가 케이스. NULL=미수확. 케이스 삭제 시 SET NULL
    # (재수확 가능). 재수확 방지·피드백↔케이스 추적.
    harvested_case_pk: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("eval_cases.id", ondelete="SET NULL"), default=None, index=True
    )


# ----------------------------- 승인 큐 -----------------------------
class Approval(AuditMixin, Base):
    __tablename__ = "approvals"
    id: Mapped[uuid.UUID] = _pk()
    approval_id: Mapped[str] = mapped_column(String(80), unique=True)  # apr_...
    session_id: Mapped[str | None] = mapped_column(String(80), default=None)
    # 요청 주체(auth User UUID str). None = 머신/레거시 = owner-resolvable 아님(admin 전용).
    # owner self-승인(스펙 066)의 진실 원천 — resolve는 이 값을 current_principal과 대조한다.
    user_id: Mapped[str | None] = mapped_column(String(80), default=None)
    agent_pk: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL"), default=None
    )
    agent_name: Mapped[str] = mapped_column(String(200), default="")
    permission: Mapped[str] = mapped_column(String(120), default="")
    # 승인자(스펙 177 P2) — "admin"=관리자만 resolve, "self"=요청 소유자 본인. None=레거시·메모리·A2A
    # → _may_resolve가 Casbin can_self_approve 폴백(무회귀). MCP 도구 승인만 리졸버가 이 값을 스탬프.
    approver: Mapped[str | None] = mapped_column(String(20), default=None)
    action: Mapped[str] = mapped_column(String(120), default="")
    args: Mapped[dict] = mapped_column(JSONB, default=dict)
    summary: Mapped[str] = mapped_column(Text, default="")
    checkpoint: Mapped[str | None] = mapped_column(String(80), default=None)
    # 생성 시점 impl 키 스냅샷(위상 정체, 스펙 171). "" = 기본(DefaultUiAgent), "key" = 커스텀,
    # None = 마이그레이션 이전 행(대조 스킵). 재개가 다른 impl(다른 그래프 위상)로 stale checkpoint에
    # resume하는 미정의 동작을 명시 가드로 막는 대조 기준.
    impl: Mapped[str | None] = mapped_column(String(120), default=None)
    # pending|approved|rejected|expired — expired는 사람의 결정이 아니라 체크포인트 스윕이
    # TTL을 넘긴 대기 건을 회수하며 남긴 상태다(스펙 346). 재개 불가이며 resolve는 409.
    status: Mapped[str] = mapped_column(String(20), default="pending")
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # 처리 감사(스펙 181) — resolve 시 스탬프. NULL=미처리 또는 레거시(마이그레이션 이전 행).
    # resolved_by=처리자 user_id str. user_id(요청자)와 같으면 본인 승인, 다르면 관리자 처리.
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    resolved_by: Mapped[str | None] = mapped_column(String(80), default=None)


# ----------------------------- 인증·권한 (스펙 031) -----------------------------
# 인증은 fastapi-users 규약을 차용한다. User/AccessToken 베이스 믹스인을 우리 Base와 결합해
# 같은 metadata(alembic·create_all)에 매핑한다. 테이블명은 라이브러리 기본값(user/accesstoken).
# 권한(RBAC)은 Casbin이 담당하며 role 할당의 진실 원천은 casbin_rule(어댑터가 런타임 생성)이다.
# roles는 UI 표시·관리용 가벼운 카탈로그일 뿐(할당 저장소가 아님).

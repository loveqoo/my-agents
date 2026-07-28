"""models.batch — 도메인 테이블(스펙 379 분할·verbatim 이관)."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..audit import AuditMixin
from .base import Base, _pk


class BatchRun(AuditMixin, Base):
    """배치 실행 감사 로그 — 매 run을 박제(시작→ok/error + 건수). 가시성·idempotency 추적."""

    __tablename__ = "batch_runs"
    id: Mapped[uuid.UUID] = _pk()
    job_name: Mapped[str] = mapped_column(String(80), index=True)
    status: Mapped[str] = mapped_column(String(20), default="running")  # running|ok|error
    dry_run: Mapped[bool] = mapped_column(Boolean, default=False)
    summary: Mapped[dict | None] = mapped_column(JSONB, default=None)  # 건수 등 결과
    error: Mapped[str | None] = mapped_column(Text, default=None)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class BatchConfig(AuditMixin, Base):
    """배치 운영 설정(싱글톤 1행). 값은 기본 NULL → 아무 것도 자동 발화·삭제하지 않는다(보수적 기본).

    `session_retention_days`: NULL=비활성. N이면 last_activity가 N일보다 오래된 세션을 정리 대상으로.
    `session_cleanup_cron`: 격리 배치 서비스의 내부 스케줄러가 읽는 cron식(예 "0 3 * * *"). NULL=미등록.
    `min_session_turns`: NULL=비활성. N이면 turns<N인 *이탈* 세션(활성 보호: last_activity가 내부
      IDLE_GUARD=1h보다 오래된 것만)을 정리 대상으로(스펙 049, #10). 나이 기준과 합집합. 0은 모든
      세션 대상이 되는 footgun이라 API에서 ge=1, jobs에서도 <1 가드(learning 037 — 파괴적 노브 바닥).
    `memory_consolidation_threshold`: NULL=비활성. 의미상 ≥2 — user_id 기억이 이 수를 넘은 유저만
      통합 대상(스펙 039). 0/1은 거의 모든 유저를 매번 통합하는 파괴적 churn이라 API에서 ge=2로 거르고
      jobs에서도 <2 가드(learning 037 — 파괴적 노브 바닥).
    `memory_consolidation_cron`: 메모리 통합 작업의 cron식. NULL=미등록.
    `test_user_email_pattern`: NULL=비활성. SQL LIKE 패턴(예 "verify%@example.com"). `user-cleanup`
      잡이 이 패턴에 일치하는 유저를 정리 대상으로(스펙 050, #13). 가장 비가역이라 바닥 3겹 —
      `%`/빈 패턴은 delete-all이라 API에서 거부, 하드코딩 keep-list(부트스트랩·데모) 제외, 마지막
      슈퍼유저는 보존. NULL은 명시 비활성(learning 037 — 파괴적 노브 바닥).
    """

    __tablename__ = "batch_config"
    id: Mapped[uuid.UUID] = _pk()
    # 기본 180일 ON(스펙 429, 구남님 승인) — 살아있는 유저 메시지의 무한 증가 차단. NULL=비활성이나
    # 신규 싱글톤은 이 기본으로 켜져 생성(checkpoint/token/approval 기본 ON 선례와 정합). 기존 싱글톤은
    # 마이그레이션이 NULL→180 반영(사용자 커스텀 값은 보존). last_activity<cutoff라 활성 세션 자연 보존.
    session_retention_days: Mapped[int | None] = mapped_column(Integer, default=180)
    session_cleanup_cron: Mapped[str | None] = mapped_column(String(120), default="0 3 * * *")
    min_session_turns: Mapped[int | None] = mapped_column(Integer, default=None)
    memory_consolidation_threshold: Mapped[int | None] = mapped_column(Integer, default=None)
    memory_consolidation_cron: Mapped[str | None] = mapped_column(String(120), default=None)
    test_user_email_pattern: Mapped[str | None] = mapped_column(String(200), default=None)
    # 체크포인트 스윕(스펙 346). `checkpoint_ttl_hours`: 이보다 오래된 스레드만 회수(진행 중 턴·폼
    # 대기 보호선). NULL/<1이면 비활성 — 0을 "즉시 전량 삭제"로 매핑하지 않는다(learning 037 바닥).
    # `checkpoint_cleanup_cron`: NULL=미등록(기존 계약). 정상 경로는 턴 종료 관문이 덮고, 이 잡은
    # 크래시가 남긴 고아와 방치된 승인 대기를 회수한다.
    # 이 둘만 기본값이 NULL이 아니다(다른 노브의 "기본 비활성" 관례에서 벗어남 — 사유 명시):
    # 청소하지 않으면 체크포인트가 무한 누적되는 게 **기본 동작**이라(스펙 346 실측: 대화의 20~30배),
    # 여기선 "안 하기"가 보수적인 쪽이 아니다. 파괴 반경도 좁다 — 지우는 대상은 재개 근거(체크포인트)
    # 뿐이고 대화·메시지·세션은 건드리지 않으며, 24h 문턱이 진행 중 턴을 지킨다. 끄려면 cron=NULL.
    checkpoint_ttl_hours: Mapped[int | None] = mapped_column(Integer, default=24)
    checkpoint_cleanup_cron: Mapped[str | None] = mapped_column(String(120), default="0 * * * *")
    # 만료 토큰 회수(스펙 349) — 수명·유예는 인증 설정(AUTH_SESSION_LIFETIME)에서 읽으므로 cron만.
    # 기본값이 있는 이유는 346과 같다: 안 치우면 무한 누적이 기본 동작이라 "안 하기"가 보수적이지 않다.
    token_cleanup_cron: Mapped[str | None] = mapped_column(String(120), default="0 4 * * *")
    # 처리된 승인 회수(스펙 350) — pending은 재개 근거라 절대 대상이 아니다(방치 pending은 346 스윕이
    # expired로 바꾼 뒤 이 보존기간을 탄다). NULL/<1이면 비활성.
    approval_retention_days: Mapped[int | None] = mapped_column(Integer, default=30)
    approval_cleanup_cron: Mapped[str | None] = mapped_column(String(120), default="30 4 * * *")
    # 실행 이력 보존(스펙 351) — eval_runs·batch_runs·memory_snapshots 공통. eval_runs는 문제집별
    # 최근 10런을 나이와 무관하게 보존한다(성적 추이 앵커). NULL/<1이면 비활성.
    history_retention_days: Mapped[int | None] = mapped_column(Integer, default=90)
    history_cleanup_cron: Mapped[str | None] = mapped_column(String(120), default="0 5 * * *")
    # 스펙 352 — mem0 도달 불가 기억(유령) 회수. 유예: 세션 행이 없는 살아있는 대화
    # (persistHistory=false·서비스 프린시펄)를 유령으로 오판하지 않기 위한 창.
    memory_orphan_grace_days: Mapped[int | None] = mapped_column(Integer, default=7)
    memory_cleanup_cron: Mapped[str | None] = mapped_column(String(120), default="30 5 * * *")


class MemorySnapshot(AuditMixin, Base):
    """유저 메모리 통합(스펙 039) 전 원본 기억의 백업·롤백 앵커. 통합 작업이 원본을 삭제하기 전에
    여기 박제(text 원문 보존)한다 → 잘못돼도 수동 복원 가능(스냅샷 text를 add(infer=False)로 재적재).

    batch_run_id는 어느 실행이 만든 백업인지 추적용 FK. 실행 감사행(batch_runs)이 지워져도 스냅샷은
    살아남아야 하므로 ondelete SET NULL(롤백 데이터는 감사행 수명과 독립). user_id=mem0 축(str),
    mem_id=원본 mem0 기억 id. 이 테이블은 mem0가 아니라 우리가 소유·관리한다(learning 033).
    """

    __tablename__ = "memory_snapshots"
    id: Mapped[uuid.UUID] = _pk()
    batch_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("batch_runs.id", ondelete="SET NULL"),
        default=None,
        index=True,
    )
    user_id: Mapped[str] = mapped_column(String(200), index=True)
    mem_id: Mapped[str] = mapped_column(String(200))
    text: Mapped[str] = mapped_column(Text)


class AllowedHost(AuditMixin, Base):
    """SSRF 가드(스펙 042) allowlist의 **진실원**(스펙 064 — env→DB 이관).

    `guard_url`은 사설/루프백 대역으로의 outbound를 기본 차단하되, 이 테이블의 host는 예외로 통과시킨다.
    이 allowlist는 한 chokepoint(`guard_url`)를 거쳐 **A2A 클라이언트·Agent Card fetch/probe·MCP 런타임·
    MCP blocks 전부**에 적용된다 — 그래서 이름에서 `A2A_` 접두어를 뗐다(공용 allowlist).

    host는 정규화(`net_guard.normalize_allowed_host` — `strip().lower()`, 스킴/포트/와일드카드/CIDR/
    userinfo 불가, IP는 canonical)되어 저장되며, guard_url의 `host.lower() in set` *정확* 매칭과 동형이다
    (와일드카드/서브넷은 allow-all SSRF footgun이라 도입 안 함, 스펙 064 §3). 런타임은 net_guard의 캐시
    스냅샷이 짧은 TTL로 이 테이블을 읽어 **무재시작** 반영. env(`ALLOWED_HOSTS`)는 첫 부팅 1회 시드
    소스일 뿐(alembic 데이터 마이그레이션이 임포트) — 이후 이 테이블이 단일 소스다(learning 012).
    """

    __tablename__ = "allowed_hosts"
    id: Mapped[uuid.UUID] = _pk()
    host: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    note: Mapped[str | None] = mapped_column(String(200), default=None)


# ----------------------------- 평가 하네스 제품화 (스펙 137) -----------------------------

"""체크포인트 수명 관리 — 턴이 끝난 스레드를 폐기하는 **관문** (스펙 346).

**왜 필요한가**: `thread_id`는 턴별 고유다(`chat.py:_resolve_graph_entry` — 세션-안정이 아니다).
그래서 턴이 끝나면 그 스레드의 체크포인트는 **영원히 아무도 안 읽는다**. 유일한 독자는 HIL 재개
(승인 대기·산출물 폼 대기)뿐이다. 지우지 않으면 끝난 턴의 시체가 무한 누적된다(실측: messages 520행
대비 checkpoints 10,191행).

**관문이 하나인 이유**(회고 316): 폐기 판정을 호출부마다 두면 새 호출부에서 샌다. `release_thread`
하나가 보존 조건을 판정하고, 배치 스윕도 **같은 술어**를 재사용한다(learning 050 — 가드는 한 술어로
모든 입구에).

**보존 조건**(둘 중 하나면 남긴다):
  - 승인 대기: `Approval.status='pending'` AND `Approval.checkpoint == thread_id` (DB — 프로세스 무관)
  - 산출물 폼 대기: `chat_approval._PENDING_ARTIFACT`가 그 스레드를 가리킴 (프로세스 메모리)

폼 대기는 프로세스 로컬이라 **배치 스윕(별 프로세스)은 볼 수 없다** — 그래서 스윕은 나이 문턱
(TTL)을 반드시 함께 건다. 24시간 넘게 폼을 열어둔 채 방치된 스레드는 이미 죽은 것으로 본다
(API 재시작만으로도 그 포인터는 사라진다).
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text, update

from . import checkpointer
from .db import SessionLocal
from .models import Approval

log = logging.getLogger("api.checkpoint_retention")

# 방치된 승인 대기의 기본 만료 시한(사용자 결정, 스펙 346). BatchConfig로 덮어쓸 수 있다.
DEFAULT_TTL_HOURS = 24


async def _pinned_by_approval(thread_id: str) -> bool:
    """미해결 승인이 이 스레드를 재개 키로 잡고 있나(DB — 워커·프로세스 무관)."""
    async with SessionLocal() as s:
        row = (
            await s.execute(
                select(Approval.id)
                .where(Approval.checkpoint == thread_id)
                .where(Approval.status == "pending")
                .limit(1)
            )
        ).first()
    return row is not None


def _pinned_by_artifact(thread_id: str) -> bool:
    """산출물 폼/질문이 이 스레드에서 사용자 입력을 기다리나(스펙 188 — 프로세스 메모리).

    지연 import: `chat_approval`이 이 모듈을 부르는 쪽이라 모듈 최상단에서 끌면 순환이 된다.
    """
    from .chat_approval import _PENDING_ARTIFACT

    return any(p.get("thread_id") == thread_id for p in _PENDING_ARTIFACT.values())


async def keep_reason(thread_id: str) -> str | None:
    """보존 사유('approval'·'artifact') 또는 None(폐기 가능). 관문과 스윕의 **공통 술어**."""
    if await _pinned_by_approval(thread_id):
        return "approval"
    if _pinned_by_artifact(thread_id):
        return "artifact"
    return None


async def release_thread(thread_id: str, *, paused: bool = False) -> str:
    """**관문** — 턴이 끝난 스레드를 폐기한다. 보존 조건이면 남긴다.

    반환: 'deleted' · 'kept:paused' · 'kept:approval' · 'kept:artifact' · 'no-checkpointer'.
    호출: 채팅 스트림 종료(정상·에러·클라 끊김 모두 = event_stream의 finally) · 승인 재개 완료.

    **`paused`가 규칙의 중심이다**(codex 적대 검토 P1): 처음엔 "핀(승인·폼 대기)이 있으면 보존"으로
    짰는데, 핀은 interrupt **이후에** 심긴다(승인 행 커밋 · _PENDING_ARTIFACT 등록). 그 사이에
    클라이언트가 끊기거나 워커가 취소되면 finally가 먼저 돌아 **멈춘 그래프를 지운다** — 아직 아무도
    가리키지 않지만 **일시정지된 상태 자체가 재개의 근거**다. 그래서 판정 기준을 "핀이 있나"가 아니라
    **"턴이 정말 끝났나"**로 바꾼다: 그래프가 멈춘 채면(paused) 핀 유무와 무관하게 남긴다. 진짜로
    버려진 것이면 TTL 스윕이 24h 뒤 회수한다(파괴보다 누수 쪽으로 기운다).

    **정리 실패가 턴을 죽이면 안 된다** — 예외는 삼키고 경고만(체크포인트 잔류는 스윕이 회수).
    """
    saver = checkpointer.get_checkpointer()
    if saver is None:
        return "no-checkpointer"
    try:
        if paused:
            return "kept:paused"
        reason = await keep_reason(thread_id)
        if reason:
            return f"kept:{reason}"
        await saver.adelete_thread(thread_id)
        return "deleted"
    except Exception as exc:  # 청소는 결코 턴을 깨뜨리지 않는다(스윕이 백스톱)
        log.warning("체크포인트 스레드 폐기 실패(스윕이 회수): %s — %s", thread_id, exc)
        return "error"


async def sweep(*, dry_run: bool, ttl_hours: int) -> dict:
    """TTL 스윕 — 관문을 못 탄 고아 + 방치된 승인 대기를 회수한다(배치 잡 본체, 스펙 346).

    관문(`release_thread`)이 정상 경로를 덮지만, **프로세스가 죽은 턴**은 못 탄다(learning 048 —
    한 수명 경계에 건 보장은 수명 전체를 못 덮는다). 그 고아를 나이로 회수한다.

    나이는 `checkpoints.checkpoint->>'ts'`(LangGraph가 박는 ISO 타임스탬프). TTL보다 **어린 스레드는
    절대 안 건드린다** — 진행 중인 턴(분 단위)과 프로세스 메모리에만 있는 폼 대기를 이 문턱이 지킨다.

    방치된 승인 대기는 **조용히 지우지 않는다**: 체크포인트만 지우면 승인은 화면에 pending으로 남은 채
    재개만 실패한다(회고 038의 적대리뷰가 잡은 resume 고아). `status='expired'`로 만료를 기록한 뒤
    스레드를 지운다 — 상태와 수명이 한 트랜잭션에서 같이 움직인다.

    파괴적 노브엔 바닥(learning 037): ttl_hours가 None/<1이면 **아무 것도 안 지운다**(0=즉시 전량
    삭제로 매핑 금지).
    """
    # 배치는 **별 프로세스**라 API lifespan이 채운 싱글턴이 비어 있다 — 없으면 여기서 연다(멱등).
    # 이 한 줄이 없으면 스윕이 no-checkpointer로 조용히 무동작한다(잡은 초록, 청소는 0).
    saver = checkpointer.get_checkpointer() or await checkpointer.init_checkpointer()
    if saver is None:
        return {"status": "no-checkpointer", "deleted": 0, "expired": 0}
    if ttl_hours is None or ttl_hours < 1:
        return {"status": "disabled", "reason": "ttl_hours<1", "deleted": 0, "expired": 0}

    cutoff = datetime.now(UTC) - timedelta(hours=ttl_hours)
    async with SessionLocal() as s:
        # TTL보다 오래된 스레드만 후보(그 안의 최신 체크포인트 ts 기준 — 진행 중 턴 보호).
        rows = (
            await s.execute(
                text(
                    "select thread_id, max(checkpoint->>'ts') as last_ts from checkpoints "
                    "group by thread_id having max(checkpoint->>'ts') < :cutoff"
                ),
                {"cutoff": cutoff.isoformat()},
            )
        ).all()
        stale = [r[0] for r in rows]

        # 나이를 모르는 스레드(ts 없음/NULL — 다른 버전·수기 삽입이 남긴 행): `NULL < cutoff`는 참이
        # 아니라 위 질의에서 **조용히 빠진다** → 영구 잔류(누수). 나이를 모른다고 지우는 건 파괴적이라
        # 지우지는 않되, **세어서 요약에 드러낸다**(안 보이는 누수 < 보이는 누수).
        unknown_age = (
            await s.execute(
                text(
                    "select count(*) from (select thread_id from checkpoints group by thread_id "
                    "having max(checkpoint->>'ts') is null) t"
                )
            )
        ).scalar_one()
        if unknown_age:
            log.warning("나이를 모르는 체크포인트 스레드 %d개 — 스윕 대상 아님(수동 확인 필요)", unknown_age)
        if not stale:
            return {"status": "dry_run" if dry_run else "ok", "ttl_hours": ttl_hours,
                    "candidates": 0, "deleted": 0, "expired": 0, "unknown_age": unknown_age}

        # 방치된 승인 대기 — 만료 대상(체크포인트를 지우면 재개 불가가 되므로 상태를 함께 바꾼다).
        pending = (
            await s.execute(
                select(Approval.approval_id, Approval.checkpoint)
                .where(Approval.checkpoint.in_(stale))
                .where(Approval.status == "pending")
            )
        ).all()
        expiring = [p[0] for p in pending]

        if dry_run:
            return {
                "status": "dry_run",
                "ttl_hours": ttl_hours,
                "cutoff": cutoff.isoformat(),
                "candidates": len(stale),
                "would_delete": len(stale),
                "would_expire": len(expiring),
                "unknown_age": unknown_age,
                "sample": stale[:20],
            }

        if expiring:
            await s.execute(
                update(Approval)
                .where(Approval.approval_id.in_(expiring))
                .values(status="expired")
            )
            await s.commit()

    deleted = 0
    for tid in stale:
        try:
            await saver.adelete_thread(tid)
            deleted += 1
        except Exception as exc:
            log.warning("스윕 삭제 실패(다음 회차 재시도): %s — %s", tid, exc)

    log.info("체크포인트 스윕: 삭제 %d · 승인 만료 %d (TTL %dh)", deleted, len(expiring), ttl_hours)
    return {
        "status": "ok",
        "ttl_hours": ttl_hours,
        "cutoff": cutoff.isoformat(),
        "candidates": len(stale),
        "deleted": deleted,
        "expired": len(expiring),
        "unknown_age": unknown_age,
    }

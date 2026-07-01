"""세션 라우터 (007 도메인). 세션 조회·메시지·종료."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from . import authz
from .auth import current_principal
from .db import get_session
from .models import Agent, Message, Session
from .schemas import MessageOut, SessionOut, SessionPage
from .serializers import session_to_out

router = APIRouter(prefix="/sessions", tags=["sessions"])


# ----------------------------- 유저별 스코핑 (스펙 067) -----------------------------
# 세션은 개인 대화 데이터다. approvals(066)·memory(052)와 동일하게 비-admin은 자기 user_id
# 세션만 본다. Session.user_id는 *서버가 도출*한 값(chat.py: 쿠키 유저=str(user.id), 머신=NULL)
# 이라 위조 불가(요청 본문 무관). admin/머신은 전체. 비교 축은 approvals.user_id와 동일.
def _is_admin(principal) -> bool:
    """전체 세션 열람 권한인가 — 머신 토큰 OR superuser OR `sessions:read` 유저.

    obj/act가 approvals와 달라 approvals._is_admin과 공유하지 않고 로컬 미러(라우터 독립).
    기본 정책엔 sessions:read가 없으므로 member는 매칭 안 됨(superuser만 전체) — 추후
    `(role, sessions, read)` 한 줄로 "전체 세션 열람 운영자"를 열 수 있는 훅.
    """
    if isinstance(principal, str):  # "machine" 센티넬 = 전체 접근(스펙 011/031)
        return True
    if getattr(principal, "is_superuser", False):
        return True
    return authz.get_enforcer().enforce(str(principal.id), "sessions", "read")


def _own_scope(principal) -> str | None:
    """스코핑 키 — 비-admin이면 자기 user_id(본인 것만), admin/머신이면 None(전체)."""
    if _is_admin(principal):
        return None
    return str(principal.id)


# 버킷 → status 매핑 (단일출처 — 프론트는 버킷 문자열만 보낸다). 스펙 034.
_STATUS_BUCKETS: dict[str, tuple[str, ...]] = {
    "live": ("active", "running", "draining"),
    "awaiting": ("awaiting",),
    "error": ("error",),
}


def _bucket_of(status: str) -> str | None:
    """status 값이 속한 배지 버킷(all 제외). 미매핑 status는 None."""
    for bucket, members in _STATUS_BUCKETS.items():
        if status in members:
            return bucket
    return None


async def _agent_id_map(session: AsyncSession) -> dict:
    """agent pk(UUID) → 외부 agent_id(agt_...) 매핑."""
    rows = (await session.execute(select(Agent.id, Agent.agent_id))).all()
    return {row.id: row.agent_id for row in rows}


_PREVIEW_LEN = 80


async def _badge_counts(session: AsyncSession, own: str | None = None) -> dict:
    """배지 카운트: GROUP BY 1회 → 버킷으로 접기 (status 필터 무관).

    `own`이 주어지면(비-admin) 본인 user_id 세션만 집계 — 전역 카운트 누설 차단(스펙 067 T6).
    admin/머신(own=None)은 전역.
    """
    counts = {"all": 0, "live": 0, "awaiting": 0, "error": 0}
    q = select(Session.status, func.count()).group_by(Session.status)
    if own is not None:
        q = q.where(Session.user_id == own)
    grouped = (await session.execute(q)).all()
    for st, n in grouped:
        counts["all"] += n
        bucket = _bucket_of(st)
        if bucket is not None:
            counts[bucket] += n
    return counts


async def _session_previews(session: AsyncSession, pks: list) -> dict:
    """세션 pk → 첫 사용자 메시지 일부(사람이 알아볼 라벨, 스펙 055). 페이지의 세션만 1쿼리.

    role='user' 메시지를 (session_pk, created_at) 정렬로 한 번에 받아 세션별 *최초*만 취한다.
    """
    if not pks:
        return {}
    rows = (
        await session.execute(
            select(Message.session_pk, Message.content)
            .where(Message.session_pk.in_(pks), Message.role == "user")
            .order_by(Message.session_pk, Message.created_at)
        )
    ).all()
    out: dict = {}
    for pk, content in rows:
        if pk not in out:  # 정렬상 첫 행 = 최초 사용자 메시지
            text = (content or "").strip().replace("\n", " ")
            out[pk] = text[:_PREVIEW_LEN] + ("…" if len(text) > _PREVIEW_LEN else "")
    return out


def _like_escape(term: str) -> str:
    """ilike 리터럴화 — 사용자 입력의 `\\`·`%`·`_`를 이스케이프해 와일드카드 오라클/과매칭 차단.
    `escape="\\"`와 함께 쓴다. 순서 중요: `\\`를 먼저 치환(뒤 치환이 넣은 이스케이프를 재이스케이프 방지)."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@router.get("", response_model=SessionPage)
async def list_sessions(
    status: str = "all",
    agent_id: str | None = None,
    q: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
    principal=Depends(current_principal),
) -> SessionPage:
    """세션 목록 (페이징·필터·검색·배지 집계). 스펙 034 + agent 필터(055) + 스코핑(067) + 검색(098).

    - `status`: 버킷(all|live|awaiting|error). 미지정/미지의 값은 all로 폴백(관대).
    - `agent_id`: 외부 agent_id(agt_...). 주어지면 해당 에이전트 세션만(items/total). Playground
      세션 이어가기용. 미지의 id는 빈 목록(404 아님 — 목록 API 관대).
    - `q`(098): 메타데이터 검색 — session_id·user_id·agent_name 부분일치(OR ilike). status·agent_id·
      스코프와 **AND**(페이징 이전 전체 스코프 매칭). 빈/공백은 무시. `%_\\`는 리터럴 이스케이프.
    - 스코핑(067): 비-admin은 자기 user_id 세션만(NULL-owner 숨김). admin/머신은 전체.
      `counts`도 동일 스코프(member 배지=본인 수). **검색은 스코프를 넓힐 수 없다**(AND는 좁히기만).
    - `total`: 현재 필터 적용 총 건수. `counts`: status·검색 무관 집계(배지용, 스코프 동일).
    """
    own = _own_scope(principal)
    members = _STATUS_BUCKETS.get(status)

    base = select(Session)
    if own is not None:  # 비-admin: 본인 세션만(NULL-owner 자동 제외)
        base = base.where(Session.user_id == own)
    if members is not None:
        base = base.where(Session.status.in_(members))
    if q and q.strip():
        # own-scope WHERE 뒤에 AND로 얹는다 → 소유권 경계 상속(스코프 확장 불가).
        term = f"%{_like_escape(q.strip())}%"
        base = base.where(
            or_(
                Session.session_id.ilike(term, escape="\\"),
                Session.user_id.ilike(term, escape="\\"),
                Session.agent_name.ilike(term, escape="\\"),
            )
        )
    if agent_id is not None:
        # 외부 agent_id → pk로 해석해 Session.agent_pk 필터. agent 스코프 한정(타 에이전트 누출 0).
        agent_pk = (
            await session.execute(select(Agent.id).where(Agent.agent_id == agent_id))
        ).scalar_one_or_none()
        if agent_pk is None:
            # 미지의 agent_id → 빈 목록(관대, 404 아님). `== None`은 SQL상 IS NULL이라
            # NULL agent_pk 행을 잡을 수 있으므로(스키마상 비-NULL이지만 방어적) 명시 단락한다.
            return SessionPage(items=[], total=0, counts=await _badge_counts(session, own))
        base = base.where(Session.agent_pk == agent_pk)

    total = (
        await session.execute(select(func.count()).select_from(base.subquery()))
    ).scalar_one()

    rows = (
        await session.execute(
            base.order_by(Session.started_at.desc(), Session.id.desc())
            .offset(offset)
            .limit(limit)
        )
    ).scalars().all()

    counts = await _badge_counts(session, own)
    amap = await _agent_id_map(session)
    previews = await _session_previews(session, [s.id for s in rows])
    items = [
        session_to_out(s, amap.get(s.agent_pk), previews.get(s.id)) for s in rows
    ]
    return SessionPage(items=items, total=total, counts=counts)


async def _get_session_or_404(
    session: AsyncSession, session_id: str, own: str | None = None
) -> Session:
    """session_id로 세션을 로드. `own`(비-admin 스코프)이 주어지면 **가시성 게이트를 쿼리에
    융합**한다 — `Session.user_id == own`을 WHERE에 더해, 타인 세션·NULL-owner·부재가 *모두*
    동일한 단일 쿼리에서 `None`으로 떨어진다(동일 404 경로).

    이렇게 거부행을 *로드조차 안 함*으로써 fetch-then-check가 남기던 타이밍 측면채널을 제거한다
    (스펙 067 D4를 070이 봉합, retrospect 056 [P3-1], 069 체크리스트 2(a)). 볼 수 없는 세션을
    404로 은폐해 403↔404 열거 오라클도 차단(learning 068). own=None(admin/머신)이면 무스코프(전체)."""
    q = select(Session).where(Session.session_id == session_id)
    if own is not None:
        q = q.where(Session.user_id == own)
    s = (await session.execute(q)).scalar_one_or_none()
    if s is None:
        raise HTTPException(status_code=404, detail="not found")
    return s


@router.get("/users", response_model=list[str])
async def list_user_ids(
    session: AsyncSession = Depends(get_session),
    principal=Depends(current_principal),
) -> list[str]:
    """대화에 쓰인 distinct userId, 최근 사용순(스펙 021 — Playground 헤더 선택지).

    스코핑(067): 비-admin은 자기 user_id만(본인 세션이 있으면 `[own]`, 없으면 `[]`). memory
    `list_memory_users`가 비-curator에게 자기 신원만 주는 것과 동형. admin/머신은 전체 distinct.

    NOTE: 이 정적 경로는 아래 `/{session_id}`보다 **먼저** 선언돼야 가려지지 않는다.
    """
    own = _own_scope(principal)
    q = (
        select(Session.user_id, func.max(Session.last_activity).label("last"))
        .where(Session.user_id.is_not(None))
        .group_by(Session.user_id)
        .order_by(func.max(Session.last_activity).desc())
    )
    if own is not None:  # 비-admin: 본인 user_id만(있을 때만 1건)
        q = q.where(Session.user_id == own)
    rows = (await session.execute(q)).all()
    return [r.user_id for r in rows]


@router.get("/{session_id}", response_model=SessionOut)
async def get_session_detail(
    session_id: str,
    session: AsyncSession = Depends(get_session),
    principal=Depends(current_principal),
) -> SessionOut:
    s = await _get_session_or_404(session, session_id, _own_scope(principal))  # 스코프 융합(067/070)
    a = await session.get(Agent, s.agent_pk)
    return session_to_out(s, a.agent_id if a else None)


@router.get("/{session_id}/messages", response_model=list[MessageOut])
async def list_session_messages(
    session_id: str,
    session: AsyncSession = Depends(get_session),
    principal=Depends(current_principal),
) -> list[MessageOut]:
    s = await _get_session_or_404(session, session_id, _own_scope(principal))  # 스코프 융합(067/070)
    result = await session.execute(
        select(Message)
        .where(Message.session_pk == s.id)
        .order_by(Message.created_at)
    )
    return [
        MessageOut(role=m.role, content=m.content, trace=m.trace)
        for m in result.scalars().all()
    ]


@router.post("/{session_id}/end", response_model=SessionOut)
async def end_session(
    session_id: str,
    session: AsyncSession = Depends(get_session),
    principal=Depends(current_principal),
) -> SessionOut:
    s = await _get_session_or_404(session, session_id, _own_scope(principal))  # 스코프 융합(067/070 T5)
    s.status = "completed"
    await session.commit()
    a = await session.get(Agent, s.agent_pk)
    return session_to_out(s, a.agent_id if a else None)

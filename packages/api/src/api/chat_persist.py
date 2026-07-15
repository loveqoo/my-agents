"""세션 영속(카운터·메시지·트레이스) — chat.py에서 분할(스펙 291 Phase 3b).

0턴 미영속 lazy-create(스펙 049)·소유권 불변식(스펙 068)·비영속 모드(스펙 235)를 담당.
파사드는 chat.py(재수출 계약).
"""

import json
import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .db import SessionLocal
from .models import Message, Session
from .ownership import next_owner

log = logging.getLogger("api.chat")


async def _resolve_session_for_persist(db: AsyncSession, ctx: dict) -> Session | None:
    """영속할 세션 행을 확보. 이미 영속된 세션이면 그대로 get. session_pk가 None이면(0턴 미영속
    보류 상태) **첫 실 턴**이므로 session_pending으로 행을 지금 만든다(스펙 049, #10).

    session_id 단위 get-or-create로 동시 첫 턴 경합도 안전 — flush가 unique 제약에 걸리면
    rollback 후 re-select로 상대가 만든 행을 집는다(플레이그라운드는 순차라 경합은 이론적).
    """
    pk = ctx.get("session_pk")
    if pk is not None:
        return await db.get(Session, pk)
    pending = ctx.get("session_pending")
    if not pending:
        return None
    # 에이전트 스코프로 조회 — 전역 unique session_id가 *다른* 에이전트 행과 잡히지 않게(누출 방지).
    q = select(Session).where(
        Session.session_id == pending["session_id"],
        Session.agent_pk == pending["agent_pk"],
    )
    sess = (await db.execute(q)).scalar_one_or_none()
    if sess is not None:
        return sess
    sess = Session(
        session_id=pending["session_id"],
        agent_pk=pending["agent_pk"],
        agent_name=pending["agent_name"],
        channel=pending["channel"],
        status="active",
    )
    db.add(sess)
    try:
        await db.flush()
    except IntegrityError:
        # 동시 첫 턴(같은 에이전트)이면 상대가 만든 행을 집는다. 전역 unique가 다른 에이전트와
        # 충돌(천문학적)하면 agent 스코프 재조회가 None → 그 id는 못 쓰므로 graceful None(누출 방지).
        await db.rollback()
        sess = (await db.execute(q)).scalar_one_or_none()
    return sess


async def _persist(
    ctx: dict,
    user_text: str,
    reply: str,
    trace: dict,
    tokens: dict,
    store_messages: bool,
    user_id: str | None = None,
    turn_id: str | None = None,
) -> str | None:
    """세션 카운터는 항상 갱신. 메시지(user/assistant+트레이스)는 store_messages일 때만 저장.

    0턴 미영속(스펙 049): session_pk가 None이면 이 첫 실 턴에서 행을 lazy-create한다.
    소유권(스펙 068): next_owner 불변식으로 기존 non-null 소유자를 다른 유저로 덮어쓰지 않는다.

    반환: 저장한 **assistant Message.id(str)** — 플레이그라운드 피드백 부착용(스펙 209 Phase 1.5).
    store_messages가 False거나 세션 미해결이면 None(피드백 대상 없음).

    비영속(스펙 235): ctx["ephemeral"]이면 세션 해결·행 생성·카운터·commit을 **전부 스킵**하고 즉시
    None(DB 무접촉 — 고트래픽 1회성 추론). store_messages(persistHistory)는 메시지만 스킵하지만 세션은
    남기는 하위 모드라 구분된다.
    """
    if ctx.get("ephemeral"):
        return None
    async with SessionLocal() as db:
        sess = await _resolve_session_for_persist(db, ctx)
        if sess is None:
            log.error("persist skipped: session unresolved (pk=%s)", ctx.get("session_pk"))
            return None
        session_pk = sess.id
        assistant_mid: str | None = None
        if store_messages:
            # 프롬프트 출처(스펙 364) — assistant 행에 id/name 스탬프(분석 축)·body 스냅샷은 trace에
            # (원본 편집 후에도 그 턴 재현 가능). turn_id는 두 행 공통(턴 그룹핑 키).
            prompt_id = ctx.get("prompt_id")
            prompt_name = ctx.get("prompt_name")
            a_trace = trace
            if a_trace is not None and (prompt_id or prompt_name or ctx.get("prompt")):
                a_trace = {
                    **a_trace,
                    "promptSnapshot": {
                        "id": prompt_id,
                        "name": prompt_name,
                        "body": ctx.get("prompt", ""),
                    },
                }
            db.add(Message(session_pk=session_pk, role="user", content=user_text, turn_id=turn_id))
            am = Message(
                session_pk=session_pk,
                role="assistant",
                content=reply,
                trace=a_trace,
                turn_id=turn_id,
                prompt_id=prompt_id,
                prompt_name=prompt_name,
            )
            db.add(am)
            await db.flush()  # am.id 확보(피드백 부착용, 스펙 209 P1.5)
            assistant_mid = str(am.id)
        # 소유권 부여는 생성 시 1회(스펙 068) — 기존 다른 소유자는 보존(이전 거부), 빈 값도 보존.
        sess.user_id = next_owner(sess.user_id, user_id)
        sess.turns = (sess.turns or 0) + 1
        sess.tokens = (sess.tokens or 0) + int(tokens.get("in", 0)) + int(tokens.get("out", 0))
        sess.status = "active"
        await db.commit()
        return assistant_mid


def _mid_frame(mid: str | None) -> str:
    """assistant 메시지 id를 SSE 프레임으로(스펙 209 P1.5) — 프론트가 이 id로 그 응답에 피드백(👍/👎)을
    부착한다(session_id는 프론트가 이미 앎). mid=None(미저장)이면 빈 문자열=프레임 없음."""
    return (
        f"event: message_id\ndata: {json.dumps({'id': mid}, ensure_ascii=False)}\n\n" if mid else ""
    )

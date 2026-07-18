"""세션 재개/신규 준비 — chat_context.py에서 분할(스펙 394 P2, 순수 이동).

파사드는 chat_context.py(재수출 계약).
"""

import secrets

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Agent, Session


async def _resolve_session(
    db: AsyncSession, agent: Agent, session_str_id: str | None, own: str | None
) -> dict:
    """세션 재개/신규 준비 — 반환 {session_pk, session_id, session_pending}.

    세션은 해당 에이전트로 스코프 — 다른 에이전트의 세션 id를 줘도 섞이지 않게.
    스펙 068: 비-admin(own is not None)은 *자기 소유* 세션만 resume. 타인/NULL session_id는
    매칭 실패 → 새 세션 발급(부재와 구별 불가 = 열거 오라클 제거).
    0턴 세션 미영속(스펙 049, #10): 행 생성을 첫 _persist(실 턴)까지 지연 — 플레이그라운드를
    열고 한 마디도 안 하면 DB에 빈 세션이 안 남는다(#11 정크 뿌리 차단). session_id는 클라가
    후속 요청에 참조하므로 지금 *생성만* 해 둔다(commit X). 첫 실 턴에서 lazy-create."""
    sess = None
    if session_str_id:
        resume_q = select(Session).where(
            Session.session_id == session_str_id,
            Session.agent_pk == agent.id,
        )
        if own is not None:
            resume_q = resume_q.where(Session.user_id == own)
        sess = (await db.execute(resume_q)).scalar_one_or_none()
    if sess is not None:
        return {"session_pk": sess.id, "session_id": sess.session_id, "session_pending": None}
    new_id = "sess-" + secrets.token_hex(16)
    return {
        "session_pk": None,
        "session_id": new_id,
        "session_pending": {
            "session_id": new_id,
            "agent_pk": agent.id,
            "agent_name": agent.name,
            "channel": "playground",
        },
    }

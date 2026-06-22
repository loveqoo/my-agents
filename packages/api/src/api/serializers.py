"""ORM 모델 → API 출력(dict) 직렬화. 여러 라우터가 공유."""

from .models import Agent, Approval, Session
from .schemas import AgentOut, ApprovalOut, SessionOut, VersionOut


def _iso(dt) -> str | None:
    return dt.isoformat() if dt is not None else None


def agent_to_out(a: Agent) -> AgentOut:
    cfg = dict(a.config or {})
    return AgentOut(
        id=a.id,
        agentId=a.agent_id,
        name=a.name,
        source=a.source,
        model=cfg.get("model", a.model),
        persona=cfg.get("persona", a.persona),
        systemPrompt=a.persona,  # 해석된 본문(서빙용)
        historyDepth=cfg.get("historyDepth", a.history_depth),
        memories=cfg.get("memories", []),
        vectorTables=cfg.get("vectorTables", []),
        permissions=cfg.get("permissions", []),
        mcps=cfg.get("mcps", []),
        exposed=dict(a.exposed or {"a2a": False}),
        status=a.status,
        activeVersion=a.active_version,
        versions=[
            VersionOut(
                version=v.version,
                status=v.status,
                note=v.note,
                config=dict(v.config or {}),
                createdAt=_iso(v.created_at),
            )
            for v in sorted(a.versions, key=lambda x: x.created_at or x.version, reverse=True)
        ],
        endpoint=a.endpoint,
        token=a.token,
        runtime=a.runtime,
        repo=a.repo,
        commit=a.commit,
        registeredAt=a.registered_at,
        lastSync=a.last_sync,
    )


def session_to_out(s: Session) -> SessionOut:
    return SessionOut(
        id=s.session_id,
        agentId=str(s.agent_pk),
        agent=s.agent_name,
        channel=s.channel,
        status=s.status,
        turns=s.turns,
        tokens=s.tokens,
        started=_iso(s.started_at),
        lastActivity=_iso(s.last_activity),
    )


def approval_to_out(p: Approval) -> ApprovalOut:
    return ApprovalOut(
        id=p.approval_id,
        sessionId=p.session_id,
        agentId=str(p.agent_pk) if p.agent_pk else None,
        agent=p.agent_name,
        permission=p.permission,
        action=p.action,
        args=dict(p.args or {}),
        summary=p.summary,
        checkpoint=p.checkpoint,
        status=p.status,
        requestedAt=_iso(p.requested_at),
    )

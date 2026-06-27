"""ORM 모델 → API 출력(dict) 직렬화. 여러 라우터가 공유."""

from .crypto import SECRET_MASK
from .models import Agent, Approval, Collection, ModelConfig, Provider, Session
from .schemas import (
    AgentOut,
    ApprovalOut,
    CollectionOut,
    ModelOut,
    ProviderOut,
    SessionOut,
    VersionOut,
)


def mask_secret(s: str | None) -> str | None:
    """비밀값 출력 마스킹 — 존재 여부만 알리고 평문/암호문은 절대 노출하지 않는다."""
    return SECRET_MASK if s else None


def provider_to_out(p: Provider, model_count: int = 0) -> ProviderOut:
    return ProviderOut(
        id=p.id,
        name=p.name,
        protocol=p.protocol,
        base_url=p.base_url,
        api_key=mask_secret(p.api_key),
        modelCount=model_count,
    )


def model_to_out(m: ModelConfig) -> ModelOut:
    """provider 관계가 로드되어 있어야 한다(연결처는 provider 상속)."""
    return ModelOut(
        id=m.id,
        name=m.name,
        provider_id=m.provider_id,
        provider_name=m.provider.name if m.provider else "",
        base_url=m.provider.base_url if m.provider else "",
        model_id=m.model_id,
        kind=m.kind,
        is_default=m.is_default,
        params=dict(m.params or {}),
    )


def collection_to_out(c: Collection) -> CollectionOut:
    """embedding_model 관계가 로드되어 있어야 한다(이름 denormalize)."""
    return CollectionOut(
        id=c.id,
        name=c.name,
        description=c.description,
        embedding_model_id=c.embedding_model_id,
        embedding_model_name=c.embedding_model.name if c.embedding_model else "",
        dims=c.dims,
        chunk_size=c.chunk_size,
        chunk_overlap=c.chunk_overlap,
        doc_count=c.doc_count,
        chunk_count=c.chunk_count,
        status=c.status,
    )


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
        persistHistory=cfg.get("persistHistory", True),
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
        token=mask_secret(a.token),
        runtime=a.runtime,
        repo=a.repo,
        commit=a.commit,
        registeredAt=a.registered_at,
        lastSync=a.last_sync,
        card=cfg.get("card"),  # 외부 에이전트 카드 스냅샷(읽기 전용 표시용)
    )


def session_to_out(s: Session, agent_external_id: str | None = None) -> SessionOut:
    return SessionOut(
        id=s.session_id,
        agentId=agent_external_id or str(s.agent_pk),
        agent=s.agent_name,
        channel=s.channel,
        status=s.status,
        turns=s.turns,
        tokens=s.tokens,
        started=_iso(s.started_at),
        lastActivity=_iso(s.last_activity),
    )


def approval_to_out(p: Approval, agent_external_id: str | None = None) -> ApprovalOut:
    return ApprovalOut(
        id=p.approval_id,
        sessionId=p.session_id,
        agentId=agent_external_id or (str(p.agent_pk) if p.agent_pk else None),
        agent=p.agent_name,
        permission=p.permission,
        action=p.action,
        args=dict(p.args or {}),
        summary=p.summary,
        checkpoint=p.checkpoint,
        status=p.status,
        requestedAt=_iso(p.requested_at),
    )

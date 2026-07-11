"""경량 환경 기록(스펙 240, 스펙 291 분할) — 런에 박제하는 진단 스냅샷(재현 보장 아님).

_env_snapshot의 부분저하 계약: 수집 실패는 partial 기록으로 우아 저하 — 최상위 try가
헬퍼 호출 전체를 감싼다(헬퍼 안으로 try를 옮기면 partial 시맨틱이 변형된다, 스펙 291).
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

_ENV_SECRET_KEYS = ("api_key", "apikey", "token", "secret", "authorization", "password")


def _env_redact(v: object) -> object:
    """env 기록용 재귀 마스킹(codex 240 #3) — ModelConfig.params는 임의 JSONB라 운영자가 넣은
    비밀(api_key류)이 성적표 JSON 덤프로 노출될 수 있다. 키 이름 기반 마스킹."""
    if isinstance(v, dict):
        return {
            k: ("***" if any(sk in k.lower() for sk in _ENV_SECRET_KEYS) else _env_redact(x))
            for k, x in v.items()
        }
    if isinstance(v, list):
        return [_env_redact(x) for x in v]
    return v


async def _model_env(session: AsyncSession, name: str | None) -> dict:
    """모델별 env.model 조각 — 오버라이드 런은 **그 모델의** params를 기록(codex 240 #2:
    name=오버라이드·params=기본 모델이면 거짓 기록). params는 마스킹."""
    from .models import ModelConfig

    out: dict = {"name": name}
    if name:
        m = (
            await session.execute(select(ModelConfig).where(ModelConfig.name == name))
        ).scalar_one_or_none()
        if m is not None:
            out["params"] = _env_redact(m.params or {})
    return out


def _caps_with_prefix(cfg: dict, prefix: str) -> list[str]:
    """config capabilities 중 해당 접두 항목의 접두 제거 값 목록."""
    return [
        c[len(prefix) :]
        for c in cfg.get("capabilities") or []
        if isinstance(c, str) and c.startswith(prefix)
    ]


def _rag_env(rag_collection: dict) -> dict:
    """RAG 시험용 env.collections 조각 — 대상 컬렉션 상태."""
    return {
        rag_collection["name"]: {
            "docs": rag_collection.get("doc_count"),
            "chunks": rag_collection.get("chunk_count"),
            "embedding": rag_collection.get("embedding_model_name"),
        }
    }


async def _mcp_env(session: AsyncSession, cfg: dict) -> dict | None:
    """배선 MCP 서버의 enabled_tools 스냅샷("도구가 달라졌나" 진단 축) — 배선 없으면 None."""
    wired_mcps = list(cfg.get("mcps") or [])
    wired_mcps += [v.split("/", 1)[0] for v in _caps_with_prefix(cfg, "mcp:")]
    if not wired_mcps:
        return None
    from .models import McpServer

    rows = (
        (await session.execute(select(McpServer).where(McpServer.name.in_(set(wired_mcps)))))
        .scalars()
        .all()
    )
    return {r.name: sorted(r.enabled_tools or []) for r in rows}


async def _collection_env(session: AsyncSession, cfg: dict) -> dict | None:
    """배선 컬렉션 상태 스냅샷(배선 표면: vectorTables ∪ capabilities rag:* — 239 codex #4와
    동일 합집합) — 배선 없으면 None."""
    cols = set(cfg.get("vectorTables") or []) | set(_caps_with_prefix(cfg, "rag:"))
    if not cols:
        return None
    # embedding_model_name은 ORM 컬럼이 아니라 serializer 파생 필드(codex 240 #2b) — 조인으로.
    from .models import Collection, ModelConfig

    rows = (
        await session.execute(
            select(
                Collection.name,
                Collection.doc_count,
                Collection.chunk_count,
                ModelConfig.name,
            )
            .join(ModelConfig, ModelConfig.id == Collection.embedding_model_id, isouter=True)
            .where(Collection.name.in_(cols))
        )
    ).all()
    return {n: {"docs": dc, "chunks": cc, "embedding": emb} for n, dc, cc, emb in rows}


async def _env_snapshot(
    session: AsyncSession,
    agent,  # noqa: ANN001 — Agent | None이나 None은 rag 경로(조기 return)에서만: 주석 시 mypy union-attr(스펙 292 P1 보고)
    rag_collection: dict | None,
    cfg_override: dict | None = None,
) -> dict:
    """경량 환경 기록(스펙 240) — **재현 보장이 아니라 진단 단서**(모델 params·도구 목록·컬렉션 상태).
    수집 실패는 부분 기록으로 우아 저하(진단 부가층이 실행을 막으면 본말전도)."""
    env: dict = {}
    try:
        if rag_collection is not None:
            env["collections"] = _rag_env(rag_collection)
            return env
        cfg = (
            cfg_override if cfg_override is not None else dict(agent.config or {})
        )  # 스펙 242: 지정 버전 config 기준
        env["impl"] = cfg.get("impl") or "default"
        if cfg.get("ephemeral"):
            env["ephemeral"] = True
        # 모델 + 레지스트리 params(실행 파라미터의 진단 축 — 스펙 077 temperature 등). 마스킹 포함.
        env["model"] = await _model_env(session, cfg.get("model"))
        if cfg.get("temperature") is not None:
            env["model"]["temperature"] = cfg.get("temperature")
        mcps = await _mcp_env(session, cfg)
        if mcps is not None:
            env["mcps"] = mcps
        collections = await _collection_env(session, cfg)
        if collections is not None:
            env["collections"] = collections
    except Exception:
        env["partial"] = True
    return env

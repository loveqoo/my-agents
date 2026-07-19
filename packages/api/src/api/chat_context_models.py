"""모델·mem0 설정 해석 — chat_context.py에서 분할(스펙 394 P3).

_resolve_model(구 CC 12)은 레지스트리 조회(_registry_chat_model·_default_chat_registry)와
행→dict 변환(_model_cfg_from_row) 추출로 분해. **의도 비대칭 보존**(codex 자문·스펙 290):
오버라이드 모델 미등록=400(시끄럽게), 저장 설정 미등록=기본(is_default) 폴백(graceful).
파사드는 chat_context.py(재수출 계약).
"""

import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from . import crypto
from .chat_context_types import _is_remote
from .mem_config import (
    _build_mem_cfg,
    _default_chat_model,
    _default_embed_model,
    llm_cfg_of,
    model_usable,
)
from .models import Agent, ModelConfig


async def _pinned_model_cfg(db: AsyncSession, pins: dict | None, name: str) -> dict | None:
    """pin이 head와 다를 때만 이력 payload로 model_cfg 구성(스펙 370) — 369 경계 그대로
    저작 내용(model_id·params·provider_id)은 pin, 연결처 비밀(base_url·api_key)은 라이브 provider."""
    from .block_versions import resolve_pinned
    from .models import Provider as _Provider

    payload = await resolve_pinned(db, pins, "model", name)
    if payload is None:
        return None
    prov = None
    if payload.get("provider_id"):
        try:
            prov = await db.get(_Provider, uuid.UUID(str(payload["provider_id"])))
        except ValueError:
            prov = None
    if prov is None or not prov.base_url or not payload.get("model_id"):
        return None  # 불완전 pin — head 폴백(정직 degrade)
    # 능력은 스냅샷하지 않는다(스펙 408) — 서버 능력은 **라이브 사실**이라 pin과 무관하게 현재
    # 등록 행에서 읽는다(구버전 pin이라도 지금 서버가 스트리밍을 껐으면 지금 사실을 따라야 함).
    live = await _registry_chat_model(db, name)
    caps = dict(live.capabilities or {}) if live is not None else {}
    return {
        "base_url": prov.base_url,
        "api_key": crypto.decrypt(prov.api_key),
        "model_id": payload["model_id"],
        "params": dict(payload.get("params") or {}),
        "capabilities": caps,
    }


async def _registry_chat_model(db: AsyncSession, name: str) -> ModelConfig | None:
    """레지스트리 chat 모델 단건 조회(name, kind=chat, provider 상속) — 해석 3경로 공유 조회."""
    return (
        await db.execute(
            select(ModelConfig)
            .where(ModelConfig.name == name, ModelConfig.kind == "chat")
            .options(selectinload(ModelConfig.provider))
        )
    ).scalar_one_or_none()


async def _default_chat_registry(db: AsyncSession) -> ModelConfig | None:
    """기본(is_default) chat 모델 조회 — 저장 설정 미지정/미등록의 graceful 폴백 대상."""
    return (
        (
            await db.execute(
                select(ModelConfig)
                .where(ModelConfig.kind == "chat", ModelConfig.is_default.is_(True))
                .options(selectinload(ModelConfig.provider))
            )
        )
        .scalars()
        .first()
    )


def _model_cfg_from_row(m: ModelConfig) -> dict:
    """모델 행 → model_cfg dict — 불완전(provider base_url/model_id 부재)은 400(명확한 안내)."""
    base_url = m.provider.base_url if m.provider else ""
    if not base_url or not m.model_id:
        raise HTTPException(
            status_code=400,
            detail=f"모델 '{m.name}' 설정이 불완전합니다 (provider base_url/model_id 필요).",
        )
    # 등록 없음·설정 불완전이 각각 다른 에러 메시지라 model_usable로 접지 않음 — dict만 정본화.
    return {**llm_cfg_of(m), "params": dict(m.params or {})}


async def _chat_model_cfg(db: AsyncSession, name: str, pins: dict | None = None) -> dict | None:
    """레지스트리 chat 모델(name→provider 상속) 해석 — pin 우선(스펙 370), 미존재/불완전이면 None."""
    pinned = await _pinned_model_cfg(db, pins, name)
    if pinned is not None:
        return pinned
    m = await _registry_chat_model(db, name)
    if model_usable(m):
        return {**llm_cfg_of(m), "params": dict(m.params or {})}
    return None


async def _resolve_node_models(
    db: AsyncSession,
    nodes: list,
    default_cfg: dict | None,
    pins: dict | None = None,
    agent_cfg: dict | None = None,
) -> list[dict]:
    """노드형(스펙 259) 노드별 모델을 레지스트리에서 미리 해석해 `model_cfg`를 심는다(085 U2 — impl은
    DB 미접촉). 에이전트 모델 해석과 **동일 조회**(`ModelConfig.name==name, kind=="chat"`, provider
    상속) — 드리프트 0. 미지정/미존재 이름은 `default_cfg`(에이전트 기본 chat 모델)로 폴백. 같은 모델
    이름은 1회만 조회해 재사용(N 노드 M 중복 모델 → distinct 쿼리). 순수 데이터 반환(잡 노드는 통과 —
    정규화는 impl의 normalize_nodes가)."""
    resolved: list[dict] = []
    cache: dict[str, dict | None] = {}
    for node in nodes:
        if not isinstance(node, dict):
            continue
        name = node.get("model")
        cfg = None
        if isinstance(name, str) and name.strip():
            if name not in cache:
                cache[name] = await _chat_model_cfg(db, name, pins)
            cfg = cache[name]
        # 심은 model_cfg는 해석된 노드 모델(없으면 에이전트 기본으로 폴백 — impl의 _model_from_node).
        # 에이전트 층 modelParams는 노드 명시 모델에도 관통(스펙 408, codex P1② — temperature가
        # ctx.params로 전 노드 적용되는 선례와 같은 계약. default_cfg는 _resolve_model서 기병합).
        node_cfg = cfg or default_cfg
        if cfg is not None and agent_cfg:
            node_cfg = _apply_agent_model_params(cfg, agent_cfg)
        resolved.append({**node, "model_cfg": node_cfg})
    return resolved


# 에이전트 층 모델 설정 오버라이드 화이트리스트(스펙 408 캐스케이드: 모델 params 기본 →
# 에이전트 config.modelParams → 세션 오버라이드). 능력(capabilities)은 층에 없다 — 사실은 불가침.
# temperature는 제외 — 기존 AgentConfig.temperature(스펙 077)가 이미 에이전트 층 정본(이중 거처 금지).
MODEL_PARAM_OVERRIDE_KEYS = ("enable_thinking", "stream")


def _apply_agent_model_params(model_cfg: dict, cfg: dict) -> dict:
    """모델 params 위에 에이전트 modelParams(화이트리스트만)를 덮는다 — 미명시 키는 상속."""
    agent_mp = cfg.get("modelParams") or {}
    if not isinstance(agent_mp, dict) or not agent_mp:
        return model_cfg
    merged = dict(model_cfg.get("params") or {})
    for key in MODEL_PARAM_OVERRIDE_KEYS:
        if key in agent_mp and agent_mp[key] is not None:
            merged[key] = agent_mp[key]
    return {**model_cfg, "params": merged}


async def _resolve_model(
    db: AsyncSession, cfg: dict, overrides: dict | None, pins: dict | None = None
) -> dict:
    """chat 모델을 레지스트리에서만 해석(env 안 봄) — 반환 model_cfg dict(연결처는 provider 상속, 스펙 035).

    에이전트가 고른 이름 → 없으면 기본(is_default) chat 모델 → 그것도 없으면 명확히 400.
    명시 오버라이드 모델이 미등록이면 **시끄럽게 거절**(스펙 290 — learning 092: 조용한 폴백은
    호출자가 다른 모델로 실행된 걸 모른 채 지나간다). 저장 설정의 미지정·미등록은 기존 기본 폴백
    유지(graceful — 범위 밖, 백로그)."""
    model_name = cfg.get("model")
    if model_name:
        pinned = await _pinned_model_cfg(db, pins, model_name)  # pin 우선(스펙 370)
        if pinned is not None:
            return _apply_agent_model_params(pinned, cfg)
    m = await _registry_chat_model(db, model_name) if model_name else None
    if m is None:
        # 거절은 **실명을 댄** 오버라이드에만(스펙 401) — 모델 미지정 에이전트(model_name=None)에
        # model 키 없는(또는 null) 오버라이드가 오면 None==None으로 오폭하던 것을 실명 요구로 봉합.
        # 미선언은 기본 폴백(learning 092: 선언-but-broken만 거절).
        if overrides and overrides.get("model") and overrides.get("model") == model_name:
            raise HTTPException(
                status_code=400,
                detail=f"오버라이드 모델 '{model_name}'이(가) 등록돼 있지 않습니다 — 모델 이름을 확인하세요.",
            )
        m = await _default_chat_registry(db)
    if m is None:
        raise HTTPException(
            status_code=400,
            detail="등록된 채팅 모델이 없습니다 — 모델을 먼저 등록하세요.",
        )
    return _apply_agent_model_params(_model_cfg_from_row(m), cfg)


async def _resolve_mem_cfg(db: AsyncSession, model_cfg: dict | None) -> dict | None:
    """mem0용 모델 설정(레지스트리) — llm=해석된 chat 모델, embedder=기본 embedding 모델.

    임베딩 모델이 없으면 None → 메모리 비활성(graceful)."""
    if not model_cfg:
        return None
    emb = (
        (
            await db.execute(
                select(ModelConfig)
                .where(ModelConfig.kind == "embedding", ModelConfig.is_default.is_(True))
                .options(selectinload(ModelConfig.provider))
            )
        )
        .scalars()
        .first()
    )
    if emb is None or emb.provider is None:
        return None
    return {
        "llm": {
            "base_url": model_cfg["base_url"],
            "api_key": model_cfg["api_key"],
            "model_id": model_cfg["model_id"],
        },
        "embedder": llm_cfg_of(emb),
    }


async def resolve_agent_mem_cfg(db: AsyncSession, agent: Agent) -> dict | None:
    """에이전트의 mem0 설정(레지스트리 chat llm + 기본 embedding)을 해석. 없으면 None.

    관리자 메모리 CRUD(agents.py 스펙 029)가 _load_context와 같은 규칙으로 mem_cfg를 얻는 단일
    경로. 코드·외부 에이전트는 비로컬(원격/A2A)이라 로컬 mem0가 없다 → None.
    """
    if _is_remote(agent.source):
        return None
    cfg = dict(agent.config or {})
    model_name = cfg.get("model")
    m = await _registry_chat_model(db, model_name) if model_name else None
    if m is None:
        m = await _default_chat_model(db)
    return _build_mem_cfg(m, await _default_embed_model(db))

"""_load_context 오케스트레이터 — chat_context.py에서 분할(스펙 394 P6).

컨텍스트 계층의 **순서 계약**이 이 파일에 드러난다(codex 자문 — 순서 변경=동작 변경):
① 버전 스냅샷 → ② 노드 ref 해석(오버라이드 **전** — 세션 패치는 해석된 유효 노드 위에) →
③ 오버라이드 병합 → ④ 풀 재파생(모델/MCP/RAG 해석 **전**) → ⑤ exec_version 확정 **후** pins →
⑥ 모델 → 노드 모델 → mem → MCP → RAG → 세션. 파사드는 chat_context.py(재수출 계약).
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from agent.capabilities import clean_setting_params

from .chat_context_mcp import _resolve_mcp_servers
from .chat_context_models import _resolve_mem_cfg, _resolve_model, _resolve_node_models
from .chat_context_overrides import _apply_overrides, _filter_capabilities
from .chat_context_pool import derive_pipeline_pool
from .chat_context_rag import _resolve_rag
from .chat_context_sessions import _resolve_session
from .chat_context_types import ChatContext, _is_remote
from .chat_context_versions import (
    _resolve_exec_pins,
    _resolve_prompt_provenance,
    _resolve_version_and_prompt,
)
from .db import SessionLocal, get_or_404
from .models import Agent
from .node_templates import resolve_node_refs

# 세션 오버라이드 화이트리스트(스펙 025/122/276/287 — 각 키 근거는 _apply_overrides docstring).
_OVERRIDE_ALLOWED = {
    "model",
    "temperature",
    "historyDepth",
    "mcps",
    "memories",
    "capabilities",
    "tools",
    "vectorTables",
    # 모델 설정 오버라이드(스펙 408 캐스케이드 3층 — 세션): per-key 병합은 _apply_overrides가 담당.
    "modelParams",
}


async def _resolve_nodes_for_ctx(
    db: AsyncSession,
    nodes: object,
    model_cfg: dict | None,
    remote: bool,
    pins: dict | None = None,
    cfg: dict | None = None,
    session_mp: dict | None = None,
) -> list[dict] | None:
    """노드형(스펙 259)이면 노드별 모델을 **플랫폼이 미리 해석**해 심는다(085 U2: build_graph는 DB
    미접촉). 로컬(ui) 경로에서만 의미 — 비노드형/원격은 None. session_mp=세션 modelParams(스펙 409
    codex P1① — 노드 층 뒤에 재적용해 세션이 노드를 이기게)."""
    if remote or not isinstance(nodes, list):
        return None
    return await _resolve_node_models(db, nodes, model_cfg, pins, agent_cfg=cfg, session_mp=session_mp)


async def _prepare_cfg(
    db: AsyncSession, agent: Agent, version: str | None, overrides: dict | None
) -> tuple[dict, str, str | None, str | None, dict | None]:
    """cfg 준비 단계(스펙 394 분해) — 버전 스냅샷·노드 ref 해석·오버라이드 병합·풀 재파생.
    반환 (cfg, prompt, pinned_version, nodes_status, applied_overrides). 순서는 모듈 docstring ①~④."""
    cfg = dict(agent.config or {})
    # (스펙 211) 구 113 P0의 저장본/override 권한 분리(stored_mcps 포착)는 사용=공용 전환으로 소멸.
    cfg, prompt, pinned_version = await _resolve_version_and_prompt(db, agent, cfg, version)
    # 노드 참조 해석(스펙 316) — ref 항목을 등록 노드 config 사본으로 치환. **오버라이드 병합
    # 전에**(해석→병합): 세션 패치는 해석된 유효 노드 위에 얹는다. 미해결 참조는 422로 명확히
    # 실패(반쪽 파이프라인 조용히 실행 금지 — 089 패턴). 핀 버전 미리보기(version=) 스냅샷의
    # 참조도 여기서 함께 해석된다(_resolve_version_and_prompt 뒤 단일 지점).
    if not _is_remote(agent.source) and isinstance(cfg.get("nodes"), list):
        cfg["nodes"] = await resolve_node_refs(db, cfg["nodes"])
    cfg, prompt, nodes_status, applied_overrides = _apply_overrides(
        cfg, prompt, overrides, agent, _OVERRIDE_ALLOWED
    )
    # 노드형 풀 서버 파생(스펙 289 P2) — 로드 시 무조건 재파생: 폼 밖 입구(API 직생성·구저장·
    # 오버라이드)로 풀이 비었거나 낡았어도 노드 참조대로 도구·문서·기억이 빌드된다(learning 151).
    # 저장 시 파생(agents.py)과 같은 규칙이라 폼 저장분엔 무변화(멱등).
    if not _is_remote(agent.source):
        await derive_pipeline_pool(cfg)
    return cfg, prompt, pinned_version, nodes_status, applied_overrides


async def _load_context(
    agent_id: uuid.UUID,
    session_str_id: str | None,
    overrides: dict | None = None,
    own: str | None = None,
    version: str | None = None,
) -> ChatContext:
    """에이전트 구성 + MCP 활성 툴 + 세션(생성/지속)을 한 번에 준비.

    overrides(스펙 025): Playground Proxy의 세션 한정 설정 덮어쓰기. **web 에이전트에만** 적용하고
    화이트리스트 키만 받는다(저장된 에이전트는 불변). 코드 에이전트는 원격 실행이라 미적용(bypass).

    own(스펙 068): resume 소유자 스코프. 비-admin이면 `str(principal.id)`, admin/머신·내부 호출은
    None. `own is not None`이면 resume 바인딩이 `Session.user_id == own`을 요구해, *타인/NULL/추측*
    session_id는 매칭 실패 → 새 세션 발급(067 읽기 게이트와 동일 판정 — 열거 오라클·소유권 탈취 봉인).
    """
    # 세션 id 위생(스펙 290 적대): Postgres text는 NUL(0x00)을 저장·조회할 수 없어, 오염된 id가
    # WHERE에 닿으면 asyncpg가 DBAPIError(500)로 샌다. NUL 포함 id는 애초에 저장 행과 매칭 불가라
    # 새 세션으로 fold하는 것이 계약("200+새 세션 발급")과 일치한다 — resume 자체를 건너뛴다.
    # (다른 특수문자·긴 길이는 파라미터 바인딩이 안전 처리하므로 그대로 통과시켜 매칭 실패에 맡긴다.)
    if session_str_id and "\x00" in session_str_id:
        session_str_id = None
    async with SessionLocal() as db:
        agent = await get_or_404(db, Agent, agent_id, detail="agent not found")
        cfg, prompt, pinned_version, nodes_status, applied_overrides = await _prepare_cfg(
            db, agent, version, overrides
        )
        remote = _is_remote(agent.source)
        # 실행 버전(스펙 242) — pinned=지정 버전(미리보기), exec=실제 실행 버전(지정 없으면 활성).
        # trace.agentVersion 기록·HIL 게이트(pinned는 승인 재개가 서빙 config로 돌아 drift) 근거.
        exec_version = pinned_version or agent.active_version
        prompt_name, prompt_id = await _resolve_prompt_provenance(
            db, cfg, applied_overrides, remote
        )
        pins = await _resolve_exec_pins(db, agent.id, exec_version, remote)
        # 코드·외부 에이전트는 비로컬(원격/A2A) 실행이라 로컬 모델이 필요 없다(건너뜀 = None).
        nodes = cfg.get("nodes")  # 노드형 파이프라인 노드 명세(스펙 259) — 아래서 노드별 모델 해석
        # 세션 modelParams(스펙 409) — 노드형에서 노드 층 뒤에 재적용해 세션이 최상위가 되게(codex P1①).
        # 화이트리스트 bool만(문자열 "false" 게이트 우회 차단 — 실행부 _as_bool와 이중 방어).
        session_mp = clean_setting_params(overrides.get("modelParams")) if isinstance(overrides, dict) else None
        model_cfg = await _resolve_model(db, cfg, overrides, pins) if not remote else None
        nodes_resolved = await _resolve_nodes_for_ctx(
            db, nodes, model_cfg, remote, pins, cfg=cfg, session_mp=session_mp
        )
        mem_cfg = await _resolve_mem_cfg(db, model_cfg)
        mcp_servers, tool_names = await _resolve_mcp_servers(db, cfg, pins)
        rag_collections, rag_unresolved = await _resolve_rag(db, cfg, remote)
        session = await _resolve_session(db, agent, session_str_id, own)
        return ChatContext(
            prompt=prompt,
            ext_agent_id=agent.agent_id,
            agent_name=agent.name,
            agent_pk=agent.id,
            source=agent.source,
            impl=cfg.get("impl"),
            artifact_spec=cfg.get("artifactSpec"),
            nodes=nodes,
            overrides_nodes_status=nodes_status,
            # 원본 오버라이드 — in-process 커스텀이 화이트리스트 밖 키도 읽게 전달(스펙 085
            # AgentBuildContext.overrides). 원격은 None(로컬 설정 주입 무의미, bypass 보존).
            overrides=applied_overrides,
            endpoint=agent.endpoint,
            token=agent.token,
            card=cfg.get("card"),
            memories=cfg.get("memories", []),
            capabilities=_filter_capabilities(cfg),
            # 도구 승인 오버라이드(스펙 177 P2) — 요청 오버라이드 허용키엔 불포함(요청으로 승인 완화
            # 우회 금지, config-only). 완화 권한은 저장 시 admin 게이트로 강제.
            tool_policy=cfg.get("toolPolicy") or {},
            # 에이전트가 명시한 temperature만 전달(없으면 None) → 모델 등록 params가 적용되게.
            temperature=cfg.get("temperature"),
            history_depth=cfg.get("historyDepth", 20),
            persist_history=cfg.get("persistHistory", True),
            # 비영속(1회성) 모드(스펙 235) — true면 DB 적재 전면 스킵(persistHistory의 상위집합).
            ephemeral=bool(cfg.get("ephemeral", False)),
            pinned_version=pinned_version,
            exec_version=exec_version,
            prompt_name=prompt_name,
            prompt_id=prompt_id,
            pins=pins,
            model_cfg=model_cfg,
            nodes_resolved=nodes_resolved,
            mem_cfg=mem_cfg,
            mcp_servers=mcp_servers,
            tool_names=tool_names,
            rag_collections=rag_collections,
            rag_unresolved=rag_unresolved,
            # 컬렉션별 최소 유사도 맵(스펙 191 v2). downstream이 범위·컬렉션 재검증하므로 raw 통과({}=무필터).
            rag_min_scores=cfg.get("ragMinScores") or {},
            session_pk=session["session_pk"],
            session_id=session["session_id"],
            session_pending=session["session_pending"],
        )

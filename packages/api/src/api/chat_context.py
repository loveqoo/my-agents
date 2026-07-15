"""채팅 컨텍스트/설정 해석 — chat.py에서 분할(스펙 291 Phase 3b).

에이전트 구성·버전·오버라이드·모델·메모리·MCP·RAG·세션을 실행 ctx(dict)로 해석한다.
외부 진입점은 파사드 chat.py가 재수출한다(`from api.chat import ...` 무변경 계약).
"""

import logging
import secrets
import uuid
from collections.abc import Sequence

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from agent.runtime import is_remote_source

from . import crypto, runtime
from .db import SessionLocal, get_or_404
from .mem_config import (
    _build_mem_cfg,
    _default_chat_model,
    _default_embed_model,
    llm_cfg_of,
    model_usable,
)
from .models import Agent, Collection, McpServer, ModelConfig, Session
from .node_templates import resolve_node_refs
from .references import config_names

log = logging.getLogger("api.chat")

# 원격 소스 판정 단일 술어는 agent.runtime로 내렸다(스펙 089) — resolve·classify·직렬화가 공유.
_is_remote = is_remote_source


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
    return {
        "base_url": prov.base_url,
        "api_key": crypto.decrypt(prov.api_key),
        "model_id": payload["model_id"],
        "params": dict(payload.get("params") or {}),
    }


async def _chat_model_cfg(db: AsyncSession, name: str, pins: dict | None = None) -> dict | None:
    """레지스트리 chat 모델(name→provider 상속) 해석 — pin 우선(스펙 370), 미존재/불완전이면 None."""
    pinned = await _pinned_model_cfg(db, pins, name)
    if pinned is not None:
        return pinned
    m = (
        await db.execute(
            select(ModelConfig)
            .where(ModelConfig.name == name, ModelConfig.kind == "chat")
            .options(selectinload(ModelConfig.provider))
        )
    ).scalar_one_or_none()
    if model_usable(m):
        return {**llm_cfg_of(m), "params": dict(m.params or {})}
    return None


async def _resolve_node_models(
    db: AsyncSession, nodes: list, default_cfg: dict | None, pins: dict | None = None
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
        resolved.append({**node, "model_cfg": cfg or default_cfg})
    return resolved


# 노드 오버라이드 필드 화이트리스트(스펙 287) — 구조 식별자(name)는 제외해 저장본 유지.
# 노드 추가/삭제는 테스트 범위 밖(사용자 결정): 오버라이드는 "이 에이전트 그대로, 설정만 바꿔
# 테스트"가 목적이라 구조 변경 요청은 받지 않는다(서버 강제 — 클라이언트 신뢰 금지).
_NODE_OVERRIDE_FIELDS = {
    "prompt",
    "model",
    "tools",
    "historyDepth",
    "memories",
    "memoryQuery",
    "context",
    "format",
    "fields",
}


def _node_patch_fields(base_n: dict) -> set[str]:
    """이 노드에 병합 가능한 오버라이드 필드(스펙 317) — 설정 노드=화이트리스트 전체, 코드 노드=
    manifest.overridable ∩ 화이트리스트(나머지는 코드가 소유 — 세션 패치로 못 바꾼다). 미등록
    impl은 빈 집합(fail-closed — 어차피 실행이 설정 오류로 거부됨)."""
    impl = base_n.get("impl")
    if not isinstance(impl, str) or not impl.strip():
        return _NODE_OVERRIDE_FIELDS
    from agent.nodes import get_node_impl

    node_impl = get_node_impl(impl)
    if node_impl is None:
        return set()
    return _NODE_OVERRIDE_FIELDS & set(node_impl.describe().overridable)


def _merge_node_overrides(saved: list, ov: object) -> tuple[list, str]:
    """노드형 세션 오버라이드 merge(스펙 287). 길이(=구조)가 같을 때만 인덱스별로 필드
    화이트리스트를 저장 노드 위에 덮는다. 불일치·형식 오류는 저장본 그대로 + "mismatch"
    (조용한 드롭 금지 — 트레이스가 표면화, 스펙 125 계열). 코드 노드(스펙 317)는 manifest가
    선언한 표면만 병합하고, 화이트리스트 필드가 표면 밖이라 떨어지면 "partial"로 표면화
    (조용한 무시 금지 — 무엇이 안 먹었는지 트레이스가 말한다). 순수 함수(테스트 단위)."""
    if not isinstance(ov, list) or len(ov) != len(saved):
        return saved, "mismatch"
    merged: list = []
    dropped = False
    for base_n, ov_n in zip(saved, ov, strict=True):
        if not isinstance(base_n, dict) or not isinstance(ov_n, dict):
            return saved, "mismatch"
        allowed = _node_patch_fields(base_n)
        patch = {k: v for k, v in ov_n.items() if k in allowed}
        if any(k in _NODE_OVERRIDE_FIELDS and k not in allowed for k in ov_n):
            dropped = True  # 코드 소유 필드를 덮으려 함 — 병합은 계속, 상태로 정직 표기
        merged.append({**base_n, **patch})
    return merged, ("partial" if dropped else "applied")


def _used_node_tools(nodes: list[dict]) -> set[str]:
    """노드들이 참조하는 도구명(접두명 srv__tool + 구저장 민이름) 합집합."""
    return {t for n in nodes for t in (n.get("tools") or []) if isinstance(t, str)}


def _server_tool_used(s: McpServer, used: set[str], bare_owners: dict[str, set[str]]) -> bool:
    """서버 도구 중 노드가 참조한 것이 있는가 — 접두명(srv__tool) 또는 전역 유일 민이름."""
    return any(
        runtime._safe_name(s.name, t) in used or (t in used and len(bare_owners.get(t) or ()) == 1)
        for t in (s.tools or [])
    )


def _mcp_pool(servers: Sequence[McpServer], used: set[str]) -> list[str]:
    """노드 참조 도구를 보유한 MCP 서버 이름 목록.

    민이름(bare, 구저장 'echo'류) 매칭은 **전역 유일할 때만**(codex 289 #4) — 같은 도구명이 여러
    서버에 있으면 모두 풀에 열려 불필요한 MCP 접속이 생긴다. 모호=제외(fail-closed — 런타임
    _resolve_tool의 모호 스킵(265)과 같은 결). 접두명(srv__tool)은 모호성이 없어 그대로."""
    bare_owners: dict[str, set[str]] = {}
    for server in servers:
        for tool in server.tools or []:
            bare_owners.setdefault(tool, set()).add(server.name)
    return [s.name for s in servers if _server_tool_used(s, used, bare_owners)]


def _doc_pool(cols: list[str], used: set[str]) -> list[str]:
    """노드 참조 문서 컬렉션 목록 — 민이름 'search_documents'는 전체 컬렉션."""
    if "search_documents" in used:
        return list(cols)
    return [c for c in cols if runtime._safe_name("search_documents", c) in used]


async def derive_pipeline_pool(cfg: dict) -> None:
    """노드형 풀 서버 파생(스펙 289 P2) — impl=pipeline이면 mcps/vectorTables/memories를 **노드 참조의
    합집합**으로 재계산해 대체한다. 폼 derivePipelinePool과 동일 규칙(단일 의미): MCP=서버 도구 중
    사용된 것이 있는 서버, 문서=컬렉션별 도구(_safe_name 매칭, 민이름 'search_documents'=전체),
    기억=노드 memories 합집합. 파생 필드는 denormalization이라 관리자 저작 의미 없음 → merge-preserve
    불요(스펙 289 근거). 이로써 폼 밖 입구(API 생성·오버라이드)도 노드 도구가 조용히 미바인딩되지
    않는다(learning 151 구조적 봉합). 권한 비상승: 풀은 노드가 이미 참조하는 것의 합집합 — 필터
    대상=합집합 자신."""
    if cfg.get("impl") != "pipeline":
        return
    nodes = [n for n in (cfg.get("nodes") or []) if isinstance(n, dict)]
    async with SessionLocal() as db:
        # 노드 참조 해석(스펙 316) — 풀 합집합은 **해석된** 노드 기준(참조 노드의 도구·기억이 조용히
        # 미바인딩되지 않게). cfg["nodes"]는 건드리지 않는다(저장본은 ref 유지 — 핀 참조가 진실원).
        # 저장 경로(생성/수정)가 이 함수를 지나므로 미해결 참조는 저장 시점에 422로 이른 실패한다.
        nodes = [n for n in await resolve_node_refs(db, nodes) if isinstance(n, dict)]
        used = _used_node_tools(nodes)
        servers = (await db.execute(select(McpServer))).scalars().all()
        cols = list((await db.execute(select(Collection.name))).scalars().all())
    cfg["mcps"] = _mcp_pool(servers, used)
    cfg["vectorTables"] = _doc_pool(cols, used)
    cfg["memories"] = sorted(
        {m for n in nodes for m in (n.get("memories") or []) if isinstance(m, str)}
    )
    # 에이전트-호출 축 파생(스펙 318) — 노드 `tools`의 `agent__{agent_id}`에서 대상 id를 뽑아
    # capabilities(브로커 allowlist)로 심는다. 폼 밖 입구(API·오버라이드)도 브로커가 그 에이전트를
    # 스코프해 도구가 조용히 미바인딩되지 않게(learning 151 agent판). 권한 비상승: 노드가 이미
    # 참조하는 것의 합집합. 자기 참조는 런타임 방문 집합(_delegable)이 최종 차단(UI도 선배제).
    cfg["capabilities"] = sorted(
        {t[len("agent__") :] for t in used if t.startswith("agent__") and len(t) > len("agent__")}
    )


async def resolve_agent_mem_cfg(db: AsyncSession, agent: Agent) -> dict | None:
    """에이전트의 mem0 설정(레지스트리 chat llm + 기본 embedding)을 해석. 없으면 None.

    관리자 메모리 CRUD(agents.py 스펙 029)가 _load_context와 같은 규칙으로 mem_cfg를 얻는 단일
    경로. 코드·외부 에이전트는 비로컬(원격/A2A)이라 로컬 mem0가 없다 → None.
    """
    if _is_remote(agent.source):
        return None
    cfg = dict(agent.config or {})
    model_name = cfg.get("model")
    m = None
    if model_name:
        m = (
            await db.execute(
                select(ModelConfig)
                .where(ModelConfig.name == model_name, ModelConfig.kind == "chat")
                .options(selectinload(ModelConfig.provider))
            )
        ).scalar_one_or_none()
    if m is None:
        m = await _default_chat_model(db)
    return _build_mem_cfg(m, await _default_embed_model(db))


# ---------------------------- _load_context 단계 헬퍼 (스펙 291 분해) ----------------------------


async def _resolve_version_and_prompt(
    db: AsyncSession, agent: Agent, cfg: dict, version: str | None
) -> tuple[dict, str, str | None]:
    """버전 지정 실행(스펙 242) — 그 버전의 config 스냅샷으로 소스 전환(초안 미리보기·버전 테스트).

    prompt는 스냅샷에 이름만 있으므로 지금 본문으로 재해석(activate와 동일 규칙).
    반환 (cfg, prompt, pinned_version). version 미지정이면 저장 config·prompt 그대로."""
    if not version:
        return cfg, agent.prompt, None
    if _is_remote(agent.source):
        raise HTTPException(
            status_code=400,
            detail="원격(code/external) 에이전트는 버전 지정 실행을 지원하지 않습니다",
        )
    from .models import AgentVersion

    vrow = (
        await db.execute(
            select(AgentVersion).where(
                AgentVersion.agent_pk == agent.id, AgentVersion.version == version
            )
        )
    ).scalar_one_or_none()
    if vrow is None:
        raise HTTPException(status_code=404, detail=f"버전을 찾을 수 없습니다: {version}")
    cfg = dict(vrow.config or {})
    # 미리보기 실행도 pin 우선(스펙 370) — 그 버전이 못박은 본문으로(head 폴백=레거시·literal).
    from .block_versions import resolve_pinned

    pinned = await resolve_pinned(db, vrow.pins, "prompt", cfg.get("prompt", ""))
    if pinned is not None:
        prompt = pinned.get("body", "")
    else:
        from .models import Prompt as _Prompt

        prow = (
            await db.execute(select(_Prompt).where(_Prompt.name == cfg.get("prompt", "")))
        ).scalar_one_or_none()
        prompt = prow.body if prow is not None else cfg.get("prompt", "")
    return cfg, prompt, version


def _coerce_history_depth(cfg: dict, agent: Agent) -> None:
    """historyDepth 형 가드(codex 287 Low) — 비정수(예: 문자열)는 _window의 `depth < 0` 비교에서
    TypeError 500. 정수화 실패 시 저장값 폴백(요청 하나로 500 못 만들게)."""
    if isinstance(cfg.get("historyDepth"), int):
        return
    try:
        cfg["historyDepth"] = int(cfg["historyDepth"])
    except (TypeError, ValueError):
        cfg["historyDepth"] = (agent.config or {}).get("historyDepth", 20)


def _apply_overrides(
    cfg: dict, prompt: str, overrides: dict | None, agent: Agent, allowed: set
) -> tuple[dict, str, str | None, dict | None]:
    """web 한정 세션 오버라이드 병합(스펙 025) — 화이트리스트 키만, 저장 에이전트는 불변.

    코드·외부(원격) 에이전트는 미적용(bypass 보존 — 026 read-only 취급). 모델은 여전히
    cfg["model"] 이름으로 레지스트리에서만 해석 → [012] 단일 소스 불변식 유지.
    - capabilities(스펙 122): 브로커가 build_broker(principal=호출자)로 호출자 RBAC 게이트
      (_permitted = allowlist ∩ RBAC)하므로 주입분도 안전(confused-deputy 무관).
    - tools(스펙 276): 직접형 도구 단위 배선 — 노출 축소/서버별 필터라 완화 아님.
    - vectorTables(스펙 287): 노드형 문서 풀 파생의 실효 축 — RAG 읽기(사용=공용 정책 211).
    - nodes(스펙 287): 구조 불변 강제 merge(allowed와 분리 — 통짜 교체가 아니라 저장 노드 위
      필드 merge, 추가/삭제=범위 밖). 미적용 사유(mismatch)는 트레이스가 표면화.
    반환 (cfg, prompt, nodes_status, passthrough) — passthrough=적용된 원본 오버라이드(미적용=None):
    in-process 커스텀 에이전트가 화이트리스트 밖 키도 읽게 ctx["overrides"]로 전달(스펙 085)."""
    if not overrides or _is_remote(agent.source):
        return cfg, prompt, None, None
    cfg.update({k: v for k, v in overrides.items() if k in allowed})
    if "historyDepth" in overrides:
        _coerce_history_depth(cfg, agent)
    # systemPrompt는 비어있지 않을 때만 prompt를 덮어쓴다 — 빈/공백 문자열로
    # 저장된 프롬프트를 지우지 않도록(백엔드 자체 가드, 클라이언트 신뢰 안 함. codex P1).
    sp = overrides.get("systemPrompt")
    if isinstance(sp, str) and sp.strip():
        prompt = sp
    nodes_status: str | None = None
    if overrides.get("nodes") is not None:
        if isinstance(cfg.get("nodes"), list):
            cfg["nodes"], nodes_status = _merge_node_overrides(cfg["nodes"], overrides["nodes"])
        else:
            nodes_status = "mismatch"  # 노드형이 아닌 에이전트에 nodes를 보냄
    return cfg, prompt, nodes_status, overrides


def _filter_capabilities(cfg: dict) -> list:
    """능력 브로커 allowlist(스펙 100) — 오케스트레이션 허용 cap id 목록(없으면 [] = deny-by-default).

    비영속(스펙 237) 방어층: DB 쓰기 능력(memwrite/memedit)은 걸러낸다 — 정본 게이트는 저장 시
    422(agents._enforce_ephemeral_boundary), 여기는 과거 저장분·우회 대비 fail-closed."""
    return [
        c
        for c in cfg.get("capabilities", [])
        if not (
            cfg.get("ephemeral")
            and isinstance(c, str)
            and c.split(":", 1)[0] in ("memwrite", "memedit")
        )
    ]


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
            return pinned
    m = None
    if model_name:
        m = (
            await db.execute(
                select(ModelConfig)
                .where(ModelConfig.name == model_name, ModelConfig.kind == "chat")
                .options(selectinload(ModelConfig.provider))
            )
        ).scalar_one_or_none()
    if m is None:
        if overrides and overrides.get("model") == model_name:
            raise HTTPException(
                status_code=400,
                detail=f"오버라이드 모델 '{model_name}'이(가) 등록돼 있지 않습니다 — 모델 이름을 확인하세요.",
            )
        m = (
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
    if m is None:
        raise HTTPException(
            status_code=400,
            detail="등록된 채팅 모델이 없습니다 — 모델을 먼저 등록하세요.",
        )
    base_url = m.provider.base_url if m.provider else ""
    if not base_url or not m.model_id:
        raise HTTPException(
            status_code=400,
            detail=f"모델 '{m.name}' 설정이 불완전합니다 (provider base_url/model_id 필요).",
        )
    # 위 두 가드가 각각 다른 에러 메시지(등록 없음·설정 불완전)라 model_usable로 접지 않음 — dict만 정본화.
    return {**llm_cfg_of(m), "params": dict(m.params or {})}


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


async def _resolve_mcp_servers(
    db: AsyncSession, cfg: dict, pins: dict | None = None
) -> tuple[list[dict], list]:
    """등록된 MCP 서버를 runtime.build_mcp_tools가 붙을 수 있는 dict로 해석(스펙 054).

    auth_token은 저장된 Fernet 암호문을 복호화한 평문(provider.api_key 동형) — 마스킹/빈값이면
    None이라 헤더 생략(a2a_client 규칙). enabled_tools가 비면 서버 전체 도구 노출(get_tools가 결정).
    사용=공용(스펙 211, RAG 172 동형) — 등록된 MCP는 어떤 에이전트든 배선 가능(구 113 배선 인가
    제거). auth 토큰 있는 MCP도 공용 배선(공유 카탈로그 모델), 관리(수정/삭제)는 여전히 소유자만.

    tool_names(스펙 276) — tools(런타임명 목록)는 서버 풀 위의 노출 필터. **직접형(DefaultUiAgent)
    전용**: 노드형(pipeline)은 노드가 자기 tools로 풀을 필터하므로 에이전트-레벨 tools로 풀을 좁히면
    노드 도구가 조용히 미바인딩된다(codex 276 Low). 조율형은 capabilities가 도구를 관장. 그래서 이
    둘은 필터 미적용(풀=전체) — UI finalize의 "pipeline/조율형은 tools:[] 저장" 규칙을 백엔드에서도
    강제(의도 값 게이트, 클라이언트 신뢰 안 함). 반환 (mcp_servers, tool_names)."""
    from .block_versions import resolve_pinned

    mcp_servers: list[dict] = []
    mcps = config_names(cfg, "mcps")  # 삭제 가드와 동일 normalizer(drift 0, codex P2)
    if mcps:
        rows = (await db.execute(select(McpServer).where(McpServer.name.in_(mcps)))).scalars().all()
        for row in rows:
            token = None if crypto.is_masked(row.auth) else crypto.decrypt(row.auth)
            # pin 오버레이(스펙 370) — 저작 내용(url/transport/enabled_tools/tools_meta)은
            # 못박은 버전 payload, 비밀(auth)·운영(published/status)은 head 라이브(369 경계).
            pinned = await resolve_pinned(db, pins, "mcp-server", row.name)
            if pinned is not None:
                url = pinned.get("url") or pinned.get("endpoint") or ""
                transport = pinned.get("transport") or "http"
                enabled = list(pinned.get("enabled_tools") or [])
                tools_meta = pinned.get("tools_meta") or {}
            else:
                url = row.url or row.endpoint or ""
                transport = row.transport or "http"
                enabled = list(row.enabled_tools or [])
                tools_meta = row.tools_meta or {}
            mcp_servers.append(
                {
                    "name": row.name,
                    "url": url,
                    "transport": transport,
                    "enabled_tools": enabled,
                    "auth_token": token,
                    "tools_meta": tools_meta,  # 도구 승인 정책 리졸버용(스펙 177)
                }
            )
    impl_key = cfg.get("impl")
    tool_filter_applies = impl_key not in ("pipeline", "orchestrate", "orchestrate_ranked")
    tool_names = config_names(cfg, "tools") if tool_filter_applies else []
    return mcp_servers, tool_names


def _rag_collection_entry(c: Collection) -> dict | None:
    """컬렉션 → 검색 배선 dict — embedding 모델/provider 불완전이면 None(검색 불가 skip)."""
    em = c.embedding_model
    ep = em.provider if em else None
    if em is None or ep is None or not ep.base_url or not em.model_id:
        return None
    return {
        "id": c.id,
        "name": c.name,
        "embed_base_url": ep.base_url,
        "embed_api_key": crypto.decrypt(ep.api_key),
        "embed_model_id": em.model_id,
    }


async def _resolve_rag(db: AsyncSession, cfg: dict, remote: bool) -> tuple[list[dict], list[str]]:
    """RAG 컬렉션 해석(스펙 037) — vectorTables(이름 목록) → 검색 도구 배선용 dict.

    질의는 **각 컬렉션이 인제스트에 쓴 임베딩 모델**로 임베딩해야 같은 벡터 공간(035 진실원).
    provider 불완전 컬렉션은 검색 불가라 skip(graceful). 컬렉션은 전부 공용(스펙 172) — 가시성 축
    제거, 관리(수정·삭제)는 소유자만. 원격(code/external)은 비로컬이라 빈 결과.
    반환 (rag_collections, unresolved — 해석 실패 이름은 트레이스로 표면화, 타자검증 F)."""
    vt_names = config_names(cfg, "vectorTables")  # 삭제 가드와 동일 normalizer(drift 0)
    if not vt_names or remote:
        return [], []
    cols = (
        (
            await db.execute(
                select(Collection)
                .where(Collection.name.in_(vt_names))
                .options(
                    selectinload(Collection.embedding_model).selectinload(ModelConfig.provider)
                )
            )
        )
        .scalars()
        .all()
    )
    rag_collections: list[dict] = []
    for col in cols:
        entry = _rag_collection_entry(col)
        if entry is None:
            log.warning("rag collection %s skipped: embedding model/provider 불완전", col.name)
            continue
        rag_collections.append(entry)
    resolved = {rc["name"] for rc in rag_collections}
    unresolved = [n for n in vt_names if n not in resolved]
    if unresolved:
        log.warning(
            "rag vectorTables 미해석: %s (요청 %s → 해석 %s)",
            unresolved,
            vt_names,
            sorted(resolved),
        )
    return rag_collections, unresolved


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


async def _resolve_nodes_for_ctx(
    db: AsyncSession, ctx: dict, remote: bool, pins: dict | None = None
) -> list[dict] | None:
    """노드형(스펙 259)이면 노드별 모델을 **플랫폼이 미리 해석**해 심는다(085 U2: build_graph는 DB
    미접촉). 로컬(ui) 경로에서만 의미 — 비노드형/원격은 None."""
    if remote or not isinstance(ctx.get("nodes"), list):
        return None
    return await _resolve_node_models(db, ctx["nodes"], ctx["model_cfg"], pins)


async def _load_context(
    agent_id: uuid.UUID,
    session_str_id: str | None,
    overrides: dict | None = None,
    own: str | None = None,
    version: str | None = None,
) -> dict:
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
        cfg = dict(agent.config or {})
        # (스펙 211) 구 113 P0의 저장본/override 권한 분리(stored_mcps 포착)는 사용=공용 전환으로 소멸.
        cfg, prompt, pinned_version = await _resolve_version_and_prompt(db, agent, cfg, version)
        # 노드 참조 해석(스펙 316) — ref 항목을 등록 노드 config 사본으로 치환. **오버라이드 병합
        # 전에**(해석→병합): 세션 패치는 해석된 유효 노드 위에 얹는다. 미해결 참조는 422로 명확히
        # 실패(반쪽 파이프라인 조용히 실행 금지 — 089 패턴). 핀 버전 미리보기(version=) 스냅샷의
        # 참조도 여기서 함께 해석된다(_resolve_version_and_prompt 뒤 단일 지점).
        if not _is_remote(agent.source) and isinstance(cfg.get("nodes"), list):
            cfg["nodes"] = await resolve_node_refs(db, cfg["nodes"])
        # 세션 오버라이드 화이트리스트(스펙 025/122/276/287 — 각 키 근거는 _apply_overrides docstring).
        allowed = {
            "model",
            "temperature",
            "historyDepth",
            "mcps",
            "memories",
            "capabilities",
            "tools",
            "vectorTables",
        }
        cfg, prompt, nodes_status, applied_overrides = _apply_overrides(
            cfg, prompt, overrides, agent, allowed
        )
        remote = _is_remote(agent.source)
        # 노드형 풀 서버 파생(스펙 289 P2) — 로드 시 무조건 재파생: 폼 밖 입구(API 직생성·구저장·
        # 오버라이드)로 풀이 비었거나 낡았어도 노드 참조대로 도구·문서·기억이 빌드된다(learning 151).
        # 저장 시 파생(agents.py)과 같은 규칙이라 폼 저장분엔 무변화(멱등).
        if not remote:
            await derive_pipeline_pool(cfg)
        ctx = {
            "prompt": prompt,
            "ext_agent_id": agent.agent_id,
            "agent_name": agent.name,
            "agent_pk": agent.id,
            "source": agent.source,
            "impl": cfg.get("impl"),  # in-process 커스텀 구현 키(스펙 085) — 신뢰 레지스트리 조회용
            "artifact_spec": cfg.get(
                "artifactSpec"
            ),  # 노코드 산출물형 필드 명세(스펙 190) — impl_config로 주입
            "nodes": cfg.get(
                "nodes"
            ),  # 노드형 파이프라인 노드 명세(스펙 259) — 아래서 노드별 모델 해석 후 impl_config로 주입
            "overrides_nodes_status": nodes_status,  # 노드 오버라이드 적용 상태(스펙 287) — 트레이스 표면화용
            # 원본 오버라이드 — in-process 커스텀 에이전트가 화이트리스트 밖 키도 읽을 수 있게 전달
            # (스펙 085 AgentBuildContext.overrides). 원격은 None(로컬 설정 주입 무의미, bypass 보존).
            "overrides": applied_overrides,
            "endpoint": agent.endpoint,
            "token": agent.token,
            "card": cfg.get("card"),  # A2A 카드 스냅샷(외부 에이전트, capabilities.streaming 등)
            "memories": cfg.get("memories", []),
            "capabilities": _filter_capabilities(cfg),
            # 도구 승인 오버라이드(스펙 177 P2) — cap_id→{approval:{required?,approver?}}. 그래프-tools·
            # 브로커 두 경로 리졸버에 급전. **요청 오버라이드 허용키(위 allowed)엔 불포함** — 요청으로
            # 승인을 완화(우회)하지 못하게 config-only(완화 권한은 저장 시 admin 게이트로 강제).
            "toolPolicy": cfg.get("toolPolicy") or {},
            # 에이전트가 명시한 temperature만 전달(없으면 None) → 모델 등록 params가 적용되게.
            "temperature": cfg.get("temperature"),
            "history_depth": cfg.get("historyDepth", 20),
            "persist_history": cfg.get("persistHistory", True),
            # 비영속(1회성) 모드(스펙 235) — true면 DB 적재 전면 스킵: 세션 행·카운터·메시지·commit·
            # 메모리 read/write 전부 무동작. persistHistory(메시지만 스킵)의 상위집합. 세션이 없으니
            # 이력·회상·소유권도 없음(순수 stateless).
            "ephemeral": bool(cfg.get("ephemeral", False)),
            # 실행 버전(스펙 242) — pinned=지정 버전(미리보기), exec=실제 실행 버전(지정 없으면 활성).
            # trace.agentVersion 기록·HIL 게이트(pinned는 승인 재개가 서빙 config로 돌아 drift) 근거.
            "pinned_version": pinned_version,
            "exec_version": pinned_version or agent.active_version,
        }
        # 프롬프트(프롬프트) 출처(스펙 364) — 이 턴에 실제 쓰인 프롬프트를 이력에 남겨 턴 분석/재현을
        # 가능케 한다. systemPrompt 오버라이드로 임시 프롬프트가 쓰였으면 라이브러리 참조가 아니므로
        # 이름/id 없음(정직). cfg["prompt"]는 이름이거나 인라인 본문 — 실제 Prompt 행이 매칭될 때만
        # 이름/id를 남기고(짧은 라이브러리 키), 인라인이면 null(본문은 아래 promptSnapshot이 보존).
        ctx["prompt_name"] = None
        ctx["prompt_id"] = None
        _sp = (applied_overrides or {}).get("systemPrompt")
        _override_prompt = isinstance(_sp, str) and bool(_sp.strip())
        # 원격(code/external)은 프롬프트가 원격 측에 있어 로컬 라이브러리 참조가 무의미 → 출처 미기록.
        _ref = "" if (remote or _override_prompt) else (cfg.get("prompt") or "")
        if _ref:
            from .models import Prompt as _Prompt

            _prow = (
                await db.execute(select(_Prompt.id).where(_Prompt.name == _ref))
            ).scalar_one_or_none()
            if _prow is not None:
                ctx["prompt_name"] = _ref
                ctx["prompt_id"] = str(_prow)
        # 실행 버전의 pins(스펙 370) — 못박은 블록 버전으로 해석(모델·MCP·노드 모델). 원격/레거시
        # (pins 없음)는 빈 dict → 전부 head 폴백(무회귀).
        pins: dict = {}
        if not remote and ctx["exec_version"]:
            from .models import AgentVersion as _AV

            _vrow = (
                await db.execute(
                    select(_AV.pins).where(
                        _AV.agent_pk == agent.id, _AV.version == ctx["exec_version"]
                    )
                )
            ).scalar_one_or_none()
            pins = dict(_vrow or {})
        ctx["pins"] = pins
        # 코드·외부 에이전트는 비로컬(원격/A2A) 실행이라 로컬 모델이 필요 없다(건너뜀 = None).
        ctx["model_cfg"] = await _resolve_model(db, cfg, overrides, pins) if not remote else None
        ctx["nodes_resolved"] = await _resolve_nodes_for_ctx(db, ctx, remote, pins)
        ctx["mem_cfg"] = await _resolve_mem_cfg(db, ctx["model_cfg"])
        ctx["mcp_servers"], ctx["tool_names"] = await _resolve_mcp_servers(db, cfg, pins)
        ctx["rag_collections"], ctx["rag_unresolved"] = await _resolve_rag(db, cfg, remote)
        # 컬렉션별 최소 유사도 맵(스펙 191 v2) — {컬렉션명: 임계값}. 미만 문서를 검색 코어에서 드롭.
        # downstream(build_rag_tool·RagProvider)이 범위(0<x≤1)·컬렉션 한정 재검증하므로 raw 통과({}=무필터).
        ctx["rag_min_scores"] = cfg.get("ragMinScores") or {}
        ctx.update(await _resolve_session(db, agent, session_str_id, own))
        return ctx

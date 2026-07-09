"""등록된 에이전트와의 대화 (SSE 스트리밍).

persona + (선택)mem0 장기 메모리 + (선택)MCP 합성 툴을 LangGraph로 합성해 실행하고,
세션/메시지/트레이스를 영속화한다. 트레이스는 Playground 인스펙터가 소비.

지배 스펙: docs/spec/007-real-agent-service.md (Phase 2)
"""

import asyncio
import json
import logging
import secrets
import time
import uuid

from agent.runtime import (
    AgentBuildContext,
    AgentConfigError,
    DefaultUiAgent,
    get_agent_impl,
    is_remote_source,
)
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from langgraph.types import Command
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from . import a2a_client, authz, checkpointer, crypto, memory, observability, runtime
from . import trace_capture
from .auth import current_principal
from .broker import PolicyScopedBroker, build_broker
from .db import SessionLocal
from .mem_config import _build_mem_cfg, _default_chat_model, _default_embed_model
from .models import (
    Agent,
    Approval,
    Collection,
    McpServer,
    Message,
    ModelConfig,
    Session,
    User,
)
from .ownership import next_owner
from .references import config_names
from .schemas import ChatRequest
from .sessions import _own_scope

router = APIRouter(prefix="/agents", tags=["chat"])
log = logging.getLogger("api.chat")

# 산출물형 ask/form 대기 포인터(스펙 188) — session_id → {"thread_id"}. thread_id가 턴별 고유라
# ask interrupt가 걸린 체크포인트는 이전 턴 thread에 남는다(승인은 Approval.checkpoint가 이 역할).
# 다음 사용자 입력이 오면 이 thread를 Command(resume=)로 재개한다. 프로세스 메모리(P1 경계) —
# 재시작 시 소실되면 다음 입력이 새 produce 실행으로 폴백(영속화는 후속 스펙).
_PENDING_ARTIFACT: dict[str, dict] = {}


# 원격 소스 판정 단일 술어는 agent.runtime로 내렸다(스펙 089) — resolve·classify·직렬화가 공유.
_is_remote = is_remote_source


def resolve_agent_runtime(ctx: dict):
    """이 에이전트의 **in-process 런타임 구현**을 해석한다(스펙 085 + 089 폴백 교정).

    - 원격(code/external) → None: 인터페이스 미대상 → 호출측이 `_a2a_stream` fallback(지금처럼).
    - 로컬(ui) + impl 미선언 → `DefaultUiAgent`(레퍼런스 적합, 정상 default).
    - 로컬(ui) + impl 적중(적합) → 그 커스텀 에이전트.
    - 로컬(ui) + impl 선언했으나 미해결(미등록/부적합) → **`AgentConfigError` raise**(스펙 089 교정3):
      `DefaultUiAgent`로 *만회·폴백하지 않는다* — 등록/설정 실수를 default가 가리지 않게 서빙을
      거부한다. 호출측이 잡아 정직히 통보.

    `impl`은 레지스트리의 *키*일 뿐 코드가 아니다 — eval/import 경로 없음(스펙 085 §보안경계)."""
    if _is_remote(ctx["source"]):
        return None
    impl_key = ctx.get("impl")
    if not impl_key:
        return DefaultUiAgent()
    inst = get_agent_impl(impl_key)
    if inst is None:
        raise AgentConfigError(impl_key)
    return inst


async def _config_error_stream(impl_key: str):
    """설정 실패(스펙 089) — 선언한 in-process 구현이 미해결. default로 만회하지 않고 SSE로 정직히
    통보한다. **클라이언트 메시지는 일반화**(impl 값 미반영) — config["impl"]은 관리자가 임의로 저장한
    값(합의 B)이라 *레지스트리 키임이 증명되지 않으며*, 채팅 클라이언트는 관리자보다 권한이 낮을 수
    있다(GET /agents의 impl은 인증 관리자 전용). 구체 키는 서버 로그에만 남겨 운영 디버깅을 보존한다
    (codex 적대 리뷰 089-F1: 미해결 impl 원문이 SSE로 새던 정보노출 봉합 — 비밀누출 0)."""
    log.warning("config_error 채팅 거부: 미해결 impl %r", impl_key)
    msg = "에이전트 설정 오류로 응답할 수 없습니다 — 관리자에게 문의하세요(런타임 구현 미해결)."
    yield f"data: {json.dumps({'error': msg}, ensure_ascii=False)}\n\n"
    yield "event: done\ndata: [DONE]\n\n"


# 스펙 211: 배선 인가 헬퍼(_wiring_owner_privileged, 스펙 113)는 "사용=공용" 정책 전환으로 제거.
# 관리(수정/삭제)는 blocks.py의 assert_may_manage가 계속 게이트한다.


async def _load_context(
    agent_id: uuid.UUID,
    session_str_id: str | None,
    overrides: dict | None = None,
    own: str | None = None,
    version: str | None = None,
):
    """에이전트 구성 + MCP 활성 툴 + 세션(생성/지속)을 한 번에 준비.

    overrides(스펙 025): Playground Proxy의 세션 한정 설정 덮어쓰기. **web 에이전트에만** 적용하고
    화이트리스트 키만 받는다(저장된 에이전트는 불변). 코드 에이전트는 원격 실행이라 미적용(bypass).

    own(스펙 068): resume 소유자 스코프. 비-admin이면 `str(principal.id)`, admin/머신·내부 호출은
    None. `own is not None`이면 resume 바인딩이 `Session.user_id == own`을 요구해, *타인/NULL/추측*
    session_id는 매칭 실패 → 새 세션 발급(067 읽기 게이트와 동일 판정 — 열거 오라클·소유권 탈취 봉인).
    """
    async with SessionLocal() as db:
        agent = await db.get(Agent, agent_id)
        if agent is None:
            raise HTTPException(status_code=404, detail="agent not found")
        cfg = dict(agent.config or {})
        # (스펙 211) 구 113 P0의 저장본/override 권한 분리(stored_mcps 포착)는 사용=공용 전환으로
        # 소멸 — 등록된 MCP는 누구 에이전트든 배선 가능하므로 주입 경로 구분이 무의미해졌다.
        persona = agent.persona
        # 버전 지정 실행(스펙 242) — 그 버전의 config 스냅샷으로 소스 전환(초안 미리보기·버전 테스트).
        # persona는 스냅샷에 이름만 있으므로 지금 본문으로 재해석(activate와 동일 규칙).
        pinned_version: str | None = None
        if version:
            if _is_remote(agent.source):
                raise HTTPException(status_code=400, detail="원격(code/external) 에이전트는 버전 지정 실행을 지원하지 않습니다")
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
            from .models import Persona as _Persona

            prow = (
                await db.execute(select(_Persona).where(_Persona.name == cfg.get("persona", "")))
            ).scalar_one_or_none()
            persona = prow.body if prow is not None else cfg.get("persona", "")
            pinned_version = version
        # web 한정 세션 오버라이드(화이트리스트). 코드·외부 에이전트는 분기 진입 안 함 = bypass 보존.
        # (외부=A2A는 비로컬이라 로컬 설정 오버라이드 의미 없음 — 026 read-only 취급.)
        # 모델은 여전히 cfg["model"] 이름으로 레지스트리에서만 해석 → [012] 단일 소스 불변식 유지.
        if overrides and not _is_remote(agent.source):
            # capabilities(스펙 122): 조율형 MCP는 config.capabilities로 담기므로 오버라이드도 이 키를
            # 허용해야 세션에 반영된다. 브로커가 build_broker(principal=호출자, capabilities)로
            # 호출자 RBAC 게이트(_permitted = allowlist ∩ RBAC)하므로 주입분도 안전(confused-deputy 무관).
            allowed = {"model", "temperature", "historyDepth", "mcps", "memories", "capabilities"}
            cfg.update({k: v for k, v in overrides.items() if k in allowed})
            # systemPrompt는 비어있지 않을 때만 persona를 덮어쓴다 — 빈/공백 문자열로
            # 저장된 페르소나를 지우지 않도록(백엔드 자체 가드, 클라이언트 신뢰 안 함. codex P1).
            sp = overrides.get("systemPrompt")
            if isinstance(sp, str) and sp.strip():
                persona = sp
        ctx = {
            "persona": persona,
            "ext_agent_id": agent.agent_id,
            "agent_name": agent.name,
            "agent_pk": agent.id,
            "source": agent.source,
            "impl": cfg.get("impl"),  # in-process 커스텀 구현 키(스펙 085) — 신뢰 레지스트리 조회용
            "artifact_spec": cfg.get("artifactSpec"),  # 노코드 산출물형 필드 명세(스펙 190) — impl_config로 주입

            # 원본 오버라이드 — in-process 커스텀 에이전트가 화이트리스트 밖 키도 읽을 수 있게 전달
            # (스펙 085 AgentBuildContext.overrides). 원격은 None(로컬 설정 주입 무의미, bypass 보존).
            "overrides": overrides if (overrides and not _is_remote(agent.source)) else None,
            "endpoint": agent.endpoint,
            "token": agent.token,
            "card": cfg.get("card"),  # A2A 카드 스냅샷(외부 에이전트, capabilities.streaming 등)
            "memories": cfg.get("memories", []),
            # 능력 브로커 allowlist(스펙 100) — 이 에이전트가 오케스트레이션 허용된 cap id 목록.
            # 없으면 [] = deny-by-default(브로커가 발견 공집합). RBAC과 교집합해 최종 스코프.
            # 비영속(스펙 237) 방어층: DB 쓰기 능력(memwrite/memedit)은 걸러낸다 — 정본 게이트는
            # 저장 시 422(agents._enforce_ephemeral_boundary), 여기는 과거 저장분·우회 대비 fail-closed.
            "capabilities": [
                c for c in cfg.get("capabilities", [])
                if not (cfg.get("ephemeral") and isinstance(c, str) and c.split(":", 1)[0] in ("memwrite", "memedit"))
            ],
            # 도구 승인 오버라이드(스펙 177 P2) — cap_id→{approval:{required?,approver?}}. 그래프-tools·
            # 브로커 두 경로 리졸버에 급전. **요청 오버라이드 허용키(위 allowed)엔 불포함** — 요청으로
            # 승인을 완화(우회)하지 못하게 config-only(완화 권한은 저장 시 admin 게이트로 강제).
            "toolPolicy": cfg.get("toolPolicy") or {},
            # 에이전트가 명시한 temperature만 전달(없으면 None) → 모델 등록 params가 적용되게.
            "temperature": cfg.get("temperature"),
            "history_depth": cfg.get("historyDepth", 20),
            "persist_history": cfg.get("persistHistory", True),
            # 비영속(1회성) 모드(스펙 235) — true면 DB 적재 전면 스킵: 세션 행·카운터·메시지·commit·
            # 메모리 read/write 전부 무동작. 고트래픽·기록 무의미한 단순 추론 제공용. persistHistory(메시지만
            # 스킵)의 상위집합. 세션이 없으니 이력·회상·소유권도 없음(순수 stateless).
            "ephemeral": bool(cfg.get("ephemeral", False)),
            # 실행 버전(스펙 242) — pinned=지정 버전(미리보기), exec=실제 실행 버전(지정 없으면 활성).
            # trace.agentVersion 기록·HIL 게이트(pinned는 승인 재개가 서빙 config로 돌아 drift) 근거.
            "pinned_version": pinned_version,
            "exec_version": pinned_version or agent.active_version,
        }

        # 모델은 레지스트리에서만 해석한다(env 안 봄). 에이전트가 고른 이름 → 없으면
        # 기본(is_default) chat 모델. 그것도 없으면 명확히 400.
        # 코드·외부 에이전트는 비로컬(원격/A2A) 실행이라 로컬 모델이 필요 없다(여기선 건너뜀).
        if not _is_remote(agent.source):
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
                m = (
                    await db.execute(
                        select(ModelConfig)
                        .where(ModelConfig.kind == "chat", ModelConfig.is_default.is_(True))
                        .options(selectinload(ModelConfig.provider))
                    )
                ).scalars().first()
            if m is None:
                raise HTTPException(
                    status_code=400,
                    detail="등록된 채팅 모델이 없습니다 — 모델을 먼저 등록하세요.",
                )
            # 연결처는 provider에서 상속(스펙 035).
            base_url = m.provider.base_url if m.provider else ""
            if not base_url or not m.model_id:
                raise HTTPException(
                    status_code=400,
                    detail=f"모델 '{m.name}' 설정이 불완전합니다 (provider base_url/model_id 필요).",
                )
            ctx["model_cfg"] = {
                "base_url": base_url, "api_key": crypto.decrypt(m.provider.api_key),
                "model_id": m.model_id, "params": dict(m.params or {}),
            }
        else:
            ctx["model_cfg"] = None

        # mem0용 모델 설정(레지스트리). llm=해석된 chat 모델, embedder=기본 embedding 모델.
        # 임베딩 모델이 없으면 mem_cfg=None → 메모리 비활성(graceful).
        mem_cfg = None
        if ctx["model_cfg"]:
            emb = (
                await db.execute(
                    select(ModelConfig)
                    .where(ModelConfig.kind == "embedding", ModelConfig.is_default.is_(True))
                    .options(selectinload(ModelConfig.provider))
                )
            ).scalars().first()
            if emb is not None and emb.provider is not None:
                mem_cfg = {
                    "llm": {
                        "base_url": ctx["model_cfg"]["base_url"],
                        "api_key": ctx["model_cfg"]["api_key"],
                        "model_id": ctx["model_cfg"]["model_id"],
                    },
                    "embedder": {
                        "base_url": emb.provider.base_url,
                        "api_key": crypto.decrypt(emb.provider.api_key),
                        "model_id": emb.model_id,
                    },
                }
        ctx["mem_cfg"] = mem_cfg

        # 등록된 MCP 서버를 runtime.build_mcp_tools가 실제로 붙을 수 있는 dict로 해석한다(스펙 054).
        # name/url/transport/enabled_tools + auth_token. auth_token은 저장된 Fernet 암호문을
        # 복호화한 평문(provider.api_key 동형) — 마스킹/빈값이면 None이라 헤더 생략(a2a_client 규칙).
        # enabled_tools가 비면 서버 전체 도구를 노출(get_tools가 결정).
        mcp_servers: list[dict] = []
        mcps = config_names(cfg, "mcps")  # 삭제 가드와 동일 normalizer(drift 0, codex P2)
        if mcps:
            rows = (
                await db.execute(select(McpServer).where(McpServer.name.in_(mcps)))
            ).scalars().all()
            for r in rows:
                # 사용=공용(스펙 211, RAG 172 동형) — 등록된 MCP는 어떤 에이전트든 배선 가능.
                # 구 배선 인가(스펙 113 agent_may_wire·published 게이트)는 사용자 정책 결정으로 제거.
                # published는 이제 "커스텀 MCP 외부 서빙" 전용 축(served_mcp._is_served가 소비).
                # 주의: auth 토큰 있는 MCP도 공용 배선된다(공유 카탈로그 모델) — 관리(수정/삭제)는
                # 여전히 소유자만(assert_may_manage 불변).
                token = None if crypto.is_masked(r.auth) else crypto.decrypt(r.auth)
                mcp_servers.append(
                    {
                        "name": r.name,
                        "url": r.url or r.endpoint or "",
                        "transport": r.transport or "http",
                        "enabled_tools": list(r.enabled_tools or []),
                        "auth_token": token,
                        "tools_meta": r.tools_meta or {},  # 도구 승인 정책 리졸버용(스펙 177)
                    }
                )
        ctx["mcp_servers"] = mcp_servers

        # RAG 컬렉션 해석(스펙 037) — vectorTables(이름 목록) → 검색 도구 배선용 dict.
        # 질의는 **각 컬렉션이 인제스트에 쓴 임베딩 모델**로 임베딩해야 같은 벡터 공간이 된다
        # (035 진실원). provider 불완전(base_url/model_id 없음) 컬렉션은 검색 불가라 skip(graceful).
        # 코드·외부 에이전트는 비로컬이라 위에서 이미 분기되지 않고 도달할 수 있으나, 이 블록은
        # 로컬 실행 경로에서만 의미가 있다 — code/external은 chat()에서 프록시/안내로 빠진다.
        rag_collections: list[dict] = []
        vt_names = config_names(cfg, "vectorTables")  # 삭제 가드와 동일 normalizer(drift 0)
        if vt_names and not _is_remote(agent.source):
            cols = (
                await db.execute(
                    select(Collection)
                    .where(Collection.name.in_(vt_names))
                    .options(
                        selectinload(Collection.embedding_model).selectinload(ModelConfig.provider)
                    )
                )
            ).scalars().all()
            for c in cols:
                # 컬렉션은 전부 공용(스펙 172) — 어느 에이전트든 배선 가능(가시성 축 제거).
                # 관리(수정·삭제)는 여전히 소유자만. 완전성(embedding) 검사만 남긴다.
                em = c.embedding_model
                ep = em.provider if em else None
                if em is None or ep is None or not ep.base_url or not em.model_id:
                    log.warning("rag collection %s skipped: embedding model/provider 불완전", c.name)
                    continue
                rag_collections.append(
                    {
                        "id": c.id,
                        "name": c.name,
                        "embed_base_url": ep.base_url,
                        "embed_api_key": crypto.decrypt(ep.api_key),
                        "embed_model_id": em.model_id,
                    }
                )
            # 관측성(타자검증 F): 요청된 vectorTables 중 실 컬렉션으로 해석되지 못한 이름을 남긴다.
            # 삭제·개명·provider 불완전으로 도구가 조용히 0개 되는 footgun을 트레이스로 드러냄.
            resolved = {rc["name"] for rc in rag_collections}
            unresolved = [n for n in vt_names if n not in resolved]
            if unresolved:
                log.warning("rag vectorTables 미해석: %s (요청 %s → 해석 %s)",
                            unresolved, vt_names, sorted(resolved))
            ctx["rag_unresolved"] = unresolved
        else:
            ctx["rag_unresolved"] = []
        ctx["rag_collections"] = rag_collections
        # 컬렉션별 최소 유사도 맵(스펙 191 v2) — {컬렉션명: 임계값}. 미만 문서를 검색 코어에서 드롭.
        # downstream(build_rag_tool·RagProvider)이 범위(0<x≤1)·컬렉션 한정 재검증하므로 raw 통과({}=무필터).
        ctx["rag_min_scores"] = cfg.get("ragMinScores") or {}

        sess = None
        if session_str_id:
            # 세션은 해당 에이전트로 스코프 — 다른 에이전트의 세션 id를 줘도 섞이지 않게.
            # 스펙 068: 비-admin(own is not None)은 *자기 소유* 세션만 resume. 타인/NULL session_id는
            # 매칭 실패 → 아래 else가 새 세션을 발급(부재와 구별 불가 = 열거 오라클 제거).
            resume_q = select(Session).where(
                Session.session_id == session_str_id,
                Session.agent_pk == agent.id,
            )
            if own is not None:
                resume_q = resume_q.where(Session.user_id == own)
            sess = (await db.execute(resume_q)).scalar_one_or_none()
        if sess is not None:
            ctx["session_pk"] = sess.id
            ctx["session_id"] = sess.session_id
            ctx["session_pending"] = None
        else:
            # 0턴 세션 미영속(스펙 049, #10): 행 생성을 첫 _persist(실 턴)까지 지연한다. 플레이그라운드를
            # 열고 한 마디도 안 하면 DB에 빈 세션이 안 남는다(#11 정크 뿌리 차단). session_id는 클라가
            # 후속 요청에 참조하므로 지금 *생성만* 해 둔다(commit X). 첫 실 턴에서 lazy-create.
            new_id = "sess-" + secrets.token_hex(16)
            ctx["session_pk"] = None
            ctx["session_id"] = new_id
            ctx["session_pending"] = {
                "session_id": new_id,
                "agent_pk": agent.id,
                "agent_name": agent.name,
                "channel": "playground",
            }
        return ctx


async def resolve_agent_mem_cfg(db, agent) -> dict | None:
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


def _window(messages: list[dict], depth: int | None) -> list[dict]:
    """실행 컨텍스트를 최근 N개로 절단. 0=현재 턴만, 음수/None=전체.
    ([-0:]가 전체가 되는 파이썬 함정 처리)."""
    if depth is None or depth < 0:
        return messages
    if depth == 0:
        return messages[-1:]
    return messages[-depth:]


async def _resolve_session_for_persist(db, ctx: dict) -> Session | None:
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




# 전송 프롬프트 캡처 상한(스펙 131) — 메시지당 자수 캡 + **개수 캡**(codex 131 #3: historyDepth
# 오버라이드로 무제한 히스토리가 trace JSONB에 통째 영속되는 비대 차단).
_SENT_MSG_CHAR_CAP = 2000
_SENT_MSG_COUNT_CAP = 30


def _build_sent_messages(persona_prompt: str, messages: list[dict]) -> list[dict]:
    """전송 프롬프트 전문 캡처(스펙 131) — 실제 그래프 입력(system=persona+회상 포함)을 표시용으로.

    안전장치: (a) 메시지당 자수 캡, (b) 개수 캡(초과분은 생략 표식 1건으로), (c) **비밀 마스킹 백스톱**
    (codex 131 #2 — 페르소나/오버라이드에 사용자가 적은 API 키가 trace JSONB에 복제되지 않게,
    125 _sanitize 재사용). 원문 전문은 저장하지 않는다(캡 절단본)."""
    from .memory import _sanitize as _mask

    out = [{"role": "system", "content": _mask(persona_prompt, cap=_SENT_MSG_CHAR_CAP)}]
    tail = messages[-_SENT_MSG_COUNT_CAP:]
    omitted = len(messages) - len(tail)
    if omitted > 0:
        out.append({"role": "notice", "content": f"(이전 {omitted}개 메시지 생략 — 표시 상한 {_SENT_MSG_COUNT_CAP}개)"})
    out.extend(
        {"role": m["role"], "content": _mask(m["content"] or "", cap=_SENT_MSG_CHAR_CAP)} for m in tail
    )
    return out


def _format_sent_measured(call: list[dict]) -> list[dict]:
    """실측 모델 호출 메시지 → 표시용(스펙 205) — 131과 같은 캡·마스킹. 첫 메시지(system)는 항상
    보존하고 나머지는 꼬리 캡(재구성판과 동일 시맨틱)."""
    from .memory import _sanitize as _mask

    if not call:
        return []
    head, rest = call[0], call[1:]
    out = [{"role": head.get("role", "system"), "content": _mask(head.get("content") or "", cap=_SENT_MSG_CHAR_CAP)}]
    tail = rest[-_SENT_MSG_COUNT_CAP:]
    omitted = len(rest) - len(tail)
    if omitted > 0:
        out.append({"role": "notice", "content": f"(이전 {omitted}개 메시지 생략 — 표시 상한 {_SENT_MSG_COUNT_CAP}개)"})
    out.extend({"role": m.get("role", "?"), "content": _mask(m.get("content") or "", cap=_SENT_MSG_CHAR_CAP)} for m in tail)
    return out


# 트레이스에 기록할 오버라이드 허용 키(스펙 134) — _load_context 병합 allowlist + systemPrompt.
_OVERRIDE_TRACE_KEYS = ("model", "temperature", "historyDepth", "mcps", "memories", "capabilities", "systemPrompt")


def _overrides_trace(overrides: dict | None) -> dict | None:
    """이 턴에 적용된 오버라이드를 트레이스 표시용으로 정화(스펙 134) — 한 세션에 설정이 다른 턴이
    섞여도 턴별로 구분 가능하게 영구 기록. 값 정화는 131 프레임 재사용: 문자열=비밀 마스킹+캡 300,
    리스트=항목별 캡 100·개수 20, 숫자 통과. 실제 온 허용 키만 — 없으면 None(필드 미기록=무회귀)."""
    if not isinstance(overrides, dict):
        return None
    from .memory import _sanitize

    out: dict = {}
    for k in _OVERRIDE_TRACE_KEYS:
        if k not in overrides or overrides[k] is None:
            continue
        v = overrides[k]
        if isinstance(v, str):
            # systemPrompt는 _load_context가 **비어있지 않을 때만 적용**(빈/공백은 무시) — 트레이스도
            # 같은 가드를 미러(적용 안 된 값을 "적용됨"으로 기록 금지, codex 134 #1).
            if k == "systemPrompt" and not v.strip():
                continue
            out[k] = _sanitize(v, cap=300)
        elif isinstance(v, (int, float, bool)):
            out[k] = v
        elif isinstance(v, list):
            out[k] = [_sanitize(str(it), cap=100) for it in v[:20]]
    return out or None


def _broker_calls_trace(invocations: list[dict]) -> list[dict]:
    """브로커 호출 이력 → 트레이스 표시용 투영(스펙 130) — **키 화이트리스트 단일 출처**(메인/승인대기/
    재개 세 경로 공유, drift 0). 본문·args 불포함(087/092 원문 누출 0 유지)."""
    return [
        {k: v for k, v in inv.items() if k in ("node", "cap_id", "ms", "hits", "topScore", "error", "resultPreview", "hitsDetail", "minScore", "query", "local", "subTraceNodes")}
        for inv in invocations
    ]


async def _persist(
    ctx: dict, user_text: str, reply: str, trace: dict, tokens: dict, store_messages: bool,
    user_id: str | None = None,
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
            db.add(Message(session_pk=session_pk, role="user", content=user_text))
            am = Message(session_pk=session_pk, role="assistant", content=reply, trace=trace)
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
    return f"event: message_id\ndata: {json.dumps({'id': mid}, ensure_ascii=False)}\n\n" if mid else ""


# 연결-실패로 보이는 에러의 지문(httpx/openai/asyncpg 계층 공통). model_id 불일치(404 등)나
# 인증 오류(401)는 *연결*이 아니므로 힌트를 붙이지 않는다 — 잘못된 안내가 더 혼란스럽다.
_CONN_ERR_MARKERS = (
    "connection error",
    "connection refused",
    "cannot connect",
    "all connection attempts failed",
    "connect call failed",
    "errno 61",
    "name or service not known",
    "timed out",
    "timeout",
    "apiconnectionerror",
    "connecterror",
    "max retries exceeded",
)


def _model_error_hint(exc: Exception, model_cfg: dict | None) -> str | None:
    """모델 연결 실패로 보이면 전환 힌트(없으면 None). 스펙 058 G4 — 기본 chat은 무외부 'Mock LLM'
    (스펙 059)이라 곧장 실패하지 않는다. 이 힌트는 운영자가 Provider UI로 추가한 실 모델을 기본으로
    전환했는데 그 서버가 안 떠 있을 때 첫 채팅이 연결 실패하는 경우를 위한 것이다."""
    if not model_cfg:
        return None
    blob = f"{type(exc).__name__} {exc}".lower()
    if not any(m in blob for m in _CONN_ERR_MARKERS):
        return None
    base_url = model_cfg.get("base_url", "")
    return (
        f"채팅 모델 연결 실패 (base_url={base_url}) — 모델 서버가 떠 있는지/주소가 맞는지 확인하세요. "
        "외부 모델 없이 바로 시험하려면 admin에서 기본 채팅 모델을 'Mock LLM'으로 되돌리세요"
        "(무외부 동작, 기본값)."
    )


def _card_streaming(card: object) -> bool:
    """카드 capabilities.streaming. 없으면 True(message/stream 우선, 안 되면 에이전트가 단건 응답)."""
    if isinstance(card, dict):
        caps = card.get("capabilities")
        if isinstance(caps, dict) and "streaming" in caps:
            return bool(caps.get("streaming"))
    return True


async def _a2a_stream(ctx: dict, user_text: str, user_id: str | None):
    """원격(A2A) 에이전트: 등록된 카드 url로 JSON-RPC message/stream 호출 → 응답을 우리 SSE로 재전송.

    code(우리가 배포한 SDK)·external(제3자) 모두 이 경로를 탄다(스펙 057: A2A 단일화). 전송은
    a2a_client 계층이 담당(JSON-RPC message/stream|send).
    """
    yield f"data: {json.dumps({'session': ctx['session_id']}, ensure_ascii=False)}\n\n"
    endpoint = ctx.get("endpoint")
    if not endpoint:
        yield f"data: {json.dumps({'error': '외부 에이전트에 A2A 엔드포인트(url)가 없습니다'}, ensure_ascii=False)}\n\n"
        yield "event: done\ndata: [DONE]\n\n"
        return

    streaming = _card_streaming(ctx.get("card"))
    acc: list[str] = []
    errored = False
    t0 = time.perf_counter()
    # 세션 id를 A2A contextId로 — 호출당 단일 메시지지만 서버가 맥락을 잇게 한다(스펙 057, 멀티턴 보존).
    async for frame in a2a_client.a2a_stream(
        endpoint, ctx.get("token"), user_text, streaming=streaming, context_id=ctx.get("session_id")
    ):
        if "error" in frame:
            errored = True
            msg = frame["error"]
            # 텍스트가 한 줄도 안 온 채 에러로 끝나면(엔드포인트 미도달 류) raw 코드만 보여주지 않고
            # 행동가능 안내를 덧붙인다(스펙 081 P2). 부분 스트림 뒤 에러엔 미부가 — 그땐 도달은 됐다.
            if not acc:
                msg = f"{msg} — 엔드포인트에 도달하지 못했습니다. 재동기화(자가치유) 또는 재연결을 시도하세요."
            yield f"data: {json.dumps({'error': msg}, ensure_ascii=False)}\n\n"
        elif frame.get("text"):
            acc.append(frame["text"])
            yield f"data: {json.dumps({'text': frame['text']}, ensure_ascii=False)}\n\n"

    full = "".join(acc)
    total_ms = int((time.perf_counter() - t0) * 1000)
    tokens = runtime.estimate_tokens(len(user_text), len(full))
    trace = {
        "latencyMs": total_ms,
        "tokens": tokens,
        "promptRef": ctx["ext_agent_id"],
        "memories": [],
        "mcp": [],
        "graph": [
            {"node": "__start__", "ms": 0},
            {"node": "a2a_call", "ms": total_ms},
            {"node": "__end__", "ms": 0},
        ],
        "remote": True,
        "a2a": True,
    }
    if not errored and full.strip():  # 공백-only 응답은 영속하지 않음(적대리뷰 L1)
        mid = await _persist(
            ctx, user_text, full, trace, tokens, ctx["persist_history"],
            user_id=user_id,
        )
        yield _mid_frame(mid)  # 스펙 209 P1.5 — 피드백 부착용 assistant id
    yield f"event: trace\ndata: {json.dumps(trace, ensure_ascii=False)}\n\n"
    yield "event: done\ndata: [DONE]\n\n"


async def stream_local_reply(agent_id: uuid.UUID, user_text: str):
    """로컬(ui) 에이전트를 **A2A 서빙용**으로 실행 — 텍스트 청크만 yield(스펙 061).

    a2a_server가 노출된 로컬 에이전트의 JSON-RPC 호출을 받아 실 LangGraph 런타임을 돌릴 때 쓴다.
    기존 chat() 경로는 건드리지 않는다(핵심 채팅 무회귀) — _load_context·build_agent·astream만 재사용.
    v1 단순화(스펙 061 §6, 범위 밖): persist·HIL 승인 게이트·자동 memory-add·세션 영속 미적용
    (노출 런타임=순수 컴퓨트; 영속은 호출측 _a2a_stream이 자기 external 세션에 한다). 위험 도구는
    checkpointer=None이라 fail-closed(승인 게이트가 노출 경로엔 없음 — interrupt가 예외로 떨어짐).
    code/external 소스·모델 미해석이면 ValueError(로컬 그래프 아님 → 라우터가 4xx).
    """
    ctx = await _load_context(agent_id, None)
    try:
        impl = resolve_agent_runtime(ctx)
    except AgentConfigError as e:
        # 선언한 in-process 구현 미해결(스펙 089) — 노출 서빙 거부(default 만회 없음, 라우터가 4xx).
        # 구체 impl 키는 서버 로그에만(089-F1: 임의 저장값이라 응답에 미반영 — 비밀누출 0).
        log.warning("A2A 노출 거부: 미해결 impl %r (agent %s)", str(e), agent_id)
        raise ValueError("에이전트 설정 실패: 런타임 구현 미해결(A2A 노출 불가)") from e
    if impl is None or ctx["model_cfg"] is None:
        raise ValueError("로컬(ui) 에이전트가 아니거나 채팅 모델이 없습니다(A2A 노출 불가)")
    calls_sink: list[dict] = []
    tools = await runtime.build_mcp_tools(ctx["mcp_servers"], calls_sink, ctx.get("toolPolicy"))
    if ctx["rag_collections"]:
        tools.append(runtime.build_rag_tool(ctx["rag_collections"], calls_sink, ctx.get("rag_min_scores")))
    run_params = {} if ctx["temperature"] is None else {"temperature": ctx["temperature"]}
    build_ctx = AgentBuildContext(
        persona=ctx["persona"],
        model_cfg=ctx["model_cfg"],
        tools=tools,
        checkpointer=None,
        params=run_params,
        overrides=ctx.get("overrides"),
    )
    graph = impl.build_graph(build_ctx)
    # 노출 호출은 호출당 단일 메시지(맥락은 A2A contextId가 호출측 책임 — v1 서빙은 무상태).
    messages = _window([{"role": "user", "content": user_text}], ctx["history_depth"])
    # 관측(스펙 118) — checkpointer=None이라 thread_id 불요, 콜백만 병합(미설정=무동작).
    _cfg = observability.with_trace(None, name="a2a-serve-local")
    async for msg_chunk, _meta in graph.astream(
        {"messages": messages}, config=_cfg, stream_mode="messages"
    ):
        # A2A 서빙도 도구 원본 응답은 외부 소비자에게 노출 않음(스펙 092, 본문 sink와 동일 술어).
        if runtime.is_tool_message(msg_chunk):
            continue
        # content-block 리스트 → str 정규화(본문 sink와 동일, 092 codex P1).
        text = runtime._content_text(getattr(msg_chunk, "content", ""))
        if text:
            yield text


@router.post("/{agent_id}/chat")
async def chat(agent_id: uuid.UUID, body: ChatRequest, principal=Depends(current_principal)):
    # 스펙 068: resume 바인딩에 067과 *동일한* 소유자 스코프를 주입(단일 출처 _own_scope 재사용).
    # 비-admin이 타인/추측 session_id를 줘도 매칭 실패 → 새 세션(열거 오라클·소유권 탈취 봉인).
    own = _own_scope(principal)
    # 사용 게이트(스펙 147): private 에이전트는 소유자·특권만 — 목록에서 안 보이는 존재이므로
    # 404-fold(068 — 403으로 존재를 알려주지 않는다).
    from .models import Agent as _AgentRow
    from .ownership import may_use_agent
    async with SessionLocal() as _s:
        _arow = await _s.get(_AgentRow, agent_id)
    if _arow is None or not may_use_agent(_arow, principal):
        raise HTTPException(status_code=404, detail="agent not found")
    req_version = body.version
    if req_version is not None:
        # 버전 지정 실행은 관리 권한(codex 242 #2) — 초안은 미공개 작업본이라 "사용 권한만" 있는
        # 유저의 미리보기는 누출. 버전 목록 자체는 상세에 보이므로 403 명시(404-fold 불요).
        from .ownership import may_manage as _may_manage

        if not _may_manage(_arow, principal):
            raise HTTPException(status_code=403, detail="버전 지정 실행은 이 에이전트를 관리할 수 있어야 합니다")
    elif body.sessionId:
        # ask/form 재개 턴의 버전 승계(codex 242 #1) — 미리보기 턴이 만든 pending(체크포인트)은 그
        # 버전 config로만 재개해야 한다(활성 config로 재개하면 drift). 클라이언트가 재개 턴에 version을
        # 안 보내도 서버가 pending에 저장해 둔 버전을 이어받는다.
        _pend = _PENDING_ARTIFACT.get(body.sessionId)
        if _pend and _pend.get("version"):
            req_version = _pend["version"]
    ctx = await _load_context(agent_id, body.sessionId, body.overrides, own=own, version=req_version)
    user_text = body.messages[-1].content if body.messages else ""

    # mem0 user_id 축 = 인증 주체에서 도출(스펙 032). 쿠키 유저면 안정 UUID(str(user.id)),
    # 머신 토큰("machine" 센티넬)이면 None → 세션 단기 폴백(기존 "빈 userId" 동작과 동일, 무회귀).
    user_id = None if isinstance(principal, str) else str(principal.id)

    # 코드(SDK)·외부(A2A) 에이전트 모두 비로컬 — 등록된 카드 url로 A2A 런타임 호출(스펙 057: A2A 단일화).
    # code=우리가 SDK로 배포한 A2A(provenance 메타 보유), external=제3자 A2A. 전송은 _a2a_stream 하나.
    # (구 _remote_stream 자체 SSE·code 분기는 057에서 폐기 — 플랫폼 전제대로 SDK도 A2A를 말한다.)
    # in-process 런타임 구현 해석(스펙 085). None이면 원격(A2A 불투명) → 기존 fallback 그대로.
    # 선언한 impl이 미해결이면 AgentConfigError(스펙 089 교정3) → default로 만회 않고 설정 실패 통보.
    try:
        impl = resolve_agent_runtime(ctx)
    except AgentConfigError as e:
        return StreamingResponse(
            _config_error_stream(str(e)), media_type="text/event-stream"
        )
    if impl is None:
        return StreamingResponse(
            _a2a_stream(ctx, user_text, user_id), media_type="text/event-stream"
        )

    # 메모리 스코프(다층 — 스펙 020/029). 회상(search)과 자동 쓰기(add)는 **축이 다르다**:
    # - recall_scope: user_id(세션 가로지름)+run_id(세션 단기)+agent_id(에이전트 전용 — 스펙 029).
    #   search는 축별로 따로 검색해 합집합 병합(mem0 필터는 AND이므로 — memory.py 참고).
    # - add_scope: user_id+run_id만. **agent_id는 자동 add에 절대 태깅하지 않는다** — 유저 턴
    #   자동추출이 agent_id로 새면 user A의 사적 사실이 다른 유저에게 회상된다(스펙 020 누출 차단).
    #   agent_id 쓰기는 **관리자 저작(agents.py CRUD)으로만** — 채팅 자가기록은 제거됨(스펙 051).
    add_scope = {"user_id": user_id, "run_id": ctx["session_id"]}
    recall_scope = {**add_scope, "agent_id": ctx["ext_agent_id"]}

    # 의미론적 메모리 회상 (켠 에이전트 + 등록 임베딩 모델 있을 때만). mem0는 동기 → 스레드로.
    # 스펙 233 발견 봉합: 회상은 impl 실행 전 플랫폼 선처리라 impl의 consumes를 무시했다 — 편집 폼은
    # "이 실행 방식은 기억을 무시합니다"라 경고하는데(스펙 206) 런타임은 회상해 **거짓 표시**였다.
    # 사용자 결정(타입별 게이트): impl이 "memories" 표면을 consumes로 선언했을 때만 회상·자동기록.
    # consumes=None(미선언)은 게이트 안 함(스펙 206 "폼 전부 노출" 계약과 정합 — 무회귀).
    _impl_consumes = impl.describe().consumes
    _impl_reads_memory = _impl_consumes is None or "memories" in _impl_consumes
    used_memory = (
        not ctx.get("ephemeral")  # 비영속(스펙 235): 회상·자동기록 전면 off(stateless)
        and _impl_reads_memory
        and memory.memory_enabled(ctx["memories"])
        and ctx["mem_cfg"] is not None
    )
    mem_hits = (
        await asyncio.to_thread(memory.search, recall_scope, user_text, ctx["mem_cfg"])
        if used_memory
        else []
    )

    calls_sink: list[dict] = []
    tools = await runtime.build_mcp_tools(ctx["mcp_servers"], calls_sink, ctx.get("toolPolicy"))
    # 채팅 자가기록 도구는 제거됨(스펙 051) — agent_id 메모리는 어드민 저작 전용. 회상은 아래 유지.
    # RAG 검색 도구 — vectorTables가 실 컬렉션으로 해석됐을 때만 주입(스펙 037). mem0 비종속.
    if ctx["rag_collections"]:
        tools.append(runtime.build_rag_tool(ctx["rag_collections"], calls_sink, ctx.get("rag_min_scores")))

    # 회상된 기억은 persona(시스템 프롬프트)에 합친다. 별도 system 메시지로 주입하면
    # create_agent의 system_prompt와 충돌해 모델 채팅 템플릿이 거부한다
    # ("System message must be at the beginning"). 단일 system 프롬프트 유지.
    persona_prompt = ctx["persona"]
    if mem_hits:
        # 브로커 memory 능력과 공유하는 포맷(스펙 104 drift 0) — 회상 텍스트 표현이 한 곳.
        recalled = memory.format_memory_hits(mem_hits)
        persona_prompt = f"{persona_prompt}\n\n# 관련 기억(회상됨)\n{recalled}"
    run_params = {} if ctx["temperature"] is None else {"temperature": ctx["temperature"]}
    # HIL 체크포인터(스펙 041). 있으면 위험 도구가 interrupt로 일시정지·재개될 수 있다. 없으면
    # 기존 무상태 동작(무회귀) — 단 위험 도구가 호출되면 interrupt가 예외로 새 fail-closed(미실행).
    # 비영속(스펙 235): 체크포인터 미부착 → 그래프 무상태 실행(checkpoints/checkpoint_writes/blobs
    # 테이블 미기록). **정정(스펙 237 실측)**: 체크포인터가 없어도 interrupt 자체는 발생한다 — 승인
    # 경로의 DB 쓰기는 아래 interrupted 분기의 ephemeral 게이트가 막는다(여기만으론 불충분).
    ckpt = None if ctx.get("ephemeral") else checkpointer.get_checkpointer()
    # 능력 브로커(스펙 100) — 정책(에이전트 allowlist ∩ 유저 RBAC)으로 **미리 스코프**해 주입.
    # 로컬(ui) 실행 경로에만 준다: 원격 통째 프록시(_a2a_stream)는 broker 미주입(bypass 보존).
    # broker를 쓰는 flow(예: orchestrate)만 소비하고, 안 쓰면 무해(deny-by-default).
    build_broker_scoped = build_broker(principal, ctx["capabilities"], ctx.get("toolPolicy"), ctx.get("rag_min_scores"))
    build_ctx = AgentBuildContext(
        persona=persona_prompt,
        model_cfg=ctx["model_cfg"],
        tools=tools,
        checkpointer=ckpt,
        params=run_params,
        memories=mem_hits,
        overrides=ctx.get("overrides"),
        broker=build_broker_scoped,
        impl_config=ctx.get("artifact_spec"),  # 스펙 190 — 노코드 산출물형 필드 명세 주입(그 외 impl은 무시)
    )
    graph = impl.build_graph(build_ctx)
    # thread_id는 **턴별 고유**(세션-안정 아님): 세션-안정으로 두고 매 턴 전체 히스토리를 넘기면
    # 체크포인트의 add_messages 리듀서가 메시지를 중복 누적한다(무상태 윈도잉과 충돌). 턴마다 새
    # thread를 만들어 그 턴의 일시정지/재개에만 쓰고, Approval.checkpoint에 박아 재개 키로 삼는다.
    # 산출물형 ask/form 대기(스펙 188)면 **그 thread를 이어** Command(resume=union 봉투)로 재개한다
    # (새 실행 금지 — produce의 기록된 답 리플레이가 그 체크포인트에 있다). pop = 재개 시도는 1회.
    # 이중 입력 일급: 폼 대기 중이라도 텍스트가 오면 {"type":"text"}로 재개(병합은 뼈대 ctx.form 소유).
    pending_artifact = _PENDING_ARTIFACT.pop(ctx["session_id"], None)
    if body.form is not None and (
        pending_artifact is None or body.form.formId != pending_artifact.get("form_id")
    ):
        # 폼 제출인데 대응 pending이 없거나 formId 불일치(스테일/위조/재시작 소실) — 조용히 텍스트로
        # 오인하지 않고 명시적으로 거절(fail-closed). pending은 원복(유효한 폼이 남아 있으면 재사용).
        if pending_artifact is not None:
            _PENDING_ARTIFACT[ctx["session_id"]] = pending_artifact
        raise HTTPException(status_code=409, detail="폼이 만료되었거나 일치하지 않습니다 — 다시 시도해 주세요.")
    if pending_artifact:
        thread_id = pending_artifact["thread_id"]
        if body.form is not None and pending_artifact.get("kind") == "form":
            # 서버측 1차 검증(값∈후보·알려진 key만) — 뼈대 ctx.form이 같은 함수로 재검증(이중 게이트).
            from agent.flows.artifact import validate_form_values

            vals = validate_form_values(pending_artifact.get("fields") or [], body.form.values)
            graph_input = Command(resume={"type": "form", "values": vals})
        else:
            graph_input = Command(resume={"type": "text", "message": user_text})
    else:
        thread_id = f"{ctx['ext_agent_id']}:{ctx['session_id']}:{secrets.token_hex(4)}"
        graph_input = None  # 아래에서 {"messages": messages}로 채움(messages는 이후 계산)
    config = {"configurable": {"thread_id": thread_id}}
    # 관측(스펙 118) — Langfuse가 설정됐을 때만 콜백 부착(미설정=무동작). 핵심 채팅 경로 무영향.
    # 비영속(스펙 235): 외부 관측 기록도 스킵(고트래픽·기록 무의미 계약 — 앱 DB 밖이라도 적재 안 함).
    if not ctx.get("ephemeral"):
        config = observability.with_trace(
            config, name=f"chat:{ctx['ext_agent_id']}", session_id=ctx["session_id"], user_id=user_id
        )
    # 실측 캡처(스펙 205) — 모델 호출 메시지·usage. Langfuse 콜백과 병행(둘 다 callbacks 리스트).
    capture = trace_capture.TraceCaptureHandler()
    config["callbacks"] = list(config.get("callbacks") or []) + [capture]

    # 실행 컨텍스트를 historyDepth로 절단(최근 N개만 모델에 전달).
    messages = _window(
        [{"role": m.role, "content": m.content} for m in body.messages], ctx["history_depth"]
    )
    # 전송 프롬프트 전문(스펙 131) — 실제 그래프 입력을 캡·마스킹해 캡처(_build_sent_messages).
    # 조율형의 synthesize 내부 데이터 채널 재조립은 delegated 노드 값(131 #3)으로 관측. 재개 턴은
    # 체크포인트 내부 재개라 조립본이 여기 없음 — N/A(스펙 131 경계).
    sent_messages = _build_sent_messages(persona_prompt, messages)

    async def event_stream():
        t0 = time.perf_counter()
        yield f"data: {json.dumps({'session': ctx['session_id']}, ensure_ascii=False)}\n\n"
        acc: list[str] = []
        errored = False
        interrupts: list[dict] = []
        # updates 발화 레코드 [{node, ms(실측), summary}] — 스펙 085(노드열) + 086(실측·요약).
        observed: list[dict] = []
        t_prev = t0
        try:
            # 멀티 stream_mode: "messages"=토큰 스트림(기존), "updates"=노드 업데이트에서 __interrupt__
            # 감지(위험 도구가 그래프를 멈춘 신호). probe로 검증한 형태. 한 업데이트가 다중 interrupt를
            # 담을 수 있어(한 턴에 위험 도구 여러 개) 모두 모은다 — [0]만 보면 나머지가 조용히 샌다.
            async for stream_mode, chunk in graph.astream(
                graph_input if graph_input is not None else {"messages": messages},
                config=config, stream_mode=["messages", "updates"]
            ):
                if stream_mode == "messages":
                    msg_chunk, _meta = chunk
                    # 도구 원본 응답(ToolMessage)은 본문서 제외 — 표시·영속(acc)·메모리·토큰 일괄 정화
                    # (스펙 092). 도구 호출은 인스펙터 trace(calls_sink)에 독립 보존(args·타이밍·상태+
                    # 결과요약; MCP는 2000자 캡, RAG는 건수 — 092 codex P2로 정정). 본문 숨김이 사용자 요청.
                    if runtime.is_tool_message(msg_chunk):
                        continue
                    # content는 str이 아니라 content-block 리스트일 수 있다(AIMessageChunk) →
                    # _content_text로 str 보장. 안 하면 acc 합치기(`"".join`)서 TypeError(092 codex P1).
                    text = runtime._content_text(getattr(msg_chunk, "content", ""))
                    if text:
                        acc.append(text)
                        yield f"data: {json.dumps({'text': text}, ensure_ascii=False)}\n\n"
                elif stream_mode == "updates" and isinstance(chunk, dict):
                    if "__interrupt__" in chunk:
                        interrupts.extend(i.value for i in chunk["__interrupt__"])
                    # 실 노드 발화 누적(하드코딩 아님). __로 시작하는 내부 채널(__interrupt__ 등) 제외.
                    # ms=직전 update 이후 경과(직렬 그래프=노드별 실측, 스펙 086 ①), summary=안전 요약
                    # (키기반 redaction + raw 캡, 086 ②). 같은 노드 재발화는 별도 레코드(재진입 보존).
                    now = time.perf_counter()
                    ms = int((now - t_prev) * 1000)
                    fired = [(n, d) for n, d in chunk.items() if not n.startswith("__")]
                    # 한 청크에 노드 2+ = 병렬 superstep → 공유 ms를 노드별 실측처럼 과장 말라(F4).
                    is_parallel = len(fired) > 1
                    for node, delta in fired:
                        rec = {
                            "node": node,
                            "ms": ms,
                            "summary": runtime._summarize_node_update(node, delta),
                        }
                        if is_parallel:
                            rec["parallel"] = True
                        observed.append(rec)
                        # 산출물형(스펙 188): produce가 커밋한 artifact를 프레임으로 노출. 요약
                        # 텍스트(AIMessage)는 "messages" 스트림이 이미 흘린다(노드 반환 메시지도
                        # 스트림됨 — 실측) → 여기선 artifact 프레임만(중복 방지). 타 에이전트 무영향.
                        if isinstance(delta, dict) and delta.get("artifact"):
                            yield f"data: {json.dumps({'artifact': delta['artifact']}, ensure_ascii=False)}\n\n"
                    if fired:
                        t_prev = now
        except Exception as exc:  # 모델/툴 오류도 프레임으로 전달
            errored = True
            # 산출물형 재개 중 크래시면 pending을 **원복**한다(적대 검증 P1-3). pop은 재개 진입 시
            # 1회였고(라인 787), 체크포인트(interrupt 상태)는 재개 실패로 그대로 남아 있으므로,
            # 포인터를 되살려야 다음 요청이 같은 thread로 재시도할 수 있다(안 하면 in-flight 폼/질문이
            # 고아가 돼 새 스레드로 시작 — 진행 소실). 새 interrupt를 낸 정상 경로는 이 except에 안 옴.
            if pending_artifact is not None:
                _PENDING_ARTIFACT[ctx["session_id"]] = pending_artifact
            # 연결 실패로 보이면 'Mock LLM' 전환 힌트를 덧붙인다(스펙 058 G4). 그 외 오류는 원문 유지.
            hint = _model_error_hint(exc, ctx.get("model_cfg"))
            msg = f"{exc}\n{hint}" if hint else str(exc)
            yield f"data: {json.dumps({'error': msg}, ensure_ascii=False)}\n\n"

        # 한 턴에 위험 도구가 둘 이상 호출되면(다중 pending interrupt) 현재 재개 프로토콜은 **단일
        # interrupt만** 지원한다 — Command(resume=)에 interrupt id를 안 주므로 langgraph가 "must
        # specify interrupt id"로 실패하고, except가 삼켜 status=approved인데 도구는 영영 미실행으로
        # 멈춘다(적대 검증 Finding 1). 다중을 무시하고 하나만 Approval로 만들면 오도하는 approved row가
        # 남는다. 그래서 다중은 **승인 row를 만들지 않고** 명시적 에러로 닫는다(fail-closed·정직:
        # 부수효과 미실행 유지). 사용자는 한 번에 하나씩 재시도. 다중 동시 게이트는 §7 빚.
        if len(interrupts) > 1 and not errored:
            yield f"data: {json.dumps({'error': '한 턴에 승인이 필요한 위험 도구가 둘 이상 호출되었습니다. 하나씩 다시 시도해 주세요.'}, ensure_ascii=False)}\n\n"
            yield "event: done\ndata: [DONE]\n\n"
            return

        interrupted = interrupts[0] if interrupts else None
        # 산출물형 ask(스펙 188) — kind로 엄격 게이트(승인 interrupt에는 kind가 없음 → 기존 경로
        # 무접촉). 질문을 텍스트 프레임으로 내보내고, 이 thread를 세션 pending에 등록해 다음 사용자
        # 입력이 Command(resume=)로 재개하게 한다. ask 턴은 정상 대화 교환 — 질문을 assistant
        # 메시지로 영속(승인 턴의 "영속 안 함"과 다름: 질문·답이 대화 이력에 남아야 한다).
        if interrupted and not errored and interrupted.get("kind") == "ask":
            question = str(interrupted.get("text") or "").strip() or "(질문)"
            _PENDING_ARTIFACT[ctx["session_id"]] = {"thread_id": thread_id, "version": ctx.get("pinned_version")}
            yield f"data: {json.dumps({'text': question}, ensure_ascii=False)}\n\n"
            ask_tokens = runtime.estimate_tokens(
                sum(len(m["content"]) for m in messages), len(question)
            )
            ask_trace = {
                "latencyMs": int((time.perf_counter() - t0) * 1000),
                "tokens": ask_tokens, "promptRef": ctx["ext_agent_id"],
                "memories": mem_hits, "mcp": calls_sink, "graph": observed,
                "artifact": {"awaiting": "ask"},
                **({"agentVersion": ctx["exec_version"], **({"versionPinned": True} if ctx.get("pinned_version") else {})} if ctx.get("exec_version") else {}),  # 인스펙터: 산출물 진행 중 표기
                "sentMessages": sent_messages,
            }
            if not errored:
                mid = await _persist(
                    ctx, user_text, question, ask_trace, ask_tokens, ctx["persist_history"],
                    user_id=user_id,
                )
                yield _mid_frame(mid)  # 스펙 209 P1.5
            yield f"event: trace\ndata: {json.dumps(ask_trace, ensure_ascii=False)}\n\n"
            yield "event: done\ndata: [DONE]\n\n"
            return

        # 산출물형 form(스펙 188 P2) — 승인 프레임의 일반화. 필드 명세+프리필을 프레임으로 내보내고
        # pending에 (thread, formId, fields)를 등록: 제출(body.form)이든 텍스트든 다음 입력이 재개한다.
        if interrupted and not errored and interrupted.get("kind") == "form":
            form_id = "frm-" + secrets.token_hex(4)
            form_fields = interrupted.get("fields") or []
            _PENDING_ARTIFACT[ctx["session_id"]] = {
                "thread_id": thread_id, "kind": "form", "form_id": form_id, "fields": form_fields,
                "version": ctx.get("pinned_version"),  # 재개 턴 버전 승계(codex 242 #1)
            }
            form_frame = {
                "form": {
                    "fields": form_fields,
                    "prefill": interrupted.get("prefill") or {},
                    **({"note": interrupted["note"]} if interrupted.get("note") else {}),
                },
                "formId": form_id,
            }
            # 이력에는 폼 요약 한 줄(프레임 자체는 휘발) — 질문·답 흐름이 대화 기록에 남게.
            # 라이브 버블에도 같은 텍스트를 흘린다(세션 재로드 표시와 일치 — 빈 버블 방지).
            form_msg = "📋 입력이 필요합니다: " + ", ".join(
                str(f.get("label") or f.get("key") or "?") for f in form_fields
            )
            yield f"data: {json.dumps({'text': form_msg}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps(form_frame, ensure_ascii=False)}\n\n"
            form_tokens = runtime.estimate_tokens(
                sum(len(m["content"]) for m in messages), len(form_msg)
            )
            form_trace = {
                "latencyMs": int((time.perf_counter() - t0) * 1000),
                "tokens": form_tokens, "promptRef": ctx["ext_agent_id"],
                "memories": mem_hits, "mcp": calls_sink, "graph": observed,
                "artifact": {"awaiting": "form", "formId": form_id},
                **({"agentVersion": ctx["exec_version"], **({"versionPinned": True} if ctx.get("pinned_version") else {})} if ctx.get("exec_version") else {}),
                "sentMessages": sent_messages,
            }
            if not errored:
                mid = await _persist(
                    ctx, user_text, form_msg, form_trace, form_tokens, ctx["persist_history"],
                    user_id=user_id,
                )
                yield _mid_frame(mid)  # 스펙 209 P1.5
            yield f"event: trace\ndata: {json.dumps(form_trace, ensure_ascii=False)}\n\n"
            yield "event: done\ndata: [DONE]\n\n"
            return

        # 위험 도구가 그래프를 멈췄다 → 런타임 Approval 생성 + "대기" 프레임 후 종료(정상 턴 영속 안 함).
        # 부수효과(canned·calls_sink)는 interrupt 이전이라 0 — 승인 전 무실행 불변식(스펙 041 §3.3).
        if interrupted and not errored:
            if ctx.get("pinned_version"):
                # 버전 미리보기(스펙 242) — 승인 재개는 서빙 config로 돌아 버전이 어긋난다(drift).
                # Approval을 만들지 않고 명시 안내(235 비영속 게이트와 동형). 도구는 interrupt 이전이라 미실행.
                yield f"data: {json.dumps({'error': '버전 미리보기에서는 승인이 필요한 도구를 사용할 수 없습니다 — 활성 버전에서 실행하거나 승인 없는 도구를 사용하세요.'}, ensure_ascii=False)}\n\n"
                yield "event: done\ndata: [DONE]\n\n"
                return
            if ctx.get("ephemeral"):
                # 비영속(스펙 237) — 승인 대기는 만들 수 없다: _create_approval이 세션+Approval 행을
                # 쓰고(235 "쓰기 0" 위반), 체크포인터도 없어 재개 불가. **실측 주의**: 체크포인터가
                # None이어도 interrupt 자체는 발생해 여기 도달한다(235의 "구조적 미도달" 가정은 틀렸다
                # — 이 게이트가 실제 봉합). 도구는 interrupt 이전이라 미실행(부수효과 0). 조용한 실패
                # 대신 명시 안내(회고 214).
                yield f"data: {json.dumps({'error': '비영속(1회성) 에이전트는 승인이 필요한 도구를 사용할 수 없습니다 — 승인·재개에는 기록(DB)이 필요합니다. 승인 없는 도구를 쓰거나 일반 에이전트를 사용하세요.'}, ensure_ascii=False)}\n\n"
                yield "event: done\ndata: [DONE]\n\n"
                return
            apid = await _create_approval(ctx, thread_id, interrupted, user_id)
            action = interrupted.get("action", "(작업)")
            # approver 반영(스펙 180) — self면 요청자 본인이 승인. 하드코딩 "관리자 승인"은 오표기였다.
            approver = interrupted.get("approver")
            kind_label = "본인 승인" if approver == "self" else "관리자 승인"
            wait_msg = f"⏸ 승인 대기: {action} — {kind_label}이 필요합니다. (승인 큐 {apid})"
            yield f"data: {json.dumps({'text': wait_msg, 'approval': apid, 'approver': approver}, ensure_ascii=False)}\n\n"
            pending_trace = {
                "latencyMs": int((time.perf_counter() - t0) * 1000),
                "tokens": {"in": 0, "out": 0}, "promptRef": ctx["ext_agent_id"],
                "memories": mem_hits, "mcp": calls_sink, "graph": [],
                "approval": {"id": apid, "action": action, "status": "pending"},
                **({"agentVersion": ctx["exec_version"]} if ctx.get("exec_version") else {}),
            }
            # 승인대기 턴도 회상 조회 이력 일관 노출(스펙 079).
            if used_memory:
                pending_trace["memoryQuery"] = user_text[:300]
            if build_broker_scoped.invocations:
                # 일시정지 **이전에 이미 실행된** 선행 브로커 호출 표면화(스펙 130, codex #2).
                pending_trace["brokerCalls"] = _broker_calls_trace(build_broker_scoped.invocations)
            pending_trace["sentMessages"] = sent_messages  # 승인대기 턴도 전송 전문(스펙 131)
            ov_trace_p = _overrides_trace(ctx.get("overrides"))
            if ov_trace_p:
                pending_trace["overrides"] = ov_trace_p  # 스펙 134
            if ctx["rag_collections"]:
                pending_trace["ragCollections"] = [c["name"] for c in ctx["rag_collections"]]
            yield f"event: trace\ndata: {json.dumps(pending_trace, ensure_ascii=False)}\n\n"
            yield "event: done\ndata: [DONE]\n\n"
            return

        # 브로커 서브스텝 호출을 관측 타임라인에 합류(스펙 100/101 설계결정 7 — broker.invoke가
        # invisible하지 않게). delegate 노드 update와 별개로 cap별 broker_invoke:<kind>:<...> 노드를
        # 남긴다(A2A는 broker_invoke:agent:*, MCP는 broker_invoke:mcp:<server>/<tool>). 위임이 없던
        # 턴은 invocations가 비어 무영향(무회귀).
        for inv in build_broker_scoped.invocations:
            observed.append({"node": inv["node"], "ms": inv.get("ms", 0)})

        full = "".join(acc)
        total_ms = int((time.perf_counter() - t0) * 1000)
        prompt_chars = sum(len(m["content"]) for m in messages)
        # 토큰(스펙 205): 모델 usage 실측 우선, 부재 시 추정 폴백(estimated로 정직 표기).
        if capture.usage_seen:
            tokens = {"in": capture.tokens_in, "out": capture.tokens_out, "estimated": False}
        else:
            tokens = {**runtime.estimate_tokens(prompt_chars, len(full)), "estimated": True}
        trace = runtime.assemble_trace(
            agent_id=ctx["ext_agent_id"],
            memories=mem_hits,
            mcp_calls=calls_sink,
            used_memory=used_memory,
            total_ms=total_ms,
            tokens=tokens,
            graph_observations=observed,
        )
        trace["contextMessages"] = len(messages)  # 모델에 넣은 메시지 수(historyDepth 적용 결과)
        if ctx.get("exec_version"):
            # 실행 버전(스펙 242) — 이 턴이 어느 버전 config였나(지정 버전 미리보기 포함, 240 평가 귀속과 대칭).
            trace["agentVersion"] = ctx["exec_version"]
            if ctx.get("pinned_version"):
                trace["versionPinned"] = True  # 미리보기 턴 표식(활성 아님)
        # 도구 무발동 진단(스펙 236) — 도구가 바인딩된 턴의 호출 수를 항상 기록. called=0이면 UI가
        # "왜 안 되는지" 후보(모델이 도구 호출 미지원(mock 등)·질문이 도구와 무관)를 표면화한다
        # (158 회상·125 검색 진단의 결 — 조용한 무발동 금지). impl이 도구 표면(mcps/vectorTables)을
        # 안 읽는 타입(route·artifact류)은 제외 — 그건 무발동이 아니라 설계상 무소비(폼이 이미 경고).
        _td_consumes = impl.describe().consumes
        _td_reads_tools = _td_consumes is None or bool({"mcps", "vectorTables"} & set(_td_consumes))
        if tools and _td_reads_tools:
            trace["toolDiag"] = {
                "bound": [getattr(tl, "name", "?") for tl in tools][:20],
                "called": len(calls_sink),
            }
        # 전송 프롬프트(스펙 205): 콜백 실측(마지막 모델 호출 — 커스텀 impl의 계획·도구 안내 포함)
        # 우선, 콜백 미발화면 기존 재구성(131) 폴백. 출처를 표기해 UI가 정직하게 라벨링.
        if capture.calls:
            trace["sentMessages"] = _format_sent_measured(capture.calls[-1])
            trace["modelCalls"] = len(capture.calls)
            trace["sentMessagesSource"] = "measured"
        else:
            trace["sentMessages"] = sent_messages  # 전송 프롬프트 전문(스펙 131, 메시지당 2000자 캡)
            trace["sentMessagesSource"] = "reconstructed"
        ov_trace = _overrides_trace(ctx.get("overrides"))
        if ov_trace:
            # 이 턴에 적용된 오버라이드(스펙 134) — 세션에 설정 다른 턴이 섞여도 턴별 구분 가능.
            trace["overrides"] = ov_trace
        if build_broker_scoped.invocations:
            # 브로커 호출 상세(스펙 130) — 조율형의 RAG 검색이 인스펙터에 "N건·최고 유사도"로 보이게.
            # 위임 없던 턴은 필드 자체가 없음(무회귀).
            trace["brokerCalls"] = _broker_calls_trace(build_broker_scoped.invocations)
        if ctx["rag_collections"]:
            # 구성된 RAG 컬렉션 — 호출 안 해도 인스펙터에 노출(실제 호출은 trace["mcp"]의 server="rag").
            trace["ragCollections"] = [c["name"] for c in ctx["rag_collections"]]
        if ctx.get("rag_unresolved"):
            # 요청됐으나 해석 실패한 이름 — 도구가 조용히 비는 footgun을 인스펙터에 드러냄(타자검증 F).
            trace["ragUnresolved"] = ctx["rag_unresolved"]
        if used_memory:
            # None이 아닌 회상 축만 — {"user_id","run_id","agent_id"} 부분집합 (Inspector가 축별 렌더).
            trace["memoryScope"] = {k: v for k, v in recall_scope.items() if v}
            # 회상에 쓴 쿼리(=user_text)를 에코 — 0건 회상이어도 "조회 행위"를 인스펙터에 남긴다(스펙 079).
            # 표시 전용·길이상한(방금 그 유저가 보낸 텍스트라 경계 이동 없음).
            trace["memoryQuery"] = user_text[:300]
        # 오류 턴은 영속/메모리 저장하지 않는다 (부분/실패 응답 오염 방지).
        mid = None
        if not errored:
            mid = await _persist(
                ctx, user_text, full, trace, tokens, ctx["persist_history"],
                user_id=user_id,
            )
        if mid:
            yield _mid_frame(mid)  # 스펙 209 P1.5 — 피드백 부착용 assistant id
        if not errored and used_memory and full:
            # 자동 턴 add는 add_scope(user_id+run_id만) — agent_id 미포함(누출 차단, 스펙 029).
            await asyncio.to_thread(
                memory.add,
                add_scope,
                [{"role": "user", "content": user_text}, {"role": "assistant", "content": full}],
                ctx["mem_cfg"],
            )
        yield f"event: trace\ndata: {json.dumps(trace, ensure_ascii=False)}\n\n"
        yield "event: done\ndata: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ----------------------------- HIL 승인 게이트 (스펙 041) -----------------------------
async def _create_approval(
    ctx: dict, thread_id: str, payload: dict, user_id: str | None
) -> str:
    """위험 도구가 그래프를 멈춘 순간 런타임 Approval(pending) 생성. checkpoint=thread_id가 재개 키.

    DB 접근은 API 계층(여기)에서만 — 도구는 순수(interrupt payload만 만든다). 이 row가
    ApprovalsView에 뜨고, resolve하면 resume_approval이 같은 thread_id로 그래프를 재개한다.

    user_id = 요청 주체(쿠키 유저 UUID str, 머신이면 None). owner self-승인(스펙 066)의 대조 기준 —
    여기서 박지 않으면 self-승인 자체가 불가능하고, NULL은 admin 전용으로 fail-closed.
    """
    apid = "apr-" + secrets.token_hex(4)
    async with SessionLocal() as db:
        # 0턴 미영속(스펙 049)이라도 *승인 게이트에 도달한 턴은 실 상호작용*이므로 여기서 세션 행을
        # 보장한다. 그래야 resume_approval의 _load_context가 같은 session_id로 세션을 찾아(새 id를
        # 안 만들고) 최종 답변을 원 세션에 영속한다(approval-resume 연속성 보존).
        sess = await _resolve_session_for_persist(db, ctx)
        if sess is not None:
            ctx["session_pk"] = sess.id
            ctx["session_pending"] = None
            # 스펙 068 D6: 승인 게이트에 도달한 턴은 실 상호작용이므로 *생성 시점*에 소유자를 박는다.
            # 이게 없으면 세션이 NULL-owned로 남아, D1(소유자 스코프 resume) 도입 후 그 턴을 시작한
            # member가 *자기 세션을* 이어가지 못한다(무회귀 깨짐). next_owner라 기존 소유자 보존·안전.
            sess.user_id = next_owner(sess.user_id, user_id)
        db.add(
            Approval(
                approval_id=apid,
                session_id=ctx["session_id"],
                user_id=user_id,
                agent_pk=ctx["agent_pk"],
                agent_name=ctx["agent_name"],
                permission=payload.get("permission", ""),
                approver=payload.get("approver"),  # 스펙 177 P2 — MCP 도구만 값 有, 그 외 None→Casbin 폴백
                action=payload.get("action", ""),
                args=payload.get("args", {}),
                summary=payload.get("summary", ""),
                checkpoint=thread_id,
                # 위상 정체 스냅샷(스펙 171) — 재개 시 impl이 바뀌었으면 stale checkpoint에
                # 다른 그래프를 resume하지 않도록 대조 기준. "" = 기본(DefaultUiAgent).
                impl=ctx.get("impl") or "",
                status="pending",
            )
        )
        await db.commit()
    return apid


async def _build_resume_broker(user_id: str | None, capabilities, tool_policy: dict | None = None) -> PolicyScopedBroker:
    """재개용 스코프 브로커 — 원 요청자(user_id)의 RBAC를 재구성해 request-time 게이트를 그대로 복원.

    build_broker(principal, ...)와 **동일 술어**를 principal 객체 없이 재현한다: superuser면 우회(원
    요청과 동일 안전판), 아니면 casbin `enforce(user_id, capability:{kind}, invoke)`. user_id가 없으면
    deny(머신 발 — 이 경로는 애초에 브로커 interrupt를 못 만들므로 실질 미도달, 안전측 기본)."""
    is_super = False
    if user_id:
        try:
            async with SessionLocal() as s:
                u = await s.get(User, uuid.UUID(user_id))
                is_super = bool(u and u.is_superuser)
        except (ValueError, TypeError):
            is_super = False  # user_id가 UUID 형식이 아니면 casbin 경로로만(우회 없음)

    def rbac_allows(kind: str, name: str | None = None) -> bool:
        # per-cap 부여 지원(스펙 112) — build_broker와 **동일 술어**(`_rbac_check`, drift 0).
        if not user_id:
            return False
        if is_super:
            return True
        from .broker import _rbac_check
        return _rbac_check(authz.get_enforcer(), user_id, kind, name)

    # user_id 주입(스펙 104) — MemoryProvider가 재개 경로에서도 원 요청자 스코프를 복원한다. 없으면
    # 재개 시 `memory:user`가 사라져 자기 기억 접근이 깨진다(fail-closed지만 기능 회귀, 적대 리뷰 104 P2).
    return PolicyScopedBroker(capabilities, rbac_allows, user_id=user_id, tool_policy=tool_policy)


def _impl_drifted(snap_impl: str | None, cur_impl: str | None) -> bool:
    """스펙 171 — 재개 시 impl(그래프 위상)이 생성 시점과 달라졌나. 순수 함수(단위 검증 가능).

    - snap None = 스펙 171 마이그레이션 이전에 만든 행 = 스냅샷 부재 = 대조 불가 → False(스킵, 하위호환).
    - "" = 기본(DefaultUiAgent). cur도 None/""면 기본이므로 `cur or ""`로 정규화해 대조.
    - snap이 있고 현재와 다르면 True → 재개는 미정의 동작(다른 그래프를 stale checkpoint에 resume)이라 거부.
    """
    if snap_impl is None:
        return False
    return snap_impl != (cur_impl or "")


async def resume_approval(approval: Approval, decision: str) -> None:
    """admin 결정(approve/reject)으로 멈춘 그래프를 재개하고 최종 메시지를 원 세션에 영속.

    approvals.resolve_approval이 status 설정 후 호출(상시). 체크포인트(Postgres 공유)에서 그래프를
    재구축해 `Command(resume=...)`로 이어 달린다 — 멀티워커 안전. approve면 도구 실행 후 ReAct가
    마무리 답변을, reject면 도구 미실행으로 마무리한다. 라이브 스트리밍은 빚(§7) — 여기선
    서버사이드로 끝까지 돌려 결과만 세션에 남긴다.

    가드: checkpoint(thread_id)·agent_pk 없으면 재개 불가(무시). code/external 소스는 로컬 그래프가
    아니므로 애초에 approval을 만들지 않는다(여기 도달 시 graceful 무시).
    """
    thread_id = approval.checkpoint
    if not thread_id or not approval.agent_pk:
        log.warning("resume 건너뜀: checkpoint/agent_pk 없음 (approval %s)", approval.approval_id)
        return
    ckpt = checkpointer.get_checkpointer()
    if ckpt is None:
        log.warning("resume 불가: 체크포인터 비활성 (approval %s)", approval.approval_id)
        return

    # 원 턴과 동일하게 컨텍스트·도구·페르소나를 재구성(같은 세션 id → 기존 세션 로딩, 새로 안 만듦).
    ctx = await _load_context(approval.agent_pk, approval.session_id)
    try:
        impl = resolve_agent_runtime(ctx)
    except AgentConfigError as e:
        # 선언한 구현이 미해결(스펙 089) — 재개 불가, graceful 무시(approval은 이미 결재됨, 세션 무파손).
        log.warning("resume 불가: 설정 실패 impl '%s' (approval %s)", e, approval.approval_id)
        return
    if impl is None or ctx["model_cfg"] is None:
        log.warning("resume 불가: 비로컬/모델없음 소스 (approval %s)", approval.approval_id)
        return
    # impl-drift 명시 가드(스펙 171): approval은 생성 시점 impl의 그래프 topology로 checkpoint를
    # 만들었다. 그 사이 admin이 `config.impl`을 **다른 impl**로 바꾸면(HIL→non-HIL이든 HIL→다른 HIL이든)
    # 그 checkpoint는 현 그래프와 위상이 어긋난다 — 다른 그래프를 stale checkpoint에 resume하는 건
    # LangGraph 미정의 동작이다. 생성 시 박은 impl 스냅샷과 현재를 대조해 다르면 **graceful 거부**
    # (approval은 이미 결재됨·세션 무파손·approved-but-not-executed=안전방향). 미정의 동작에 의존하지
    # 않는다. 단, impl 스냅샷이 None인 행(스펙 171 마이그레이션 이전 생성)은 대조 불가라 스킵하고
    # 아래 supports_hil 가드로만 넘긴다(하위호환).
    #
    # 다중 HIL impl 출하 중(DefaultUiAgent·orchestrate·orchestrate_ranked, 전부 supports_hil=True)이라
    # 이 스왑은 실제 도달 가능하다(deep-reasoner 적대 검토, 스펙 171). 방아쇠는 admin의 impl 교체
    # (agents:manage)에 갇혀 권한상승은 아니나, 미정의 동작 의존을 명시 가드로 닫는다.
    if _impl_drifted(approval.impl, ctx.get("impl")):
        log.warning(
            "resume 불가: impl drift — 생성 '%s' vs 현재 '%s' (checkpoint 위상 불일치, approval %s)",
            approval.impl or "(기본)", ctx.get("impl") or "(기본)", approval.approval_id,
        )
        return
    # 잔여 방어(codex F2 원본): 현 런타임이 HIL 미지원이면 애초 interrupt/checkpoint를 만들 수 없으므로
    # 재개 불가. impl-drift 가드가 impl 변경을 이미 잡으므로 대개 이 지점 도달 = impl 불변 + 원래
    # HIL 지원이나, 방어적으로 유지(예: 마이그레이션 이전 None-snap 행이 non-HIL로 바뀐 경우).
    if not impl.describe().supports_hil:
        log.warning(
            "resume 불가: 현 런타임(%s)이 HIL 미지원 — checkpoint 생성 그래프와 drift (approval %s)",
            type(impl).__name__, approval.approval_id,
        )
        return

    recall_scope = {"user_id": None, "run_id": ctx["session_id"], "agent_id": ctx["ext_agent_id"]}
    # 스펙 233 봉합(이중 배선 축 — 신규 chat과 동일 게이트를 재개 경로에도, codex 잔여 회귀): impl이
    # "memories"를 consumes로 선언할 때만 회상(폼 "무시됩니다"를 재개 경로에서도 참으로).
    _resume_reads_memory = impl.describe().consumes is None or "memories" in impl.describe().consumes
    used_memory = (
        not ctx.get("ephemeral")  # 스펙 235 대칭
        and _resume_reads_memory
        and memory.memory_enabled(ctx["memories"])
        and ctx["mem_cfg"] is not None
    )
    # user_id가 없으니(재개 주체=admin) user/run 축 회상은 의미가 약하나, 페르소나 톤 유지를 위해
    # agent 축 회상만이라도 접목(없어도 무해). 자동 메모리 add는 user_id 부재로 생략(빚).
    mem_hits = (
        await asyncio.to_thread(memory.search, recall_scope, approval.summary or "", ctx["mem_cfg"])
        if used_memory
        else []
    )

    calls_sink: list[dict] = []
    tools = await runtime.build_mcp_tools(ctx["mcp_servers"], calls_sink, ctx.get("toolPolicy"))
    # 채팅 자가기록 도구 제거됨(스펙 051) — agent_id 메모리는 어드민 저작 전용. 회상(recall_scope)은 유지.
    if ctx["rag_collections"]:
        tools.append(runtime.build_rag_tool(ctx["rag_collections"], calls_sink, ctx.get("rag_min_scores")))

    persona_prompt = ctx["persona"]
    if mem_hits:
        # 브로커 memory 능력과 공유하는 포맷(스펙 104 drift 0) — 회상 텍스트 표현이 한 곳.
        recalled = memory.format_memory_hits(mem_hits)
        persona_prompt = f"{persona_prompt}\n\n# 관련 기억(회상됨)\n{recalled}"
    run_params = {} if ctx["temperature"] is None else {"temperature": ctx["temperature"]}
    # 서브스텝 HIL 재개(스펙 101 §3.5): 위임 cap의 interrupt를 재개하려면 원 턴과 **동일 스코프**의
    # 브로커를 재주입해야 한다 — 없으면 orchestrate.delegate가 broker=None으로 위임을 통째 건너뛰어
    # *승인된* cap이 영영 미실행된다(approved-but-not-executed = 거부 방향 오류). allowlist=에이전트
    # config(결정적). RBAC 축은 **원 요청자**(approval.user_id)로 재확인 — 요청 시 이미 통과했고 유저
    # 축은 재개 사이 불변. user_id None(머신 발)은 요청 시 build_broker가 이미 거부해 브로커 interrupt
    # 자체가 안 생기므로 여기 도달 시 항상 존재(그 경우만 deny로 안전측). superuser 우회도 원 요청과 동일 보존.
    resume_broker = await _build_resume_broker(approval.user_id, ctx["capabilities"], ctx.get("toolPolicy"))
    build_ctx = AgentBuildContext(
        persona=persona_prompt,
        model_cfg=ctx["model_cfg"],
        tools=tools,
        checkpointer=ckpt,
        params=run_params,
        memories=mem_hits,
        overrides=ctx.get("overrides"),
        broker=resume_broker,
    )
    graph = impl.build_graph(build_ctx)
    config = {"configurable": {"thread_id": thread_id}}
    # 관측(스펙 118) — 재개 경로도 Langfuse가 설정됐을 때만 콜백 부착(미설정=무동작).
    # 비영속(스펙 235) 대칭 가드(codex): 정상 ephemeral은 approval을 못 만들어 미도달이나, "과거 approval +
    # 설정을 ephemeral로 변경" 엣지에서 이 경로가 호출될 수 있어 langfuse도 대칭으로 스킵(_persist는 이미 차단).
    if not ctx.get("ephemeral"):
        config = observability.with_trace(config, name="chat-resume", user_id=approval.user_id)

    t0 = time.perf_counter()
    try:
        result = await graph.ainvoke(Command(resume={"decision": decision}), config=config)
    except Exception as exc:  # noqa: BLE001 — 재개 실패도 세션을 깨지 않는다(로그+graceful)
        log.error("resume 실패 (approval %s): %s", approval.approval_id, exc)
        return

    # 최종 상태에서 사용자 질문·최종 답변 추출(체크포인트가 보유 — Approval에 user_text 미저장).
    msgs = result.get("messages", []) if isinstance(result, dict) else []
    user_text = next(
        (getattr(m, "content", "") for m in msgs if getattr(m, "type", "") == "human"), ""
    )
    reply = next(
        (
            getattr(m, "content", "")
            for m in reversed(msgs)
            if getattr(m, "type", "") == "ai" and getattr(m, "content", "")
        ),
        "",
    )
    total_ms = int((time.perf_counter() - t0) * 1000)
    tokens = runtime.estimate_tokens(len(user_text), len(reply))
    trace = runtime.assemble_trace(
        agent_id=ctx["ext_agent_id"], memories=mem_hits, mcp_calls=calls_sink,
        used_memory=used_memory, total_ms=total_ms, tokens=tokens,
    )
    trace["resumedApproval"] = {"id": approval.approval_id, "decision": decision}
    if resume_broker.invocations:
        # 재개 턴의 브로커 호출도 표면화(스펙 130, codex #1).
        trace["brokerCalls"] = _broker_calls_trace(resume_broker.invocations)
    await _persist(
        ctx, user_text, reply, trace, tokens, ctx["persist_history"], user_id=None
    )

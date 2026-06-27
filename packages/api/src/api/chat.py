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

import httpx
from agent.main import build_agent
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from . import crypto, memory, runtime
from .auth import current_principal
from .db import SessionLocal
from .models import Agent, Collection, McpServer, Message, ModelConfig, Session
from .schemas import ChatRequest

router = APIRouter(prefix="/agents", tags=["chat"])
log = logging.getLogger("api.chat")


async def _load_context(
    agent_id: uuid.UUID, session_str_id: str | None, overrides: dict | None = None
):
    """에이전트 구성 + MCP 활성 툴 + 세션(생성/지속)을 한 번에 준비.

    overrides(스펙 025): Playground Proxy의 세션 한정 설정 덮어쓰기. **web 에이전트에만** 적용하고
    화이트리스트 키만 받는다(저장된 에이전트는 불변). 코드 에이전트는 원격 실행이라 미적용(bypass).
    """
    async with SessionLocal() as db:
        agent = await db.get(Agent, agent_id)
        if agent is None:
            raise HTTPException(status_code=404, detail="agent not found")
        cfg = dict(agent.config or {})
        persona = agent.persona
        # web 한정 세션 오버라이드(화이트리스트). 코드·외부 에이전트는 분기 진입 안 함 = bypass 보존.
        # (외부=A2A는 비로컬이라 로컬 설정 오버라이드 의미 없음 — 026 read-only 취급.)
        # 모델은 여전히 cfg["model"] 이름으로 레지스트리에서만 해석 → [012] 단일 소스 불변식 유지.
        if overrides and agent.source not in ("code", "external"):
            allowed = {"model", "temperature", "historyDepth", "mcps", "memories"}
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
            "endpoint": agent.endpoint,
            "token": agent.token,
            "memories": cfg.get("memories", []),
            # 에이전트가 명시한 temperature만 전달(없으면 None) → 모델 등록 params가 적용되게.
            "temperature": cfg.get("temperature"),
            "history_depth": cfg.get("historyDepth", 20),
            "persist_history": cfg.get("persistHistory", True),
        }

        # 모델은 레지스트리에서만 해석한다(env 안 봄). 에이전트가 고른 이름 → 없으면
        # 기본(is_default) chat 모델. 그것도 없으면 명확히 400.
        # 코드·외부 에이전트는 비로컬(원격/A2A) 실행이라 로컬 모델이 필요 없다(여기선 건너뜀).
        if agent.source not in ("code", "external"):
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

        mcp_pairs: list[tuple[str, str]] = []
        mcps = cfg.get("mcps", [])
        if mcps:
            rows = (
                await db.execute(select(McpServer).where(McpServer.name.in_(mcps)))
            ).scalars().all()
            for r in rows:
                for t in (r.enabled_tools or r.tools or []):
                    mcp_pairs.append((r.name, t))
        ctx["mcp_pairs"] = mcp_pairs

        # RAG 컬렉션 해석(스펙 037) — vectorTables(이름 목록) → 검색 도구 배선용 dict.
        # 질의는 **각 컬렉션이 인제스트에 쓴 임베딩 모델**로 임베딩해야 같은 벡터 공간이 된다
        # (035 진실원). provider 불완전(base_url/model_id 없음) 컬렉션은 검색 불가라 skip(graceful).
        # 코드·외부 에이전트는 비로컬이라 위에서 이미 분기되지 않고 도달할 수 있으나, 이 블록은
        # 로컬 실행 경로에서만 의미가 있다 — code/external은 chat()에서 프록시/안내로 빠진다.
        rag_collections: list[dict] = []
        vt_names = cfg.get("vectorTables", [])
        if vt_names and agent.source not in ("code", "external"):
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

        sess = None
        if session_str_id:
            # 세션은 해당 에이전트로 스코프 — 다른 에이전트의 세션 id를 줘도 섞이지 않게.
            sess = (
                await db.execute(
                    select(Session).where(
                        Session.session_id == session_str_id,
                        Session.agent_pk == agent.id,
                    )
                )
            ).scalar_one_or_none()
        if sess is None:
            sess = Session(
                session_id="sess-" + secrets.token_hex(3),
                agent_pk=agent.id,
                agent_name=agent.name,
                channel="playground",
                status="active",
            )
            db.add(sess)
            await db.commit()
            await db.refresh(sess)
        ctx["session_pk"] = sess.id
        ctx["session_id"] = sess.session_id
        return ctx


def _build_mem_cfg(chat_m, emb_m) -> dict | None:
    """레지스트리 chat+embedding 모델 → mem0 mem_cfg(llm+embedder dict, 복호화 포함).
    연결처는 각 모델의 provider에서 상속(스펙 035). 어느 쪽이라도 provider base_url/model_id가
    없으면 None. get_all/update/delete는 embedder만 쓰지만 mem0 인스턴스화에 llm 자리가 필요하다
    (스펙 030 공유 빌더). 호출 측은 provider 관계를 eager-load해야 한다."""
    cp = chat_m.provider if chat_m else None
    ep = emb_m.provider if emb_m else None
    if chat_m is None or cp is None or not cp.base_url or not chat_m.model_id:
        return None
    if emb_m is None or ep is None or not ep.base_url or not emb_m.model_id:
        return None
    return {
        "llm": {
            "base_url": cp.base_url, "api_key": crypto.decrypt(cp.api_key), "model_id": chat_m.model_id,
        },
        "embedder": {
            "base_url": ep.base_url, "api_key": crypto.decrypt(ep.api_key), "model_id": emb_m.model_id,
        },
    }


async def _default_chat_model(db):
    return (
        await db.execute(
            select(ModelConfig)
            .where(ModelConfig.kind == "chat", ModelConfig.is_default.is_(True))
            .options(selectinload(ModelConfig.provider))
        )
    ).scalars().first()


async def _default_embed_model(db):
    return (
        await db.execute(
            select(ModelConfig)
            .where(ModelConfig.kind == "embedding", ModelConfig.is_default.is_(True))
            .options(selectinload(ModelConfig.provider))
        )
    ).scalars().first()


async def resolve_agent_mem_cfg(db, agent) -> dict | None:
    """에이전트의 mem0 설정(레지스트리 chat llm + 기본 embedding)을 해석. 없으면 None.

    관리자 메모리 CRUD(agents.py 스펙 029)가 _load_context와 같은 규칙으로 mem_cfg를 얻는 단일
    경로. 코드·외부 에이전트는 비로컬(원격/A2A)이라 로컬 mem0가 없다 → None.
    """
    if agent.source in ("code", "external"):
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


async def default_mem_cfg(db) -> dict | None:
    """특정 에이전트에 안 묶인 mem0 설정 — 기본 chat + 기본 embedding. 유저 메모리
    관리(스펙 030)용. 공유 pgvector·user_id 키라 기본 설정으로 조회·교정이 가능하다."""
    return _build_mem_cfg(await _default_chat_model(db), await _default_embed_model(db))


def _window(messages: list[dict], depth: int | None) -> list[dict]:
    """실행 컨텍스트를 최근 N개로 절단. 0=현재 턴만, 음수/None=전체.
    ([-0:]가 전체가 되는 파이썬 함정 처리)."""
    if depth is None or depth < 0:
        return messages
    if depth == 0:
        return messages[-1:]
    return messages[-depth:]


async def _persist(
    session_pk: uuid.UUID, user_text: str, reply: str, trace: dict, tokens: dict, store_messages: bool,
    user_id: str | None = None,
):
    """세션 카운터는 항상 갱신. 메시지(user/assistant+트레이스)는 store_messages일 때만 저장.

    non-empty userId가 오면 세션에 기록(distinct 목록 출처 — 스펙 021). 빈 값이면 기존 값 보존.
    """
    async with SessionLocal() as db:
        sess = await db.get(Session, session_pk)
        if sess is None:
            log.error("persist skipped: session %s not found", session_pk)
            return
        if store_messages:
            db.add(Message(session_pk=session_pk, role="user", content=user_text))
            db.add(Message(session_pk=session_pk, role="assistant", content=reply, trace=trace))
        if user_id:  # non-empty만 기록 — 빈칸으로 대화해도 기존 userId를 지우지 않음
            sess.user_id = user_id
        sess.turns = (sess.turns or 0) + 1
        sess.tokens = (sess.tokens or 0) + int(tokens.get("in", 0)) + int(tokens.get("out", 0))
        sess.status = "active"
        await db.commit()


async def _remote_stream(ctx: dict, body: ChatRequest, user_text: str, user_id: str | None):
    """코드 에이전트: 등록된 원격 엔드포인트로 프록시하고 응답을 우리 SSE로 재전송."""
    yield f"data: {json.dumps({'session': ctx['session_id']}, ensure_ascii=False)}\n\n"
    api_messages = _window(
        [{"role": m.role, "content": m.content} for m in body.messages], ctx["history_depth"]
    )
    # 저장된 토큰을 복호화해 실제 Bearer로 전송(이제 실 토큰 보안 저장 → 원격 인증 가능).
    # 레거시 마스킹 토큰은 복호화 폴백으로 •가 남으므로 그땐 헤더 생략. HTTP 헤더는 ascii만.
    tok = crypto.decrypt(ctx.get("token"))
    headers = {"Authorization": f"Bearer {tok}"} if tok and "•" not in tok else {}
    acc: list[str] = []
    errored = False
    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream(
                "POST", ctx["endpoint"], json={"messages": api_messages}, headers=headers
            ) as resp:
                if resp.status_code >= 400:
                    # 원격 본문은 보낸 Authorization/토큰을 에코할 수 있어 클라에도 로그에도
                    # 남기지 않는다(자격증명 누출 방지). 상태코드만 기록.
                    await resp.aread()
                    log.warning("remote agent %s error %s", ctx["endpoint"], resp.status_code)
                    errored = True
                    yield f"data: {json.dumps({'error': f'원격 응답 오류 {resp.status_code}'}, ensure_ascii=False)}\n\n"
                else:
                    async for line in resp.aiter_lines():
                        # SSE: 'data:' 또는 'data: ' 모두 허용.
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].lstrip()
                        if data == "[DONE]":
                            break
                        try:
                            d = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        text = d.get("text")
                        if text:
                            acc.append(text)
                            yield f"data: {json.dumps({'text': text}, ensure_ascii=False)}\n\n"
    except Exception as exc:  # noqa: BLE001 — 원격 오류도 프레임으로
        errored = True
        yield f"data: {json.dumps({'error': str(exc)}, ensure_ascii=False)}\n\n"

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
            {"node": "remote_call", "ms": total_ms},
            {"node": "__end__", "ms": 0},
        ],
        "remote": True,
        "contextMessages": len(api_messages),
    }
    if not errored:
        await _persist(
            ctx["session_pk"], user_text, full, trace, tokens, ctx["persist_history"],
            user_id=user_id,
        )
    yield f"event: trace\ndata: {json.dumps(trace, ensure_ascii=False)}\n\n"
    yield "event: done\ndata: [DONE]\n\n"


async def _external_notice_stream(ctx: dict):
    """외부(A2A) 에이전트: 1차(026)는 등록·표시까지만. 실제 호출은 2차 스펙.

    크래시·로컬 폴백 없이 안내 1프레임만 흘리고 종료한다(런타임 특수분기는 데이터로만 가름).
    """
    yield f"data: {json.dumps({'session': ctx['session_id']}, ensure_ascii=False)}\n\n"
    msg = "외부(A2A) 에이전트 실행은 아직 준비 중입니다(런타임 호출은 2차 스펙). 지금은 등록·카드 확인까지 지원합니다."
    yield f"data: {json.dumps({'text': msg}, ensure_ascii=False)}\n\n"
    yield "event: done\ndata: [DONE]\n\n"


@router.post("/{agent_id}/chat")
async def chat(agent_id: uuid.UUID, body: ChatRequest, principal=Depends(current_principal)):
    ctx = await _load_context(agent_id, body.sessionId, body.overrides)
    user_text = body.messages[-1].content if body.messages else ""

    # mem0 user_id 축 = 인증 주체에서 도출(스펙 032). 쿠키 유저면 안정 UUID(str(user.id)),
    # 머신 토큰("machine" 센티넬)이면 None → 세션 단기 폴백(기존 "빈 userId" 동작과 동일, 무회귀).
    user_id = None if isinstance(principal, str) else str(principal.id)

    # 코드(SDK) 에이전트는 자기 원격 엔드포인트에서 실행 — 프록시.
    if ctx["source"] == "code" and ctx["endpoint"]:
        return StreamingResponse(
            _remote_stream(ctx, body, user_text, user_id), media_type="text/event-stream"
        )

    # 외부(A2A) 에이전트는 비로컬 — 1차는 안내만(실제 호출은 2차 스펙).
    if ctx["source"] == "external":
        return StreamingResponse(
            _external_notice_stream(ctx), media_type="text/event-stream"
        )

    # 메모리 스코프(다층 — 스펙 020/029). 회상(search)과 자동 쓰기(add)는 **축이 다르다**:
    # - recall_scope: user_id(세션 가로지름)+run_id(세션 단기)+agent_id(에이전트 전용 — 스펙 029).
    #   search는 축별로 따로 검색해 합집합 병합(mem0 필터는 AND이므로 — memory.py 참고).
    # - add_scope: user_id+run_id만. **agent_id는 자동 add에 절대 태깅하지 않는다** — 유저 턴
    #   자동추출이 agent_id로 새면 user A의 사적 사실이 다른 유저에게 회상된다(스펙 020 누출 차단).
    #   agent_id 쓰기는 의도적 채널(save_agent_knowledge 도구·관리자 저작)로만. run_id=session_id.
    add_scope = {"user_id": user_id, "run_id": ctx["session_id"]}
    recall_scope = {**add_scope, "agent_id": ctx["ext_agent_id"]}

    # 의미론적 메모리 회상 (켠 에이전트 + 등록 임베딩 모델 있을 때만). mem0는 동기 → 스레드로.
    used_memory = memory.memory_enabled(ctx["memories"]) and ctx["mem_cfg"] is not None
    mem_hits = (
        await asyncio.to_thread(memory.search, recall_scope, user_text, ctx["mem_cfg"])
        if used_memory
        else []
    )

    calls_sink: list[dict] = []
    tools = runtime.build_tools(ctx["mcp_pairs"], calls_sink)
    # 에이전트 자가기록 도구 — mem0 켜진 에이전트에만 주입(스펙 029). agent_id-only·infer=False.
    if used_memory:
        tools.append(
            runtime.build_agent_memory_tool(ctx["ext_agent_id"], ctx["mem_cfg"], calls_sink)
        )
    # RAG 검색 도구 — vectorTables가 실 컬렉션으로 해석됐을 때만 주입(스펙 037). mem0 비종속.
    if ctx["rag_collections"]:
        tools.append(runtime.build_rag_tool(ctx["rag_collections"], calls_sink))

    # 회상된 기억은 persona(시스템 프롬프트)에 합친다. 별도 system 메시지로 주입하면
    # create_react_agent의 persona system과 충돌해 모델 채팅 템플릿이 거부한다
    # ("System message must be at the beginning"). 단일 system 프롬프트 유지.
    persona_prompt = ctx["persona"]
    if mem_hits:
        recalled = "\n".join(f"- {h['text']}" for h in mem_hits)
        persona_prompt = f"{persona_prompt}\n\n# 관련 기억(회상됨)\n{recalled}"
    run_params = {} if ctx["temperature"] is None else {"temperature": ctx["temperature"]}
    graph = build_agent(persona_prompt, run_params, tools, ctx["model_cfg"])

    # 실행 컨텍스트를 historyDepth로 절단(최근 N개만 모델에 전달).
    messages = _window(
        [{"role": m.role, "content": m.content} for m in body.messages], ctx["history_depth"]
    )

    async def event_stream():
        t0 = time.perf_counter()
        yield f"data: {json.dumps({'session': ctx['session_id']}, ensure_ascii=False)}\n\n"
        acc: list[str] = []
        errored = False
        try:
            async for chunk, _meta in graph.astream({"messages": messages}, stream_mode="messages"):
                text = getattr(chunk, "content", "")
                if text:
                    acc.append(text)
                    yield f"data: {json.dumps({'text': text}, ensure_ascii=False)}\n\n"
        except Exception as exc:  # 모델/툴 오류도 프레임으로 전달
            errored = True
            yield f"data: {json.dumps({'error': str(exc)}, ensure_ascii=False)}\n\n"

        full = "".join(acc)
        total_ms = int((time.perf_counter() - t0) * 1000)
        prompt_chars = sum(len(m["content"]) for m in messages)
        tokens = runtime.estimate_tokens(prompt_chars, len(full))
        trace = runtime.assemble_trace(
            agent_id=ctx["ext_agent_id"],
            memories=mem_hits,
            mcp_calls=calls_sink,
            used_memory=used_memory,
            total_ms=total_ms,
            tokens=tokens,
        )
        trace["contextMessages"] = len(messages)  # 모델에 넣은 메시지 수(historyDepth 적용 결과)
        if ctx["rag_collections"]:
            # 구성된 RAG 컬렉션 — 호출 안 해도 인스펙터에 노출(실제 호출은 trace["mcp"]의 server="rag").
            trace["ragCollections"] = [c["name"] for c in ctx["rag_collections"]]
        if ctx.get("rag_unresolved"):
            # 요청됐으나 해석 실패한 이름 — 도구가 조용히 비는 footgun을 인스펙터에 드러냄(타자검증 F).
            trace["ragUnresolved"] = ctx["rag_unresolved"]
        if used_memory:
            # None이 아닌 회상 축만 — {"user_id","run_id","agent_id"} 부분집합 (Inspector가 축별 렌더).
            trace["memoryScope"] = {k: v for k, v in recall_scope.items() if v}
        # 오류 턴은 영속/메모리 저장하지 않는다 (부분/실패 응답 오염 방지).
        if not errored:
            await _persist(
                ctx["session_pk"], user_text, full, trace, tokens, ctx["persist_history"],
                user_id=user_id,
            )
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

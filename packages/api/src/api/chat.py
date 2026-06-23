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
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from . import crypto, memory, runtime
from .db import SessionLocal
from .models import Agent, McpServer, Message, ModelConfig, Session
from .schemas import ChatRequest

router = APIRouter(prefix="/agents", tags=["chat"])
log = logging.getLogger("api.chat")


async def _load_context(agent_id: uuid.UUID, session_str_id: str | None):
    """에이전트 구성 + MCP 활성 툴 + 세션(생성/지속)을 한 번에 준비."""
    async with SessionLocal() as db:
        agent = await db.get(Agent, agent_id)
        if agent is None:
            raise HTTPException(status_code=404, detail="agent not found")
        cfg = dict(agent.config or {})
        ctx = {
            "persona": agent.persona,
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
        # 코드 에이전트는 원격 실행이라 로컬 모델이 필요 없다(여기선 건너뜀).
        if agent.source != "code":
            model_name = cfg.get("model")
            m = None
            if model_name:
                m = (
                    await db.execute(
                        select(ModelConfig).where(
                            ModelConfig.name == model_name, ModelConfig.kind == "chat"
                        )
                    )
                ).scalar_one_or_none()
            if m is None:
                m = (
                    await db.execute(
                        select(ModelConfig).where(
                            ModelConfig.kind == "chat", ModelConfig.is_default.is_(True)
                        )
                    )
                ).scalars().first()
            if m is None:
                raise HTTPException(
                    status_code=400,
                    detail="등록된 채팅 모델이 없습니다 — 모델을 먼저 등록하세요.",
                )
            if not m.base_url or not m.model_id:
                raise HTTPException(
                    status_code=400,
                    detail=f"모델 '{m.name}' 설정이 불완전합니다 (base_url/model_id 필요).",
                )
            ctx["model_cfg"] = {
                "base_url": m.base_url, "api_key": crypto.decrypt(m.api_key),
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
                    select(ModelConfig).where(
                        ModelConfig.kind == "embedding", ModelConfig.is_default.is_(True)
                    )
                )
            ).scalars().first()
            if emb is not None:
                mem_cfg = {
                    "llm": {
                        "base_url": ctx["model_cfg"]["base_url"],
                        "api_key": ctx["model_cfg"]["api_key"],
                        "model_id": ctx["model_cfg"]["model_id"],
                    },
                    "embedder": {
                        "base_url": emb.base_url, "api_key": crypto.decrypt(emb.api_key),
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


def _window(messages: list[dict], depth: int | None) -> list[dict]:
    """실행 컨텍스트를 최근 N개로 절단. 0=현재 턴만, 음수/None=전체.
    ([-0:]가 전체가 되는 파이썬 함정 처리)."""
    if depth is None or depth < 0:
        return messages
    if depth == 0:
        return messages[-1:]
    return messages[-depth:]


async def _persist(
    session_pk: uuid.UUID, user_text: str, reply: str, trace: dict, tokens: dict, store_messages: bool
):
    """세션 카운터는 항상 갱신. 메시지(user/assistant+트레이스)는 store_messages일 때만 저장."""
    async with SessionLocal() as db:
        sess = await db.get(Session, session_pk)
        if sess is None:
            log.error("persist skipped: session %s not found", session_pk)
            return
        if store_messages:
            db.add(Message(session_pk=session_pk, role="user", content=user_text))
            db.add(Message(session_pk=session_pk, role="assistant", content=reply, trace=trace))
        sess.turns = (sess.turns or 0) + 1
        sess.tokens = (sess.tokens or 0) + int(tokens.get("in", 0)) + int(tokens.get("out", 0))
        sess.status = "active"
        await db.commit()


async def _remote_stream(ctx: dict, body: ChatRequest, user_text: str):
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
        await _persist(ctx["session_pk"], user_text, full, trace, tokens, ctx["persist_history"])
    yield f"event: trace\ndata: {json.dumps(trace, ensure_ascii=False)}\n\n"
    yield "event: done\ndata: [DONE]\n\n"


@router.post("/{agent_id}/chat")
async def chat(agent_id: uuid.UUID, body: ChatRequest):
    ctx = await _load_context(agent_id, body.sessionId)
    user_text = body.messages[-1].content if body.messages else ""

    # 코드(SDK) 에이전트는 자기 원격 엔드포인트에서 실행 — 프록시.
    if ctx["source"] == "code" and ctx["endpoint"]:
        return StreamingResponse(
            _remote_stream(ctx, body, user_text), media_type="text/event-stream"
        )

    # 의미론적 메모리 회상 (켠 에이전트 + 등록 임베딩 모델 있을 때만). mem0는 동기 → 스레드로.
    used_memory = memory.memory_enabled(ctx["memories"]) and ctx["mem_cfg"] is not None
    mem_hits = (
        await asyncio.to_thread(memory.search, ctx["ext_agent_id"], user_text, ctx["mem_cfg"])
        if used_memory
        else []
    )

    calls_sink: list[dict] = []
    tools = runtime.build_tools(ctx["mcp_pairs"], calls_sink)

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
        # 오류 턴은 영속/메모리 저장하지 않는다 (부분/실패 응답 오염 방지).
        if not errored:
            await _persist(ctx["session_pk"], user_text, full, trace, tokens, ctx["persist_history"])
        if not errored and used_memory and full:
            await asyncio.to_thread(
                memory.add,
                ctx["ext_agent_id"],
                [{"role": "user", "content": user_text}, {"role": "assistant", "content": full}],
                ctx["mem_cfg"],
            )
        yield f"event: trace\ndata: {json.dumps(trace, ensure_ascii=False)}\n\n"
        yield "event: done\ndata: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")

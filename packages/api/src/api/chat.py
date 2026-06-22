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

from agent.main import build_agent
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from . import memory, runtime
from .db import SessionLocal
from .models import Agent, McpServer, Message, Session
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
            "memories": cfg.get("memories", []),
            "temperature": cfg.get("temperature", 0.7),
        }

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


async def _persist(session_pk: uuid.UUID, user_text: str, reply: str, trace: dict, tokens: dict):
    async with SessionLocal() as db:
        sess = await db.get(Session, session_pk)
        if sess is None:
            log.error("persist skipped: session %s not found", session_pk)
            return
        db.add(Message(session_pk=session_pk, role="user", content=user_text))
        db.add(Message(session_pk=session_pk, role="assistant", content=reply, trace=trace))
        sess.turns = (sess.turns or 0) + 1
        sess.tokens = (sess.tokens or 0) + int(tokens.get("in", 0)) + int(tokens.get("out", 0))
        sess.status = "active"
        await db.commit()


@router.post("/{agent_id}/chat")
async def chat(agent_id: uuid.UUID, body: ChatRequest):
    ctx = await _load_context(agent_id, body.sessionId)
    user_text = body.messages[-1].content if body.messages else ""

    # 의미론적 메모리 회상 (켠 에이전트만). mem0는 동기 → 스레드로.
    used_memory = memory.memory_enabled(ctx["memories"])
    mem_hits = (
        await asyncio.to_thread(memory.search, ctx["ext_agent_id"], user_text)
        if used_memory
        else []
    )

    calls_sink: list[dict] = []
    tools = runtime.build_tools(ctx["mcp_pairs"], calls_sink)
    graph = build_agent(ctx["persona"], {"temperature": ctx["temperature"]}, tools)

    messages = [{"role": m.role, "content": m.content} for m in body.messages]
    if mem_hits:
        recalled = "\n".join(f"- {h['text']}" for h in mem_hits)
        messages = [{"role": "system", "content": f"관련 기억(회상됨):\n{recalled}"}] + messages

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
        # 오류 턴은 영속/메모리 저장하지 않는다 (부분/실패 응답 오염 방지).
        if not errored:
            await _persist(ctx["session_pk"], user_text, full, trace, tokens)
        if not errored and used_memory and full:
            await asyncio.to_thread(
                memory.add,
                ctx["ext_agent_id"],
                [{"role": "user", "content": user_text}, {"role": "assistant", "content": full}],
            )
        yield f"event: trace\ndata: {json.dumps(trace, ensure_ascii=False)}\n\n"
        yield "event: done\ndata: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")

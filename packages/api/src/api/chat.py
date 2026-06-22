"""등록된 에이전트와의 대화 (SSE 스트리밍 노출)."""

import json
import uuid

from agent.main import build_agent
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from .db import SessionLocal
from .models import Agent
from .schemas import ChatRequest

router = APIRouter(prefix="/agents", tags=["chat"])


@router.post("/{agent_id}/chat")
async def chat(agent_id: uuid.UUID, body: ChatRequest):
    # 페르소나/파라미터만 읽고 세션을 즉시 닫는다 (스트리밍 동안 커넥션 점유 방지).
    async with SessionLocal() as session:
        record = await session.get(Agent, agent_id)
        if record is None:
            raise HTTPException(status_code=404, detail="agent not found")
        persona = record.persona
        # Phase 1: config에서 런타임 파라미터만 추출 (Phase 2에서 mem0/툴까지 확장).
        cfg = dict(record.config or {})
        params = {"temperature": cfg.get("temperature", 0.7)}

    graph = build_agent(persona, params)
    messages = [{"role": m.role, "content": m.content} for m in body.messages]

    async def event_stream():
        async for chunk, _meta in graph.astream(
            {"messages": messages}, stream_mode="messages"
        ):
            text = getattr(chunk, "content", "")
            if text:
                # JSON 인코딩으로 개행/필드 주입에 의한 SSE 프레임 깨짐 방지.
                yield f"data: {json.dumps({'text': text}, ensure_ascii=False)}\n\n"
        yield "event: done\ndata: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")

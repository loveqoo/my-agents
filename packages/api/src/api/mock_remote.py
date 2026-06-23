"""개발용 mock 원격 에이전트 (my-agents-sdk 배포 스탠드인).

코드 정의 에이전트가 가리키는 '원격 엔드포인트' 역할. 실제 외부 배포 대신
이 라우터가 같은 계약(POST {messages} → SSE text 프레임)을 구현해, 코드 에이전트
원격 프록시를 동작·테스트할 수 있게 한다. 인증은 검증하지 않는다(개발용).

지배 스펙: docs/spec/009-code-agent-remote-exec.md
"""

import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from .schemas import ChatRequest

router = APIRouter(prefix="/_remote", tags=["mock-remote"])


@router.get("/models")
async def remote_models():
    """OpenAI 호환 모델 목록(mock). chat 모델 연결 테스트의 결정적 대상."""
    return {"data": [{"id": "mock-chat", "object": "model"}]}


@router.post("/embeddings")
async def remote_embeddings(body: dict):
    """OpenAI 호환 임베딩(mock). embedding 모델 연결 테스트의 결정적 대상.
    입력과 무관하게 8차원 더미 벡터를 반환한다."""
    return {
        "object": "list",
        "data": [{"object": "embedding", "index": 0, "embedding": [0.1] * 8}],
        "model": body.get("model", "mock-embed"),
    }


@router.post("/agent")
async def remote_agent(body: ChatRequest):
    """원격 에이전트 채팅(mock). 마지막 사용자 메시지를 받아 간단히 스트리밍 응답."""
    last = body.messages[-1].content if body.messages else ""
    reply = (
        f"원격 에이전트(mock) 응답입니다. 요청 \"{last[:40]}\"을(를) 배포된 코드에서 처리했어요. "
        "이 응답은 등록된 엔드포인트에서 스트리밍되었습니다."
    )

    async def event_stream():
        # 토큰 단위로 쪼개 SSE text 프레임 전송 (chat.py 프록시가 그대로 재전송).
        step = 12
        for i in range(0, len(reply), step):
            chunk = reply[i : i + step]
            yield f"data: {json.dumps({'text': chunk}, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")

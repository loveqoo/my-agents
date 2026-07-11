"""개발용 mock 원격 에이전트 (my-agents-sdk 배포 스탠드인).

코드 정의 에이전트가 가리키는 '원격 엔드포인트' 역할. 실제 외부 배포 대신
이 라우터가 같은 계약(POST {messages} → SSE text 프레임)을 구현해, 코드 에이전트
원격 프록시를 동작·테스트할 수 있게 한다. 인증은 검증하지 않는다(개발용).

또한 OpenAI 호환 `/_remote/v1/*`(models·chat/completions)를 구현해 **레지스트리에
등록된 mock chat 모델**(`mock-llm`, 스펙 024)이 일반 런타임 경로(`build_agent` →
`ChatOpenAI`)로 결정적으로 돌게 한다 — 라이브 MLX 없이 동작·테스트.

지배 스펙: docs/spec/009-code-agent-remote-exec.md, docs/spec/024-mock-llm-registry-model.md
"""

import hashlib
import json
import struct
import time
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from .a2a_wire import a2a_error, a2a_result, a2a_status_event, a2a_user_text
from .models import RAG_EMBED_DIMS
from .schemas import ChatRequest

router = APIRouter(prefix="/_remote", tags=["mock-remote"])


@router.get("/models")
async def remote_models() -> dict:
    """OpenAI 호환 모델 목록(mock). chat 모델 연결 테스트의 결정적 대상."""
    return {"data": [{"id": "mock-chat", "object": "model"}]}


# ---------- OpenAI 호환 v1 (레지스트리 mock-llm 모델, 스펙 024) ----------


def _last_user_text(messages: list) -> str:
    """messages에서 마지막 user 메시지 텍스트를 뽑는다(멀티모달 content는 평탄화)."""
    for message in reversed(messages or []):
        if (message or {}).get("role") == "user":
            content = message.get("content")
            if isinstance(content, list):  # [{type,text}, ...] 멀티모달
                return " ".join(
                    str(p.get("text", "")) for p in content if isinstance(p, dict)
                ).strip()
            return str(content or "")
    return ""


def _mock_reply(messages: list) -> str:
    """마지막 user 메시지 기반 결정적 응답(입력 같으면 출력도 같음)."""
    last = _last_user_text(messages)
    return (
        f'[mock-llm] 요청 "{last[:60]}"에 대한 결정적 mock 응답입니다. '
        "등록된 mock 모델이 라이브 LLM 없이 응답했습니다."
    )


# ---------- 개발용 도구 트리거(스펙 179) ----------
# mock은 원래 툴콜을 못 낸다(평문만) → HIL 승인(delete_record) 등을 대화로 실습 불가. 바인딩된
# 도구가 있고 마지막 user 메시지가 트리거 키워드에 맞으면 그 도구의 tool_call을 결정적으로 낸다.
# 평상 채팅(트리거 무매치·도구 미바인딩)은 기존 평문 그대로 — 무회귀.
import re  # noqa: E402


def _extract_record_id(text: str) -> str:
    """user 텍스트에서 레코드 식별자 추출(r1·rec-001·42 등). 없으면 기본값."""
    m = re.search(
        r"[A-Za-z]+[-_]?\d+|\d+", text or ""
    )  # rec-001·r1 우선, 없으면 숫자(한글 접미 무관)
    return m.group(0) if m else "rec-001"


# 도구명 → (트리거 키워드들, 인자 빌더). 등록된 도구만, 결정적 규칙.
# search_documents(스펙 191) — RAG 도구가 바인딩되고 "검색/찾아" 등이 있으면 문서검색 tool_call을
# 결정적으로 낸다(인스펙터 RAG 표시·필터 e2e 실습용). query=user 텍스트(인스펙터 "검색어"에 그대로).
_TOOL_TRIGGERS: dict = {
    "delete_record": (
        ("삭제", "지워", "제거", "delete"),
        lambda t: {"record_id": _extract_record_id(t)},
    ),
    "search_documents": (
        ("검색", "찾아", "문서", "search"),
        lambda t: {"query": (t or "").strip()[:200]},
    ),
}


def _bound_tool_names(body: dict) -> set:
    names = set()
    for tool in body.get("tools") or []:
        fn = tool.get("function") if isinstance(tool, dict) else None
        name = fn.get("name") if isinstance(fn, dict) else None
        if name:
            names.add(name)
    return names


def _tool_params_schema(body: dict, name: str) -> dict:
    """바인딩된 도구의 parameters(JSON Schema) — 일반 트리거의 인자 조립용."""
    for tool in body.get("tools") or []:
        fn = tool.get("function") if isinstance(tool, dict) else None
        if isinstance(fn, dict) and fn.get("name") == name:
            return fn.get("parameters") or {}
    return {}


def _generic_args(schema: dict, text: str) -> dict | None:
    """required string 파라미터에 사용자 문장을 채우는 휴리스틱(캡 200자) — 임의 도구 실습용.
    required에 비-string(integer 등)이 있으면 **None(트리거 포기)** — 채울 수 없는 필수 인자를
    누락한 invalid tool_call을 만드느니 안 부르는 게 정직(codex 236 #5). required가 없으면
    첫 string 프로퍼티 하나에 채운다(무인자 호출로 헛돌지 않게)."""
    props = schema.get("properties") or {}
    required = list(schema.get("required") or [])
    if any((props.get(p) or {}).get("type") not in (None, "string") for p in required):
        return None
    if not required:
        required = [
            k for k, v in props.items() if isinstance(v, dict) and v.get("type") in (None, "string")
        ][:1]
    val = (text or "").strip()[:200]
    return dict.fromkeys(required, val)


def _pick_tool_call(body: dict) -> tuple[str, dict] | None:
    """트리거 매치면 (tool_name, args), 아니면 None(평문). messages에 tool 결과가 있으면(재개 후
    요약 턴) None — 무한 tool_call 루프 차단."""
    messages = body.get("messages") or []
    if any(isinstance(m, dict) and m.get("role") == "tool" for m in messages):
        return None
    bound = _bound_tool_names(body)
    if not bound:
        return None
    raw = _last_user_text(messages)
    low = raw.lower()
    for tool, (keywords, argfn) in _TOOL_TRIGGERS.items():
        # 그래프가 바인딩하는 실제 도구명은 네임스페이스가 붙는다(예: local-tools__delete_record) →
        # 정확명 또는 `__{tool}` suffix로 찾고, tool_call은 **실제 바인딩명**으로 emit(라우팅 정합).
        bound_name = next((b for b in bound if b == tool or b.endswith("__" + tool)), None)
        if bound_name and any(k.lower() in low for k in keywords):
            return bound_name, argfn(raw)
    # 일반 트리거(스펙 236) — 문장에 바인딩된 도구의 base 이름이 언급되면 그 도구를 호출
    # (예: "wiki_search로 파이썬 검색해줘"). mock으로도 임의 등록 도구 실습이 되게. 위 키워드
    # 트리거가 항상 우선(기존 테스트 결정성 보존). 오발동 방어(codex 236 #4): base 4자 미만 제외 +
    # **단어 경계 매칭**(search⊂research·echo⊂echolocation 우발 매치 차단).
    for name in sorted(bound):
        base = name.rsplit("__", 1)[-1]
        if len(base) >= 4 and re.search(
            rf"(?<![a-z0-9_]){re.escape(base.lower())}(?![a-z0-9_])", low
        ):
            text = re.sub(re.escape(base), " ", raw, flags=re.IGNORECASE).strip()
            args = _generic_args(_tool_params_schema(body, name), text or raw)
            if args is not None:  # None=required 비-string(채울 수 없음) → 트리거 포기
                return name, args
    return None


@router.get("/v1/models")
async def remote_v1_models() -> dict:
    """OpenAI 호환 모델 목록(mock-llm 연결 테스트 대상). probe가 `{base_url}/models`를 GET."""
    return {"object": "list", "data": [{"id": "mock-chat", "object": "model"}]}


# response_model=None: 반환이 dict|StreamingResponse 유니언이라 FastAPI 응답모델 생성 불가(계약 불변).
@router.post("/v1/chat/completions", response_model=None)
async def remote_v1_chat_completions(body: dict) -> dict | StreamingResponse:
    """OpenAI 호환 chat completions(mock). `ChatOpenAI`가 치는 계약.

    기본은 평문 응답(결정적). 단, **개발용 도구 트리거**(스펙 179) — 바인딩된 도구가 있고 마지막
    user 메시지가 트리거 키워드에 맞으면 그 도구의 `tool_call`을 낸다(HIL 승인 실습용).
    `stream:true`면 OpenAI chunk SSE, 아니면 단건 JSON.
    """
    messages = body.get("messages") or []
    model = body.get("model") or "mock-chat"
    cid = "chatcmpl-mock-" + uuid.uuid4().hex[:24]
    created = int(time.time())

    def _chunk(delta: dict, finish: str | None) -> str:
        payload = {
            "id": cid,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        }
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    # 개발용 도구 트리거(스펙 179) — 매치되면 평문 대신 tool_call.
    picked = _pick_tool_call(body)
    if picked is not None:
        tool_name, tool_args = picked
        tcid = "call_" + uuid.uuid4().hex[:20]
        args_json = json.dumps(tool_args, ensure_ascii=False)
        if not body.get("stream"):
            return {
                "id": cid,
                "object": "chat.completion",
                "created": created,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": tcid,
                                    "type": "function",
                                    "function": {"name": tool_name, "arguments": args_json},
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            }

        async def tool_stream() -> AsyncIterator[str]:
            yield _chunk({"role": "assistant"}, None)
            yield _chunk(
                {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": tcid,
                            "type": "function",
                            "function": {"name": tool_name, "arguments": ""},
                        }
                    ]
                },
                None,
            )
            step = 12
            for i in range(0, len(args_json), step):
                yield _chunk(
                    {
                        "tool_calls": [
                            {"index": 0, "function": {"arguments": args_json[i : i + step]}}
                        ]
                    },
                    None,
                )
            yield _chunk({}, "tool_calls")
            yield "data: [DONE]\n\n"

        return StreamingResponse(tool_stream(), media_type="text/event-stream")

    reply = _mock_reply(messages)
    if not body.get("stream"):
        return {
            "id": cid,
            "object": "chat.completion",
            "created": created,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": reply},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }

    async def event_stream() -> AsyncIterator[str]:
        yield _chunk({"role": "assistant"}, None)  # 첫 프레임에 role
        step = 12
        for i in range(0, len(reply), step):
            yield _chunk({"content": reply[i : i + step]}, None)
        yield _chunk({}, "stop")
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/v1/embeddings")
@router.post("/embeddings")
async def remote_embeddings(body: dict) -> dict:
    """OpenAI 호환 임베딩(mock) — embedding 모델 probe·RAG 인제스트의 결정적 대상.

    실제 모델처럼 **입력 1건당 벡터 1개**를 반환한다(배치 보존). 차원은 RAG 저장소 차원
    (`RAG_EMBED_DIMS`)에 맞춰 mock 임베딩 모델로 happy-path 인제스트가 결정적으로 통과하게
    한다. OpenAI `dimensions` 파라미터를 주면 그 길이로 잘라 차원 불일치 케이스도 흉내낼 수 있다.

    벡터는 **입력 텍스트에 결정적으로 의존**한다(sha256 시드). 같은 입력 → 같은 벡터(→ cosine 거리 0),
    다른 입력 → 다른 벡터(→ cosine 으로 변별 가능). 037 retrieval 검증이 랭킹 변별을 실제로 행사하도록
    상수 벡터(이전 `[0.1]*dims`, 모든 거리 0)를 대체했다. 프로세스 간 안정(파이썬 hash 무작위화 비의존).

    `/v1/embeddings`(mock provider base_url `/_remote/v1` 경유) + `/embeddings`(직접 probe) 둘 다 매핑.
    """
    inp = body.get("input")
    items = inp if isinstance(inp, list) else [inp if inp is not None else ""]
    if not items:
        items = [""]
    dims = int(body.get("dimensions") or RAG_EMBED_DIMS)
    return {
        "object": "list",
        "data": [
            {"object": "embedding", "index": i, "embedding": _det_embedding(str(text), dims)}
            for i, text in enumerate(items)
        ],
        "model": body.get("model", "mock-embed"),
        "usage": {"prompt_tokens": 0, "total_tokens": 0},
    }


def _det_embedding(text: str, dims: int) -> list[float]:
    """텍스트로 시드된 결정적 의사난수 벡터(길이 dims). [-0.5,0.5) 범위, 비영(non-zero) 보장.

    sha256를 카운터와 함께 반복 해시해 dims개 float을 채운다. 같은 텍스트 → 동일 벡터.
    """
    out: list[float] = []
    counter = 0
    while len(out) < dims:
        digest = hashlib.sha256(f"{text}#{counter}".encode()).digest()  # 32 bytes
        for offset in range(0, len(digest), 4):
            if len(out) >= dims:
                break
            (v,) = struct.unpack(">I", digest[offset : offset + 4])
            out.append(v / 4294967296.0 - 0.5)  # [-0.5, 0.5)
        counter += 1
    return out


# ---------- mock A2A Agent Card (외부 에이전트 등록 검증용, 스펙 026) ----------
@router.get("/.well-known/agent-card.json")
async def remote_agent_card() -> dict:
    """개발용 mock A2A Agent Card(**확장 없음** → provenance=external). `POST /agents/connect`가
    제3자로 분류하는 결정적 대상(SDK 카드 `/sdk/...`와 짝).

    베이스 `/_remote`로 등록하면 fetch_card가 well-known 관례로 이 카드를 찾는다. `x-my-agents`
    확장이 없으므로 connect는 external로 분류한다. 실 호출은 `/_remote/a2a` JSON-RPC(스펙 042)."""
    return {
        "name": "Mock A2A Weather Agent",
        "description": "개발용 mock 외부 에이전트 — 날씨 질의에 답하는 척하는 A2A 카드 스탠드인.",
        "url": "http://127.0.0.1:8000/_remote/a2a",
        "version": "1.0.0",
        "provider": {"organization": "my-agents-dev", "url": "http://127.0.0.1:8000"},
        "capabilities": {"streaming": True, "pushNotifications": False},
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain"],
        "skills": [
            {
                "id": "weather-now",
                "name": "현재 날씨",
                "description": "도시 이름을 받아 현재 날씨를 알려준다(mock).",
                "tags": ["weather"],
            }
        ],
    }


# ---------- mock 제1자(SDK) A2A Agent Card (connect provenance=code 검증용, 스펙 057) ----------
@router.get("/sdk/.well-known/agent-card.json")
async def remote_sdk_agent_card() -> dict:
    """개발용 mock **제1자(SDK 배포)** A2A Agent Card. `POST /agents/connect`가 source=code로
    분류하는 결정적 대상.

    weather 카드(확장 없음 → external)와 짝을 이뤄 connect 자동분류 양 분기를 결정적으로
    검증한다(045 self-fixture). `x-my-agents` 확장에 manifest(표시 메타)·deploy(provenance)를
    실어, 우리가 my-agents-sdk로 배포한 에이전트임을 자기선언한다. 실 서비스 호출은 기존
    `/_remote/a2a` JSON-RPC 재사용(런타임은 external과 동일 _a2a_stream)."""
    return {
        "name": "Mock SDK Translator (A2A)",
        "description": "개발용 mock 제1자 에이전트 — my-agents-sdk로 배포한 번역 에이전트 스탠드인.",
        "url": "http://127.0.0.1:8000/_remote/a2a",
        "version": "1.0.0",
        "provider": {"organization": "my-agents-dev", "url": "http://127.0.0.1:8000"},
        "capabilities": {"streaming": True, "pushNotifications": False},
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain"],
        "skills": [
            {
                "id": "translate",
                "name": "문서 번역",
                "description": "문서를 받아 다른 언어로 번역한다(mock).",
                "tags": ["translate"],
            }
        ],
        "x-my-agents": {
            "manifest": {
                "model": "mock-chat",
                "persona": "정확한 기술 번역가 (SDK)",
                "memories": ["용어집 일관성 유지"],
                "mcps": [],
                "historyDepth": 10,
            },
            "deploy": {
                "repo": "acme/doc-translator",
                "commit": "f3a91c2",
                "runtime": "my-agents-sdk · Python 2.4.1",
                "versions": [
                    {"version": "f3a91c2", "status": "active", "note": "Deploy · A2A 카드 동기화"},
                    {"version": "b1d77e0", "status": "archived", "note": "이전 배포"},
                ],
            },
        },
    }


# ---------- mock A2A JSON-RPC 서비스 (외부 에이전트 실호출 검증용, 스펙 042) ----------


def _a2a_reply(user_text: str) -> str:
    """결정적 mock 날씨 응답(같은 입력 → 같은 출력)."""
    return (
        f'[mock-a2a] "{user_text[:40]}" 요청에 답합니다. 현재 날씨는 맑음, 22도입니다(mock). '
        "이 응답은 외부 A2A 에이전트가 JSON-RPC로 보냈습니다."
    )


# response_model=None: 반환이 dict|StreamingResponse 유니언이라 FastAPI 응답모델 생성 불가(계약 불변).
@router.post("/a2a", response_model=None)
async def remote_a2a(body: dict) -> dict | StreamingResponse:
    """개발용 mock A2A JSON-RPC 엔드포인트(message/send·message/stream).

    카드(`/_remote/.well-known/agent-card.json`)가 광고하는 `url`. 외부 에이전트 실호출
    (`a2a_client.a2a_stream`)의 결정적 대상. 인증은 검증하지 않는다(개발용)."""
    rpc_id = body.get("id")
    method = body.get("method")
    params = body.get("params") or {}
    reply = _a2a_reply(a2a_user_text(params))

    if method == "message/send":
        # 단건: result = Message(role=agent, text part).
        return a2a_result(
            rpc_id,
            {
                "role": "agent",
                "parts": [{"kind": "text", "text": reply}],
                "messageId": uuid.uuid4().hex,
                "kind": "message",
            },
        )

    if method == "message/stream":
        # 스트리밍: status-update 이벤트 여러 개(텍스트 청크) + final.
        task_id = uuid.uuid4().hex

        async def event_stream() -> AsyncIterator[str]:
            step = 16
            chunks = [reply[i : i + step] for i in range(0, len(reply), step)] or [""]
            for i, chunk in enumerate(chunks):
                last = i == len(chunks) - 1
                yield a2a_status_event(
                    rpc_id,
                    task_id,
                    chunk,
                    final=last,
                    state="completed" if last else "working",
                )
            yield "data: [DONE]\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    # 미지원 메서드 → JSON-RPC error.
    return a2a_error(rpc_id, -32601, f"메서드 미지원: {method}")


@router.post("/agent")
async def remote_agent(body: ChatRequest) -> StreamingResponse:
    """원격 에이전트 채팅(mock). 마지막 사용자 메시지를 받아 간단히 스트리밍 응답."""
    last = body.messages[-1].content if body.messages else ""
    reply = (
        f'원격 에이전트(mock) 응답입니다. 요청 "{last[:40]}"을(를) 배포된 코드에서 처리했어요. '
        "이 응답은 등록된 엔드포인트에서 스트리밍되었습니다."
    )

    async def event_stream() -> AsyncIterator[str]:
        # 토큰 단위로 쪼개 SSE text 프레임 전송 (chat.py 프록시가 그대로 재전송).
        step = 12
        for i in range(0, len(reply), step):
            chunk = reply[i : i + step]
            yield f"data: {json.dumps({'text': chunk}, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")

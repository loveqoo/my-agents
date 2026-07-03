"""로컬(ui) 에이전트를 실제 A2A로 서빙 (스펙 061).

`exposed.a2a=True`인 로컬 에이전트를 well-known Agent Card + JSON-RPC(message/send·stream)로 노출해,
우리 자신의 에이전트를 A2A로 등록·테스트(dogfood)할 수 있게 한다. canned mock(mock_remote)이 아니라
**실 로컬 LangGraph 런타임**(chat.stream_local_reply)을 그대로 돌린다.

라우터는 **전역 인증 없이** 마운트한다(main.py — mock_remote와 동일 패턴). 이유: 등록 시 우리 서버가
자기 카드를 fetch하는데(agent_card.fetch_card는 인증 헤더 미전송), 카드가 전역 인증 뒤면 self-fetch가
401로 깨진다. 그래서 **카드는 공개**, **JSON-RPC 호출만 라우트 단위 인증**(current_principal)한다.

게이트(두 라우트 공통): 존재 + source==ui + exposed.a2a is True. 하나라도 아니면 404(노출 안 된
에이전트의 존재·구성을 누출하지 않음 — fail-closed).
"""

import json
import os
import uuid
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from . import a2a_client, chat, net_guard
from .auth import current_principal
from .db import SessionLocal
from .models import Agent

router = APIRouter(prefix="/agents", tags=["a2a-server"])


async def _load_exposed_agent(agent_id: uuid.UUID) -> Agent:
    """노출 게이트(스펙 154). 존재 + source∈{ui, code} + exposed.a2a is True. 아니면 404(누출 없음).
    ui=로컬 런타임 직접 실행, code=제1자 SDK 배포를 우리 A2A가 중계(릴레이). external은 재공개
    금지(152) — expose 입구에서 이미 400이지만 여기서도 404로 접는다(이중 게이트)."""
    async with SessionLocal() as db:
        agent = await db.get(Agent, agent_id)
    if agent is None or agent.source not in ("ui", "code") or not (agent.exposed or {}).get("a2a"):
        raise HTTPException(status_code=404, detail="노출된 로컬 에이전트가 아닙니다")
    return agent


def _self_base(request: Request) -> str:
    """카드 url 구성용 self base. env `A2A_SELF_BASE_URL` 우선, 없으면 request.base_url(로컬 한정).

    카드의 서비스 `url`(JSON-RPC 엔드포인트)은 절대 http(s)여야 한다(connect가 그걸 호출 endpoint로
    저장). env가 신뢰 경계다. **Host 헤더 오염 방어(적대리뷰 H1, 스펙 061 §5)**: A2A_SELF_BASE_URL이
    설정되면 그걸 신뢰하고 request.base_url(=Host 파생)은 무시한다. 미설정이면 request.base_url을
    **로컬/사설 Host에만** 허용한다 — 공인 Host로 들어온 요청에 env가 없으면 `Host: attacker.example`로
    카드 url을 공격자 호스트로 돌려 이후 A2A 호출의 프롬프트·Bearer 토큰을 탈취당할 수 있으므로 거부
    (운영자가 A2A_SELF_BASE_URL을 명시하도록 강제). 루프백 dogfood(127.0.0.1)·Tailscale(100.x)는 통과.
    """
    env = (os.environ.get("A2A_SELF_BASE_URL") or "").strip()
    if env:
        if not env.lower().startswith(("http://", "https://")):
            raise HTTPException(
                status_code=500,
                detail="A2A_SELF_BASE_URL은 'http(s)://host[:port]' 절대 URL이어야 합니다.",
            )
        return env.rstrip("/")
    base = str(request.base_url)
    host = urlparse(base).hostname or ""
    if not net_guard.host_is_private(host):
        # 공인 Host인데 self-base env가 없다 — 카드 url 오염 위험으로 fail-closed(설정 강제).
        raise HTTPException(
            status_code=503,
            detail=(
                "공개 호스트로 A2A 카드를 서빙하려면 환경변수 A2A_SELF_BASE_URL을 이 서버의 절대 "
                "URL(예: https://my-host.example)로 설정해야 합니다(Host 헤더 신뢰 불가)."
            ),
        )
    return base.rstrip("/")


async def _org_name() -> str:
    """카드 organization(스펙 153) — 저장값 → env A2A_ORG_NAME → "my-agents".
    저장 *여부*로 분기(codex 153 — 값 비교 추정은 관리자가 기본 문자열로 의도 저장한 경우를 뭉갠다)."""
    import os

    from .app_settings import get_setting_stored

    found, org = await get_setting_stored("a2a_org_name")
    if found:
        return org
    return os.environ.get("A2A_ORG_NAME", "my-agents")


@router.get("/{agent_id}/.well-known/agent-card.json")
async def exposed_agent_card(agent_id: uuid.UUID, request: Request):
    """공개 — 노출된 ui 에이전트의 A2A 카드. connect가 fetch해 external로 분류(x-my-agents 없음).

    base 입력 `<self>/agents/<id>`로 connect하면 fetch_card가 well-known 관례로 이 카드를 찾는다.
    카드 `url`=`<self>/agents/<id>/a2a`가 호출 endpoint로 저장된다.
    """
    agent = await _load_exposed_agent(agent_id)
    base = _self_base(request)
    org = await _org_name()  # 설정→env→기본 3단(스펙 153, 무재시작 반영)
    return {
        "name": agent.name,
        "description": f"{agent.name} — 로컬 에이전트의 A2A 노출(스펙 061).",
        "url": f"{base}/agents/{agent_id}/a2a",
        "version": agent.active_version or "1.0.0",
        "provider": {"organization": org, "url": base},
        "capabilities": {"streaming": True, "pushNotifications": False},
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain"],
        "skills": [
            {
                "id": "chat",
                "name": agent.name,
                "description": "이 로컬 에이전트와 대화한다(A2A).",
                "tags": ["chat"],
            }
        ],
    }


def _a2a_user_text(params: dict) -> str:
    """JSON-RPC params.message.parts[].text(kind=='text')를 모아 잇는다(a2a_client 송신과 동형)."""
    msg = (params or {}).get("message") or {}
    parts = msg.get("parts") or []
    out = []
    for p in parts:
        if isinstance(p, dict) and p.get("kind") == "text" and p.get("text"):
            out.append(str(p["text"]))
    return "".join(out)


RELAY_HEADER = "x-my-agents-relay"  # 중계 홉 표식(스펙 154) — 표식 달린 요청은 재중계 거부(1홉 한정)


def _relay_chunks(agent: Agent, user_text: str):
    """code(제1자 SDK 배포) 에이전트로 중계(스펙 154) — a2a_client 경유(SSRF 가드·캡·타임아웃 그대로).
    text 프레임을 청크로 yield, error 프레임은 RuntimeError로(호출측이 JSON-RPC error로 접음 —
    a2a_client의 error 메시지는 우리가 생성한 문구라 비밀 에코 없음)."""

    async def _gen():
        async for frame in a2a_client.a2a_stream(
            agent.endpoint or "", agent.token, user_text,
            streaming=True, extra_headers={RELAY_HEADER: "1"},
        ):
            if frame.get("text"):
                yield frame["text"]
            elif "error" in frame:
                raise RuntimeError(str(frame["error"])[:200])

    return _gen()


@router.post("/{agent_id}/a2a")
async def exposed_agent_a2a(
    agent_id: uuid.UUID, body: dict, request: Request, principal=Depends(current_principal)
):
    """인증 — 노출된 에이전트의 JSON-RPC(message/send·stream). ui=실 로컬 런타임, code=1홉 중계(스펙 154).

    인증은 current_principal(쿠키 유저 또는 머신 토큰) — a2a_client가 등록 토큰을 Bearer로 실어
    보낸다. 무인증/잘못된 토큰 → 401. 실행 예외는 JSON-RPC error로(자격증명·내부정보 미에코).
    """
    agent = await _load_exposed_agent(agent_id)
    rpc_id = body.get("id")
    method = body.get("method")
    params = body.get("params") or {}
    user_text = _a2a_user_text(params)

    if agent.source == "code":
        if request.headers.get(RELAY_HEADER):
            # 루프 가드(스펙 154): 중계 표식이 달린 요청을 다시 중계하면 자기/상호 참조 사이클 —
            # 2번째 홉에서 절단. 직접 소비자(플레이그라운드·외부)는 표식이 없어 정상.
            return {
                "jsonrpc": "2.0", "id": rpc_id,
                "error": {"code": -32000, "message": "중계 루프 감지 — 다홉 중계는 지원하지 않습니다(1홉 한정)"},
            }
        chunk_source = _relay_chunks(agent, user_text)
    else:
        chunk_source = chat.stream_local_reply(agent.id, user_text)

    def _response(result: dict) -> dict:
        return {"jsonrpc": "2.0", "id": rpc_id, "result": result}

    def _error(code: int, message: str) -> dict:
        return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": code, "message": message}}

    if method == "message/send":
        try:
            acc: list[str] = []
            async for text in chunk_source:
                acc.append(text)
            reply = "".join(acc)
        except Exception as exc:  # noqa: BLE001 — 타입만 에코(자격증명/내부정보 누출 방지)
            return _error(-32000, f"로컬 에이전트 실행 실패({type(exc).__name__})")
        return _response(
            {
                "role": "agent",
                "parts": [{"kind": "text", "text": reply}],
                "messageId": uuid.uuid4().hex,
                "kind": "message",
            }
        )

    if method == "message/stream":
        task_id = uuid.uuid4().hex

        def _status_event(text: str, *, final: bool, state: str) -> str:
            result = {
                "kind": "status-update",
                "taskId": task_id,
                "status": {
                    "state": state,
                    "message": {
                        "role": "agent",
                        "parts": [{"kind": "text", "text": text}],
                        "kind": "message",
                    },
                },
                "final": final,
            }
            return f"data: {json.dumps(_response(result), ensure_ascii=False)}\n\n"

        async def event_stream():
            try:
                async for text in chunk_source:
                    yield _status_event(text, final=False, state="working")
            except Exception as exc:  # noqa: BLE001 — 타입만 에코
                err = _error(-32000, f"로컬 에이전트 실행 실패({type(exc).__name__})")
                yield f"data: {json.dumps(err, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"
                return
            yield _status_event("", final=True, state="completed")
            yield "data: [DONE]\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    return _error(-32601, f"메서드 미지원: {method}")

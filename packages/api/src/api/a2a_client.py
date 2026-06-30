"""A2A 런타임 클라이언트 전송 (스펙 042, 026 2차).

외부(`source="external"`) 에이전트를 **실제로 호출**하는 계층. A2A는 JSON-RPC 2.0 +
SSE다(코드-에이전트의 `_remote_stream` `{messages}`→`{text}` 포맷과 비호환 → 별도 전송).

- 스트리밍: `message/stream` → SSE, 각 `data:`가 JSONRPCResponse. result kind별로 텍스트 추출.
- 단건: `message/send` → 단일 JSONRPCResponse(카드 capabilities.streaming=false 폴백).
- 보안: `net_guard.guard_url`(SSRF), 응답 누적 상한, 타임아웃, 4xx 본문 미에코(자격증명 누출 방지).

`a2a_stream`은 `{"text": ...}` / `{"error": ...}` dict를 yield한다(라우터가 우리 SSE로 재전송).
"""

import json
import uuid

import httpx

from . import crypto
from .net_guard import guard_url, normalize_http_url, refresh_allowed_hosts

# A2A 응답 누적 상한 — 악의적/오작동 에이전트가 끝없이 흘려 메모리·시간을 소진하는 걸 막는다.
MAX_RESPONSE_BYTES = 1024 * 1024
A2A_TIMEOUT_S = 120


def _jsonrpc_request(user_text: str, *, streaming: bool, context_id: str | None = None) -> dict:
    """message/send|stream JSON-RPC 요청 본문. params.message는 A2A Message(role=user, text part).

    context_id가 있으면 message.contextId로 실어 멀티턴을 잇는다 — A2A는 호출당 단일 메시지를 보내고
    대화 맥락은 contextId로 서버가 유지한다(스펙 표준). 057에서 _remote_stream(윈도우 히스토리 인라인
    전송)을 폐기하며, 멀티턴 책임을 A2A 표준대로 contextId로 옮겼다(적대리뷰 057 Finding 2)."""
    method = "message/stream" if streaming else "message/send"
    message: dict = {
        "role": "user",
        "parts": [{"kind": "text", "text": user_text}],
        "messageId": uuid.uuid4().hex,
        "kind": "message",
    }
    if context_id:
        message["contextId"] = context_id
    return {
        "jsonrpc": "2.0",
        "id": uuid.uuid4().hex,
        "method": method,
        "params": {"message": message},
    }


def _parts_text(parts: object) -> str:
    """A2A parts 배열에서 text part만 모아 잇는다. 형식 관대(아니면 빈 문자열)."""
    if not isinstance(parts, list):
        return ""
    out: list[str] = []
    for p in parts:
        if isinstance(p, dict) and p.get("kind") == "text":
            t = p.get("text")
            if isinstance(t, str) and t:
                out.append(t)
    return "".join(out)


def extract_text(result: object) -> str:
    """JSONRPCResponse.result(Message/Task/status-update/artifact-update)에서 표시 텍스트 추출.

    A2A는 result 모양이 여러 가지다. kind/필드를 보고 관대하게 텍스트만 뽑는다(미지원 모양은 빈 문자열).
    """
    if not isinstance(result, dict):
        return ""
    kind = result.get("kind")
    # TaskStatusUpdateEvent: {kind:"status-update", status:{message:{parts}}}
    if kind == "status-update":
        status = result.get("status")
        if isinstance(status, dict):
            msg = status.get("message")
            if isinstance(msg, dict):
                return _parts_text(msg.get("parts"))
        return ""
    # TaskArtifactUpdateEvent: {kind:"artifact-update", artifact:{parts}}
    if kind == "artifact-update":
        artifact = result.get("artifact")
        if isinstance(artifact, dict):
            return _parts_text(artifact.get("parts"))
        return ""
    # Message: {role:"agent", parts:[...]} (kind 생략되거나 "message")
    if "parts" in result:
        return _parts_text(result.get("parts"))
    # Task: {status:{message:{parts}}} (+ 선택적 artifacts)
    status = result.get("status")
    if isinstance(status, dict):
        msg = status.get("message")
        if isinstance(msg, dict):
            txt = _parts_text(msg.get("parts"))
            if txt:
                return txt
    artifacts = result.get("artifacts")
    if isinstance(artifacts, list):
        return "".join(_parts_text(a.get("parts")) for a in artifacts if isinstance(a, dict))
    return ""


def _is_final(result: object) -> bool:
    """status-update의 final 플래그(스트림 종료 신호)."""
    return isinstance(result, dict) and result.get("kind") == "status-update" and bool(
        result.get("final")
    )


def _frame_from_response(resp_obj: dict) -> dict | None:
    """JSONRPCResponse → {text}/{error}/None. error 우선, 없으면 result에서 텍스트."""
    if not isinstance(resp_obj, dict):
        return None
    err = resp_obj.get("error")
    if isinstance(err, dict):
        # JSON-RPC error message만(자격증명·내부정보 누출 방지 위해 코드/메시지만).
        msg = err.get("message") or "외부 에이전트 오류"
        return {"error": f"외부 에이전트 오류: {msg}"}
    text = extract_text(resp_obj.get("result"))
    if text:
        return {"text": text}
    return None


def _auth_headers(token: str | None) -> dict:
    """저장 토큰 복호화 → Bearer. 마스킹(`•`) 값이면 헤더 생략(`_remote_stream` 동일 규칙)."""
    tok = crypto.decrypt(token)
    if tok and "•" not in tok:
        return {"Authorization": f"Bearer {tok}"}
    return {}


async def a2a_stream(
    endpoint: str,
    token: str | None,
    user_text: str,
    *,
    streaming: bool = True,
    context_id: str | None = None,
):
    """외부 A2A 엔드포인트를 호출하고 {text}/{error} 프레임을 yield. SSRF 가드·캡·타임아웃 적용.

    context_id(우리 세션 id)를 주면 message.contextId로 실어 서버가 멀티턴 맥락을 잇게 한다(스펙 057).
    이 제너레이터는 절대 raise하지 않는다 — 모든 실패를 {error} 프레임으로 변환(라우터가 done까지 보냄).
    """
    try:
        # 호출 경계 자가치유(스펙 063): 등록 정규화(스펙 060) 이전에 만들어졌거나 정규화를 건너뛴
        # 경로의 스킴 없는 endpoint를 호출 직전 절대화한다 — 안 하면 guard_url이 "URL은 http(s)
        # 절대 URL이어야 합니다"로 모호하게 깨진다(learning 065: 계약은 경로 전체에서 유지). 보안 불변:
        # 절대화만 하고 사설 판정은 guard_url이 정규화된 url에 그대로 돌아 수행한다(우회 아님).
        endpoint = normalize_http_url(endpoint)
        await refresh_allowed_hosts()  # DB allowlist 무재시작 반영(스펙 064)
        guard_url(endpoint)
    except ValueError as exc:
        yield {"error": str(exc)}
        return

    body = _jsonrpc_request(user_text, streaming=streaming, context_id=context_id)
    try:
        # 토큰 복호화(키 회전 시 RuntimeError 가능)도 try 안에서 — try 밖이면 미프레임 크래시(적대리뷰 H3).
        headers = {"Content-Type": "application/json", **_auth_headers(token)}
        # redirects 비활성(명시) — 리다이렉트로 SSRF 가드/Authorization 경계를 우회 못 하게.
        async with httpx.AsyncClient(timeout=A2A_TIMEOUT_S, follow_redirects=False) as client:
            if streaming:
                fell_back = False
                async for frame in _stream_sse(client, endpoint, body, headers):
                    if "_fallback" in frame:  # stream 404/405 — send로 1회 폴백(스펙 081 P3)
                        fell_back = True
                        break
                    yield frame
                if fell_back:
                    # 같은 endpoint·headers로 message/send 1회. _fallback은 본문 전에만 나오므로(상태
                    # 코드 검사 시점) 텍스트 이중방출 없음. send도 실패하면 그 에러 프레임을 그대로 전달.
                    send_body = _jsonrpc_request(user_text, streaming=False, context_id=context_id)
                    async for frame in _send_single(client, endpoint, send_body, headers):
                        yield frame
            else:
                async for frame in _send_single(client, endpoint, body, headers):
                    yield frame
    except httpx.HTTPError as exc:
        # 본문/헤더는 보낸 토큰을 에코할 수 있어 메시지에 넣지 않는다 — 예외 타입만.
        yield {"error": f"외부 에이전트 요청 실패({type(exc).__name__})"}
    except Exception as exc:  # noqa: BLE001 — decrypt RuntimeError 등도 프레임으로(스트림 미크래시)
        yield {"error": f"외부 에이전트 호출 실패({type(exc).__name__})"}


async def _capped_lines(resp):
    """응답을 raw 바이트로 읽으며 MAX_RESPONSE_BYTES를 누적 상한으로 강제하고 줄 단위로 내준다.

    `aiter_lines`는 개행 없는 입력을 무한 버퍼링하므로(적대리뷰 H2) raw 바이트를 직접 세야 한다.
    상한 초과 시 마지막에 None을 내 신호한다(호출자가 에러 프레임 후 종료)."""
    buf = b""
    total = 0
    async for chunk in resp.aiter_bytes():
        total += len(chunk)
        if total > MAX_RESPONSE_BYTES:
            yield None  # 상한 초과 신호
            return
        buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            yield line.decode("utf-8", errors="replace")
    if buf:
        yield buf.decode("utf-8", errors="replace")


async def _stream_sse(client, endpoint, body, headers):
    async with client.stream(
        "POST", endpoint, json=body, headers={**headers, "Accept": "text/event-stream"}
    ) as resp:
        # stream 라우트/메서드 부재(404/405)는 본문 전이라 message/send 폴백이 안전하다(스펙 081 P3).
        # 신호만 내고 종료 — a2a_stream이 같은 endpoint로 1회 send 폴백. 표준 단일-endpoint 서버에선
        # send도 같은 404라 동일 실패지만, stream만 별도 라우트로 둔 비표준 서버를 구제한다.
        if resp.status_code in (404, 405):
            # 본문을 읽지 않고 신호만 낸다 — 폴백은 같은 endpoint로 _send_single을 새로 열어 본문이
            # 불필요하고, 적대 응답의 거대 에러 바디를 aread로 무경계 버퍼링하지 않는다(적대리뷰 081 F1,
            # memory: cap-the-raw-source). `async with client.stream`이 미소비 응답을 닫는다.
            yield {"_fallback": resp.status_code}
            return
        if resp.status_code >= 400:
            await resp.aread()  # 본문 소비하되 에코 금지(자격증명 누출 방지)
            yield {"error": f"외부 에이전트 응답 오류 {resp.status_code}"}
            return
        async for line in _capped_lines(resp):
            if line is None:  # 누적 상한 초과
                yield {"error": "외부 에이전트 응답이 너무 큽니다"}
                return
            line = line.rstrip("\r")
            if not line.startswith("data:"):
                continue
            data = line[5:].lstrip()
            if data == "[DONE]":
                break
            try:
                resp_obj = json.loads(data)
            except json.JSONDecodeError:
                continue
            frame = _frame_from_response(resp_obj)
            if frame:
                yield frame
            if _is_final(resp_obj.get("result") if isinstance(resp_obj, dict) else None):
                break


async def _send_single(client, endpoint, body, headers):
    # 단건도 stream으로 읽어 raw 바이트 캡을 강제한다 — resp.content는 전체를 먼저 버퍼링(적대리뷰 H1).
    async with client.stream(
        "POST", endpoint, json=body, headers={**headers, "Accept": "application/json"}
    ) as resp:
        if resp.status_code >= 400:
            await resp.aread()
            yield {"error": f"외부 에이전트 응답 오류 {resp.status_code}"}
            return
        chunks: list[bytes] = []
        total = 0
        async for chunk in resp.aiter_bytes():
            total += len(chunk)
            if total > MAX_RESPONSE_BYTES:
                yield {"error": "외부 에이전트 응답이 너무 큽니다"}
                return
            chunks.append(chunk)
    try:
        resp_obj = json.loads(b"".join(chunks))
    except (json.JSONDecodeError, ValueError):
        yield {"error": "외부 에이전트 응답이 JSON이 아닙니다"}
        return
    frame = _frame_from_response(resp_obj)
    if frame:
        yield frame

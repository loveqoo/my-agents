"""전역 요청 body 상한 미들웨어(스펙 415 P1) — pre-parse 메모리 DoS 차단.

이전엔 앱 전역 body limit이 없어 수백 MB JSON이 전부 수신·파싱된 뒤에야 스키마 422가 났다
(per-endpoint 캡은 첨부 5MB raw·RAG PUT 선검사만 점재). 여기서 ASGI 층으로 내려 한 관문에서
막는다([[policy-at-the-chokepoint]]):

- **Content-Length 선검사**: 헤더가 상한 초과를 선언하면 본문 수신 전 413(빠른 거절).
- **raw receive 누적 실측**: 헤더는 스푸핑 가능(learning 041 — 캡은 raw 바이트에서) —
  receive 메시지의 body 길이를 누적해 상한 초과 시점에 413. chunked 전송도 잡는다.

상한(2026-07-20 개발자 승인값 — 사용자 가시 한계): 기본 2MB, 업로드 라우트(/chat/attachments)만
6MB(파일 5MB + multipart 오버헤드). 프록시/인프라 층 limit은 배포 미정의라 OUT(앱 층이 1차 방어).
"""

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

Scope = dict[str, Any]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]

log = logging.getLogger("api.body_limit")

BODY_CAP = 2 * 1024 * 1024  # 기본 2MB(승인값)
UPLOAD_CAP = 6 * 1024 * 1024  # 첨부 업로드 6MB(승인값 — 파일 5MB + multipart 오버헤드)


def _rag_cap() -> int:
    """RAG 업로드/편집 상한 — rag.limits와 **같은 값**(+multipart/JSON 오버헤드 1MB). env
    (RAG_MAX_UPLOAD_MB)로 조정되는 값이라 import 시점 고정 대신 호출 시 조회(정합 단일 출처)."""
    from .rag.limits import MAX_UPLOAD_BYTES

    return MAX_UPLOAD_BYTES + 1024 * 1024


def _cap_for(path: str) -> int:
    if path == "/chat/attachments":
        return UPLOAD_CAP
    # RAG 문서 업로드/편집(/collections/{cid}/documents[/{id}])은 자체 캡 25MB(rag.limits)가 관할 —
    # 전역 2MB로 덮으면 정상 업로드가 깨진다(limits.py가 "전역 미들웨어 몫"으로 예고한 층이 여기).
    # **세그먼트 매칭**(codex 415 P2 — 부분문자열은 /documentsXYZ 같은 임의 경로에 큰 캡을 준다).
    segs = path.split("/")
    if len(segs) >= 4 and segs[1] == "collections" and segs[3] == "documents":
        return _rag_cap()
    return BODY_CAP


def _too_large_body(cap: int) -> bytes:
    mb = cap // (1024 * 1024)
    return json.dumps(
        {"detail": f"요청 본문이 너무 큽니다 — {mb}MB까지 보낼 수 있습니다."},
        ensure_ascii=False,
    ).encode()


class BodyLimitMiddleware:
    """순수 ASGI 미들웨어 — BaseHTTPMiddleware는 body를 선버퍼링해 캡 취지가 죽으므로 쓰지 않는다."""

    def __init__(self, app: Callable) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        cap = _cap_for(scope.get("path", ""))

        # ① Content-Length 선검사 — 정직한 클라이언트는 본문 수신 없이 즉시 거절.
        for k, v in scope.get("headers", []):
            if k == b"content-length":
                try:
                    if int(v) > cap:
                        await self._reject(send, cap)
                        return
                except ValueError:
                    pass  # 비정상 헤더는 실측 경로가 잡는다
                break

        # ② raw 수신 누적 실측 — 헤더 스푸핑·chunked 무력(learning 041 cap-raw-source).
        # 예외로 앱을 뚫고 나오는 방식은 못 쓴다: FastAPI가 body 파싱 중 예외를 전부
        # 400("error parsing the body")으로 삼킨다(실측). 대신 초과 시점에 ①수신을 disconnect로
        # 접고(앱이 더 못 읽게) ②앱이 아직 응답을 **시작 안 했으면** send를 413으로 재작성한다.
        # 앱이 이미 응답을 시작한 뒤 초과가 감지되면(요청·응답 동시 스트리밍) start를 못 덮으므로
        # (이중 start 금지) 재작성하지 않고 그대로 흘린다 — 현 FastAPI 라우트는 body 파싱 후 핸들러
        # 진입이라 이 분기 미도달(codex 415 P2 방어).
        state = {"received": 0, "too_large": False, "app_started": False, "rewritten": False}

        async def limited_receive() -> dict[str, Any]:
            msg = await receive()
            if msg["type"] == "http.request" and not state["too_large"]:
                state["received"] += len(msg.get("body", b""))
                if state["received"] > cap:
                    state["too_large"] = True
                    return {"type": "http.disconnect"}
            return msg

        async def rewriting_send(msg: dict[str, Any]) -> None:
            if state["rewritten"]:
                return  # 우리 413(start+body) 이미 전송 — 뒤따르는 앱 프레임 전부 버린다
            # 재작성 가능 조건: 초과 감지 + 앱이 아직 응답 start 전. 앱의 첫 프레임(start)을 가로채
            # 413 start+body를 한 번에 보내고 나머지 앱 출력을 봉쇄한다.
            if state["too_large"] and not state["app_started"]:
                body = _too_large_body(cap)
                await send(
                    {
                        "type": "http.response.start",
                        "status": 413,
                        "headers": [
                            (b"content-type", b"application/json; charset=utf-8"),
                            (b"content-length", str(len(body)).encode()),
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": body})
                state["rewritten"] = True
                return
            if msg["type"] == "http.response.start":
                state["app_started"] = True
            await send(msg)

        await self.app(scope, limited_receive, rewriting_send)

    @staticmethod
    async def _reject(send: Send, cap: int) -> None:
        body = _too_large_body(cap)
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json; charset=utf-8"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

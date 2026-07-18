"""업로드/본문 크기 상한 — shared.py에서 분할(스펙 398 P1).

POST 업로드(documents.upload)와 PUT 편집(_content_length_guard)이 **같은 값**을 봐야 한다
(codex 398 함정 5 — 두 입구 단일 캡). 파사드 없음 — 소비자는 이 모듈을 직접 import.
"""

import os

from fastapi import HTTPException, Request

# 업로드 상한 — `await file.read()`는 전체를 메모리로 올리므로 무제한이면 단일/동시 업로드로 OOM.
# 기본 25MB, RAG_MAX_UPLOAD_MB로 조정. 초과 시 413(적재 전 차단).
MAX_UPLOAD_BYTES = int(os.environ.get("RAG_MAX_UPLOAD_MB", "25")) * 1024 * 1024


async def _content_length_guard(request: Request) -> None:
    """PUT 본문 크기 선검사(codex 331 P2) — Pydantic이 JSON을 파싱하기 *전에* Content-Length로
    거대 요청을 차단한다(파싱 후 len 검사만 있으면 이미 메모리에 올라온 뒤라 상한이 방어가 아님).
    **정직 경계**: Content-Length 없는 chunked 전송은 이 선검사를 우회한다(h11 수신 자체의 누적
    상한은 플랫폼 전역 미들웨어 몫 — 인증 필수 admin 표면이라 수용, 본검사 len(data)가 이중 그물)."""
    cl = request.headers.get("content-length", "")
    if cl.isdigit() and int(cl) > MAX_UPLOAD_BYTES + 65536:  # JSON 이스케이프 여유
        limit_mb = MAX_UPLOAD_BYTES // (1024 * 1024)
        raise HTTPException(status_code=413, detail=f"본문이 너무 큽니다(최대 {limit_mb}MB).")

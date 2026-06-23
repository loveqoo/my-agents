"""API 인증 — Bearer 토큰.

토큰 출처(우선순위): env `API_AUTH_TOKEN` → `.dev/.api_token`(없으면 생성·영속, gitignore).
도메인 라우터에 `Depends(require_auth)`로 적용. 단일 워크스페이스이므로 인증=소유자 전체 접근
(다중 사용자 RBAC는 추후).

지배 스펙: docs/spec/011-api-auth.md
"""

import logging
import secrets
from functools import lru_cache
from pathlib import Path

from fastapi import Header, HTTPException

log = logging.getLogger("api.auth")


@lru_cache(maxsize=1)
def _token() -> str:
    import os

    tok = (os.environ.get("API_AUTH_TOKEN") or "").strip()
    if tok:
        return tok
    # auth.py = packages/api/src/api/auth.py → parents[4] = repo 루트
    path = Path(__file__).resolve().parents[4] / ".dev" / ".api_token"
    if path.exists():
        existing = path.read_text().strip()
        if existing:  # 빈 파일이면 무시하고 재생성(빈 토큰 인증 방지)
            return existing
    tok = "mat_" + secrets.token_urlsafe(24)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tok)
    log.warning("API_AUTH_TOKEN 미설정 — %s에 개발용 토큰 생성. UI는 같은 값을 VITE_API_TOKEN로.", path)
    return tok


async def require_auth(authorization: str | None = Header(default=None)) -> None:
    """`Authorization: Bearer <token>` 검증. 누락/형식오류/불일치 → 401."""
    expected = _token()
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="인증 필요 (Bearer 토큰)")
    presented = authorization[7:]
    # 빈 토큰 거부 + 상수시간 비교(타이밍 공격 방지).
    if not presented or not secrets.compare_digest(presented, expected):
        raise HTTPException(status_code=401, detail="유효하지 않은 토큰")

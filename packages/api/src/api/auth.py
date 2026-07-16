"""API 인증 — Bearer 토큰.

토큰 출처(우선순위): env `API_AUTH_TOKEN` → `.dev/.api_token`(없으면 생성·영속, gitignore).
도메인 라우터에 `Depends(require_auth)`로 적용. 단일 워크스페이스이므로 인증=소유자 전체 접근
(다중 사용자 RBAC는 추후).

지배 스펙: docs/spec/011-api-auth.md
"""

import logging
import secrets
from collections.abc import Awaitable, Callable
from functools import lru_cache
from pathlib import Path

from fastapi import Header, HTTPException

from . import audit
from .models import User

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
    log.warning(
        "API_AUTH_TOKEN 미설정 — %s에 개발용 토큰 생성. UI는 같은 값을 VITE_API_TOKEN로.", path
    )
    return tok


def is_valid_machine_token(authorization: str | None) -> bool:
    """머신 Bearer 토큰 유효성(예외 없이 bool). 통합 principal의 fallback에 사용."""
    if not authorization or not authorization.startswith("Bearer "):
        return False
    presented = authorization[7:]
    # 빈 토큰 거부 + 상수시간 비교(타이밍 공격 방지).
    return bool(presented) and secrets.compare_digest(presented, _token())


async def require_auth(authorization: str | None = Header(default=None)) -> None:
    """`Authorization: Bearer <token>` 검증. 누락/형식오류/불일치 → 401."""
    if not is_valid_machine_token(authorization):
        raise HTTPException(status_code=401, detail="유효하지 않은 토큰")


# 통합 principal — 세션 쿠키 유저(fastapi-users) OR 머신 Bearer 토큰 둘 다 허용(하위호환).
# 도메인 라우터의 게이트로 쓴다(반환값은 인증 주체: User 또는 "machine"). 민감 라우트는 추가로
# authz.require(obj, act)로 보호한다. auth.py 임포트 시점에 users를 끌어오지 않도록 지연 import. 스펙 031.
def _make_current_principal() -> Callable[..., Awaitable[User | str]]:
    from fastapi import Depends

    from .users import current_user_optional

    async def _principal(
        authorization: str | None = Header(default=None),
        user: User | None = Depends(current_user_optional),
    ) -> User | str:
        if user is not None:  # 세션 쿠키 인증
            audit.set_actor(audit.actor_of(user))  # 감사 actor(스펙 343) — 이메일 로컬파트
            return user
        if is_valid_machine_token(authorization):  # 머신 토큰 인증
            audit.set_actor(audit.SYSTEM_ACTOR)  # 사람 아닌 주체
            return "machine"
        raise HTTPException(status_code=401, detail="인증 필요")

    return _principal


current_principal = _make_current_principal()


def resolve_memory_user_id(principal: "User | str", requested: str | None) -> str | None:
    """mem0 user 축 정체성 결정(스펙 387) — 모든 입구(chat body·A2A metadata)가 이 단일 관문을 지난다.

    - requested 없음: 쿠키 유저=자기 id, 머신 토큰=None(세션 축만 — 기존 동작 보존).
    - requested 있음: **머신 토큰만 수용**(owner 전권의 위임 호출 — 외부 시스템이 자기 유저를 대신).
      쿠키 유저가 보내면 422 — 자기 정체성 위조 금지(스펙 032의 보안 목적 보존). 조용한 무시가 아니라
      명시 거부(스펙 383 결 — 안 읽는 소스로 온 정체성이 조용히 다른 값으로 떨어지면 안 된다).
    - 위생: strip 후 빈값=미지정. NUL(0x00)은 pg text 불가라 422. 200자 캡(payload 위생).
    """
    if requested is not None:
        requested = requested.strip()
    if not requested:
        return None if isinstance(principal, str) else str(principal.id)
    if not isinstance(principal, str):
        raise HTTPException(
            status_code=422,
            detail="userId는 머신 토큰 호출에서만 지정할 수 있습니다 — 로그인 사용자는 본인 정체성으로 기억합니다.",
        )
    # 캡 80 = 세션/승인 영속 컬럼 String(80)과 정렬(codex 387 P2 — 관문 수용치가 저장 경계를 넘으면
    # commit에서 늦게 터진다. 수용치는 가장 좁은 하류 경계에 맞춘다).
    if "\x00" in requested or len(requested) > 80:
        raise HTTPException(
            status_code=422, detail="userId 형식 오류 — 80자 이하의 일반 문자열이어야 합니다."
        )
    return requested

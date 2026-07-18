"""설정 오류 SSE·모델 연결 힌트 — chat_stream.py에서 분할(스펙 392 P1, 순수 이동).

설정 오류 SSE(스펙 089), 모델 연결 힌트(스펙 058 G4). 파사드는 chat.py(재수출 계약).
"""

import json
import logging
from collections.abc import AsyncIterator

log = logging.getLogger("api.chat")


async def _config_error_stream(impl_key: str) -> AsyncIterator[str]:
    """설정 실패(스펙 089) — 선언한 in-process 구현이 미해결. default로 만회하지 않고 SSE로 정직히
    통보한다. **클라이언트 메시지는 일반화**(impl 값 미반영) — config["impl"]은 관리자가 임의로 저장한
    값(합의 B)이라 *레지스트리 키임이 증명되지 않으며*, 채팅 클라이언트는 관리자보다 권한이 낮을 수
    있다(GET /agents의 impl은 인증 관리자 전용). 구체 키는 서버 로그에만 남겨 운영 디버깅을 보존한다
    (codex 적대 리뷰 089-F1: 미해결 impl 원문이 SSE로 새던 정보노출 봉합 — 비밀누출 0)."""
    log.warning("config_error 채팅 거부: 미해결 impl %r", impl_key)
    msg = "에이전트 설정 오류로 응답할 수 없습니다 — 관리자에게 문의하세요(런타임 구현 미해결)."
    yield f"data: {json.dumps({'error': msg}, ensure_ascii=False)}\n\n"
    yield "event: done\ndata: [DONE]\n\n"


# 연결-실패로 보이는 에러의 지문(httpx/openai/asyncpg 계층 공통). model_id 불일치(404 등)나
# 인증 오류(401)는 *연결*이 아니므로 힌트를 붙이지 않는다 — 잘못된 안내가 더 혼란스럽다.
_CONN_ERR_MARKERS = (
    "connection error",
    "connection refused",
    "cannot connect",
    "all connection attempts failed",
    "connect call failed",
    "errno 61",
    "name or service not known",
    "timed out",
    "timeout",
    "apiconnectionerror",
    "connecterror",
    "max retries exceeded",
)


def _model_error_hint(exc: Exception, model_cfg: dict | None) -> str | None:
    """모델 연결 실패로 보이면 전환 힌트(없으면 None). 스펙 058 G4 — 기본 chat은 무외부 'Mock LLM'
    (스펙 059)이라 곧장 실패하지 않는다. 이 힌트는 운영자가 Provider UI로 추가한 실 모델을 기본으로
    전환했는데 그 서버가 안 떠 있을 때 첫 채팅이 연결 실패하는 경우를 위한 것이다."""
    if not model_cfg:
        return None
    blob = f"{type(exc).__name__} {exc}".lower()
    if not any(m in blob for m in _CONN_ERR_MARKERS):
        return None
    base_url = model_cfg.get("base_url", "")
    return (
        f"채팅 모델 연결 실패 (base_url={base_url}) — 모델 서버가 떠 있는지/주소가 맞는지 확인하세요. "
        "외부 모델 없이 바로 시험하려면 admin에서 기본 채팅 모델을 'Mock LLM'으로 되돌리세요"
        "(무외부 동작, 기본값)."
    )

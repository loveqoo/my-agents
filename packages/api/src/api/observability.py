"""관측·측정 계층(스펙 118) — LangGraph 실행 trace를 **Langfuse로 내보내되 설정될 때만** 켜진다.

설계 원칙(사용자 선택 "설정되면 켜지게"): **inert-until-configured**. `LANGFUSE_PUBLIC_KEY`·
`LANGFUSE_SECRET_KEY` 환경변수가 **둘 다** 있을 때만 콜백 핸들러를 붙이고, 없으면 조용히 무동작(no-op).
패키지 미설치·핸들러 생성 실패도 예외 없이 빈 콜백으로 접는다(핵심 채팅 경로가 관측 때문에 깨지지
않게 — 관측은 부가물이지 하중이 아니다). 키는 외부 비밀이라 코드/로그에 절대 남기지 않는다(env만 읽음).

기존 관측(스펙 085/086/100 — trace 이벤트·broker_invoke 노드)은 그대로. Langfuse는 그 위에 얹는
**외부 집계/측정** 계층으로, 수치 기반 자율(목표 주고 반복)의 토대가 된다.
"""

from __future__ import annotations

import os


def is_configured() -> bool:
    """Langfuse 활성 조건 — 공개키·비밀키가 **둘 다** env에 있을 때만(키 자체는 읽되 값은 노출 안 함)."""
    return bool(os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY"))


def _make_handler():
    """Langfuse LangChain 콜백 핸들러 생성 — 미설치/실패 시 None(graceful). v3(langfuse.langchain)
    우선, v2(langfuse.callback) 폴백. 핸들러는 env에서 키·host를 자동으로 읽는다."""
    try:
        from langfuse.langchain import CallbackHandler  # langfuse v3
    except Exception:
        try:
            from langfuse.callback import CallbackHandler  # langfuse v2 폴백
        except Exception:
            return None
    try:
        return CallbackHandler()
    except Exception:
        return None


def trace_callbacks(_factory=_make_handler) -> list:
    """이 실행에 붙일 콜백 리스트 — 미설정이면 **[]**(inert). 설정+핸들러 가용이면 [handler]."""
    if not is_configured():
        return []
    handler = _factory()
    return [handler] if handler is not None else []


def with_trace(
    config: dict | None,
    *,
    name: str | None = None,
    session_id: str | None = None,
    user_id: str | None = None,
    metadata: dict | None = None,
    _factory=_make_handler,
) -> dict:
    """실행 config에 Langfuse 콜백·메타데이터를 **병합**한다(미설정이면 원본 그대로 — 무동작). 기존
    callbacks/metadata를 덮지 않고 확장한다. session_id/user_id는 Langfuse 표준 키로 실어 trace를 묶는다."""
    cbs = trace_callbacks(_factory)
    if not cbs:
        return config or {}
    cfg = dict(config or {})
    # 기존 callbacks는 list일 수도, None일 수도, CallbackManager(비-iterable)일 수도 있다(RunnableConfig
    # 계약 = Any|None). splat은 list만 안전하므로 타입별로 접어 **절대 던지지 않는다**(codex 118 P2 —
    # 관측 헬퍼가 채팅 경로를 깨면 안 됨). 현 배선 3곳은 callbacks 미주입이라 항상 None 경로.
    existing = cfg.get("callbacks")
    if existing is None:
        cfg["callbacks"] = list(cbs)
    elif isinstance(existing, list):
        cfg["callbacks"] = [*existing, *cbs]
    else:  # CallbackManager/단일 핸들러 등 — 리스트로 감싸 병합(비-iterable splat 회피)
        cfg["callbacks"] = [existing, *cbs]
    md = dict(metadata or {})
    if session_id:
        md["langfuse_session_id"] = session_id
    if user_id:
        md["langfuse_user_id"] = str(user_id)
    if md:
        base_md = cfg.get("metadata")
        cfg["metadata"] = {**(base_md if isinstance(base_md, dict) else {}), **md}
    if name:
        cfg["run_name"] = name
    return cfg

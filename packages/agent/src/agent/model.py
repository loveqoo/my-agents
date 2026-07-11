"""모델 구성 정본(스펙 295) — 주입된 model_cfg로 ChatOpenAI를 만드는 유일한 곳.

이전엔 route·orchestrate·plan_execute·artifact·pipeline·main 6곳이 같은 구성 블록을 복제했다
(도크스트링이 "동일 규칙"이라 상호참조로 자백). 차이 지점(cfg 출처·미설정 처리·기본 temperature·
에러 문구)만 인자로 뽑아 하나로 합친다. env·DB 미접촉 — 모델은 레지스트리 해석본(cfg)만 쓴다.
"""

from __future__ import annotations

from typing import Literal, overload

from langchain_openai import ChatOpenAI

_MISSING_MSG = "모델 설정이 필요합니다 (base_url/model_id) — 모델을 등록하세요."


# on_missing="raise"(기본)면 None 불가 → 호출부가 model을 바로 쓴다. "none"이면 None 가능(artifact).
@overload
def build_chat_openai(
    cfg: dict | None,
    params: dict | None = ...,
    *,
    default_temperature: float = ...,
    on_missing: Literal["raise"] = ...,
    error_label: str = ...,
) -> ChatOpenAI: ...
@overload
def build_chat_openai(
    cfg: dict | None,
    params: dict | None = ...,
    *,
    default_temperature: float = ...,
    on_missing: Literal["none"],
    error_label: str = ...,
) -> ChatOpenAI | None: ...
def build_chat_openai(
    cfg: dict | None,
    params: dict | None = None,
    *,
    default_temperature: float = 0.7,
    on_missing: str = "raise",
    error_label: str = _MISSING_MSG,
) -> ChatOpenAI | None:
    """model_cfg → ChatOpenAI. base_url/model_id 없으면 `on_missing`: "raise"(기본)면 명확히 실패,
    "none"이면 None 반환(모델 없이도 도는 경로용 — artifact ask-only). temperature 우선순위:
    호출자 params > 모델 등록 params > `default_temperature`."""
    cfg = cfg or {}
    base_url = cfg.get("base_url") or ""
    model_id = cfg.get("model_id") or ""
    if not base_url or not model_id:
        if on_missing == "none":
            return None
        raise RuntimeError(error_label)
    cfg_params = cfg.get("params") or {}
    params = params or {}
    temperature = params.get("temperature", cfg_params.get("temperature", default_temperature))
    enable_thinking = cfg_params.get("enable_thinking", False)
    return ChatOpenAI(
        base_url=base_url,
        api_key=cfg.get("api_key") or "sk-noauth",
        model=model_id,
        temperature=temperature,
        extra_body={"chat_template_kwargs": {"enable_thinking": enable_thinking}},
    )

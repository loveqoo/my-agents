"""모델 구성 정본(스펙 295) — 주입된 model_cfg로 ChatOpenAI를 만드는 유일한 곳.

이전엔 route·orchestrate·plan_execute·artifact·pipeline·main 6곳이 같은 구성 블록을 복제했다
(도크스트링이 "동일 규칙"이라 상호참조로 자백). 차이 지점(cfg 출처·미설정 처리·기본 temperature·
에러 문구)만 인자로 뽑아 하나로 합친다. env·DB 미접촉 — 모델은 레지스트리 해석본(cfg)만 쓴다.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Literal, overload

from langchain_openai import ChatOpenAI

from .capabilities import PARAMS, resolve_effective, resolve_number
from .reasoning_chat import ReasoningChatOpenAI

_MISSING_MSG = "모델 설정이 필요합니다 (base_url/model_id) — 모델을 등록하세요."

# 프로바이더별 클라이언트 풀(스펙 371 D2) — 프로세스-로컬, 상한 초과 시 최고령 축출.
_CLIENT_POOL: dict[tuple, ChatOpenAI] = {}
_CLIENT_POOL_MAX = 64


def _resolve_wire_params(
    caps: dict, params: dict, cfg_params: dict, default_temperature: float
) -> tuple[dict, dict, bool]:
    """PARAMS 서술자(스펙 411)로 유효값을 해석·wire 배선 → (top_kwargs, extra_body, disable_streaming).

    build_chat_openai에서 추출(스펙 416 — CC 분해). 층 우선순위=호출자 params(세션) > cfg_params
    (모델·에이전트·노드 병합). bool=능력 AND 설정(게이트), number=범위 클램프. wire별 배선이 유일한
    축별 코드: top=ChatOpenAI 직접 kwargs, extra_body=비표준, disable_streaming.
    """
    top_kwargs: dict = {}
    chat_template_kwargs: dict = {}
    extra_body: dict = {}
    disable_streaming = False
    for p in PARAMS:
        if p.kind == "bool":
            eff = resolve_effective(p.key, caps, params, cfg_params)
            if p.wire == "disable_streaming":
                disable_streaming = not eff
            elif p.wire == "extra_body":
                chat_template_kwargs[p.key] = eff
            continue
        # number
        if p.key == "temperature":
            # temperature는 미명시 시 caller default_temperature 존중(기존 계약 — 스펙 077 흡수).
            num = resolve_number("temperature", params, cfg_params)
            explicit = any(
                isinstance(lay.get("temperature"), (int, float))
                and not isinstance(lay.get("temperature"), bool)
                for lay in (params, cfg_params)
            )
            num = num if explicit else default_temperature
        else:
            num = resolve_number(p.key, params, cfg_params)
        if p.key == "max_tokens" and (num is None or num <= 0):
            continue  # 0/미설정=서버 기본(안 보냄)
        if num is None:
            continue
        if p.wire == "top":
            top_kwargs[p.key] = num
        elif p.wire == "extra_body":
            extra_body[p.key] = num
    if chat_template_kwargs:
        extra_body["chat_template_kwargs"] = chat_template_kwargs
    return top_kwargs, extra_body, disable_streaming


def _pool_key(
    loop_id: int | None,
    base_url: str,
    api_key: str,
    model_id: str,
    top_kwargs: dict,
    extra_body: dict,
    disable_streaming: bool,
) -> tuple:
    """클라이언트 풀 키(스펙 371 D2) — 해석된 모든 파라미터 반영(스펙 411, 값 다르면 다른 클라이언트).
    api_key는 지문으로만(평문 저장 금지). loop_id 포함 — httpx async 클라는 자기 이벤트 루프에 묶인다."""
    return (
        loop_id,
        base_url,
        hashlib.sha256(api_key.encode()).hexdigest()[:8],
        model_id,
        json.dumps(top_kwargs, sort_keys=True),
        json.dumps(extra_body, sort_keys=True),
        disable_streaming,
    )


def _pool_remember(key: tuple, client: ChatOpenAI) -> None:
    """LRU 저장(삽입순 최고령 축출, 상한 _CLIENT_POOL_MAX). loop_id None(동기)은 호출부가 미저장."""
    if len(_CLIENT_POOL) >= _CLIENT_POOL_MAX:
        _CLIENT_POOL.pop(next(iter(_CLIENT_POOL)))
    _CLIENT_POOL[key] = client


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
    # 파라미터 유효값 해석·wire 배선(스펙 411 — temperature·top_p·max_tokens·repetition_penalty·
    # stream·enable_thinking 단일 메커니즘). 상세 규칙은 _resolve_wire_params(스펙 416 추출).
    top_kwargs, extra_body, disable_streaming = _resolve_wire_params(
        cfg.get("capabilities") or {}, params or {}, cfg.get("params") or {}, default_temperature
    )
    api_key = cfg.get("api_key") or "sk-noauth"
    # 클라이언트 풀(스펙 371 D2) — 같은 연결·모델·파라미터면 인스턴스 재사용(ChatOpenAI는 호출간
    # 무상태·async-safe). 목적은 생성 비용(~0.1ms)이 아니라 **커넥션 재사용**(실 프로바이더 TLS
    # 핸드셰이크 — mock 루프백 사각지대). 루프별 격리 — httpx async 클라는 자기 이벤트 루프에 묶인다.
    # 서버는 루프 하나라 늘 적중, asyncio.run 반복(in-proc 테스트)은 루프마다 새 인스턴스(죽은 루프
    # 엔트리는 LRU 축출). 루프 밖(동기)이면 풀 미사용.
    try:
        loop_id = id(asyncio.get_running_loop())
    except RuntimeError:
        loop_id = None
    key = _pool_key(loop_id, base_url, api_key, model_id, top_kwargs, extra_body, disable_streaming)
    if loop_id is not None and (pooled := _CLIENT_POOL.get(key)) is not None:
        return pooled
    # ReasoningChatOpenAI(스펙 410): base가 버리는 reasoning_content를 additional_kwargs로 되살린다
    # (사고 없는 모델·응답엔 무영향 — 항상 써도 안전). 사고 과정 표시(410 P2/P3)가 이를 소비.
    # top_kwargs=temperature/top_p/max_tokens(표준 인자), extra_body=enable_thinking/repetition_penalty(비표준).
    client = ReasoningChatOpenAI(
        base_url=base_url,
        api_key=api_key,
        model=model_id,
        # 능력 없음/사용 끔 → astream이 ainvoke로 접혀 완성문 1회 yield(비스트리밍 안전 실행).
        disable_streaming=disable_streaming,
        extra_body=extra_body,
        **top_kwargs,
    )
    if loop_id is not None:
        _pool_remember(key, client)
    return client

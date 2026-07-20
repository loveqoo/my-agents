"""모델 구성 정본(스펙 295) — 주입된 model_cfg로 ChatOpenAI를 만드는 유일한 곳.

이전엔 route·orchestrate·plan_execute·artifact·pipeline·main 6곳이 같은 구성 블록을 복제했다
(도크스트링이 "동일 규칙"이라 상호참조로 자백). 차이 지점(cfg 출처·미설정 처리·기본 temperature·
에러 문구)만 인자로 뽑아 하나로 합친다. env·DB 미접촉 — 모델은 레지스트리 해석본(cfg)만 쓴다.
"""

from __future__ import annotations

import asyncio
import hashlib
from typing import Literal, overload

from langchain_openai import ChatOpenAI

from .capabilities import resolve_effective
from .reasoning_chat import ReasoningChatOpenAI

_MISSING_MSG = "모델 설정이 필요합니다 (base_url/model_id) — 모델을 등록하세요."

# 프로바이더별 클라이언트 풀(스펙 371 D2) — 프로세스-로컬, 상한 초과 시 최고령 축출.
_CLIENT_POOL: dict[tuple, ChatOpenAI] = {}
_CLIENT_POOL_MAX = 64


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
    # 능력→설정 유효값(스펙 409): 서술자 목록(capabilities.py) 단일 정본이 "능력 AND 설정"을 계산.
    # 층 우선순위=호출자 params(세션) > cfg params(모델·에이전트·노드 병합). 능력 false면 어느 층도
    # 못 켠다(부분집합 불가침) — streaming뿐 아니라 thinking도 능력 게이트(408은 thinking 미게이트였음).
    # SDK 배선만 축별로 다르다: stream→disable_streaming, enable_thinking→extra_body(그 매핑이 유일한
    # 축별 코드). 스트리밍 꺼짐=LangChain이 astream을 ainvoke로 접어 완성문 1회 yield(SSE 계약 유지).
    caps = cfg.get("capabilities") or {}
    stream_effective = resolve_effective("streaming", caps, params, cfg_params)
    enable_thinking = resolve_effective("thinking", caps, params, cfg_params)
    api_key = cfg.get("api_key") or "sk-noauth"
    # 클라이언트 풀(스펙 371 D2) — 같은 연결·모델·파라미터면 인스턴스 재사용(ChatOpenAI는 호출간
    # 무상태·async-safe). 목적은 생성 비용(~0.1ms)이 아니라 **커넥션 재사용**(실 프로바이더 TLS
    # 핸드셰이크 — mock 루프백 사각지대). 키에 api_key 지문 포함 → 로테이션=새 인스턴스.
    # 루프별 격리 — httpx async 클라이언트는 자기 이벤트 루프에 묶인다. 서버는 루프 하나라 늘
    # 적중하고, 루프를 새로 여는 컨텍스트(in-process 테스트의 asyncio.run 반복)는 루프마다 새
    # 인스턴스(죽은 루프의 엔트리는 LRU가 축출). 루프 밖(동기)이면 풀 미사용.
    try:
        loop_id = id(asyncio.get_running_loop())
    except RuntimeError:
        loop_id = None
    key = (
        loop_id,
        base_url,
        hashlib.sha256(api_key.encode()).hexdigest()[:8],
        model_id,
        temperature,
        enable_thinking,
        stream_effective,  # 스트리밍 모드가 다르면 다른 클라이언트(풀 키 분리 — 스펙 408)
    )
    pooled = _CLIENT_POOL.get(key) if loop_id is not None else None
    if pooled is not None:
        return pooled
    # ReasoningChatOpenAI(스펙 410): base가 버리는 reasoning_content를 additional_kwargs로 되살린다
    # (사고 없는 모델·응답엔 무영향 — 항상 써도 안전). 사고 과정 표시(410 P2/P3)가 이를 소비.
    client = ReasoningChatOpenAI(
        base_url=base_url,
        api_key=api_key,
        model=model_id,
        temperature=temperature,
        # 능력 없음/사용 끔 → astream이 ainvoke로 접혀 완성문 1회 yield(비스트리밍 안전 실행).
        disable_streaming=not stream_effective,
        extra_body={"chat_template_kwargs": {"enable_thinking": enable_thinking}},
    )
    if loop_id is not None:
        if len(_CLIENT_POOL) >= _CLIENT_POOL_MAX:
            _CLIENT_POOL.pop(next(iter(_CLIENT_POOL)))  # 최고령 축출(삽입순)
        _CLIENT_POOL[key] = client
    return client

"""모델 파라미터·능력 서술자 단일 정본(스펙 409 → 411 확장).

**두 축**:
- **능력(capability)**: 모델이 선언하는 사실(streaming/thinking/vision). `ModelConfig.capabilities` JSONB.
  불가침 — 에이전트가 없는 능력을 켤 수 없다(부분집합 원칙).
- **파라미터(param)**: 요청별 튜닝값(stream·enable_thinking·temperature·top_p·max_tokens·
  repetition_penalty). 캐스케이드(모델→에이전트→노드→세션)로 오버라이드. 일부는 능력 게이트(bool).

**이 목록 하나**가 백엔드 화이트리스트·유효값·유효성·admin 4화면(모델·에이전트·플레이그라운드·노드)을
전부 구동한다. 파라미터를 추가하려면 `PARAMS`에 **한 줄**만 더하면 된다(스펙 408이 키를 하드코딩해
"설정마다 재구현"이 된 뿌리를 교정, 411이 temperature·숫자 파라미터까지 일반화 — 3중 불균일 소멸).

agent 패키지에 둔 이유: agent(model.py)와 api가 모두 임포트해야 하는데 agent가 하위 층이라 순환 없음
(api→agent 단방향). SDK 배선(ChatOpenAI 인자 매핑)만 build_chat_openai가 `wire`별로 갖는다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


def _is_finite_number(v: object) -> bool:
    """진짜 유한 수치만 인정(스펙 411 codex P2③) — bool 배제, NaN/Infinity 거부(int() 변환 예외·
    클램프 무의미 차단)."""
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)

# ----------------------------- 능력 사실 -----------------------------
# 모델이 선언하는 능력(ModelConfig.capabilities JSONB). vision은 능력만(요청 파라미터 없음 — 첨부 축).
CAPABILITIES: tuple[str, ...] = ("streaming", "thinking", "vision")
# 능력 기본값(신규 모델·누락 보정) — 마이그레이션 server_default와 단일 출처.
DEFAULT_CAPABILITIES: dict[str, bool] = {"streaming": True, "thinking": False, "vision": False}
_CAP_LABEL: dict[str, str] = {"streaming": "스트리밍", "thinking": "Thinking 모드", "vision": "비전(이미지)"}


# ----------------------------- 파라미터 서술자 -----------------------------
@dataclass(frozen=True)
class ParamDescriptor:
    """요청별 튜닝 파라미터 하나(스펙 411).

    - key: modelParams 키(요청·저장·오버라이드에서 쓰는 이름).
    - kind: "bool" | "number".
    - label: admin UI 라벨.
    - default: 모델 층 기본값(미명시 상속의 바닥).
    - wire: build_chat_openai가 API에 실는 방식 — "disable_streaming"|"extra_body"|"top".
    - cap: 능력 게이트(bool만) — 이 능력이 false면 어느 층도 못 켬. None이면 게이트 없음.
    - minimum/maximum/step/is_int: number 범위(클램프·UI 슬라이더).
    """

    key: str
    kind: str
    label: str
    default: float | bool
    wire: str
    cap: str | None = None
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    is_int: bool = False
    advanced: bool = False  # UI 고급 접기 축(스펙 412) — 핵심 파라미터는 펼치고 나머지는 Collapse.


# 정본 목록 — 여기에 한 줄 = 4화면+백엔드 전체 반영. 구남님 승인(411): temperature 흡수(077 은퇴),
# repetition_penalty·top_p·max_tokens 추가. max_tokens=0/미설정은 "서버 기본"(안 보냄).
PARAMS: tuple[ParamDescriptor, ...] = (
    ParamDescriptor("stream", "bool", "스트리밍", True, "disable_streaming", cap="streaming"),
    ParamDescriptor("enable_thinking", "bool", "Thinking 모드", False, "extra_body", cap="thinking"),
    ParamDescriptor("temperature", "number", "Temperature", 0.7, "top", minimum=0.0, maximum=2.0, step=0.1),
    ParamDescriptor("max_tokens", "number", "최대 토큰", 0, "top", minimum=0, maximum=32768, step=1, is_int=True),
    # 고급(스펙 412 — 기본 화면서 접힘): top_p·repetition_penalty는 세밀 튜닝 축.
    ParamDescriptor("top_p", "number", "Top P", 1.0, "top", minimum=0.0, maximum=1.0, step=0.05, advanced=True),
    ParamDescriptor("repetition_penalty", "number", "반복 패널티", 1.0, "extra_body", minimum=0.5, maximum=2.0, step=0.05, advanced=True),
)

_BY_KEY: dict[str, ParamDescriptor] = {p.key: p for p in PARAMS}
# 요청별 조정 가능한 파라미터 키(화이트리스트 파생) — 에이전트/노드/세션 오버라이드는 이 집합만 수용.
PARAM_KEYS: tuple[str, ...] = tuple(p.key for p in PARAMS)


def _as_bool(value: object, default: bool) -> bool:
    """**진짜 bool만** 인정하고 그 외(문자열 "false"·정수·None)는 default로 폴백(스펙 409 codex P1②).
    `bool("false")`가 True인 함정을 실행부에서 봉인 — 게이트가 문자열 주입으로 뚫리지 않는다."""
    return value if isinstance(value, bool) else default


def _cap_default(cap: str) -> bool:
    return DEFAULT_CAPABILITIES.get(cap, True)


def resolve_effective(cap_or_key: str, capabilities: dict, *layers: dict) -> bool:
    """bool 파라미터의 유효값 = **능력 AND 설정**(스펙 409 — 능력 false면 어느 층도 못 켬).

    cap_or_key: 능력 키(streaming/thinking) 또는 파라미터 키(stream/enable_thinking) — 둘 다 허용.
    설정값은 층을 뒤에서 앞으로 훑어 처음 명시된 진짜 bool을 취하고, 없으면 서술자 default.
    """
    # 능력 키로 왔으면 대응 파라미터 서술자를 찾는다(stream↔streaming, enable_thinking↔thinking).
    d = _BY_KEY.get(cap_or_key)
    if d is None:
        d = next((p for p in PARAMS if p.cap == cap_or_key), None)
    if d is None or d.kind != "bool":
        return False
    cap = d.cap
    capable = _as_bool(capabilities.get(cap), _cap_default(cap)) if cap else True
    want = bool(d.default)
    for layer in layers:
        if layer and isinstance(layer.get(d.key), bool):
            want = layer[d.key]
            break
    return capable and want


def resolve_number(key: str, *layers: dict) -> float | int | None:
    """number 파라미터의 유효값 — 층을 뒤에서 앞으로 훑어 처음 명시된 수치를 취하고, 없으면 서술자
    default. 범위 클램프. max_tokens처럼 default=0(미설정=서버 기본)이면 0 반환(호출부가 안 보냄)."""
    d = _BY_KEY.get(key)
    if d is None or d.kind != "number":
        return None
    val: float | int | None = d.default
    for layer in layers:
        if not layer:
            continue
        raw = layer.get(key)
        if _is_finite_number(raw):
            val = raw
            break
    if val is None:
        return None
    if d.minimum is not None:
        val = max(d.minimum, val)
    if d.maximum is not None:
        val = min(d.maximum, val)
    return int(val) if d.is_int else float(val)


def clean_model_params(mp: object) -> dict:
    """modelParams 정리 — 화이트리스트 키의 **타입·범위 검증** 통과분만 보존(스펙 411). bool은 진짜
    bool만, number는 진짜 수치(bool 배제)만·범위 클램프. 에이전트/노드/세션 저장 경계가 공유(하드코딩
    없음 — 서술자 파생). 미지 키·타입 불일치는 드롭(문자열 "false"로 게이트 우회 차단)."""
    if not isinstance(mp, dict):
        return {}
    out: dict = {}
    for key, val in mp.items():
        d = _BY_KEY.get(key)
        if d is None:
            continue
        if d.kind == "bool" and isinstance(val, bool):
            out[key] = val
        elif d.kind == "number" and _is_finite_number(val):
            num = val
            if d.minimum is not None:
                num = max(d.minimum, num)
            if d.maximum is not None:
                num = min(d.maximum, num)
            out[key] = int(num) if d.is_int else float(num)
    return out


# 하위호환 별칭(스펙 409 소비처) — 411에서 clean_model_params가 정본, 이 이름은 재수출.
clean_setting_params = clean_model_params
SETTING_KEYS = PARAM_KEYS


def clean_capabilities(caps: object) -> dict:
    """능력(capabilities) 정리 — 알려진 능력 키의 **진짜 bool만** 보존(스펙 409). 비-bool은 드롭
    (그 능력은 저장 안 됨 → cap_default 폴백 = 안전 기본)."""
    if not isinstance(caps, dict):
        return {}
    return {c: caps[c] for c in CAPABILITIES if isinstance(caps.get(c), bool)}


def descriptors_public() -> dict:
    """admin 공급용 서술자(GET /model-capabilities/descriptors) — FE가 이걸 받아 4화면을 렌더.

    FE/BE 드리프트 0(사본 금지). capabilities(사실 축)와 params(튜닝 축)를 함께 실어 FE가 모델 폼의
    능력 토글과 파라미터 오버라이드를 각각 렌더한다."""
    return {
        "capabilities": [
            {"cap": c, "label": _CAP_LABEL.get(c, c), "capDefault": DEFAULT_CAPABILITIES.get(c, False)}
            for c in CAPABILITIES
        ],
        "params": [
            {
                "key": p.key,
                "kind": p.kind,
                "label": p.label,
                "default": p.default,
                "wire": p.wire,
                "cap": p.cap,
                "min": p.minimum,
                "max": p.maximum,
                "step": p.step,
                "isInt": p.is_int,
                "advanced": p.advanced,
            }
            for p in PARAMS
        ],
    }

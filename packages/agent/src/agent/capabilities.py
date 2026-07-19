"""능력→설정 서술자 단일 정본(스펙 409).

능력(capability)=모델이 선언하는 사실(불가침) / 설정(usage)=능력에서 파생하는 요청별 조정값.
**이 목록 하나**가 백엔드 화이트리스트·유효값 계산·유효성·admin 4화면(모델·에이전트·플레이그라운드·
노드)을 전부 구동한다. 설정을 추가하려면 이 목록에 **한 줄**만 더하면 된다(스펙 408이 키 두 개를
다섯 곳에 하드코딩해 "설정마다 재구현"이 된 뿌리를 교정 — 회고 261 "사본이면 드리프트"의 설정 축 판).

agent 패키지에 둔 이유: agent(model.py)와 api가 모두 임포트해야 하는데 agent가 하위 층이라 순환이
없다(api→agent 단방향). SDK 배선(ChatOpenAI 인자 매핑)만 build_chat_openai가 축별로 갖고, 그 외
파생은 전부 여기서 나온다.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CapabilityDescriptor:
    """능력 하나와 그로부터 파생하는 요청별 설정.

    - cap: `ModelConfig.capabilities` JSONB 키(사실, 불가침).
    - setting: 요청별 조정 키(usage). None이면 **능력만** 있는 축(요청별 토글 없음 — 예 vision).
    - label: admin UI 라벨.
    - default: 모델 층 설정 기본값(설정 있는 축만 의미) — 미명시 상속의 바닥.
    - cap_default: 능력 기본값(신규 모델·누락 보정) — 마이그레이션 server_default와 단일 출처.
    """

    cap: str
    setting: str | None
    label: str
    default: bool
    cap_default: bool


# 정본 목록 — 여기에 한 줄 = 4화면+백엔드 전체 반영. vision은 능력만(요청별 설정 없음 — 첨부/비전
# 처리는 별 축, 스펙 408 OUT). streaming/thinking은 요청별로 켜고 끌 수 있는 설정을 가진다.
CAPABILITY_SETTINGS: tuple[CapabilityDescriptor, ...] = (
    CapabilityDescriptor("streaming", "stream", "스트리밍", True, True),
    CapabilityDescriptor("thinking", "enable_thinking", "Thinking 모드", False, False),
    CapabilityDescriptor("vision", None, "비전(이미지)", False, False),
)

_BY_CAP: dict[str, CapabilityDescriptor] = {d.cap: d for d in CAPABILITY_SETTINGS}

# 요청별 조정 가능한 설정 키(화이트리스트 파생) — 에이전트/노드/세션 오버라이드는 이 집합만 수용.
SETTING_KEYS: tuple[str, ...] = tuple(d.setting for d in CAPABILITY_SETTINGS if d.setting)

# 능력 기본값 dict(신규 모델·누락 보정) — 마이그레이션 server_default와 같은 값이어야 한다.
DEFAULT_CAPABILITIES: dict[str, bool] = {d.cap: d.cap_default for d in CAPABILITY_SETTINGS}


def _as_bool(value: object, default: bool) -> bool:
    """**진짜 bool만** 값으로 인정하고 그 외(문자열 "false"·정수·None)는 default로 폴백(스펙 409
    codex P1②). `bool("false")`가 True인 함정을 실행부에서 봉인 — 능력/설정 게이트가 문자열 주입으로
    뚫리지 않는다(인제스션 검증과 이중 방어: installed-guard-isnt-covering-guard)."""
    return value if isinstance(value, bool) else default


def resolve_effective(cap: str, capabilities: dict, *layers: dict) -> bool:
    """유효값 = **능력 AND 설정**(스펙 409 원칙 — 능력 false면 어느 층도 못 켬, 부분집합 불가침).

    설정값은 층을 **뒤에서 앞으로**(우선순위 높은 층이 뒤) 훑어 처음 명시된 값을 취하고, 없으면
    서술자 default. layers 예: build_chat_openai에서 `(params, cfg_params)` — 호출자(세션)가 최우선.
    비-bool 값은 인정하지 않는다(문자열 "false"로 게이트 우회 차단 — _as_bool).
    """
    d = _BY_CAP[cap]
    capable = _as_bool(capabilities.get(cap), d.cap_default)
    want = d.default
    if d.setting is not None:
        for layer in layers:
            if layer and isinstance(layer.get(d.setting), bool):
                want = layer[d.setting]
                break
    return capable and want


def clean_setting_params(mp: object) -> dict:
    """설정 오버라이드(modelParams) 정리 — 화이트리스트 설정 키의 **진짜 bool만** 보존(스펙 409).
    에이전트/노드/세션 저장 경계가 공유(하드코딩 없음 — 서술자 파생). 비-bool·미지 키는 드롭."""
    if not isinstance(mp, dict):
        return {}
    return {k: v for k, v in mp.items() if k in SETTING_KEYS and isinstance(v, bool)}


def clean_capabilities(caps: object) -> dict:
    """능력(capabilities) 정리 — 알려진 능력 키의 **진짜 bool만** 보존(스펙 409). 문자열 "false"·정수
    등 비-bool은 드롭(그 능력은 저장 안 됨 → resolve_effective의 cap_default로 폴백 = 안전 기본)."""
    if not isinstance(caps, dict):
        return {}
    return {d.cap: caps[d.cap] for d in CAPABILITY_SETTINGS if isinstance(caps.get(d.cap), bool)}


def descriptors_public() -> list[dict]:
    """admin 공급용 서술자(GET /model-capabilities/descriptors) — FE가 이걸 받아 4화면을 렌더.

    FE/BE 드리프트 0(사본 금지). setting=None 축은 그대로 실어 FE가 '능력만' 블록으로 구분한다.
    """
    return [
        {
            "cap": d.cap,
            "setting": d.setting,
            "label": d.label,
            "default": d.default,
            "capDefault": d.cap_default,
        }
        for d in CAPABILITY_SETTINGS
    ]

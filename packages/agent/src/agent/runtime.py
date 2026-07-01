"""커스텀 에이전트 SDK 인터페이스 (스펙 085).

플랫폼(API)이 **in-process로 로드해 돌리는** 에이전트의 공통 계약. 이 인터페이스를 구현하면
플랫폼이 `astream` 루프를 소유 → 플레이그라운드 설정 주입·LangGraph 호출 스택 추적을 1급으로
받는다. 미구현 에이전트(원격 code/external)는 플랫폼이 fallback 경로로 지금처럼 처리한다.

핵심 통찰: **주입·추적은 그래프가 아니라 그것을 돌리는 *루프*의 속성**이다. 커스텀 에이전트는
`build_graph`로 '그래프를 어떻게 만들지'만 책임지고, 주입·추적·스트림은 플랫폼이 책임진다.
그래서 어떤 적합 그래프든 오버라이드 주입·호출 스택 추적을 자동으로 받는다.

지배 스펙: docs/spec/085-custom-agent-runtime-interface.md
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from .main import build_agent


class AgentConfigError(Exception):
    """에이전트 설정 실패(스펙 089) — `config["impl"]`을 *선언*했는데 신뢰 레지스트리에서
    미해결(미등록 또는 Protocol 미구현)일 때 발생. 핵심: 이걸 `DefaultUiAgent`로 *만회·폴백*하지
    않는다(등록/설정 실수를 default가 가리는 건 문제 — 교정3). 호출측이 잡아 정직히 통보한다.
    예외 인자는 미해결 impl 키(레지스트리 키일 뿐 비밀 아님 — 통보 메시지에 안전)."""


def is_remote_source(source: str) -> bool:
    """원격(A2A 프록시) 소스인가 — code(우리 SDK A2A)·external(제3자 A2A)는 비로컬(스펙 057).

    in-process 인터페이스(스펙 085)의 *대상이 아니다* — 우리 런타임 밖에서 돌아 설정 주입·그래프
    추적이 불가하다. **단일 술어**(스펙 089) — resolve_agent_runtime·classify_runtime·chat.py가
    모두 이걸 공유해 `source in ("code","external")` 리터럴 드리프트를 0으로 만든다(learning 060)."""
    return source in ("code", "external")


@dataclass
class AgentBuildContext:
    """플랫폼이 커스텀 에이전트에 *주입*하는 모든 것. 오버라이드는 이미 병합된 상태로 도착한다
    (persona=오버라이드 병합 후 system_prompt, model_cfg=레지스트리 해석 후). 에이전트는 이 ctx만
    보고 그래프를 만든다 — 자기 설정을 DB에서 직접 읽지 않는다(주입 단일 출처)."""

    persona: str
    model_cfg: dict | None
    tools: list = field(default_factory=list)
    checkpointer: Any = None  # HIL durable 체크포인터(스펙 041). None이면 무상태.
    params: dict = field(default_factory=dict)  # temperature 등 런타임 파라미터
    memories: list = field(default_factory=list)  # 회상된 기억(플랫폼이 이미 persona에 합칠 수도)
    overrides: dict | None = None  # 원본 오버라이드(에이전트가 추가 키를 읽고 싶을 때)
    broker: Any = None  # 능력 브로커(스펙 100). 플랫폼이 **정책으로 미리 스코프**해 주입. None이면
    # 발견 공집합(deny-by-default). 에이전트는 이 핸들만 보고 능력을 오케스트레이션한다(정책·DB 미접촉).


@dataclass
class Capability:
    """능력 서술자(스펙 100) — discover/describe가 반환. `hook`은 한 줄 요약(=INDEX 후크와 같은
    load-bearing: 나쁜 설명이 엉뚱한 선택을 부른다). `input_schema`는 describe 시점에만 채운다.
    `kind`는 Phase 1에서 `"agent"`(A2A)만 — 후속으로 mcp|rag|memory 확장."""

    id: str
    kind: str
    name: str
    hook: str = ""
    trust: str = "untrusted"
    input_schema: dict | None = None


@dataclass
class InvokeResult:
    """invoke 반환(스펙 100) — kind별 실제 반환을 "텍스트로 접힌 공통 표현"으로(다음 노드 입력·
    트레이스용). 결과는 **지시가 아니라 데이터**다(trust=untrusted): flow는 이를 인용·요약할 뿐
    실행하지 않는다(프롬프트 인젝션 방어). error가 차면 호출 실패(로컬만으로 진행)."""

    text: str = ""
    trust: str = "untrusted"
    raw: dict | None = None
    error: str | None = None


@runtime_checkable
class CapabilityBroker(Protocol):
    """능력 브로커(스펙 100) — 능력(에이전트·MCP·RAG·memory)을 컨텍스트에 preload하지 않고
    **discovery**로 오케스트레이션한다(값싼 발견→필요시 상세→호출). 플랫폼(API)이 **정책으로 미리
    스코프한** 인스턴스를 `ctx.broker`로 주입한다 — 에이전트는 정책·DB를 직접 만지지 않는다(주입
    단일 출처 085 U2). 스코프 밖 능력은 discover에 안 뜨고 describe/invoke는 not-found로 접힌다
    (존재 비노출·deny-by-default)."""

    async def discover(self, query: str, *, limit: int = 5) -> list[Capability]: ...

    async def describe(self, cap_id: str) -> Capability: ...

    async def invoke(self, cap_id: str, args: dict) -> InvokeResult: ...


@dataclass
class AgentManifest:
    """커스텀 에이전트 자기소개 — 이름·설명·capabilities. describe()가 반환."""

    name: str
    description: str = ""
    accepts_overrides: bool = True  # 플레이그라운드 설정 주입 수용 여부
    supports_hil: bool = True  # HIL interrupt/Command(resume) 계약 지원 여부


@runtime_checkable
class CustomAgent(Protocol):
    """커스텀 에이전트가 구현하는 공통 인터페이스.

    `build_graph(ctx)`가 돌려준 그래프는 **기존 호출 계약**을 만족해야 한다:
    `astream({"messages":...}, stream_mode=["messages","updates"])`로 토큰·노드 업데이트를 내고,
    위험 도구가 있으면 `__interrupt__`/`ainvoke(Command(resume=...))`로 멈추고 재개한다
    (verify_041이 증명하는 그 계약). 플랫폼은 그래프 *내부*를 모른 채 루프만 돌린다.
    """

    def describe(self) -> AgentManifest: ...

    def build_graph(self, ctx: AgentBuildContext): ...


class DefaultUiAgent:
    """레퍼런스 구현 — 현 `build_agent`(create_agent ReAct)를 인터페이스로 감싼다.

    ui 에이전트가 인터페이스에 적합함을 증명한다. 같은 그래프·같은 계약이라 무회귀(verify_041이
    `build_agent`를 직접 검증하므로 이 래퍼는 그 계약을 그대로 노출). `config["impl"]`을 지정하지
    않은 모든 로컬(ui) 에이전트의 기본값."""

    def describe(self) -> AgentManifest:
        return AgentManifest(
            name="default-ui",
            description="기본 ReAct 에이전트(create_agent) — UI 빌더로 만든 로컬 에이전트",
        )

    def build_graph(self, ctx: AgentBuildContext):
        return build_agent(
            ctx.persona, ctx.params, ctx.tools, ctx.model_cfg, checkpointer=ctx.checkpointer
        )


# ----------------------------- 신뢰 레지스트리 (스펙 085 §보안경계) -----------------------------
# **코드 내부 명시 dict**. `config["impl"]`은 이 dict의 *키*일 뿐 코드가 아니다 — 임의 문자열
# eval/import 경로가 없다(키 미존재 → 호출측이 기본으로 폴백). in-process 로딩의 신뢰경계는 이
# dict에 무엇이 등록됐느냐로 닫힌다(검증된 우리 코드만 register).
_REGISTRY: dict[str, type] = {}


def register_agent(key: str, cls: type) -> None:
    """신뢰 레지스트리에 커스텀 에이전트 구현을 등록(코드 로드 시 1회)."""
    _REGISTRY[key] = cls


def get_agent_impl(key: str | None) -> CustomAgent | None:
    """등록된 **적합** 커스텀 에이전트 인스턴스 반환. 적합하지 않으면 None.

    None/빈 키 → None(impl 미선언). 등록됐어도 인스턴스가 `CustomAgent` Protocol에 **부적합**하거나
    `cls()` 생성이 던지면 None(스펙 089: isinstance 게이트로 085 갭 봉합 — `@runtime_checkable`을
    resolve 시점에 *실제로* 적용, fail-closed). **dict 조회만** 한다 — 키 문자열을 코드로
    해석(eval/importlib)하지 않는다(스펙 085 §보안경계). 알 수 없는 키는 조용히 None(열거 오라클 없음).

    주의: None은 "미선언"과 "선언했으나 부적합"을 구분하지 않는다 — 그 구분(폴백 vs 설정 실패)은
    호출측(resolve_agent_runtime·classify_runtime)이 *키 선언 여부*로 판정한다(스펙 089 교정3)."""
    if not key:
        return None
    cls = _REGISTRY.get(key)
    if cls is None:
        return None
    try:
        inst = cls()
    except Exception:  # noqa: BLE001 — 생성 실패=부적합으로 본다(fail-closed, 만회 없음)
        return None
    return inst if isinstance(inst, CustomAgent) else None


def list_agent_impls() -> list[str]:
    """등록된 커스텀 에이전트 키 목록(관측·테스트용)."""
    return sorted(_REGISTRY)


def classify_runtime(source: str, impl: str | None) -> str:
    """에이전트 런타임 분류(스펙 089) — `"conforming" | "non_conforming" | "config_error"` 3상태.

    - **non_conforming**: 원격(code/external, A2A) — in-process 인터페이스 미대상. *정당한 다른
      종류*이지 실패가 아니다(교정2).
    - **conforming**: impl 미선언(→DefaultUiAgent, 레퍼런스 적합) 또는 impl이 적합 구현으로 해결.
    - **config_error**: impl을 *선언*했으나 미해결(미등록/부적합) — `DefaultUiAgent`로 만회하지 않고
      설정 실패로 표면화(교정3). 런타임은 서빙을 거부한다.

    **파생값(저장 안 함)** — 레지스트리 변경 시 stale 드리프트 방지(learning 060). resolve_agent_runtime과
    *같은 게이트*(`is_remote_source` + `get_agent_impl` isinstance)를 공유한다(술어 단일 출처)."""
    if is_remote_source(source):
        return "non_conforming"
    if not impl:
        return "conforming"
    return "conforming" if get_agent_impl(impl) is not None else "config_error"


def _bootstrap_builtins() -> None:
    """기본 제공 커스텀 에이전트 등록. 이 모듈 import 시 1회 실행(아래 호출).

    examples/flows는 *여기서* 늦게 import한다 — 그들이 이 모듈의 AgentManifest/AgentBuildContext를
    import하므로(순환), 모든 이름이 바인딩된 모듈 끝에서 부른다(부분초기화 모듈 캐시 안전).

    **agent-flow 스킬 규약(스펙 099)**: 새 flow 생성 시 아래에 두 줄을 추가한다 —
    `from .flows.<key> import <Cls>` + `register_agent("<key>", <Cls>)`. 신뢰 등록만(런타임 eval 없음)."""
    from .examples.plan_execute import PlanExecuteAgent
    from .flows.orchestrate import OrchestrateAgent
    from .flows.route import RouteAgent

    register_agent("plan_execute", PlanExecuteAgent)
    register_agent("route", RouteAgent)
    register_agent("orchestrate", OrchestrateAgent)


_bootstrap_builtins()

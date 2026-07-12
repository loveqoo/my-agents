"""코드 노드(스펙 317) — 공통 노드 인터페이스 + 신뢰 레지스트리.

UI로 설정하지 못하는 복잡한 로직을 **코드로 노드화**해 노드형 파이프라인에서 등록 노드처럼
참조한다(스펙 316의 kind=code). 커스텀 에이전트(스펙 085 `CustomAgent`+`register_agent`)와 같은
구조를 노드 수준으로 내린 것:

- **신뢰 레지스트리** — dict에 등록된 우리 코드만 실행된다. 런타임 eval/동적 import 없음
  (085 §보안경계). `impl` 키는 레지스트리의 *키*일 뿐 코드가 아니다.
- **버전은 코드(manifest)가 선언** — 부팅 시 API가 `node_manifests()`를 읽어 node_templates에
  upsert한다(스펙 317 합의: 같은 버전 재선언=덮어쓰기로 핀 에이전트 전체에 의도 전파, 새 버전
  선언=새 행으로 기존 핀 무영향).
- **오버라이드 표면 선언** — `NodeManifest.overridable`에 든 필드만 플레이그라운드 세션
  오버라이드가 병합된다(나머지는 코드가 소유). 공통 인터페이스를 요구한 이유(사용자 2026-07-13).
- 스텝 계약: `build_step(node_cfg, ctx)`가 LangGraph 노드 함수(messages state → {"messages": [...]})
  를 돌려준다. 도구가 필요하면 `ctx.tools`(이미 RBAC 스코프)에서 고른다 — 권한 상승 0(085 U2).

pipeline(스펙 259)의 `_make_step`이 노드에 `impl` 키가 있으면 여기서 해석한다. 미등록이면
`AgentConfigError`(폴백 마스킹 금지 — 089 패턴).
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from langchain_core.messages import AIMessage

if TYPE_CHECKING:
    from .runtime import AgentBuildContext

#: 스텝 계약 — LangGraph 노드 함수(state in → 부분 상태 out). Mapping으로 받아 pipeline의
#: TypedDict 상태(_State)와 호환(반공변 — 구체 상태형을 몰라도 된다).
NodeStep = Callable[[Mapping[str, Any]], Awaitable[dict]]


@dataclass(frozen=True)
class NodeManifest:
    """코드 노드 자기소개 — 카탈로그 동기화(upsert)와 오버라이드 표면의 단일 출처."""

    name: str  # 카탈로그 식별 이름(스펙 148 규칙 준용 — 영소문자·숫자·대시)
    version: int  # 이 코드가 구현하는 버전 — 같은 버전 재선언=의도된 덮어쓰기(전파)
    description: str
    # 세션 오버라이드 허용 표면 — _NODE_OVERRIDE_FIELDS(스펙 287)의 부분집합만 유효.
    # 빈 튜플=전부 코드 소유(오버라이드 불가).
    overridable: tuple[str, ...] = field(default=())


@runtime_checkable
class CustomNode(Protocol):
    """코드 노드 공통 인터페이스(스펙 317) — describe()로 자기소개, build_step()으로 스텝 생성."""

    def describe(self) -> NodeManifest: ...

    def build_step(self, node_cfg: dict, ctx: AgentBuildContext) -> NodeStep: ...


# 신뢰 레지스트리 — register_agent(085)와 동일 구조. 신뢰 경계는 이 dict에 무엇이 등록됐느냐로
# 닫힌다(검증된 우리 코드만 register).
_NODES: dict[str, type] = {}


def register_node(key: str, cls: type) -> None:
    """코드 노드 등록(신뢰 코드 전용) — 부팅 부트스트랩에서만 호출한다."""
    _NODES[key] = cls


def get_node_impl(key: str | None) -> CustomNode | None:
    """레지스트리 키 → 코드 노드 인스턴스. 미등록·Protocol 부적합·생성 실패는 None —
    호출측(pipeline)이 AgentConfigError로 정직 실패한다(get_agent_impl과 동일 시맨틱)."""
    if not key:
        return None
    cls = _NODES.get(key)
    if cls is None:
        return None
    try:
        inst = cls()
    except Exception:
        return None
    return inst if isinstance(inst, CustomNode) else None


def node_manifests() -> list[tuple[str, NodeManifest]]:
    """(레지스트리 키, manifest) 목록 — 부팅 카탈로그 동기화(API sync_code_nodes)가 소비.
    describe()가 깨진 노드는 건너뛰지 않고 예외를 그대로 낸다(부팅 시점에 시끄럽게 — 코드 결함을
    카탈로그 누락으로 조용히 가리지 않는다)."""
    return [(key, cls().describe()) for key, cls in _NODES.items()]


def _text_of(m: object) -> str:
    """메시지 텍스트 추출 — pipeline._text_of와 같은 시맨틱(모듈 순환 회피를 위한 지역 사본:
    pipeline→nodes 방향만 import하고 nodes는 pipeline을 모른다)."""
    c = getattr(m, "content", "")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "\n".join(str(p.get("text", "")) if isinstance(p, dict) else str(p) for p in c)
    return str(c)


# ----------------------------- 레퍼런스 코드 노드 -----------------------------
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# 전화번호 — 한국식(02/010 등 2~3자리-3~4자리-4자리, 구분자 -, ., 공백)과 +82 국제표기.
_PHONE_RE = re.compile(r"(?:\+82[-\s]?|0)\d{1,2}[-.\s]?\d{3,4}[-.\s]?\d{4}")


def mask_pii_text(text: str) -> str:
    """이메일·전화번호 마스킹(순수 함수 — 단위 검증 가능). 이메일은 로컬파트 첫 글자만 남기고
    가림, 전화번호는 뒤 4자리만 남긴다 — 무엇이 가려졌는지 종류는 알아볼 수 있게(정직 표기)."""

    def _mask_email(m: re.Match) -> str:
        local, _, domain = m.group(0).partition("@")
        return f"{local[:1]}***@{domain}"

    def _mask_phone(m: re.Match) -> str:
        digits = re.sub(r"\D", "", m.group(0))
        return f"***-****-{digits[-4:]}"

    return _PHONE_RE.sub(_mask_phone, _EMAIL_RE.sub(_mask_email, text))


class MaskPiiNode:
    """레퍼런스 코드 노드 — 이전 노드 출력의 이메일·전화번호를 마스킹하는 **결정적 후처리**.

    UI 설정 노드로는 표현 불가(프롬프트로 시키면 모델이 흉내낼 뿐 보장이 없다 — 정규식은 보장).
    모델을 쓰지 않으므로 오버라이드 표면도 없다(overridable=() — 전부 코드 소유)."""

    NAME = "mask_pii"

    def describe(self) -> NodeManifest:
        return NodeManifest(
            name="mask-pii",
            version=1,
            description="이전 노드 출력의 이메일·전화번호를 정규식으로 마스킹(결정적 후처리, 모델 미사용)",
            overridable=(),
        )

    def build_step(self, node_cfg: dict, ctx: AgentBuildContext) -> NodeStep:  # noqa: ARG002
        async def _step(state: Mapping[str, Any]) -> dict:
            msgs = state.get("messages") or []
            masked = mask_pii_text(_text_of(msgs[-1]) if msgs else "")
            return {"messages": [AIMessage(content=masked)]}

        return _step


def _bootstrap_builtin_nodes() -> None:
    """빌트인 코드 노드 신뢰 등록 — runtime._bootstrap_builtins와 동일 패턴(등록만, eval 없음)."""
    register_node("mask_pii", MaskPiiNode)


_bootstrap_builtin_nodes()

"""능력 브로커 구현 + 정책 게이트 (스펙 100 Phase 1).

계약(`CapabilityBroker` Protocol)은 `packages/agent`에 있고, **구현·정책은 여기(API)** 에 둔다
(설계결정 1: 계약=agent, 배선·정책=api). `PolicyScopedBroker`는 생성 시 (allowlist ∩ RBAC)로
**미리 스코프**되며, 에이전트는 스코프된 인스턴스만 `ctx.broker`로 받는다 — 정책·DB를 직접 만지지
않는다(주입 단일 출처 085 U2).

정책(RBAC/소유권 경계 체크리스트):
- 입구 = discover / describe / invoke (닫힌 집합). 외부 프로토콜 입구는 invoke 내부의 a2a 호출 하나.
- 판정 = `_permitted`(allowlist ∩ RBAC) **단일 헬퍼**로 발견·호출 통일(drift 0). deny-by-default.
- invoke는 호출 경계서 **재검증**(discover 결과 신뢰 안 함 — check-then-act 원자화, TOCTOU 차단).
- 스코프 밖은 discover 미노출·describe는 `CapabilityNotFound`·invoke는 not-found error(존재 비노출).

Phase 1 provider = A2A(원격 code/external Agent + endpoint). 전송은 `a2a_client`가 담당하며 SSRF/
net_guard·캡·타임아웃을 이미 적용한다(설계결정 6 재사용). 결과는 **untrusted 데이터**(설계결정 5).

**인가 입도(Phase 1 커버 범위 — 명시 경계, codex 100 [P1] #1/#2 수용)**: 경계는
`(에이전트 config allowlist) ∩ (유저 kind-단위 RBAC)`다. 두 축의 커버 범위를 정확히 적는다 —
- allowlist 축은 **에이전트별**이다. Agent 모델엔 owner가 없어(공유 카탈로그) allowlist는 유저별이
  아니라 *에이전트별* 스코프다. 즉 어떤 에이전트와 대화하면 그 에이전트의 allowlist를 물려받는다.
- RBAC 축은 **kind 단위**다(`capability:{kind}` invoke). *특정 cap을 특정 유저에게* 막는 per-cap·
  per-user 인가는 Phase 1에서 강제하지 않는다. 기본 정책은 admin('*','*')만 시드돼 member는
  kind 자체가 거부(deny-by-default) — 그래서 실사용 경계는 "admin만 오케스트레이션"이다.
  member에게 `capability:agent invoke`를 부여하면 그 유저는 *접근 가능한 에이전트의 allowlist 전부*를
  호출할 수 있다(per-cap 제한 없음). 이는 우회가 아니라 **의도된 입도의 한계**이며, per-cap/per-user
  인가와 에이전트 소유권은 후속 스펙 몫이다(지배 스펙 §비목표에 기록).
"""

from __future__ import annotations

import time
from collections.abc import Callable

from agent.runtime import Capability, InvokeResult, is_remote_source
from sqlalchemy import select

from . import a2a_client
from .db import SessionLocal
from .models import Agent

CAP_KIND_AGENT = "agent"  # Phase 1 유일 kind. mcp|rag|memory는 후속 스펙.


class CapabilityNotFound(Exception):
    """능력 미해결 — **미존재와 미허가를 구분하지 않는다**(403/404 접기, 존재 비노출)."""


def _card_streaming(card: object) -> bool:
    """카드 capabilities.streaming(chat._card_streaming과 동일 술어 — 순환 import 피해 로컬 복제).
    없으면 True(message/stream 우선, 안 되면 에이전트가 단건 응답)."""
    if isinstance(card, dict):
        caps = card.get("capabilities")
        if isinstance(caps, dict) and "streaming" in caps:
            return bool(caps.get("streaming"))
    return True


def _hook_for(agent: Agent) -> str:
    """한 줄 후크 — 카드 description → persona → name 순 첫 비어있지 않은 줄(≤200자). load-bearing:
    발견 선택 품질이 여기 달렸다(설계결정 3)."""
    card = (agent.config or {}).get("card")
    desc = card.get("description") if isinstance(card, dict) else None
    for cand in (desc, agent.persona, agent.name):
        if cand and str(cand).strip():
            return str(cand).strip().splitlines()[0][:200]
    return ""


class PolicyScopedBroker:
    """정책으로 미리 스코프된 능력 브로커. `agent.runtime.CapabilityBroker` Protocol 적합.

    `allowlist` = 호출 에이전트 config `capabilities`(cap id 목록, 없으면 [] = deny-by-default).
    `rbac_allows(kind)` = 유저 RBAC 판정 클로저(casbin enforce 등을 이미 바인딩). 둘의 **교집합**만
    발견·호출된다.
    """

    def __init__(
        self,
        allowlist,
        rbac_allows: Callable[[str], bool],
        *,
        session_factory=SessionLocal,
    ):
        self._allow: set[str] = set(allowlist or [])
        self._rbac_allows = rbac_allows
        self._session_factory = session_factory
        # 관측(설계결정 7) — invoke 이력. broker.invoke가 invisible하지 않음을 보증(호출별 노드 프레임).
        self.invocations: list[dict] = []

    def _permitted(self, cap_id: str, kind: str = CAP_KIND_AGENT) -> bool:
        """**단일 판정 헬퍼**(체크리스트 §3, drift 0) — allowlist ∩ RBAC. deny-by-default."""
        return bool(cap_id) and cap_id in self._allow and bool(self._rbac_allows(kind))

    async def discover(self, query: str, *, limit: int = 5) -> list[Capability]:
        # deny-by-default: allowlist 비었거나 RBAC 거부 → 모집단 공집합(존재조차 안 샘).
        if not self._allow or not self._rbac_allows(CAP_KIND_AGENT):
            return []
        # allowlist를 SELECT WHERE에 밀어 거부 대상을 **로드조차 안 함**(체크리스트 §2 존재 오라클 차단).
        async with self._session_factory() as db:
            rows = (
                (await db.execute(select(Agent).where(Agent.agent_id.in_(self._allow))))
                .scalars()
                .all()
            )
        q = (query or "").strip().lower()
        caps: list[Capability] = []
        for a in rows:
            if not is_remote_source(a.source) or not a.endpoint:
                continue  # Phase 1 provider = A2A(원격 + 호출 가능한 엔드포인트)만
            hook = _hook_for(a)
            # lexical(부분일치, 대소문자 무시) — 카탈로그 작아 벡터 없이 시작(설계결정 10).
            if q and q not in f"{a.name} {a.agent_id} {hook}".lower():
                continue
            caps.append(Capability(id=a.agent_id, kind=CAP_KIND_AGENT, name=a.name, hook=hook))
        return caps[:limit]

    async def _load_permitted(self, cap_id: str) -> Agent | None:
        """허가된 cap을 실 Agent 행으로 해석. 미허가/미존재/비-A2A → None(존재 비노출로 접힘)."""
        if not self._permitted(cap_id):
            return None
        async with self._session_factory() as db:
            a = (
                await db.execute(select(Agent).where(Agent.agent_id == cap_id))
            ).scalar_one_or_none()
        if a is None or not is_remote_source(a.source) or not a.endpoint:
            return None
        return a

    async def describe(self, cap_id: str) -> Capability:
        a = await self._load_permitted(cap_id)
        if a is None:
            raise CapabilityNotFound(cap_id)  # 미존재·미허가 동일 처리(존재 비노출)
        return Capability(
            id=a.agent_id,
            kind=CAP_KIND_AGENT,
            name=a.name,
            hook=_hook_for(a),
            input_schema={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        )

    async def invoke(self, cap_id: str, args: dict) -> InvokeResult:
        # 호출 경계 **재검증**(discover 결과 신뢰 안 함 — TOCTOU/우회 차단, 체크리스트 §2).
        a = await self._load_permitted(cap_id)
        if a is None:
            return InvokeResult(error="capability not found", trust="untrusted")  # 존재 비노출
        user_text = str(args.get("text", "")) if isinstance(args, dict) else str(args)
        card = (a.config or {}).get("card")
        acc: list[str] = []
        errored: str | None = None
        t0 = time.perf_counter()
        # a2a_client가 SSRF/net_guard·캡·타임아웃 적용. 이 제너레이터는 raise 안 함(에러=프레임).
        async for frame in a2a_client.a2a_stream(
            a.endpoint, a.token, user_text, streaming=_card_streaming(card), context_id=None
        ):
            if "error" in frame:
                errored = frame["error"]
            elif frame.get("text"):
                acc.append(frame["text"])
        ms = int((time.perf_counter() - t0) * 1000)
        # 관측: broker.invoke 1회 = 노드 프레임 1개(설계결정 7 — invisible 금지, 트레이스 append 가능).
        self.invocations.append(
            {"node": f"broker_invoke:{CAP_KIND_AGENT}:{a.name}", "cap_id": cap_id, "ms": ms}
        )
        # 결과 = **데이터**(지시 아님). trust=untrusted 불변(인젝션 방어, 설계결정 5).
        return InvokeResult(
            text="".join(acc),
            trust="untrusted",
            error=errored,
            raw={"cap_id": cap_id, "kind": CAP_KIND_AGENT},
        )


def build_broker(principal, allowlist) -> PolicyScopedBroker:
    """chat.py 배선용 — principal(유저/머신)에서 RBAC 판정 클로저를 만들어 스코프된 브로커 구성.

    RBAC: `is_superuser` 우회(authz 패턴) 아니면 `enforce(str(id), f"capability:{kind}", "invoke")`.
    머신 토큰(str principal, id 없음) → **deny**(안전측; Phase 1 오케스트레이션은 유저 세션 대상).
    기본 정책은 admin('*','*')만 시드돼 있어 member는 거부된다(deny-by-default가 정책 부재에서도 성립)."""
    from . import authz

    def rbac_allows(kind: str) -> bool:
        if isinstance(principal, str):
            return False  # 머신 토큰: 능력 오케스트레이션 비대상(deny-by-default)
        if getattr(principal, "is_superuser", False):
            return True  # 부트스트랩·운영 안전판(authz 우회 패턴)
        return bool(
            authz.get_enforcer().enforce(str(principal.id), f"capability:{kind}", "invoke")
        )

    return PolicyScopedBroker(allowlist, rbac_allows)

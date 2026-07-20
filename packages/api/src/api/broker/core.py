"""정책 게이트 코어(스펙 100→101) — `PolicyScopedBroker`·RBAC 술어·`build_broker`.

정책(allowlist∩RBAC·deny-by-default·존재비노출·단일 `_permitted`)은 여기 살고, kind별 메커닉은
`providers/*`가 든다. 정책 판정은 provider 호출 **전에** 브로커가 수행한다(게이트 단일 지점,
체크리스트 §3 드리프트 0). 서브스텝 HIL(§3.5)은 전송(부수효과) 이전 interrupt — 기존 파이프라인
(interrupt→__interrupt__→SSE→Approval→Command(resume)) 재사용(새 배선 0).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from agent.runtime import Capability, InvokeResult

if TYPE_CHECKING:
    import casbin

    from ..models import User
from .common import (
    CAP_KIND_AGENT,
    CAP_KIND_MCP,
    CapabilityNotFoundError,
    _cap_resource,
    _CapabilityProvider,
    _kind_of,
    _parse_mcp,
)
from .composition import BrokerContext, build_providers


def _build_frame(node: str, cap_id: str, ms: int, res: InvokeResult) -> dict:
    """관측 프레임 1개(설계결정 7 — broker.invoke는 invisible 금지). 순수 함수.
    args/result 원문은 안 담고(087/092 — 원문 누출 0) provider raw의 표시용 메타만 통과."""
    inv: dict = {"node": node, "cap_id": cap_id, "ms": ms}
    raw = res.raw if isinstance(res.raw, dict) else {}
    # 표시용 메타(스펙 130) — provider가 raw에 실은 숫자만 통과(hits/topScore), args 불포함.
    # hitsDetail(스펙 191)=히트별 카드+최소 유사도 기준선+검색 질의(RAG 위임 검색 가독성).
    for key in ("hits", "topScore", "hitsDetail"):
        if key in raw:
            inv[key] = raw[key]
    if raw.get("local"):
        inv["local"] = True  # 로컬 인프로세스 위임(스펙 256)
    for key in ("subTraceNodes", "minScore", "query"):
        if key in raw:
            inv[key] = raw[key]
    if res.error:
        # 실패 사유 문자열 보존(스펙 320) — 구 `True` 불리언은 "왜"를 버렸다(예: "capability not found"·
        # "대상 없음"). 마스킹+캡 백스톱(사유가 새 노출 표면). 비어있지 않은 문자열은 truthy라 프론트
        # `b.error ? …` 태그 분기 무회귀 + 사유 표시만 추가.
        from ..memory import _sanitize  # 지연 — 순환 import 방지

        inv["error"] = _sanitize(str(res.error), cap=500) or True
    if res.text:
        # 결과 본문 프리뷰(스펙 131) — 직접 MCP의 result(2000캡, 087)와 동일 계약으로 브로커도
        # 노출(플레이그라운드=정밀 디버깅). 비밀 마스킹 백스톱(125 _sanitize) + 캡. 원문 전문은
        # 여전히 미저장(캡 절단), args는 계속 불포함.
        from ..memory import _sanitize  # 지연 — 순환 import 방지

        inv["resultPreview"] = _sanitize(res.text, cap=2000)
    return inv


class PolicyScopedBroker:
    """정책으로 미리 스코프된 능력 브로커. `agent.runtime.CapabilityBroker` Protocol 적합.

    `allowlist` = 호출 에이전트 config `capabilities`(cap id 목록, 없으면 [] = deny-by-default).
    `rbac_allows(kind)` = 유저 RBAC 판정 클로저(casbin enforce 등을 이미 바인딩). 둘의 **교집합**만
    발견·호출된다. cap_id에서 kind를 파싱해 provider로 라우팅하되, 정책 판정은 provider **호출 전에**
    브로커가 수행한다(게이트 단일 지점). 서브스텝 HIL은 브로커가 전송 이전 interrupt로 게이트(§3.5).
    """

    def __init__(
        self,
        allowlist: list[str] | None,
        rbac_allows: Callable[..., bool],  # 실호출 (kind) 또는 (kind, name) 2형태 — _permitted 참조
        providers: list[
            _CapabilityProvider
        ],  # 스펙 294 — 조립은 외부(build_providers), 소비만 여기
        *,
        tool_policy: dict
        | None = None,  # config.toolPolicy(스펙 177 P2) — McpProvider 승인 오버라이드
        force_approval: bool = False,  # 첨부 유래 턴(스펙 415 P4) — 정책 없는 부수효과 cap도 승인 강제
    ) -> None:
        # 스펙 294: 브로커는 `_CapabilityProvider` 추상에만 의존한다 — provider를 **주입받고** 구체를
        # 모른다(생성 배선은 composition.build_providers 단일 출처). anti-leak(user_id)·delegation·
        # rag_min_scores 등 조립 인자는 BrokerContext로 build_providers에 실려 이미 provider에 박혔다.
        self._allow: set[str] = set(allowlist or [])
        self._rbac_allows = rbac_allows
        self._tool_policy = tool_policy
        self._force_approval = force_approval
        self._providers: list[_CapabilityProvider] = providers
        self._by_kind = {p.kind: p for p in providers}
        # 관측(설계결정 7) — invoke 이력. broker.invoke가 invisible하지 않음을 보증(호출별 노드 프레임).
        self.invocations: list[dict] = []

    def _permitted(self, cap_id: str, kind: str | None = None) -> bool:
        """**단일 판정 헬퍼**(체크리스트 §3, drift 0) — allowlist ∩ RBAC. deny-by-default.
        kind별 매칭은 헬퍼 *내부*: mcp는 정확 툴 항목 **또는** 서버 전체(`mcp:<server>`)가 그 툴을 덮음.
        RBAC는 **per-cap 포함**(스펙 112): kind-레벨(`capability:{kind}`) OR 능력별
        (`capability:{kind}:{resource}`) — admin이 kind 전체 대신 특정 cap만 member에 부여 가능."""
        if not cap_id:
            return False
        kind = kind or _kind_of(cap_id)
        if not self._rbac_allows(kind, _cap_resource(cap_id, kind)):
            return False
        if kind == CAP_KIND_MCP:
            server, _tool = _parse_mcp(cap_id)
            return cap_id in self._allow or f"{CAP_KIND_MCP}:{server}" in self._allow
        return cap_id in self._allow

    async def _gather_permitted(self) -> list[Capability]:
        """kind-게이트 통과 provider들의 후보를 per-cap 필터로 수집(스펙 112)."""
        caps: list[Capability] = []
        for provider in self._providers:
            # DB 미접촉 게이트(존재 누출 0 보존): 이 kind에 **어떤 부여도 없으면** provider를 안 부른다.
            # `rbac_allows(kind)`(name=None) = "kind-레벨 OR 이 kind의 per-cap이 하나라도 있나"(스펙 112).
            # kind 전체 거부인데 per-cap 부여가 있으면 여기 통과 → 아래서 후보를 **per-cap 개별 필터**한다
            # (kind-gate만 두면 per-cap 부여 능력이 discover에 안 떠 오케스트레이션서 못 쓴다).
            if not self._rbac_allows(provider.kind):
                continue
            for cap in await provider.candidates(self._allow):
                # 특정 판정: kind-레벨이면 전체 통과, per-cap 전용이면 부여된 cap만(같은 술어 재사용).
                if self._rbac_allows(cap.kind, _cap_resource(cap.id, cap.kind)):
                    caps.append(cap)
        return caps

    @staticmethod
    def _rank(caps: list[Capability], query: str) -> list[Capability]:
        """lexical 겹침 랭킹 — **하드 필터가 아니라 랭킹 신호**(스펙 124). 예전엔 `q in cap-text` 하드
        필터로 자연어 쿼리가 짧은 능력 이름의 부분문자열일 리 없어 **허가된 능력이 전부 탈락→조율형이
        아무 능력도 못 씀**(버그). 이제 쿼리 토큰과 겹치는 수가 많은 순으로 **정렬만** 하고(0 겹침도
        유지), 안정 정렬로 동수는 기존 순서 보존. (allowlist∩RBAC 게이트는 수집 단계에서 이미 적용 —
        이 후처리는 허가 범위를 넓히지 않는다.)"""
        q_tokens = [t for t in (query or "").strip().lower().split() if t]
        if q_tokens:
            caps.sort(
                key=lambda c: sum(t in f"{c.name} {c.id} {c.hook}".lower() for t in q_tokens),
                reverse=True,
            )
        return caps

    async def discover(self, query: str, *, limit: int = 5) -> list[Capability]:
        # deny-by-default: allowlist 비었으면 모집단 공집합(존재조차 안 샘 — DB 미접촉).
        if not self._allow:
            return []
        return self._rank(await self._gather_permitted(), query)[:limit]

    async def agent_capabilities(self) -> list[Capability]:
        """kind=agent 허가 능력 전량(스펙 318 — 노드 도구 빌더가 소비). discover와 달리 랭킹·limit
        없이 허가된 agent cap을 **전부** 돌려준다(노드가 이름으로 개별 바인딩하므로 모집단이 필요).
        allowlist∩RBAC는 _gather_permitted가 이미 적용 — 이 메서드는 범위를 넓히지 않는다."""
        if not self._allow:
            return []
        return [c for c in await self._gather_permitted() if c.kind == CAP_KIND_AGENT]

    async def _resolve(self, cap_id: str) -> tuple[Any, Any]:
        """허가+로드된 (row, provider) 또는 (None, None). 미허가·미존재·kind불명 모두 (None,None)
        — 상관 튜플(row None ⇔ provider None)이라 provider도 Any(호출측이 row로 판별).
        (존재 비노출). _permitted가 provider.load **이전**에 서므로 거부 경로는 DB/네트워크 미접촉."""
        kind = _kind_of(cap_id)
        provider = self._by_kind.get(kind)
        if provider is None or not self._permitted(cap_id, kind):
            return None, None
        row = await provider.load(cap_id)
        if row is None:
            return None, None
        return row, provider

    async def describe(self, cap_id: str) -> Capability:
        row, provider = await self._resolve(cap_id)
        if row is None:
            raise CapabilityNotFoundError(cap_id)  # 미존재·미허가 동일 처리(존재 비노출)
        return provider.describe(row)

    def _gate(
        self, provider: _CapabilityProvider, row: Any, cap_id: str, args: dict
    ) -> InvokeResult | None:
        """서브스텝 HIL(§3.5) — 승인 요구 cap이면 전송(부수효과) **이전** interrupt로 부모 그래프 pause.
        interrupt는 재개 시 delegate 재실행에도 이 지점 이전 부수효과 0 = 전송 1회(멱등, 체크리스트 §7).
        거부면 거부 결과를, 승인·무승인 cap(payload None)이면 None(전송 진행)을 돌린다."""
        payload = provider.approval_for(row, cap_id, args, self._tool_policy)
        # 첨부 유래 턴(스펙 415 P4): 정책 없는 **부수효과** cap도 승인 강제. 대상=MCP(부수효과 미상 —
        # 보수적 전부)·에이전트 위임(하위가 무엇이든 할 수 있음). RAG·메모리 읽기는 approval_for가
        # 늘 None인 읽기 전용이라 면제, 메모리 쓰기/수정은 이미 항상 non-None(무영향).
        if payload is None and self._force_approval and _kind_of(cap_id) in (
            CAP_KIND_MCP,
            CAP_KIND_AGENT,
        ):
            from ..runtime import _redact_args
            from ..runtime_mcp import forced_attachment_approval

            # 마스킹된 인자를 실어 "정보에 근거한 승인"을 성립시킨다(codex 415 P1③ — args:{}는
            # 승인자가 무엇을 승인하는지 못 봄). _redact_args로 비밀만 가리고 구조는 노출한다.
            payload = {
                **forced_attachment_approval(cap_id),
                "action": cap_id,
                "args": _redact_args(args if isinstance(args, dict) else {"text": args}),
                "summary": "첨부 문서가 있는 대화라 본인 승인 필요 — " + cap_id,
            }
        if payload is None:
            return None
        from langgraph.types import interrupt  # 지연 임포트(그래프 밖 호출 시 부담 0)

        decision = interrupt(payload)  # 첫 호출=그래프 멈춤, 재개 시 decision 반환
        if not (isinstance(decision, dict) and decision.get("decision") == "approve"):
            return InvokeResult(
                text="거부됨 — 관리자가 실행을 승인하지 않았습니다.", trust="untrusted"
            )
        return None

    async def invoke(self, cap_id: str, args: dict) -> InvokeResult:
        # 호출 경계 **재검증**(discover 결과 신뢰 안 함 — TOCTOU/우회 차단, 체크리스트 §2).
        row, provider = await self._resolve(cap_id)
        if row is None:
            return InvokeResult(error="capability not found", trust="untrusted")  # 존재 비노출
        denied = self._gate(provider, row, cap_id, args)
        if denied is not None:
            return denied
        t0 = time.perf_counter()
        res = await provider.invoke(row, args)  # 승인된(또는 무승인) 경우만 전송(부수효과 1회)
        ms = int((time.perf_counter() - t0) * 1000)
        # 관측: broker.invoke 1회 = 노드 프레임 1개(설계결정 7 — invisible 금지). args/result는 안 담음
        # (087/092 — 원문 누출 0). interrupt payload만 _redact_args로 마스킹된 args를 싣는다.
        self.invocations.append(_build_frame(provider.node_label(row), cap_id, ms, res))
        return res


def _subject_closure(enforcer: casbin.AsyncEnforcer, subject: str) -> set[str]:
    """주체 본인 + 상속 역할(transitive) 집합 — user→role→role 전이 폐쇄(작은 정책셋,
    순환 방지 위해 visited 체크). AsyncEnforcer의 implicit 헬퍼가 async라 sync 정책 열거로 우회
    (get_grouping_policy는 in-memory sync)."""
    subjects = {subject}
    grouping = enforcer.get_grouping_policy()
    frontier = [subject]
    while frontier:
        cur = frontier.pop()
        for group in grouping:
            if len(group) >= 2 and group[0] == cur and group[1] not in subjects:
                subjects.add(group[1])
                frontier.append(group[1])
    return subjects


def _has_any_percap(enforcer: casbin.AsyncEnforcer, subject: str, kind: str) -> bool:
    """이 kind에 per-cap 부여가 하나라도 있나 — 주체+상속 역할의 정책에서 obj가
    `capability:{kind}:` prefix인 invoke를 찾는다(casbin 암묵 권한 열거, get_policy는 sync)."""
    subjects = _subject_closure(enforcer, subject)
    prefix = f"capability:{kind}:"
    return any(
        len(p) >= 3 and p[0] in subjects and p[1].startswith(prefix) and p[2] == "invoke"
        for p in enforcer.get_policy()
    )


def _has_direct_grant(enforcer: casbin.AsyncEnforcer, subject: str, kind: str, name: str) -> bool:
    """특정 능력 부여 판정 — 능력별(`capability:{kind}:{name}`) 직접 부여 OR mcp 서버단위 부여."""
    if enforcer.enforce(subject, f"capability:{kind}:{name}", "invoke"):
        return True
    # mcp 서버단위 부여(`capability:mcp:{server}`)는 그 서버의 **모든 툴**을 덮는다 — allowlist
    # 시맨틱(`mcp:{server}`가 툴 항목을 포함)과 일치시켜 per-cap 부여가 서버 입도로도 동작(codex 112 P2).
    if kind == CAP_KIND_MCP and "/" in name:
        server = name.split("/", 1)[0]
        return bool(enforcer.enforce(subject, f"capability:{kind}:{server}", "invoke"))
    return False


def _rbac_allows(enforcer: casbin.AsyncEnforcer, subject: str, kind: str, name: str | None) -> bool:
    """per-cap RBAC 판정 **단일 술어**(스펙 112 — build_broker·_build_resume_broker 공유, drift 0).
    - name 지정: kind-레벨(`capability:{kind}`) OR 능력별(`capability:{kind}:{name}`) 부여.
    - name=None: **DB 회피 게이트**용 — kind-레벨 OR 이 kind에 per-cap 부여가 *하나라도* 있나.
      discover가 provider DB 접촉을 거를 때 씀."""
    if enforcer.enforce(subject, f"capability:{kind}", "invoke"):
        return True
    if name is not None:
        return _has_direct_grant(enforcer, subject, kind, name)
    return _has_any_percap(enforcer, subject, kind)


def build_broker(
    principal: User | str,
    allowlist: list[str] | None,
    tool_policy: dict | None = None,
    rag_min_scores: dict | None = None,
    delegation_chain: tuple = (),
    delegation_budget: dict | None = None,
    force_approval: bool = False,
) -> PolicyScopedBroker:
    """chat.py 배선용 — principal(유저/머신)에서 RBAC 판정 클로저를 만들어 스코프된 브로커 구성.

    RBAC: `is_superuser` 우회(authz 패턴) 아니면 `enforce(str(id), f"capability:{kind}", "invoke")`.
    머신 토큰(str principal, id 없음) → **deny**(안전측; Phase 1 오케스트레이션은 유저 세션 대상).
    기본 정책은 admin('*','*')만 시드돼 있어 member는 거부된다(deny-by-default가 정책 부재에서도 성립)."""
    from .. import authz

    def rbac_allows(kind: str, name: str | None = None) -> bool:
        # per-cap 부여 지원(스펙 112). name 지정=특정 판정(kind-레벨 OR `capability:{kind}:{name}`).
        # name=None=**DB 회피 게이트**용 "이 kind에 부여가 하나라도 있나"(kind-레벨 OR 임의 per-cap) —
        # discover가 이걸로 provider DB 접촉을 거른다(존재 누출 0 보존).
        if isinstance(principal, str):
            return False  # 머신 토큰: 능력 오케스트레이션 비대상(deny-by-default)
        if getattr(principal, "is_superuser", False):
            return True  # 부트스트랩·운영 안전판(authz 우회 패턴)
        return _rbac_allows(authz.get_enforcer(), str(principal.id), kind, name)

    # user_id = 주체 도출값(스펙 104 MemoryProvider self-scope). 머신 토큰(str)은 id 없음 → None →
    # 메모리 능력 없음(rbac_allows도 deny). 어드민이어도 자기 id라 타인 기억 위임 접근 불가(에스컬레이션 X).
    uid = None if isinstance(principal, str) else str(principal.id)
    # 스펙 294: 조립 표면을 BrokerContext로 명문화 → build_providers가 구체 배선(broker는 소비만).
    providers = build_providers(
        BrokerContext(
            principal=principal,
            user_id=uid,
            delegation_chain=delegation_chain,
            delegation_budget=delegation_budget,
            rag_min_scores=rag_min_scores,
        )
    )
    return PolicyScopedBroker(
        allowlist, rbac_allows, providers, tool_policy=tool_policy, force_approval=force_approval
    )

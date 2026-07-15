"""kind=agent provider — A2A(원격 code/external) + 로컬 인프로세스 위임(스펙 100→256).

spec 100 A2A 코드를 **행위 보존**으로 이관. `_a2a_text`는 approval_for·invoke 공유
(드리프트 0, "승인한 것 == 전송되는 것") — AgentProvider와 같은 모듈 필수.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from agent.runtime import Capability, InvokeResult, is_remote_source

from ... import a2a_client
from ...models import Agent
from ...ownership import may_use_agent
from ..common import CAP_KIND_AGENT, _kind_of

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from ...models import User

# 위임 깊이 상한(스펙 256 v2 — 사용자: 깊이 N). 종료 보장의 핵심은 방문 집합(체인 내 재방문 금지 —
# 유한 에이전트 수로 종료 보장)이고, 이 캡은 비용 폭주 방지용 여유 상한.
DELEGATION_MAX_DEPTH = 8
# 위임 총량 예산(스펙 256, codex [P2] — breadth 폭주 차단). 방문 집합은 *깊이*만 막고 *너비*는
# 안 막는다(한 노드가 여러 새 에이전트에 위임 가능). 순환은 없어도 팬아웃 곱(최악 분기^깊이)으로
# 모델 호출이 폭주할 수 있다. 턴 단위 공유 카운터로 로컬 위임 총 실행 수에 상한을 건다(원격 A2A는
# HTTP 왕복 자연 상한이 있어 제외). 정상 다중 에이전트 협업(수 개~십수 개)엔 넉넉, 폭주만 접는다.
DELEGATION_MAX_TOTAL = 32

A2A_DELEGATE_PERMISSION = (
    "a2a.delegate"  # A2A 위임 승인 action(대상 Agent opt-in requires_approval, 스펙 117)
)


def _a2a_text(args: dict) -> str:
    """A2A 위임 입력 텍스트 정규화 — approval_for·invoke **공유**(드리프트 0, 승인=전송)."""
    return str(args.get("text", "")) if isinstance(args, dict) else str(args)


def _hook_for(agent: Agent) -> str:
    """한 줄 후크 — 카드 description → prompt → name 순 첫 비어있지 않은 줄(≤200자). load-bearing:
    발견 선택 품질이 여기 달렸다(설계결정 3)."""
    card = (agent.config or {}).get("card")
    desc = card.get("description") if isinstance(card, dict) else None
    for cand in (desc, agent.prompt, agent.name):
        if cand and str(cand).strip():
            return str(cand).strip().splitlines()[0][:200]
    return ""


class AgentProvider:
    """kind=agent — A2A(원격 code/external Agent + endpoint). spec 100 A2A 코드를 **행위 보존**으로 이관."""

    kind = CAP_KIND_AGENT

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        principal: User | str | None = None,
        delegation_chain: tuple = (),
        delegation_budget: dict | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._principal = principal  # 로컬 위임(스펙 256) — 하위 실행의 RBAC 주체(호출자와 동일)
        # 호출 체인(스펙 256 v2 — 깊이 N): 이 실행 경로에서 이미 실행 중인 agent_id들(루트 포함).
        # 체인 내 재방문 금지 = 순환 차단, 새 에이전트로는 계속 하강 가능(종료는 유한성으로 보장).
        self._chain: tuple = tuple(delegation_chain)
        # 위임 총량 예산(codex [P2]): 턴 전체가 공유하는 mutable {"n": 실행수}. 루트에서 1회 생성돼
        # 하위 브로커까지 참조로 관통 → 너비 폭주를 전역 카운터로 상한. None이면 미적용(비위임 경로).
        self._budget = delegation_budget

    def _delegable(self, a: Agent) -> bool:
        """candidates·load **공유 술어**(드리프트 0) — 위임 후보/대상 자격 게이트.

        - 사용 게이트(스펙 147 — codex 256 [P1] 봉합): 타인 private 에이전트는 존재조차 접는다.
          chat 본경로(may_use_agent 404-fold)와 정합 — 브로커 경로만 게이트가 빠져 있어 override/config에
          타인 agt_id를 심어 실행·존재 오라클이 가능하던 구멍을 닫는다. external=항상 허용·public=모두·
          private=소유자/특권만(fail-closed: principal None인 재개 경로는 private 자동 제외).
        - 원격은 호출 가능한 엔드포인트 필수(A2A).
        - 로컬 ui 위임(스펙 256)은 서빙 중(활성 버전 보유)만(초안-only 제외) + 체인 내 재방문 금지
          (순환 차단, v2) + 깊이 상한(비용 폭주 여유 캡 — 종료 자체는 방문 집합이 보장).
        """
        if not may_use_agent(a, self._principal):
            return False
        if is_remote_source(a.source):
            return bool(a.endpoint)
        if not a.active_version:
            return False
        return a.agent_id not in self._chain and len(self._chain) < DELEGATION_MAX_DEPTH

    async def candidates(self, allow: set[str]) -> list[Capability]:
        agent_ids = {a for a in allow if _kind_of(a) == CAP_KIND_AGENT}
        if not agent_ids:
            return []  # agent-kind 항목 없음 → DB 미접촉
        # allowlist를 SELECT WHERE에 밀어 거부 대상을 **로드조차 안 함**(체크리스트 §2 존재 오라클 차단).
        async with self._session_factory() as db:
            rows = (
                (await db.execute(select(Agent).where(Agent.agent_id.in_(agent_ids))))
                .scalars()
                .all()
            )
        return [
            Capability(id=a.agent_id, kind=CAP_KIND_AGENT, name=a.name, hook=_hook_for(a))
            for a in rows
            if self._delegable(a)
        ]

    async def load(self, cap_id: str) -> Agent | None:
        async with self._session_factory() as db:
            a = (
                await db.execute(select(Agent).where(Agent.agent_id == cap_id))
            ).scalar_one_or_none()
        if a is None:
            return None  # 미존재 → 존재 비노출로 접힘
        # 호출 시점 재검증(discover 결과 신뢰 안 함) — candidates와 동일 술어(사용 게이트 스펙 147·
        # 순환·깊이 게이트 동일 적용), 미자격은 존재 비노출로 접힘.
        if not self._delegable(a):
            return None
        return a

    def describe(self, row: Agent) -> Capability:
        return Capability(
            id=row.agent_id,
            kind=CAP_KIND_AGENT,
            name=row.name,
            hook=_hook_for(row),
            input_schema={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        )

    async def invoke(self, row: Agent, args: dict) -> InvokeResult:
        user_text = _a2a_text(args)  # approval_for와 동일 헬퍼(승인한 것 == 전송되는 것)
        if not is_remote_source(row.source):
            return await self._invoke_local(row, user_text)
        return await self._invoke_remote(row, user_text)

    async def _invoke_local(self, row: Agent, user_text: str) -> InvokeResult:
        """로컬 ui 위임(스펙 256) — A2A(HTTP) 대신 인프로세스 직접 실행(I/O 최소, 사용자 결정)."""
        # principal 부재 방어(codex 256 [P2] — 크래시 대신 정직 실패): 로컬 위임은 하위
        # eval_run_agent→build_broker가 principal.id를 요구한다. principal이 없으면(요청자 유실 등)
        # build_broker가 즉시 크래시하므로, 여기서 정직 에러 obs로 접어 승인된 cap이 조용히 죽지
        # 않게 한다. 정상 경로(chat·eval 위임)는 항상 principal 관통이라 도달하지 않는다.
        if self._principal is None:
            return InvokeResult(
                text="",
                trust="untrusted",
                error="로컬 위임 실행 주체(principal) 미상 — 위임 불가",
                raw={"cap_id": row.agent_id, "kind": CAP_KIND_AGENT, "local": True},
            )
        # 위임 총량 예산(codex [P2]): 턴 전체 로컬 실행 수 상한. 초과 시 정직 에러로 접어 팬아웃
        # 폭주를 차단(순환 아님 — 방문 집합이 이미 순환은 막음, 이건 *너비* 상한). 카운트는 실행
        # 직전 증가(승인·검증 통과분만).
        if self._budget is not None:
            if self._budget.get("n", 0) >= DELEGATION_MAX_TOTAL:
                return InvokeResult(
                    text="",
                    trust="untrusted",
                    error=f"위임 총량 상한({DELEGATION_MAX_TOTAL}) 초과 — 이 턴의 추가 위임 차단",
                    raw={"cap_id": row.agent_id, "kind": CAP_KIND_AGENT, "local": True},
                )
            self._budget["n"] = self._budget.get("n", 0) + 1
        # 평가 러너 재사용: 무오염(세션·memory.add 없음)·승인 걸리면 error obs(정직 실패)·
        # deny_agent_delegation=깊이 1(하위에서 재위임 불가 — A→B→A 순환 구조 차단).
        from ...eval_runner import eval_run_agent  # 함수 내 임포트 — chat→broker 순환 회피

        obs = await eval_run_agent(
            row.id,
            user_text,
            self._principal,
            delegation_chain=self._chain,
            delegation_budget=self._budget,
        )
        return InvokeResult(
            text=str(obs.get("output") or ""),
            trust="untrusted",  # 로컬이어도 결과는 데이터(지시 아님) — 채널 격리 불변(설계결정 5)
            error=(str(obs.get("detail") or "하위 실행 실패") if obs.get("error") else None),
            raw={
                "cap_id": row.agent_id,
                "kind": CAP_KIND_AGENT,
                "local": True,  # 인스펙터 표식(호출 방식이 다름을 정직하게)
                # 하위 실행 흐름(사용자 결정 — 트레이싱 관점): canonical 노드 상한 50개
                "subTraceNodes": list(obs.get("trace_nodes") or [])[:50],
            },
        )

    async def _invoke_remote(self, row: Agent, user_text: str) -> InvokeResult:
        """원격 A2A 전송 1회 → 텍스트 접기. a2a_client가 SSRF/net_guard·캡·타임아웃 적용."""
        card = (row.config or {}).get("card")
        acc: list[str] = []
        errored: str | None = None
        # a2a_client의 이 제너레이터는 raise 안 함(에러=프레임).
        async for frame in a2a_client.a2a_stream(
            row.endpoint,
            row.token,
            user_text,
            streaming=a2a_client.card_streaming(card),
            context_id=None,
        ):
            if "error" in frame:
                errored = frame["error"]
            elif frame.get("text"):
                acc.append(frame["text"])
        # 결과 = **데이터**(지시 아님). trust=untrusted 불변(인젝션 방어, 설계결정 5).
        return InvokeResult(
            text="".join(acc),
            trust="untrusted",
            error=errored,
            raw={"cap_id": row.agent_id, "kind": CAP_KIND_AGENT},
        )

    def node_label(self, row: Agent) -> str:
        return f"broker_invoke:{CAP_KIND_AGENT}:{row.name}"

    def approval_for(
        self, row: Agent, _cap_id: str, args: dict, _tool_policy: dict | None = None
    ) -> dict | None:
        """A2A 위임 승인 = **대상 Agent의 opt-in 플래그**(스펙 117). config.requires_approval가 참일 때만
        게이트(부재/거짓 = 게이트 없음 = **현동작 보존·무회귀**). MCP `_APPROVAL_ACTIONS` 옵트인의
        에이전트 단위 형제. approval_for와 invoke가 `_a2a_text`로 동일 정규화 → **승인한 것 == 전송되는 것**."""
        cfg = getattr(row, "config", None)
        cfg = (
            cfg if isinstance(cfg, dict) else {}
        )  # 오염 데이터(비-dict config) 방어 — .get AttributeError 차단
        if not cfg.get("requires_approval"):
            return None
        text = _a2a_text(
            args
        )  # invoke와 동일 헬퍼(드리프트 0) — 마스킹 없이 노출(사람이 무엇이 전송되는지 봐야 승인)
        return {
            "permission": A2A_DELEGATE_PERMISSION,
            "action": A2A_DELEGATE_PERMISSION,
            "args": {"text": text},
            "summary": f"에이전트 '{row.name}'에게 위임 전송(A2A) — 승인 필요",
        }

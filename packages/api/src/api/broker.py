"""능력 브로커 구현 + 정책 게이트 (스펙 100 Phase 1 → 101 Phase 2-a: provider 시임 + MCP).

계약(`CapabilityBroker` Protocol)은 `packages/agent`에 있고, **구현·정책은 여기(API)** 에 둔다
(설계결정 1: 계약=agent, 배선·정책=api). `PolicyScopedBroker`는 생성 시 (allowlist ∩ RBAC)로
**미리 스코프**되며, 에이전트는 스코프된 인스턴스만 `ctx.broker`로 받는다 — 정책·DB를 직접 만지지
않는다(주입 단일 출처 085 U2).

**provider 시임(스펙 101)**: 정책(allowlist∩RBAC·deny-by-default·존재비노출·단일 `_permitted`)은
브로커에 남기고, kind별 메커닉(후보 나열·cap 로드·invoke 전송·hook·input_schema·승인정책)을
`_CapabilityProvider`로 이관한다. `PolicyScopedBroker`는 cap_id에서 kind를 파싱해 provider로 라우팅하되,
정책 판정은 **provider 호출 전에** 브로커가 수행한다(게이트 단일 지점, 체크리스트 §3 드리프트 0).
- `AgentProvider`(kind=agent) — A2A(원격 code/external Agent + endpoint). 전송은 `a2a_client`가 담당.
- `McpProvider`(kind=mcp) — `McpServer` 툴 단위. 전송은 `runtime.mcp_connection`+`MultiServerMCPClient`.
결과는 두 provider 모두 **untrusted 데이터**(설계결정 5, learning 100 — 데이터 채널로 격리는 flow 몫).

**브로커 서브스텝 HIL(스펙 101 §3.5)**: 위임한 cap이 승인을 요구하면(`provider.approval_for`) 브로커가
전송(부수효과) **이전**에 `interrupt()`를 호출해 부모 그래프를 pause시킨다 — 기존 HIL 파이프라인
(interrupt→__interrupt__→SSE→Approval→Command(resume))을 그대로 재사용(새 배선 0). 게이트는 브로커
단일 지점, 승인 정책은 provider별(MCP=`_APPROVAL_ACTIONS` 재사용 → 그래프-tools와 드리프트 0).

**인가 입도(Phase 2-a 커버 범위 — 명시 경계, codex 100 [P1] #1/#2 수용)**: 경계는
`(에이전트 config allowlist) ∩ (유저 kind-단위 RBAC)`다. allowlist 축은 **에이전트별**(Agent/McpServer
모델에 owner 없음 = 공유 카탈로그). RBAC 축은 **kind 단위**(`capability:{kind}`) — 기본 정책은
admin('*','*')만 시드돼 member는 kind 자체가 거부(deny-by-default). per-cap·per-user 인가와 소유권은
후속 스펙 몫(지배 스펙 §비목표에 기록).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Protocol

from agent.runtime import Capability, InvokeResult, is_remote_source
from sqlalchemy import select

from . import a2a_client
from .db import SessionLocal
from .models import Agent, McpServer
from .ownership import may_use_agent

CAP_KIND_AGENT = "agent"  # A2A provider(Phase 1).
CAP_KIND_MCP = "mcp"  # MCP provider(Phase 2-a).
CAP_KIND_RAG = "rag"  # RAG provider(Phase 2, 스펙 103 — 문서 컬렉션 검색).
CAP_KIND_MEMORY = "memory"  # Memory read provider(Phase 2-c, 스펙 104 — 유저 장기 기억 검색, per-user 소유).
CAP_KIND_MEMORY_WRITE = "memwrite"  # Memory write provider(스펙 105 — 유저 장기 기억 저장, 첫 부수효과·승인 게이트).
CAP_KIND_MEMORY_EDIT = "memedit"  # Memory edit provider(스펙 111 — 유저 장기 기억 수정/삭제, 대상 있는 첫 부수효과·소유권 선행).


class CapabilityNotFound(Exception):
    """능력 미해결 — **미존재와 미허가를 구분하지 않는다**(403/404 접기, 존재 비노출)."""


# ------------------------------- 네임스페이싱(스펙 101 §3.3) -------------------------------
# allowlist·cap_id 항목은 `"<kind>:<id>"`. `mcp:<server>/<tool>`(툴 단위) 또는 `mcp:<server>`(서버 전체).
# **접두사 없는 bare 항목 = kind agent**(하위호환 — spec 100 config 불변, agent_id는 `agt_...`라 콜론 없음).
# 위임 깊이 상한(스펙 256 v2 — 사용자: 깊이 N). 종료 보장의 핵심은 방문 집합(체인 내 재방문 금지 —
# 유한 에이전트 수로 종료 보장)이고, 이 캡은 비용 폭주 방지용 여유 상한.
DELEGATION_MAX_DEPTH = 8
# 위임 총량 예산(스펙 256, codex [P2] — breadth 폭주 차단). 방문 집합은 *깊이*만 막고 *너비*는
# 안 막는다(한 노드가 여러 새 에이전트에 위임 가능). 순환은 없어도 팬아웃 곱(최악 분기^깊이)으로
# 모델 호출이 폭주할 수 있다. 턴 단위 공유 카운터로 로컬 위임 총 실행 수에 상한을 건다(원격 A2A는
# HTTP 왕복 자연 상한이 있어 제외). 정상 다중 에이전트 협업(수 개~십수 개)엔 넉넉, 폭주만 접는다.
DELEGATION_MAX_TOTAL = 32


def _kind_of(item: str) -> str:
    """cap_id/allowlist 항목에서 kind 파싱(별도 조회 없이 id만으로).
    `mcp:`/`rag:` 접두사 → 해당 kind, 그 외(콜론 없는 bare `agt_...`) → agent(하위호환)."""
    if isinstance(item, str):
        if item.startswith(f"{CAP_KIND_MCP}:"):
            return CAP_KIND_MCP
        if item.startswith(f"{CAP_KIND_RAG}:"):
            return CAP_KIND_RAG
        if item.startswith(f"{CAP_KIND_MEMORY_WRITE}:"):
            return CAP_KIND_MEMORY_WRITE
        if item.startswith(f"{CAP_KIND_MEMORY_EDIT}:"):
            return CAP_KIND_MEMORY_EDIT
        if item.startswith(f"{CAP_KIND_MEMORY}:"):
            return CAP_KIND_MEMORY
    return CAP_KIND_AGENT


def _parse_mcp(item: str) -> tuple[str, str | None]:
    """`mcp:server/tool` → (server, tool); `mcp:server` → (server, None). 접두사 없으면 (item, None) 방어."""
    body = item[len(CAP_KIND_MCP) + 1:] if item.startswith(f"{CAP_KIND_MCP}:") else item
    if "/" in body:
        server, tool = body.split("/", 1)
        return server, tool
    return body, None


def _parse_rag(item: str) -> str:
    """`rag:<collection_name>` → `<collection_name>`(접두사만 스트립 — 이름에 콜론/슬래시 있어도 안전).
    RAG는 mcp의 server/tool 2레벨과 달리 1레벨(컬렉션 이름 하나). 접두사 없으면 원본 방어."""
    return item[len(CAP_KIND_RAG) + 1:] if item.startswith(f"{CAP_KIND_RAG}:") else item


def _parse_mem(item: str) -> str:
    """`memory:<resource>` → `<resource>`(첫 출하는 `"user"`만 유효 — 주체 자신의 장기 기억).
    **대상 user_id는 cap_id에 담기지 않는다**(스펙 104 핵심 anti-leak) — 리소스는 자원 *종류*만 가리키고
    누구의 것인지는 런타임 principal에서 도출한다. 접두사 없으면 원본 방어."""
    return item[len(CAP_KIND_MEMORY) + 1:] if item.startswith(f"{CAP_KIND_MEMORY}:") else item


def _parse_memedit(item: str) -> str:
    """memedit cap 리소스 파싱(`memedit:user` → `user`). 미지원 리소스는 load가 거른다(존재 비노출)."""
    return item[len(CAP_KIND_MEMORY_EDIT) + 1:] if item.startswith(f"{CAP_KIND_MEMORY_EDIT}:") else item


def _cap_resource(cap_id: str, kind: str) -> str:
    """per-cap RBAC object의 리소스 부분(스펙 112) — `capability:{kind}:{resource}`로 특정 능력만 부여.
    kind별 식별자: mcp=`server[/tool]`, rag=컬렉션명, memory/memwrite/memedit=`user`, agent=cap_id(agt_…).
    kind-레벨 부여(`capability:{kind}`)와 별개로 admin이 세분 부여할 수 있게 하는 안정 키."""
    if kind == CAP_KIND_MCP:
        return cap_id[len(CAP_KIND_MCP) + 1:] if cap_id.startswith(f"{CAP_KIND_MCP}:") else cap_id
    if kind == CAP_KIND_RAG:
        return _parse_rag(cap_id)
    if kind == CAP_KIND_MEMORY:
        return _parse_mem(cap_id)
    if kind == CAP_KIND_MEMORY_WRITE:
        return _parse_memwrite(cap_id)
    if kind == CAP_KIND_MEMORY_EDIT:
        return _parse_memedit(cap_id)
    return cap_id  # agent: cap_id 자체가 리소스 식별자(agt_…)


def _parse_memwrite(item: str) -> str:
    """`memwrite:<resource>` → `<resource>`(첫 출하 `"user"`만 — 주체 자신의 기억에 저장). `_parse_mem`과
    대칭. 대상 user_id는 cap_id에 없다(스펙 105 anti-leak, 104와 동일). 접두사 없으면 원본 방어."""
    return item[len(CAP_KIND_MEMORY_WRITE) + 1:] if item.startswith(f"{CAP_KIND_MEMORY_WRITE}:") else item


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


def _first_line(text: str, fallback: str) -> str:
    """설명 첫 줄 후크(≤200자). 비면 fallback(툴 이름)."""
    s = (text or "").strip()
    return s.splitlines()[0][:200] if s else fallback


def _tool_input_schema(tool) -> dict | None:
    """MCP 툴의 inputSchema를 JSON 스키마 dict로 정규화(pydantic 모델이면 model_json_schema)."""
    schema = getattr(tool, "args_schema", None)
    if isinstance(schema, dict):
        return schema
    if schema is not None and hasattr(schema, "model_json_schema"):
        try:
            return schema.model_json_schema()
        except Exception:  # noqa: BLE001 — 스키마 추출 실패는 None(describe가 죽지 않게)
            return None
    return None


def _adapt_args(tool, args: dict) -> dict:
    """generic 위임 인자(`{"text": query}`, orchestrate가 kind-무관하게 넘김)를 **툴의 실제 파라미터**로
    적응한다. flow는 A2A 모양(`text`)으로 부르지만 MCP 툴은 자기 시그니처(예 web_search(query),
    delete_record(record_id))를 가진다 — flow 코드 변경 없이(스펙 101 §3.4) 여기서 매핑한다.
    스키마 키가 이미 맞으면 통과, 아니면 단일 파라미터/알려진 이름으로 값 하나를 실어 보낸다."""
    if not isinstance(args, dict):
        args = {"text": str(args)}
    props = (_tool_input_schema(tool) or {}).get("properties") or {}
    if not props or set(args) <= set(props):
        return args  # 스키마 없음(무검증 통과) 또는 이미 적합
    val = args.get("text") or args.get("query") or args.get("input") or next(iter(args.values()), "")
    if len(props) == 1:
        return {next(iter(props)): val}  # 단일 파라미터 툴 → 그 파라미터로
    for cand in ("text", "query", "input", "message", "q"):
        if cand in props:
            return {cand: val}
    return args  # 매핑 불가 → 원본(툴이 graceful 실패로 처리)


# ------------------------------- provider 시임(스펙 101 §3.1) -------------------------------
class _CapabilityProvider(Protocol):
    """브로커 내부 전용 provider 계약(계약 packages/agent는 불변). 정책은 **모른다** — 브로커가
    호출 전에 `_permitted`로 게이트한다(게이트 단일 지점)."""

    kind: str

    async def candidates(self, allow: set[str]) -> list[Capability]:  # allow∩모집단 → 후보(hook 채움)
        ...

    async def load(self, cap_id: str) -> object | None:  # 허가 전제, cap_id→backing row(미존재→None)
        ...

    def describe(self, row) -> Capability:  # row→input_schema 채운 Capability
        ...

    async def invoke(self, row, args: dict) -> InvokeResult:  # 전송 1회→텍스트 접기(untrusted)
        ...

    def node_label(self, row) -> str:  # 관측 프레임 노드명 broker_invoke:<kind>:<...>
        ...

    def approval_for(self, row, cap_id: str, args: dict, tool_policy: dict | None = None) -> dict | None:  # HIL 승인 payload | None
        ...


A2A_DELEGATE_PERMISSION = "a2a.delegate"  # A2A 위임 승인 action(대상 Agent opt-in requires_approval, 스펙 117)


def _a2a_text(args: dict) -> str:
    """A2A 위임 입력 텍스트 정규화 — approval_for·invoke **공유**(드리프트 0, 승인=전송)."""
    return str(args.get("text", "")) if isinstance(args, dict) else str(args)


class AgentProvider:
    """kind=agent — A2A(원격 code/external Agent + endpoint). spec 100 A2A 코드를 **행위 보존**으로 이관."""

    kind = CAP_KIND_AGENT

    def __init__(self, session_factory, principal=None, delegation_chain: tuple = (), delegation_budget=None):
        self._session_factory = session_factory
        self._principal = principal  # 로컬 위임(스펙 256) — 하위 실행의 RBAC 주체(호출자와 동일)
        # 호출 체인(스펙 256 v2 — 깊이 N): 이 실행 경로에서 이미 실행 중인 agent_id들(루트 포함).
        # 체인 내 재방문 금지 = 순환 차단, 새 에이전트로는 계속 하강 가능(종료는 유한성으로 보장).
        self._chain: tuple = tuple(delegation_chain)
        # 위임 총량 예산(codex [P2]): 턴 전체가 공유하는 mutable {"n": 실행수}. 루트에서 1회 생성돼
        # 하위 브로커까지 참조로 관통 → 너비 폭주를 전역 카운터로 상한. None이면 미적용(비위임 경로).
        self._budget = delegation_budget

    async def candidates(self, allow: set[str]) -> list[Capability]:
        agent_ids = {a for a in allow if _kind_of(a) == CAP_KIND_AGENT}
        if not agent_ids:
            return []  # agent-kind 항목 없음 → DB 미접촉
        # allowlist를 SELECT WHERE에 밀어 거부 대상을 **로드조차 안 함**(체크리스트 §2 존재 오라클 차단).
        async with self._session_factory() as db:
            rows = (
                (await db.execute(select(Agent).where(Agent.agent_id.in_(agent_ids)))).scalars().all()
            )
        caps: list[Capability] = []
        for a in rows:
            # 사용 게이트(스펙 147 — codex 256 [P1] 봉합): 타인 private 에이전트는 존재조차 후보에서
            # 접는다. chat 본경로(may_use_agent 404-fold)와 정합 — 브로커 경로만 게이트가 빠져 있어
            # override/config에 타인 agt_id를 심어 실행·존재 오라클이 가능하던 구멍을 닫는다.
            # external=항상 허용(가져다 쓰는 것)·public=모두·private=소유자/특권만(fail-closed: principal
            # None인 재개 경로는 private 자동 제외).
            if not may_use_agent(a, self._principal):
                continue
            if is_remote_source(a.source):
                if not a.endpoint:
                    continue  # 원격은 호출 가능한 엔드포인트 필수(A2A)
            else:
                if not a.active_version:
                    continue  # 로컬 ui 위임(스펙 256) — 서빙 중(활성 버전 보유)만. 초안-only는 후보 아님.
                if a.agent_id in self._chain:
                    continue  # 순환 차단(스펙 256 v2) — 이 경로에서 이미 실행 중인 에이전트는 후보 제외
                if len(self._chain) >= DELEGATION_MAX_DEPTH:
                    continue  # 비용 폭주 상한(여유 캡 — 종료 자체는 방문 집합이 보장)
            caps.append(Capability(id=a.agent_id, kind=CAP_KIND_AGENT, name=a.name, hook=_hook_for(a)))
        return caps

    async def load(self, cap_id: str) -> Agent | None:
        async with self._session_factory() as db:
            a = (
                await db.execute(select(Agent).where(Agent.agent_id == cap_id))
            ).scalar_one_or_none()
        if a is None:
            return None  # 미존재 → 존재 비노출로 접힘
        if not may_use_agent(a, self._principal):
            return None  # 사용 게이트 재검증(스펙 147, codex 256 [P1]) — discover와 동일, 존재 비노출 접기
        if is_remote_source(a.source):
            if not a.endpoint:
                return None
        else:
            if not a.active_version:
                return None  # 로컬 ui(스펙 256) — 서빙 중만
            if a.agent_id in self._chain or len(self._chain) >= DELEGATION_MAX_DEPTH:
                return None  # 호출 시점 재검증(discover 결과 신뢰 안 함 — 순환·깊이 게이트 동일 적용)
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
            # 로컬 ui 위임(스펙 256) — A2A(HTTP) 대신 인프로세스 직접 실행(I/O 최소, 사용자 결정).
            # 평가 러너 재사용: 무오염(세션·memory.add 없음)·승인 걸리면 error obs(정직 실패)·
            # deny_agent_delegation=깊이 1(하위에서 재위임 불가 — A→B→A 순환 구조 차단).
            from .eval_runner import eval_run_agent  # 함수 내 임포트 — chat→broker 순환 회피

            obs = await eval_run_agent(
                row.id, user_text, self._principal,
                delegation_chain=self._chain, delegation_budget=self._budget,
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
        card = (row.config or {}).get("card")
        acc: list[str] = []
        errored: str | None = None
        # a2a_client가 SSRF/net_guard·캡·타임아웃 적용. 이 제너레이터는 raise 안 함(에러=프레임).
        async for frame in a2a_client.a2a_stream(
            row.endpoint, row.token, user_text, streaming=_card_streaming(card), context_id=None
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

    def approval_for(self, row, cap_id: str, args: dict, tool_policy: dict | None = None) -> dict | None:
        """A2A 위임 승인 = **대상 Agent의 opt-in 플래그**(스펙 117). config.requires_approval가 참일 때만
        게이트(부재/거짓 = 게이트 없음 = **현동작 보존·무회귀**). MCP `_APPROVAL_ACTIONS` 옵트인의
        에이전트 단위 형제. approval_for와 invoke가 `_a2a_text`로 동일 정규화 → **승인한 것 == 전송되는 것**."""
        cfg = getattr(row, "config", None)
        cfg = cfg if isinstance(cfg, dict) else {}  # 오염 데이터(비-dict config) 방어 — .get AttributeError 차단
        if not cfg.get("requires_approval"):
            return None
        text = _a2a_text(args)  # invoke와 동일 헬퍼(드리프트 0) — 마스킹 없이 노출(사람이 무엇이 전송되는지 봐야 승인)
        return {
            "permission": A2A_DELEGATE_PERMISSION,
            "action": A2A_DELEGATE_PERMISSION,
            "args": {"text": text},
            "summary": f"에이전트 '{row.name}'에게 위임 전송(A2A) — 승인 필요",
        }


class _McpBacking:
    """McpProvider.load가 돌려주는 backing — 서버명·툴명 + **연결로 실제 가져온 BaseTool**.
    describe(스키마)·invoke(ainvoke)·node_label이 이 tool을 그대로 쓴다."""

    __slots__ = ("server", "tool_name", "tool", "tools_meta")

    def __init__(self, server: str, tool_name: str, tool, tools_meta: dict | None = None):
        self.server = server
        self.tool_name = tool_name
        self.tool = tool
        self.tools_meta = tools_meta  # 도구 승인 정책 리졸버용(스펙 177)


class McpProvider:
    """kind=mcp — `McpServer`의 **enabled_tools 툴 단위**를 능력으로. 전송은 `runtime.mcp_connection`
    (build_mcp_tools와 공유) + `MultiServerMCPClient` 재사용. MCP는 이름만 DB에 저장하므로 hook·스키마·
    invoke는 서버에 실제로 붙어 얻는다(catalog 작아 one-shot 연결 허용, 설계결정 10)."""

    kind = CAP_KIND_MCP

    def __init__(self, session_factory):
        self._session_factory = session_factory

    def _mcp_allow(self, allow: set[str]) -> dict:
        """allowlist의 mcp 항목 → `{server: set(tools) | None}`(None=서버 전체 허용, 그 서버 enabled_tools 전부)."""
        spec: dict[str, set | None] = {}
        for it in allow:
            if _kind_of(it) != CAP_KIND_MCP:
                continue
            server, tool = _parse_mcp(it)
            if tool is None:
                spec[server] = None  # 서버 전체(그 툴을 덮음)
            elif spec.get(server, "∅") is None:
                continue  # 이미 서버 전체 허용 → 개별 툴 항목은 무의미
            else:
                spec.setdefault(server, set())
                spec[server].add(tool)
        return spec

    async def _server_dicts(self, server_names: set[str]) -> list[dict]:
        """McpServer 행 → build_mcp_tools 계약 dict(name/url/transport/enabled_tools/auth_token).
        auth는 chat._load_context와 동일 규칙으로 복호화(마스킹/빈값→None → 헤더 생략, drift 0)."""
        from . import crypto

        async with self._session_factory() as db:
            rows = (
                (await db.execute(select(McpServer).where(McpServer.name.in_(server_names)))).scalars().all()
            )
        out: list[dict] = []
        for r in rows:
            token = None if crypto.is_masked(r.auth) else crypto.decrypt(r.auth)
            out.append(
                {
                    "name": r.name,
                    "url": r.url or r.endpoint or "",
                    "transport": r.transport or "http",
                    "enabled_tools": list(r.enabled_tools or []),
                    "auth_token": token,
                    "tools_meta": r.tools_meta or {},  # 도구 승인 정책 리졸버용(스펙 177)
                }
            )
        return out

    async def _get_tools(self, server_name: str, conn: dict) -> list:
        from langchain_mcp_adapters.client import MultiServerMCPClient  # 지연 임포트

        client = MultiServerMCPClient({server_name: conn})
        return await client.get_tools(server_name=server_name)

    async def candidates(self, allow: set[str]) -> list[Capability]:
        spec = self._mcp_allow(allow)
        if not spec:
            return []  # mcp-kind 항목 없음 → DB/네트워크 미접촉
        from . import net_guard

        await net_guard.refresh_allowed_hosts()  # DB allowlist 무재시작 반영(127.0.0.1 mock 통과)
        caps: list[Capability] = []
        for s in await self._server_dicts(set(spec)):
            conn = _rt().mcp_connection(s)
            if conn is None:
                continue  # 미지원 transport/SSRF 차단 → 그 서버 스킵
            enabled = set(s.get("enabled_tools") or [])
            allowset = spec.get(s["name"])  # None=서버 전체
            try:
                tools = await self._get_tools(s["name"], conn)
            except Exception:  # noqa: BLE001 — 서버 다운/프로토콜 오류는 그 서버만 스킵(부분 실패 격리)
                continue
            for t in tools:
                if enabled and t.name not in enabled:
                    continue  # enabled_tools 밖(서버측 강제)
                if allowset is not None and t.name not in allowset:
                    continue  # allowlist가 특정 툴만 허용 → 그 외 미노출
                caps.append(
                    Capability(
                        id=f"{CAP_KIND_MCP}:{s['name']}/{t.name}",
                        kind=CAP_KIND_MCP,
                        name=t.name,
                        hook=_first_line(getattr(t, "description", "") or "", t.name),
                    )
                )
        return caps

    async def load(self, cap_id: str) -> _McpBacking | None:
        server, tool = _parse_mcp(cap_id)
        if tool is None:
            return None  # `mcp:server`(툴 미지정)는 호출 불가 대상 → 존재 비노출
        from . import net_guard

        await net_guard.refresh_allowed_hosts()
        servers = await self._server_dicts({server})
        if not servers:
            return None
        s = servers[0]
        conn = _rt().mcp_connection(s)
        if conn is None:
            return None
        enabled = set(s.get("enabled_tools") or [])
        if enabled and tool not in enabled:
            return None  # enabled 밖 → 존재 비노출
        try:
            tools = await self._get_tools(server, conn)
        except Exception:  # noqa: BLE001 — 연결 실패는 미해결(존재 비노출)
            return None
        match = next((t for t in tools if t.name == tool), None)
        if match is None:
            return None
        return _McpBacking(server, tool, match, s.get("tools_meta"))

    def describe(self, row: _McpBacking) -> Capability:
        return Capability(
            id=f"{CAP_KIND_MCP}:{row.server}/{row.tool_name}",
            kind=CAP_KIND_MCP,
            name=row.tool_name,
            hook=_first_line(getattr(row.tool, "description", "") or "", row.tool_name),
            input_schema=_tool_input_schema(row.tool),  # A2A의 고정 {text}와 달리 툴별 실제 스키마
        )

    async def invoke(self, row: _McpBacking, args: dict) -> InvokeResult:
        import asyncio

        from .runtime import _TOOL_TIMEOUT_S, _content_text

        cap_id = f"{CAP_KIND_MCP}:{row.server}/{row.tool_name}"
        try:
            async with asyncio.timeout(_TOOL_TIMEOUT_S):
                raw = await row.tool.ainvoke(_adapt_args(row.tool, args))
            text = _content_text(raw)  # content-block 리스트 → str 정규화(092 재사용)
            err = None
        except Exception as exc:  # noqa: BLE001 — 도구 오류가 에이전트를 죽이지 않는다(graceful)
            text = ""
            err = f"MCP 도구 실행 실패({row.server}/{row.tool_name}): {type(exc).__name__}"
        return InvokeResult(
            text=text, trust="untrusted", error=err,
            raw={"cap_id": cap_id, "kind": CAP_KIND_MCP},
        )

    def node_label(self, row: _McpBacking) -> str:
        return f"broker_invoke:{CAP_KIND_MCP}:{row.server}/{row.tool_name}"

    def approval_for(self, row, cap_id: str, args: dict, tool_policy: dict | None = None) -> dict | None:
        """MCP 승인 정책 = 그래프-tools 경로와 **동일 리졸버**(`resolve_tool_approval`, 스펙 177) 공유
        (드리프트 0 — 관리자가 tools_meta로 설정한 정책이 두 경로 일관 적용). 마스킹은 `_redact_args`
        재사용. 걸리지 않는 툴은 None(즉시 실행)."""
        from .runtime import _redact_args, resolve_tool_approval

        server, tool = _parse_mcp(cap_id)
        appr = resolve_tool_approval(server, tool, getattr(row, "tools_meta", None), tool_policy)
        if appr is None:
            return None
        approver = appr.get("approver", "admin")
        return {
            "permission": appr["permission"],
            "approver": approver,  # 스펙 177 P2 — Approval 스탬프 → _may_resolve 인가
            "server": server,
            "tool": tool,
            "action": f"{server}.{tool}",
            "args": _redact_args(args if isinstance(args, dict) else {"text": args}),
            "summary": f"{server}.{tool} 실행 — {'본인' if approver == 'self' else '관리자'} 승인 필요",
        }


class _RagBacking:
    """RagProvider.load가 돌려주는 backing — 컬렉션 이름·설명 + retrieval 코어용 `col` dict.
    `col`이 None이면 임베딩 설정 불완전(describe는 되고 invoke가 graceful 오류로 표면화)."""

    __slots__ = ("name", "description", "col")

    def __init__(self, name: str, description: str, col: dict | None):
        self.name = name
        self.description = description
        self.col = col


class RagProvider:
    """kind=rag — `Collection`(문서 컬렉션)을 **읽기 전용** 검색 능력으로. 전송은 `runtime.search_collections`
    코어(인-챗 RAG 도구·retrieval 시험 072와 공유) + `runtime.format_rag_hits`(스펙 103 공유 포맷터)를
    재사용 = 평행 구현 0. 부수효과 없음 → `approval_for` 항상 None(HIL 불요, 저위험의 핵심).
    결과는 문서 내용 = **untrusted 데이터**(learning 100 채널 격리는 flow synthesize 몫)."""

    kind = CAP_KIND_RAG

    def __init__(self, session_factory, min_scores: dict | None = None):
        self._session_factory = session_factory
        # 컬렉션별 최소 유사도 맵(스펙 191 v2) — invoke가 row.name으로 조회해 그 컬렉션 임계값을 적용.
        self._min_scores = min_scores if isinstance(min_scores, dict) else {}

    async def _load_rows(self, names: set[str]) -> list:
        """Collection 행을 embedding_model.provider까지 selectinload(col dict 구성에 필요)."""
        from sqlalchemy.orm import selectinload

        from .models import Collection, ModelConfig

        async with self._session_factory() as db:
            return (
                (
                    await db.execute(
                        select(Collection)
                        .where(Collection.name.in_(names))
                        .options(
                            selectinload(Collection.embedding_model).selectinload(ModelConfig.provider)
                        )
                    )
                )
                .scalars()
                .all()
            )

    def _col_dict(self, c) -> dict | None:
        """Collection → retrieval 코어 계약 dict. **chat._load_context와 동일 규칙**(drift 0). 임베딩
        모델/provider 불완전하거나 kind!=embedding이면 None(search_collection 400 가드와 동형)."""
        from . import crypto

        em = c.embedding_model
        ep = em.provider if em else None
        if em is None or ep is None or not ep.base_url or not em.model_id or em.kind != "embedding":
            return None
        return {
            "id": c.id,
            "name": c.name,
            "embed_base_url": ep.base_url,
            "embed_api_key": crypto.decrypt(ep.api_key),  # 백엔드 전용 — 응답/로그 미노출
            "embed_model_id": em.model_id,
        }

    async def candidates(self, allow: set[str]) -> list[Capability]:
        # 빈 리소스 이름(`rag:`)은 능력으로 승격 안 함(적대 리뷰 103 P2 — cap_id 문법상 빈 id 거부).
        # 근본(컬렉션 이름 min_length)은 스펙 037 CRUD 영역이라 여기선 파싱 층에서 방어만 한다.
        names = {n for a in allow if _kind_of(a) == CAP_KIND_RAG and (n := _parse_rag(a))}
        if not names:
            return []  # rag-kind 항목 없음 → DB 미접촉
        # allowlist를 SELECT WHERE에 밀어 거부 대상을 로드조차 안 함(체크리스트 §2 존재 오라클 차단).
        rows = await self._load_rows(names)
        return [
            Capability(
                id=f"{CAP_KIND_RAG}:{c.name}",
                kind=CAP_KIND_RAG,
                name=c.name,
                hook=_first_line(c.description or "", c.name),
            )
            for c in rows
        ]

    async def load(self, cap_id: str) -> _RagBacking | None:
        name = _parse_rag(cap_id)
        if not name:
            return None  # 빈 리소스 이름 → 없는 것으로(적대 리뷰 103 P2)
        rows = await self._load_rows({name})
        if not rows:
            return None  # 미존재 → 존재 비노출
        c = rows[0]
        return _RagBacking(c.name, c.description or "", self._col_dict(c))

    def describe(self, row: _RagBacking) -> Capability:
        return Capability(
            id=f"{CAP_KIND_RAG}:{row.name}",
            kind=CAP_KIND_RAG,
            name=row.name,
            hook=_first_line(row.description, row.name),
            input_schema={
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "top_k": {"type": "integer", "default": 4},
                },
                "required": ["text"],
            },
        )

    async def invoke(self, row: _RagBacking, args: dict) -> InvokeResult:
        cap_id = f"{CAP_KIND_RAG}:{row.name}"
        if row.col is None:
            return InvokeResult(
                text="", trust="untrusted",
                error=f"컬렉션 '{row.name}'의 임베딩 설정이 불완전해 검색할 수 없습니다.",
                raw={"cap_id": cap_id, "kind": CAP_KIND_RAG},
            )
        text = str(args.get("text", "")) if isinstance(args, dict) else str(args)
        top_k = args.get("top_k", 4) if isinstance(args, dict) else 4
        rt = _rt()
        # 검색 질의 표시(스펙 191) — 직접 인-챗 RAG 도구는 이미 args.query를 trace에 노출한다.
        # 조율형(브로커)도 같은 표시-안전 값을 보이게 raw에 싣되, 비밀 마스킹(_sanitize)+캡을
        # 백스톱으로 건다(일반 args 노출이 아니라 RAG 질의 1개만 — 087/092 원문 누출 경계 유지).
        from .memory import _sanitize as _san
        query_disp = _san((text or "").strip(), cap=300)
        # 이 컬렉션의 임계값(스펙 191 v2) — 맵에서 조회, 없으면 0(무필터).
        thr = rt._norm_score(self._min_scores.get(row.name, 0.0))
        try:
            hits = await rt.search_collections([row.col], text, top_k, {row.name: thr})  # 커트라인 annotate
            # 결과 = 문서 내용 = **데이터**(지시 아님). trust=untrusted 불변(인젝션 방어).
            # 스펙 192: used(커트라인 통과분)만 에이전트에 넘긴다(미달 문서 안 봄). trace(hitsDetail)엔 전부
            # (used+dropped 플래그) — 인스펙터가 "못 쓴 문서"까지 보이게. hits=used 수·topScore=used 최고.
            used = rt.used_hits(hits)
            top = max((float(h.get("score", 0.0)) for h in used), default=0.0)
            return InvokeResult(
                text=rt.format_rag_hits(used),  # 인-챗 도구와 공유 포맷(drift 0)
                trust="untrusted", error=None,
                raw={
                    "cap_id": cap_id, "kind": CAP_KIND_RAG, "hits": len(used), "topScore": round(top, 3),
                    "hitsDetail": rt._hits_detail(hits), "minScore": round(thr, 3), "query": query_disp,
                },
            )
        except rt.RagSearchError as exc:
            # 코어가 이미 분류(empty/embed/db) — graceful 오류로 접어 에이전트를 죽이지 않는다.
            # 실패해도 무엇을 검색했는지(query)는 남긴다(스펙 191 — 진단 가치).
            return InvokeResult(
                text="", trust="untrusted", error=exc.tool_msg,
                raw={"cap_id": cap_id, "kind": CAP_KIND_RAG, "query": query_disp},
            )

    def node_label(self, row: _RagBacking) -> str:
        return f"broker_invoke:{CAP_KIND_RAG}:{row.name}"

    def approval_for(self, row, cap_id: str, args: dict, tool_policy: dict | None = None) -> dict | None:
        return None  # RAG=읽기 전용(부수효과 없음) → 승인 게이트 불요.


def _rt():
    """api.runtime 지연 접근(모듈 경량·순환 import 방지). mcp_connection 등 전송 헬퍼 공유원."""
    from . import runtime

    return runtime


class _MemBacking:
    """MemoryProvider.load가 돌려주는 backing — 리소스 종류만 담는다(첫 출하 `"user"`).
    **대상 user_id는 여기 없다** — invoke가 provider의 self._user_id(principal 도출값)만 스코프로 쓴다."""

    __slots__ = ("resource",)

    def __init__(self, resource: str):
        self.resource = resource


class MemoryProvider:
    """kind=memory — 유저 장기 기억(user_id 축)을 **읽기 전용** 검색 능력으로. 첫 **per-user 소유** 능력.

    핵심(스펙 104): 능력은 `memory:user` 하나뿐이고 **누구의 기억인지는 cap_id·args가 아니라 런타임
    principal에서 도출한 `user_id`**로 정한다. 그래서 능력 이름으로 남을 가리킬 방법이 없어 교차 유저
    유출이 구조적으로 불가능하다. 검색 코어 `memory.recall_probe`(챗 회상·retrieval 시험 084와 공유) +
    `memory.format_memory_hits`(챗 회상 주입 포맷 추출, drift 0) 재사용. 읽기 전용 → `approval_for` None.
    결과는 기억 내용 = **untrusted 데이터**(learning 100 채널 격리는 flow synthesize 몫).
    """

    kind = CAP_KIND_MEMORY

    def __init__(self, session_factory, user_id: str | None):
        self._session_factory = session_factory
        self._user_id = user_id  # principal 도출값(build_broker). None=머신 → 자기 스코프 없음 → deny.

    def _cap(self, *, with_schema: bool) -> Capability:
        cap = Capability(
            id=f"{CAP_KIND_MEMORY}:user",
            kind=CAP_KIND_MEMORY,
            name="내 장기 기억",
            hook="내 장기 기억(user_id 축)에서 관련 사실 회상",
        )
        if with_schema:
            cap.input_schema = {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "limit": {"type": "integer", "default": 4},
                },
                "required": ["text"],
            }
        return cap

    async def candidates(self, allow: set[str]) -> list[Capability]:
        # user_id 없음(머신 principal) → 자기 스코프가 없으므로 능력 없음(DB·백엔드 미접촉). cap 문법상
        # `memory:` 항목 중 리소스가 `user`인 것만 승격(빈/미지원 리소스 거부, 적대 리뷰 대비).
        if not self._user_id:
            return []
        if not any(_kind_of(a) == CAP_KIND_MEMORY and _parse_mem(a) == "user" for a in allow):
            return []
        return [self._cap(with_schema=False)]

    async def load(self, cap_id: str) -> _MemBacking | None:
        # 리소스가 `user`가 아니거나(미지원/빈) user_id 없으면 없는 것으로(존재 비노출).
        if not self._user_id or _parse_mem(cap_id) != "user":
            return None
        return _MemBacking("user")

    def describe(self, row: _MemBacking) -> Capability:
        return self._cap(with_schema=True)

    async def invoke(self, row: _MemBacking, args: dict) -> InvokeResult:
        cap_id = f"{CAP_KIND_MEMORY}:user"
        raw = {"cap_id": cap_id, "kind": CAP_KIND_MEMORY}
        # 스코프는 **오직** principal 도출 user_id — args의 어떤 필드(user_id 등)도 무시(anti-leak 불변식).
        text = str(args.get("text", "")) if isinstance(args, dict) else str(args)
        limit = args.get("limit", 4) if isinstance(args, dict) else 4
        from . import memory
        from .mem_config import default_mem_cfg

        async with self._session_factory() as db:
            mem_cfg = await default_mem_cfg(db)
        # recall_probe: 백엔드 *가용성*을 결과와 구분(None=미가용). 챗 경로 `search`와 코어 공유(drift 0).
        # 스펙 158: 전 축 검색 실패는 recall_probe가 던진다 → 여기서 잡아 error로 표면화([]로 접으면
        # "실패를 0건으로 위장"이 재발). invoke 자체는 안 죽고(런타임 견고) error 필드로 정직히 알린다.
        try:
            hits = await asyncio.to_thread(
                memory.recall_probe, {"user_id": self._user_id}, text, mem_cfg, limit
            )
        except Exception as exc:  # noqa: BLE001 — 실행 실패를 error로(0건 위장 금지)
            return InvokeResult(
                text="", trust="untrusted",
                error=f"메모리 회상 실행 실패({type(exc).__name__}).", raw=raw,
            )
        if hits is None:
            return InvokeResult(
                text="", trust="untrusted",
                error="메모리 백엔드가 구성되지 않아 회상할 수 없습니다.", raw=raw,
            )
        # 결과 = 기억 내용 = **데이터**(지시 아님). 챗 회상 주입과 동일 포맷(drift 0).
        return InvokeResult(
            text=memory.format_memory_hits(hits), trust="untrusted", error=None, raw=raw
        )

    def node_label(self, row: _MemBacking) -> str:
        return f"broker_invoke:{CAP_KIND_MEMORY}:user"

    def approval_for(self, row, cap_id: str, args: dict, tool_policy: dict | None = None) -> dict | None:
        return None  # 메모리 읽기=부수효과 없음 → 승인 게이트 불요(memory write는 스펙 105).


# memory write 승인 permission — 066 self-approve/민감도 라벨(memory.write는 member 소유자 self-승인 기본).
MEMWRITE_PERMISSION = "memory.write"
_MEMWRITE_PREVIEW = 200  # 승인 summary에 노출할 저장 사실 미리보기 상한.
# 저장·승인 사실 길이 상한(적대 리뷰 105 P2). 브로커는 args.text를 무검증으로 받아 거대 사실이 승인
# DB(JSONB)·응답·저장 기억을 무제한 점유할 수 있었다. memory 질의 상한(4000, MemorySearchIn)과 같은
# 경계로. **approval_for와 invoke가 동일 헬퍼로 자르므로 "승인한 것 == 저장되는 것"**(길이도 일치).
MEMWRITE_MAX_CHARS = 4000


def _memwrite_text(args: dict) -> str:
    """저장할 사실 추출 — strip + 길이 상한(승인·저장 공유 = 드리프트 0). 비-dict args 방어."""
    text = str(args.get("text", "")) if isinstance(args, dict) else str(args)
    return text.strip()[:MEMWRITE_MAX_CHARS]


class MemoryWriteProvider:
    """kind=memwrite — 유저 장기 기억(user_id 축)에 사실을 **저장**. 브로커 **첫 부수효과 능력**이라
    승인 게이트가 처음 발화한다(`approval_for` **항상 non-None** — 읽기 provider들과 정반대).

    두 구조적 방어(스펙 105):
    1. **쓰기 축=user_id(자기)만·principal 바인딩** — `{"user_id": self._user_id}`에만 쓴다(agent_id 금지,
       051 교차유저 누출 축). user_id는 cap_id·args가 아니라 principal 도출값(104와 동일) → 남의 기억에
       쓸 방법이 구조적으로 없다. 자기 스코프 쓰기는 정의상 교차유저 누출 불가.
    2. **승인 게이트** — 브로커가 `memory.add`(부수효과) 이전 `interrupt`로 멈추고 승인돼야 저장(learning
       031: "기억해줘"를 프롬프트 금지보다 우선하는 LLM은 프롬프트 아닌 *구조*로 막는다). 승인 payload는
       저장될 사실을 **그대로 노출**(마스킹 X — 승인하려면 봐야 함). 저장은 **infer=False**(승인=저장 일치).
    """

    kind = CAP_KIND_MEMORY_WRITE

    def __init__(self, session_factory, user_id: str | None):
        self._session_factory = session_factory
        self._user_id = user_id  # principal 도출값(build_broker) — read provider와 공유. None=머신→deny.

    def _cap(self, *, with_schema: bool) -> Capability:
        cap = Capability(
            id=f"{CAP_KIND_MEMORY_WRITE}:user",
            kind=CAP_KIND_MEMORY_WRITE,
            name="내 장기 기억에 저장",
            hook="내 장기 기억(user_id 축)에 사실 저장 — 저장 전 승인 필요",
        )
        if with_schema:
            cap.input_schema = {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            }
        return cap

    async def candidates(self, allow: set[str]) -> list[Capability]:
        # user_id 없음(머신) → 자기 스코프 없음 → 능력 없음. `memwrite:user`만 승격(빈/미지원 거부).
        if not self._user_id:
            return []
        if not any(
            _kind_of(a) == CAP_KIND_MEMORY_WRITE and _parse_memwrite(a) == "user" for a in allow
        ):
            return []
        return [self._cap(with_schema=False)]

    async def load(self, cap_id: str) -> _MemBacking | None:
        if not self._user_id or _parse_memwrite(cap_id) != "user":
            return None  # 미지원 리소스·머신 → 존재 비노출
        return _MemBacking("user")

    def describe(self, row: _MemBacking) -> Capability:
        return self._cap(with_schema=True)

    async def invoke(self, row: _MemBacking, args: dict) -> InvokeResult:
        # 여기 도달 = 브로커가 approval_for→interrupt로 **이미 승인**을 받은 경우만(부수효과 1회, §7 멱등).
        cap_id = f"{CAP_KIND_MEMORY_WRITE}:user"
        raw = {"cap_id": cap_id, "kind": CAP_KIND_MEMORY_WRITE}
        text = _memwrite_text(args)  # strip + 길이 상한(승인 payload와 동일 = 승인한 것 == 저장되는 것)
        if not text:
            # 빈 사실은 **저장하지 않는다**(부수효과 0). 무의미 기억 방지.
            return InvokeResult(text="", trust="untrusted", error="저장할 내용이 비어 있습니다.", raw=raw)
        from . import memory
        from .mem_config import default_mem_cfg

        async with self._session_factory() as db:
            mem_cfg = await default_mem_cfg(db)
        if memory.resolve_backend(mem_cfg) is None:
            return InvokeResult(
                text="", trust="untrusted",
                error="메모리 백엔드가 구성되지 않아 저장할 수 없습니다.", raw=raw,
            )
        # 스코프는 **오직** principal 도출 user_id(agent_id·run_id·args 불가). infer=False=승인한 원문 저장.
        await asyncio.to_thread(
            memory.add, {"user_id": self._user_id}, [{"role": "user", "content": text}], mem_cfg, False
        )
        # 결과=저장 확인. 반향된 사실이 데이터 채널로 흐를 수 있어 trust=untrusted(일관).
        return InvokeResult(text=f"장기 기억에 저장했습니다: {text}", trust="untrusted", error=None, raw=raw)

    def node_label(self, row: _MemBacking) -> str:
        return f"broker_invoke:{CAP_KIND_MEMORY_WRITE}:user"

    def approval_for(self, row, cap_id: str, args: dict, tool_policy: dict | None = None) -> dict | None:
        # 쓰기=부수효과 → **항상 승인**(None 절대 안 돌림). 저장될 사실을 마스킹 없이 노출(승인 가시성).
        text = _memwrite_text(args)  # invoke와 동일 헬퍼(길이 상한 일치) → 승인한 것 == 저장되는 것
        preview = text[:_MEMWRITE_PREVIEW] + ("…" if len(text) > _MEMWRITE_PREVIEW else "")
        return {
            "permission": MEMWRITE_PERMISSION,  # 066 self-approve — 소유자 본인 승인(member 기본 정책)
            "action": MEMWRITE_PERMISSION,
            "args": {"text": text},  # 미마스킹 — 사람이 무엇이 저장되는지 봐야 승인 가능
            "summary": f"장기 기억에 저장: {preview} — 승인 필요",
        }


# ---- 스펙 111: 메모리 수정/삭제(memedit) — 대상 있는 첫 브로커 부수효과 --------------------------
# add(105)와 결정적 차이: add는 자기 스코프 *생성*(대상 없음)이나 update/delete는 **기존 mem_id 대상**
# → 소유권 선행(learning 054·069). approval_for와 invoke가 `_memedit_args`로 동일 정규화 → "승인한 것 ==
# 실행되는 것". 삭제 비가역이라 RBAC는 fail-closed(member 시드 없음, admin/superuser만; 105 self_approve
# 보다 민감도 상향). 소유권 술어는 `memory.user_owns` 단일 출처(HTTP 라우트와 공유, 드리프트 0).
MEMEDIT_PERMISSION = "memory.edit"  # admin('*','*')만 승인 가능 — member 시드 없음(삭제 비가역 fail-closed).
MEMEDIT_MAX_CHARS = 4000
_MEMEDIT_PREVIEW = 200


def _memedit_args(args: dict) -> tuple[str, str, str]:
    """(op, mem_id, text) 정규화 — 승인·실행 공유(드리프트 0). 비-dict 방어. text는 update 전용."""
    if not isinstance(args, dict):
        return "", "", ""
    op = str(args.get("op", "")).strip().lower()
    mem_id = str(args.get("mem_id", "")).strip()
    text = str(args.get("text", "")).strip()[:MEMEDIT_MAX_CHARS]
    return op, mem_id, text


class MemEditProvider:
    """kind=memedit — 유저 장기 기억(user_id 축)을 **수정/삭제**. 대상 있는 첫 브로커 부수효과.

    세 구조적 방어(스펙 111):
    1. **스코프=principal 도출 user_id 고정** — args의 user_id 등 무시(104/105 anti-leak 불변식).
    2. **대상 소유권 선행** — mem_id가 자기 것인지 `memory.user_owns`로 확인(미소유·부재 동일 error로
       404-fold = 존재 비노출, 068). add(105)엔 없던 축(대상이 있으므로).
    3. **승인 게이트 항상** — 부수효과 이전 interrupt. 승인 payload는 op·mem_id·(update)새 본문을
       마스킹 없이 노출. 삭제 비가역이라 RBAC fail-closed(member 시드 없음).
    """

    kind = CAP_KIND_MEMORY_EDIT

    def __init__(self, session_factory, user_id: str | None):
        self._session_factory = session_factory
        self._user_id = user_id  # principal 도출값(build_broker) — read/write provider와 공유. None=머신→deny.

    def _cap(self, *, with_schema: bool) -> Capability:
        cap = Capability(
            id=f"{CAP_KIND_MEMORY_EDIT}:user",
            kind=CAP_KIND_MEMORY_EDIT,
            name="내 장기 기억 수정·삭제",
            hook="내 장기 기억(user_id 축) 수정/삭제 — 실행 전 승인 필요",
        )
        if with_schema:
            cap.input_schema = {
                "type": "object",
                "properties": {
                    "op": {"type": "string", "enum": ["update", "delete"]},
                    "mem_id": {"type": "string"},
                    "text": {"type": "string"},
                },
                "required": ["op", "mem_id"],
            }
        return cap

    async def candidates(self, allow: set[str]) -> list[Capability]:
        # user_id 없음(머신) → 자기 스코프 없음 → 능력 없음(DB 미접촉). `memedit:user`만 승격.
        if not self._user_id:
            return []
        if not any(
            _kind_of(a) == CAP_KIND_MEMORY_EDIT and _parse_memedit(a) == "user" for a in allow
        ):
            return []
        return [self._cap(with_schema=False)]

    async def load(self, cap_id: str) -> _MemBacking | None:
        if not self._user_id or _parse_memedit(cap_id) != "user":
            return None  # 미지원 리소스·머신 → 존재 비노출
        return _MemBacking("user")

    def describe(self, row: _MemBacking) -> Capability:
        return self._cap(with_schema=True)

    async def invoke(self, row: _MemBacking, args: dict) -> InvokeResult:
        # 여기 도달 = approval_for→interrupt로 **이미 승인**된 경우만(부수효과 1회, 멱등).
        cap_id = f"{CAP_KIND_MEMORY_EDIT}:user"
        raw = {"cap_id": cap_id, "kind": CAP_KIND_MEMORY_EDIT}

        def err(msg: str) -> InvokeResult:  # 부수효과 0으로 실패 반환(guard)
            return InvokeResult(text="", trust="untrusted", error=msg, raw=raw)

        op, mem_id, text = _memedit_args(args)  # 승인 payload와 동일 정규화(승인한 것 == 실행되는 것)
        if op not in ("update", "delete"):
            return err("지원하지 않는 작업입니다 (update/delete).")
        if not mem_id:
            return err("대상 기억 id가 없습니다.")
        if op == "update" and not text:
            return err("수정할 내용이 비어 있습니다.")
        from . import memory
        from .mem_config import default_mem_cfg

        async with self._session_factory() as db:
            mem_cfg = await default_mem_cfg(db)
        if memory.resolve_backend(mem_cfg) is None:
            return err("메모리 백엔드가 구성되지 않아 수정/삭제할 수 없습니다.")
        # 소유권 선행 — 미소유·부재는 **동일 error**로 404-fold(존재 비노출). 스코프=self._user_id(고정).
        # **check-then-act 하중 가정(codex 111 [P1] — 정직화)**: user_owns 확인과 update/delete가 원자적으로
        # 묶이지 않는다(백엔드 계약이 scope 없는 `update(mem_id)`/`delete(mem_id)` — 전역 mem_id 대상). 이게
        # 안전한 이유는 두 사실에 의존한다: (1) mem_id = **전역 유일 UUID**(mem0 memory_id), (2) 기억의
        # 소유자(user_id)는 **불변**(소유권 이전 연산 없음). 따라서 "확인 후 실제로 다른 유저 행이 같은
        # mem_id로 해석"되는 창이 구조적으로 없다(HTTP `_assert_user_owns`→`update_memory`와 **동일** 의미 —
        # 111이 더 나빠진 게 아니라 같은 잔존). 두 가정을 깨는 백엔드(mem_id 재사용·소유자 가변)라면 이 경로가
        # 뚫리므로 그런 백엔드는 **scope-bound 원자 mutation을 제공해야 한다**(fail-closed; 현 mem0 API엔
        # scope 필터 mutation이 없어 재구조화 불가 = OUT). 안전 불변식은 verify_111 교차유저 거부가 실증.
        if not await asyncio.to_thread(memory.user_owns, self._user_id, mem_id, mem_cfg):
            return err("이 유저의 기억이 아닙니다.")
        if op == "update":
            ok = await asyncio.to_thread(memory.update_memory, mem_id, text, mem_cfg)
            if not ok:
                return err("메모리 수정 실패")
            preview = text[:_MEMEDIT_PREVIEW] + ("…" if len(text) > _MEMEDIT_PREVIEW else "")
            return InvokeResult(text=f"기억을 수정했습니다: {preview}", trust="untrusted", raw=raw)
        ok = await asyncio.to_thread(memory.delete_memory, mem_id, mem_cfg)
        if not ok:
            return err("메모리 삭제 실패")
        return InvokeResult(text="기억을 삭제했습니다.", trust="untrusted", raw=raw)

    def node_label(self, row: _MemBacking) -> str:
        return f"broker_invoke:{CAP_KIND_MEMORY_EDIT}:user"

    def approval_for(self, row, cap_id: str, args: dict, tool_policy: dict | None = None) -> dict | None:
        # 수정/삭제=부수효과 → **항상 승인**(None 절대 안 돌림). 마스킹 없이 노출(승인 가시성).
        op, mem_id, text = _memedit_args(args)  # invoke와 동일 정규화 → 승인한 것 == 실행되는 것
        if op == "delete":
            summary = f"장기 기억 삭제(id={mem_id}) — 승인 필요"
            payload_args = {"op": "delete", "mem_id": mem_id}
        elif op == "update":
            preview = text[:_MEMEDIT_PREVIEW] + ("…" if len(text) > _MEMEDIT_PREVIEW else "")
            summary = f"장기 기억 수정(id={mem_id}): {preview} — 승인 필요"
            payload_args = {"op": "update", "mem_id": mem_id, "text": text}
        else:
            summary = f"장기 기억 작업(op={op or '미지정'}, id={mem_id}) — 승인 필요"
            payload_args = {"op": op, "mem_id": mem_id}
        return {
            "permission": MEMEDIT_PERMISSION,  # admin 전용(member 시드 없음 — 삭제 비가역 fail-closed)
            "action": MEMEDIT_PERMISSION,
            "args": payload_args,  # 미마스킹 — 사람이 무엇이 바뀌는지 봐야 승인 가능
            "summary": summary,
        }


class PolicyScopedBroker:
    """정책으로 미리 스코프된 능력 브로커. `agent.runtime.CapabilityBroker` Protocol 적합.

    `allowlist` = 호출 에이전트 config `capabilities`(cap id 목록, 없으면 [] = deny-by-default).
    `rbac_allows(kind)` = 유저 RBAC 판정 클로저(casbin enforce 등을 이미 바인딩). 둘의 **교집합**만
    발견·호출된다. cap_id에서 kind를 파싱해 provider로 라우팅하되, 정책 판정은 provider **호출 전에**
    브로커가 수행한다(게이트 단일 지점). 서브스텝 HIL은 브로커가 전송 이전 interrupt로 게이트(§3.5).
    """

    def __init__(
        self,
        allowlist,
        rbac_allows: Callable[[str], bool],
        *,
        session_factory=SessionLocal,
        user_id: str | None = None,
        tool_policy: dict | None = None,
        rag_min_scores: dict | None = None,
        principal=None,  # 로컬 위임(스펙 256) — 하위 실행 브로커의 RBAC 주체(호출자 그대로)
        delegation_chain: tuple = (),  # 스펙 256 v2 — 실행 경로의 agent_id 체인(순환·깊이 게이트)
        delegation_budget=None,  # 스펙 256 codex [P2] — 턴 공유 위임 총량 카운터(너비 폭주 상한)
    ):
        self._allow: set[str] = set(allowlist or [])
        self._rbac_allows = rbac_allows
        self._session_factory = session_factory
        self._tool_policy = tool_policy  # 에이전트 config.toolPolicy(스펙 177 P2) — McpProvider 승인 오버라이드
        # user_id = 실행 주체(principal) 도출값 — MemoryProvider가 per-user 스코프에 씀(스펙 104).
        # cap_id·args가 아니라 여기서만 주입돼, 능력 이름으로 남을 가리킬 방법이 없다(anti-leak).
        self._providers: list[_CapabilityProvider] = [
            AgentProvider(session_factory, principal, delegation_chain, delegation_budget),
            McpProvider(session_factory),
            RagProvider(session_factory, rag_min_scores),  # 스펙 191 v2 컬렉션별 최소 유사도
            MemoryProvider(session_factory, user_id),
            MemoryWriteProvider(session_factory, user_id),
            MemEditProvider(session_factory, user_id),
        ]
        self._by_kind = {p.kind: p for p in self._providers}
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

    async def discover(self, query: str, *, limit: int = 5) -> list[Capability]:
        # deny-by-default: allowlist 비었으면 모집단 공집합(존재조차 안 샘 — DB 미접촉).
        if not self._allow:
            return []
        caps: list[Capability] = []
        for provider in self._providers:
            # DB 미접촉 게이트(존재 누출 0 보존): 이 kind에 **어떤 부여도 없으면** provider를 안 부른다.
            # `rbac_allows(kind)`(name=None) = "kind-레벨 OR 이 kind의 per-cap이 하나라도 있나"(스펙 112).
            # kind 전체 거부인데 per-cap 부여가 있으면 여기 통과 → 아래서 후보를 **per-cap 개별 필터**한다
            # (kind-gate만 두면 per-cap 부여 능력이 discover에 안 떠 오케스트레이션서 못 쓴다).
            if not self._rbac_allows(provider.kind):
                continue
            for c in await provider.candidates(self._allow):
                # 특정 판정: kind-레벨이면 전체 통과, per-cap 전용이면 부여된 cap만(같은 술어 재사용).
                if self._rbac_allows(c.kind, _cap_resource(c.id, c.kind)):
                    caps.append(c)
        # lexical 겹침은 **하드 필터가 아니라 랭킹 신호**다(스펙 124). 예전엔 `q in cap-text`(쿼리 전체가
        # 능력 텍스트의 부분문자열)로 하드 필터해, 자연어 쿼리가 짧은 능력 이름의 부분문자열일 리 없어
        # **허가된 도구/문서/기억이 전부 탈락→조율형이 아무 능력도 못 씀**(버그). 이제 쿼리 토큰과 겹치는
        # 수가 많은 순으로 **정렬만** 하고(0 겹침도 유지), limit까지 반환한다. 안정 정렬로 동수는 기존 순서
        # 보존. (allowlist∩RBAC 게이트는 위에서 이미 적용 — 이 후처리는 허가 범위를 넓히지 않는다.)
        q_tokens = [t for t in (query or "").strip().lower().split() if t]
        if q_tokens:
            caps.sort(
                key=lambda c: sum(t in f"{c.name} {c.id} {c.hook}".lower() for t in q_tokens),
                reverse=True,
            )
        return caps[:limit]

    async def _resolve(self, cap_id: str):
        """허가+로드된 (row, provider) 또는 (None, None). 미허가·미존재·kind불명 모두 (None,None)
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
            raise CapabilityNotFound(cap_id)  # 미존재·미허가 동일 처리(존재 비노출)
        return provider.describe(row)

    async def invoke(self, cap_id: str, args: dict) -> InvokeResult:
        # 호출 경계 **재검증**(discover 결과 신뢰 안 함 — TOCTOU/우회 차단, 체크리스트 §2).
        row, provider = await self._resolve(cap_id)
        if row is None:
            return InvokeResult(error="capability not found", trust="untrusted")  # 존재 비노출
        # 서브스텝 HIL(§3.5): 승인 요구 cap이면 전송(부수효과) **이전** interrupt로 부모 그래프 pause.
        # interrupt는 재개 시 delegate 재실행에도 이 지점 이전 부수효과 0 = 전송 1회(멱등, 체크리스트 §7).
        payload = provider.approval_for(row, cap_id, args, self._tool_policy)
        if payload is not None:
            from langgraph.types import interrupt  # 지연 임포트(그래프 밖 호출 시 부담 0)

            decision = interrupt(payload)  # 첫 호출=그래프 멈춤, 재개 시 decision 반환
            if not (isinstance(decision, dict) and decision.get("decision") == "approve"):
                return InvokeResult(
                    text="거부됨 — 관리자가 실행을 승인하지 않았습니다.", trust="untrusted"
                )
        t0 = time.perf_counter()
        res = await provider.invoke(row, args)  # 승인된(또는 무승인) 경우만 전송(부수효과 1회)
        ms = int((time.perf_counter() - t0) * 1000)
        # 관측: broker.invoke 1회 = 노드 프레임 1개(설계결정 7 — invisible 금지). args/result는 안 담음
        # (087/092 — 원문 누출 0). interrupt payload만 _redact_args로 마스킹된 args를 싣는다.
        inv: dict = {"node": provider.node_label(row), "cap_id": cap_id, "ms": ms}
        # 표시용 메타(스펙 130) — provider가 raw에 실은 숫자만 통과(hits/topScore), args 불포함.
        raw = res.raw if isinstance(res.raw, dict) else {}
        if "hits" in raw:
            inv["hits"] = raw["hits"]
        if "topScore" in raw:
            inv["topScore"] = raw["topScore"]
        # 스펙 191: 히트별 카드 + 이 에이전트 최소 유사도 기준선 + 검색 질의(RAG 위임 검색 가독성).
        if "hitsDetail" in raw:
            inv["hitsDetail"] = raw["hitsDetail"]
        if raw.get("local"):
            inv["local"] = True  # 로컬 인프로세스 위임(스펙 256)
        if "subTraceNodes" in raw:
            inv["subTraceNodes"] = raw["subTraceNodes"]
        if "minScore" in raw:
            inv["minScore"] = raw["minScore"]
        if "query" in raw:
            inv["query"] = raw["query"]
        if res.error:
            inv["error"] = True
        if res.text:
            # 결과 본문 프리뷰(스펙 131) — 직접 MCP의 result(2000캡, 087)와 동일 계약으로 브로커도
            # 노출(플레이그라운드=정밀 디버깅). 비밀 마스킹 백스톱(125 _sanitize) + 캡. 원문 전문은
            # 여전히 미저장(캡 절단), args는 계속 불포함.
            from .memory import _sanitize  # 지연 — 순환 import 방지

            inv["resultPreview"] = _sanitize(res.text, cap=2000)
        self.invocations.append(inv)
        return res


def _rbac_check(enforcer, subject: str, kind: str, name: str | None) -> bool:
    """per-cap RBAC 판정 **단일 술어**(스펙 112 — build_broker·_build_resume_broker 공유, drift 0).
    - name 지정: kind-레벨(`capability:{kind}`) OR 능력별(`capability:{kind}:{name}`) 부여.
    - name=None: **DB 회피 게이트**용 — kind-레벨 OR 이 kind에 per-cap 부여가 *하나라도* 있나
      (casbin 암묵 권한 열거, prefix `capability:{kind}:`). discover가 provider DB 접촉을 거를 때 씀."""
    if enforcer.enforce(subject, f"capability:{kind}", "invoke"):
        return True
    if name is not None:
        if enforcer.enforce(subject, f"capability:{kind}:{name}", "invoke"):
            return True
        # mcp 서버단위 부여(`capability:mcp:{server}`)는 그 서버의 **모든 툴**을 덮는다 — allowlist
        # 시맨틱(`mcp:{server}`가 툴 항목을 포함)과 일치시켜 per-cap 부여가 서버 입도로도 동작(codex 112 P2).
        if kind == CAP_KIND_MCP and "/" in name:
            server = name.split("/", 1)[0]
            return bool(enforcer.enforce(subject, f"capability:{kind}:{server}", "invoke"))
        return False
    # name=None: "이 kind에 per-cap 부여가 하나라도?" — AsyncEnforcer는 implicit 헬퍼가 async라
    # sync 정책 열거로 우회한다(get_policy/get_grouping_policy는 in-memory sync). 주체 본인 + 상속 역할
    # (transitive)의 정책에서 obj가 `capability:{kind}:` prefix인 invoke를 찾는다.
    subjects = {subject}
    grouping = enforcer.get_grouping_policy()
    frontier = [subject]
    while frontier:  # user→role→role 전이 폐쇄(작은 정책셋, 순환 방지 위해 visited 체크)
        cur = frontier.pop()
        for g in grouping:
            if len(g) >= 2 and g[0] == cur and g[1] not in subjects:
                subjects.add(g[1])
                frontier.append(g[1])
    prefix = f"capability:{kind}:"
    return any(
        len(p) >= 3 and p[0] in subjects and p[1].startswith(prefix) and p[2] == "invoke"
        for p in enforcer.get_policy()
    )


def build_broker(principal, allowlist, tool_policy: dict | None = None, rag_min_scores: dict | None = None, delegation_chain: tuple = (), delegation_budget=None) -> PolicyScopedBroker:
    """chat.py 배선용 — principal(유저/머신)에서 RBAC 판정 클로저를 만들어 스코프된 브로커 구성.

    RBAC: `is_superuser` 우회(authz 패턴) 아니면 `enforce(str(id), f"capability:{kind}", "invoke")`.
    머신 토큰(str principal, id 없음) → **deny**(안전측; Phase 1 오케스트레이션은 유저 세션 대상).
    기본 정책은 admin('*','*')만 시드돼 있어 member는 거부된다(deny-by-default가 정책 부재에서도 성립)."""
    from . import authz

    def rbac_allows(kind: str, name: str | None = None) -> bool:
        # per-cap 부여 지원(스펙 112). name 지정=특정 판정(kind-레벨 OR `capability:{kind}:{name}`).
        # name=None=**DB 회피 게이트**용 "이 kind에 부여가 하나라도 있나"(kind-레벨 OR 임의 per-cap) —
        # discover가 이걸로 provider DB 접촉을 거른다(존재 누출 0 보존).
        if isinstance(principal, str):
            return False  # 머신 토큰: 능력 오케스트레이션 비대상(deny-by-default)
        if getattr(principal, "is_superuser", False):
            return True  # 부트스트랩·운영 안전판(authz 우회 패턴)
        return _rbac_check(authz.get_enforcer(), str(principal.id), kind, name)

    # user_id = 주체 도출값(스펙 104 MemoryProvider self-scope). 머신 토큰(str)은 id 없음 → None →
    # 메모리 능력 없음(rbac_allows도 deny). 어드민이어도 자기 id라 타인 기억 위임 접근 불가(에스컬레이션 X).
    uid = None if isinstance(principal, str) else str(principal.id)
    return PolicyScopedBroker(allowlist, rbac_allows, user_id=uid, tool_policy=tool_policy, rag_min_scores=rag_min_scores, principal=principal, delegation_chain=delegation_chain, delegation_budget=delegation_budget)

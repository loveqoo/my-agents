"""브로커 공통 리프(스펙 291 Phase 3b) — kind 상수·cap_id 파싱·provider 계약.

정책 게이트는 `core.PolicyScopedBroker`, kind별 메커닉은 `providers/*` 몫. 이 모듈은 패키지 내
어느 쪽에도 의존하지 않는 리프다(의존 방향: providers→common, core→common+providers).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from agent.runtime import Capability, InvokeResult

if TYPE_CHECKING:
    from types import ModuleType

CAP_KIND_AGENT = "agent"  # A2A provider(Phase 1).
CAP_KIND_MCP = "mcp"  # MCP provider(Phase 2-a).
CAP_KIND_RAG = "rag"  # RAG provider(Phase 2, 스펙 103 — 문서 컬렉션 검색).
CAP_KIND_MEMORY = (
    "memory"  # Memory read provider(Phase 2-c, 스펙 104 — 유저 장기 기억 검색, per-user 소유).
)
CAP_KIND_MEMORY_WRITE = (
    "memwrite"  # Memory write provider(스펙 105 — 유저 장기 기억 저장, 첫 부수효과·승인 게이트).
)
CAP_KIND_MEMORY_EDIT = "memedit"  # Memory edit provider(스펙 111 — 유저 장기 기억 수정/삭제, 대상 있는 첫 부수효과·소유권 선행).

# 접두사 있는 kind 레지스트리(스펙 306, 단일 출처) — **새 kind는 여기 한 곳만 등록**하면 `_kind_of`·
# `_cap_resource`가 파생한다. 이전엔 두 if-체인을 각각 손봐야 했고, `_cap_resource` 분기를 빠뜨리면
# per-cap RBAC 리소스가 조용히 오추출(cap_id 전체 반환)되는 함정이었다(스펙 112 경계). agent는 접두사
# 없는 bare(`agt_…`) fallback이라 목록 밖. 순서 무관(콜론 종단이라 어느 것도 다른 것의 접두사 아님).
_PREFIXED_KINDS: tuple[str, ...] = (
    CAP_KIND_MCP,
    CAP_KIND_RAG,
    CAP_KIND_MEMORY_WRITE,
    CAP_KIND_MEMORY_EDIT,
    CAP_KIND_MEMORY,
)


class CapabilityNotFoundError(Exception):
    """능력 미해결 — **미존재와 미허가를 구분하지 않는다**(403/404 접기, 존재 비노출)."""


def _strip_kind(item: str, kind: str) -> str:
    """`{kind}:` 접두사를 벗긴 나머지(없으면 원본 방어). 모든 kind의 cap 리소스 추출이 이 한 규칙으로
    균일하다(스펙 306) — mcp만 2레벨(`server/tool`)이나 리소스는 body 전체라 동일, agent는 bare라
    접두사가 없어 원본 그대로. 이 프리미티브를 `_cap_resource`와 `_parse_*` 별칭이 공유(중복 0)."""
    prefix = f"{kind}:"
    return item[len(prefix) :] if item.startswith(prefix) else item


# ------------------------------- 네임스페이싱(스펙 101 §3.3) -------------------------------
# allowlist·cap_id 항목은 `"<kind>:<id>"`. `mcp:<server>/<tool>`(툴 단위) 또는 `mcp:<server>`(서버 전체).
# **접두사 없는 bare 항목 = kind agent**(하위호환 — spec 100 config 불변, agent_id는 `agt_...`라 콜론 없음).
def _kind_of(item: str) -> str:
    """cap_id/allowlist 항목에서 kind 파싱(별도 조회 없이 id만으로) — `_PREFIXED_KINDS` 레지스트리 순회.
    접두사 매칭 kind 반환, 그 외(콜론 없는 bare `agt_...`) → agent(하위호환)."""
    if isinstance(item, str):
        for kind in _PREFIXED_KINDS:
            if item.startswith(f"{kind}:"):
                return kind
    return CAP_KIND_AGENT


def _parse_mcp(item: str) -> tuple[str, str | None]:
    """`mcp:server/tool` → (server, tool); `mcp:server` → (server, None). 접두사 없으면 (item, None) 방어."""
    body = item[len(CAP_KIND_MCP) + 1 :] if item.startswith(f"{CAP_KIND_MCP}:") else item
    if "/" in body:
        server, tool = body.split("/", 1)
        return server, tool
    return body, None


def _parse_rag(item: str) -> str:
    """`rag:<collection_name>` → `<collection_name>`(접두사만 스트립 — 이름에 콜론/슬래시 있어도 안전).
    RAG는 mcp의 server/tool 2레벨과 달리 1레벨(컬렉션 이름 하나). rag provider·a2a_server가 직접 소비.
    접두사 없으면 원본 방어. `_strip_kind` 위임(스펙 306, 균일 프리미티브)."""
    return _strip_kind(item, CAP_KIND_RAG)


def _parse_mem(item: str) -> str:
    """`memory:<resource>` → `<resource>`(첫 출하는 `"user"`만 유효 — 주체 자신의 장기 기억).
    **대상 user_id는 cap_id에 담기지 않는다**(스펙 104 핵심 anti-leak) — 리소스는 자원 *종류*만 가리키고
    누구의 것인지는 런타임 principal에서 도출한다. 접두사 없으면 원본 방어."""
    return _strip_kind(item, CAP_KIND_MEMORY)


def _parse_memedit(item: str) -> str:
    """memedit cap 리소스 파싱(`memedit:user` → `user`). 미지원 리소스는 load가 거른다(존재 비노출)."""
    return _strip_kind(item, CAP_KIND_MEMORY_EDIT)


def _parse_memwrite(item: str) -> str:
    """`memwrite:<resource>` → `<resource>`(첫 출하 `"user"`만 — 주체 자신의 기억에 저장). `_parse_mem`과
    대칭. 대상 user_id는 cap_id에 없다(스펙 105 anti-leak, 104와 동일). 접두사 없으면 원본 방어."""
    return _strip_kind(item, CAP_KIND_MEMORY_WRITE)


def _cap_resource(cap_id: str, kind: str) -> str:
    """per-cap RBAC object의 리소스 부분(스펙 112) — `capability:{kind}:{resource}`로 특정 능력만 부여.
    **접두사 있는 kind는 균일 스트립**(스펙 306, `_strip_kind`); agent는 레지스트리 밖(bare `agt_…`)이라
    cap_id 전체가 리소스(옛 fallback 보존 — `agent:` 접두사를 벗기지 않아 바이트 동일). kind별 식별자:
    mcp=`server[/tool]`, rag=컬렉션명, memory/memwrite/memedit=`user`, agent=cap_id(agt_…).
    kind-레벨 부여(`capability:{kind}`)와 별개로 admin이 세분 부여할 수 있게 하는 안정 키."""
    return _strip_kind(cap_id, kind) if kind in _PREFIXED_KINDS else cap_id


def _first_line(text: str, fallback: str) -> str:
    """설명 첫 줄 후크(≤200자). 비면 fallback(툴 이름)."""
    s = (text or "").strip()
    return s.splitlines()[0][:200] if s else fallback


def _rt() -> ModuleType:
    """api.runtime 지연 접근(모듈 경량·순환 import 방지). mcp_connection 등 전송 헬퍼 공유원."""
    from .. import runtime

    return runtime


# ------------------------------- provider 시임(스펙 101 §3.1) -------------------------------
class _CapabilityProvider(Protocol):
    """브로커 내부 전용 provider 계약(계약 packages/agent는 불변). 정책은 **모른다** — 브로커가
    호출 전에 `_permitted`로 게이트한다(게이트 단일 지점)."""

    kind: str

    async def candidates(
        self, allow: set[str]
    ) -> list[Capability]:  # allow∩모집단 → 후보(hook 채움)
        ...

    async def load(
        self, cap_id: str
    ) -> object | None:  # 허가 전제, cap_id→backing row(미존재→None)
        ...

    # row = provider별 backing(Agent·_McpBacking·_RagBacking·_MemBacking) — kind마다 달라 Any.
    def describe(self, row: Any) -> Capability:  # row→input_schema 채운 Capability
        ...

    async def invoke(self, row: Any, args: dict) -> InvokeResult:  # 전송 1회→텍스트 접기(untrusted)
        ...

    def node_label(self, row: Any) -> str:  # 관측 프레임 노드명 broker_invoke:<kind>:<...>
        ...

    def approval_for(
        self, row: Any, cap_id: str, args: dict, tool_policy: dict | None = None
    ) -> dict | None:  # HIL 승인 payload | None
        ...

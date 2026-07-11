"""provider 조립(스펙 294) — 구체 provider를 아는 **유일한 곳**.

`PolicyScopedBroker`(core)는 `_CapabilityProvider` 추상에만 의존하고 provider를 **주입받는다**.
구체 6종(Agent/Mcp/Rag/Memory×3)의 생성 배선은 여기 한 곳에 격리된다 — agent(`_REGISTRY`)·
memory backend(`_BACKENDS`)가 이미 쓰는 "생성 은닉" 패턴을 provider에도 적용(소비자는 구체를 모른다).

`BrokerContext` = "provider를 만들려면 무엇이 필요한가"의 단일 규약(경계=스펙). per-request 도출값
(session_factory·principal·user_id·delegation·rag_min_scores)을 실어 `build_providers`에 넘긴다.
새 능력 소스는 여기 한 줄 추가로 붙는다(broker 무변경 = 개방-폐쇄). 런타임 가변 레지스트리를 두지
않는 이유: provider는 플랫폼 내부 고정 집합(스펙 동반 증감)이라 플러그인 구동자가 없다(스펙 294 OUT).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..db import SessionLocal
from .common import _CapabilityProvider
from .providers.agent import AgentProvider
from .providers.mcp import McpProvider
from .providers.memory import MemEditProvider, MemoryProvider, MemoryWriteProvider
from .providers.rag import RagProvider

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from ..models import User


@dataclass(frozen=True)
class BrokerContext:
    """provider 생성 규약(스펙 294) — 조립에 필요한 per-request 도출값의 닫힌 집합.

    anti-leak(스펙 104): `user_id`는 principal 도출값으로만 실린다 — cap_id·args 경로는 여기 없다
    (능력 이름으로 남의 스코프를 가리킬 방법이 구조적으로 없음). 머신 토큰(str principal)은 user_id
    None → 메모리 능력 없음.
    """

    session_factory: async_sessionmaker[AsyncSession] = SessionLocal
    principal: User | str | None = None  # 로컬 위임(스펙 256) 하위 실행의 RBAC 주체(호출자 그대로)
    user_id: str | None = None  # 주체 도출값(스펙 104 MemoryProvider self-scope)
    delegation_chain: tuple = ()  # 스펙 256 v2 — 실행 경로 agent_id 체인(순환·깊이 게이트)
    delegation_budget: dict | None = None  # 스펙 256 [P2] — 턴 공유 위임 총량(너비 상한)
    rag_min_scores: dict | None = None  # 스펙 191 v2 — 컬렉션별 최소 유사도


def build_providers(ctx: BrokerContext) -> list[_CapabilityProvider]:
    """구체 provider 6종을 배선해 반환(스펙 294) — 구체 클래스를 아는 유일한 함수.

    잎(leaf) provider의 서로 다른 생성 인자는 결함이 아니라 각자 필요한 것만 받는 좋은 DI다
    (통일 강제 금지, 스펙 294 OUT). 순서는 discover 나열 순서와 무관(정책 게이트가 kind로 디스패치).
    """
    return [
        AgentProvider(
            ctx.session_factory, ctx.principal, ctx.delegation_chain, ctx.delegation_budget
        ),
        McpProvider(ctx.session_factory),
        RagProvider(ctx.session_factory, ctx.rag_min_scores),
        MemoryProvider(ctx.session_factory, ctx.user_id),
        MemoryWriteProvider(ctx.session_factory, ctx.user_id),
        MemEditProvider(ctx.session_factory, ctx.user_id),
    ]

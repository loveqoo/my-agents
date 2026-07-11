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

**패키지 구조(스펙 291 Phase 3b)**: `common`(kind 상수·파싱·provider 계약 리프) /
`providers/{agent,mcp,rag,memory}`(kind별 메커닉) / `core`(정책 게이트·build_broker). 이 파사드가
전 심볼을 재수출해 기존 import 경로(`from . import broker`·`from .broker import X`)를 무변경 보존한다.
"""

from __future__ import annotations

# ---- 파사드 호환 재수출(분할 전 broker.py 모듈 전역 보존 — 스냅샷 diff 여집합 0) ----
# 아래 표준/서드파티/이웃 심볼은 broker.py 시절 top-level import였고 동적 속성 접근(vars)
# 가능성이 있어 그대로 유지한다(v122/191/256 — 누락은 실행 시점 AttributeError).
import asyncio  # noqa: F401  (재노출)
import time  # noqa: F401  (재노출)
from collections.abc import Callable  # noqa: F401  (재노출)
from typing import Protocol  # noqa: F401  (재노출)

from sqlalchemy import select  # noqa: F401  (재노출)

from agent.runtime import Capability, InvokeResult, is_remote_source  # noqa: F401  (재노출)

from .. import a2a_client  # noqa: F401  (재노출)
from ..db import SessionLocal  # noqa: F401  (재노출)
from ..models import Agent, McpServer  # noqa: F401  (재노출)
from ..ownership import may_use_agent  # noqa: F401  (재노출)
from .common import (  # noqa: F401  (재노출)
    CAP_KIND_AGENT,
    CAP_KIND_MCP,
    CAP_KIND_MEMORY,
    CAP_KIND_MEMORY_EDIT,
    CAP_KIND_MEMORY_WRITE,
    CAP_KIND_RAG,
    CapabilityNotFoundError,
    _cap_resource,
    _CapabilityProvider,
    _first_line,
    _kind_of,
    _parse_mcp,
    _parse_mem,
    _parse_memedit,
    _parse_memwrite,
    _parse_rag,
    _rt,
)
from .composition import BrokerContext, build_providers  # noqa: F401  (재노출, 스펙 294)
from .core import PolicyScopedBroker, _rbac_allows, build_broker  # noqa: F401  (재노출)
from .providers.agent import (  # noqa: F401  (재노출)
    A2A_DELEGATE_PERMISSION,
    DELEGATION_MAX_DEPTH,
    DELEGATION_MAX_TOTAL,
    AgentProvider,
    _a2a_text,
    _hook_for,
)
from .providers.mcp import (  # noqa: F401  (재노출)
    McpProvider,
    _adapt_args,
    _McpBacking,
    _tool_input_schema,
)
from .providers.memory import (  # noqa: F401  (재노출)
    _MEMEDIT_PREVIEW,
    _MEMWRITE_PREVIEW,
    MEMEDIT_MAX_CHARS,
    MEMEDIT_PERMISSION,
    MEMWRITE_MAX_CHARS,
    MEMWRITE_PERMISSION,
    MemEditProvider,
    MemoryProvider,
    MemoryWriteProvider,
    _MemBacking,
    _memedit_args,
    _memwrite_text,
)
from .providers.rag import RagProvider, _RagBacking  # noqa: F401  (재노출)

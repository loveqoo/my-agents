"""ChatContext 타입 — chat_context.py에서 최하위로 분할(스펙 394, 392 chat_graph_build 선례).

리졸버 형제 모듈들과 파사드(chat_context.py)가 공유하는 타입 허브. 파사드에 두면
파사드→로더→타입의 양방향 순환이 생기므로 최하위로 내린다. 소비자는 종전대로
`from .chat_context import ChatContext`(파사드 재수출 — import 표면 무변경).
"""

import uuid
from dataclasses import dataclass, field
from typing import Any

from agent.runtime import is_remote_source

# 원격 소스 판정 단일 술어는 agent.runtime로 내렸다(스펙 089) — resolve·classify·직렬화가 공유.
_is_remote = is_remote_source


@dataclass
class ChatContext:
    """실행 컨텍스트(스펙 382) — 구 ctx dict를 대체하는 타입 DTO.

    `_load_context`가 에이전트 구성·버전·오버라이드·모델·메모리·MCP·RAG·세션을 해석해 한 번에
    구성한다. **mutable**(frozen 아님): chat_approval이 resume 시 session_pk/session_pending을 수령 후
    갱신하고, 그것이 dict 시절 계약이다. 필드 기본값은 안전한 빈값 — `_load_context`가 전 필드를
    채우므로 런타임 값은 dict 시절과 1:1(동작 불변). 소비처는 `ctx.model_cfg`처럼 속성 접근하며 mypy가
    키·타입을 정적 검사(구 `dict[str, Any]`엔 없던 안전망).
    """

    # 에이전트 정체·소스
    agent_pk: uuid.UUID  # agent.id (내부 PK) — 항상 설정되는 유일한 required 필드(UUID 기본값 부재)
    prompt: str = ""
    ext_agent_id: str = ""  # agent.agent_id (외부 노출 id)
    agent_name: str = ""
    source: str = ""
    impl: str | None = None  # in-process 커스텀 구현 키(스펙 085)
    artifact_spec: Any = None  # 노코드 산출물형 필드 명세(스펙 190)
    endpoint: str | None = None
    token: str | None = None
    card: dict | None = None  # A2A 카드 스냅샷(외부 에이전트)
    # 노드형 파이프라인(스펙 259/287/316)
    nodes: list | None = None
    nodes_resolved: list | None = None  # 노드별 모델 해석 결과
    overrides_nodes_status: str | None = None  # 노드 오버라이드 적용 상태(트레이스용)
    overrides: dict | None = None  # in-process 커스텀이 화이트리스트 밖 키도 읽게 전달(스펙 085)
    # 능력·도구 정책
    memories: list = field(default_factory=list)
    capabilities: list = field(default_factory=list)
    tool_policy: dict = field(
        default_factory=dict
    )  # 도구 승인 오버라이드(스펙 177 P2, config-only)
    # 모델·온도·이력
    temperature: float | None = None
    history_depth: int = 20
    persist_history: bool = True
    ephemeral: bool = False  # 비영속 1회성 모드(스펙 235)
    model_cfg: dict | None = None  # 원격은 None(로컬 모델 불요)
    mem_cfg: dict | None = None
    # 버전 못박기(스펙 242/370)
    pinned_version: str | None = None
    exec_version: str | None = None
    pins: dict = field(default_factory=dict)
    # 프롬프트 출처(스펙 364) — 라이브러리 매칭 시만 이름/id, 인라인/오버라이드/원격은 None
    prompt_name: str | None = None
    prompt_id: str | None = None
    # MCP·RAG 해석
    mcp_servers: list = field(default_factory=list)
    tool_names: list = field(default_factory=list)
    rag_collections: list = field(default_factory=list)
    rag_unresolved: list = field(default_factory=list)
    rag_min_scores: dict = field(default_factory=dict)  # {컬렉션명: 최소 유사도}(스펙 191)
    # 세션(스펙 049/068) — resume 시 chat_approval이 수령 후 갱신
    session_pk: int | None = None
    session_id: str = ""
    session_pending: dict | None = None

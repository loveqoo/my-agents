"""채팅 컨텍스트/설정 해석 — **파사드**(스펙 394: 리졸버 가족 분할, 재수출 계약).

에이전트 구성·버전·오버라이드·모델·메모리·MCP·RAG·세션을 ChatContext로 해석한다.
스펙 394 분할(chat_*/blocks_* 291/392/393과 동형 — 평면 형제 모듈 + 파사드):
  chat_context_types(ChatContext 타입 허브) · chat_context_overrides(세션 오버라이드·노드 병합) ·
  chat_context_versions(버전·핀·프롬프트 출처) · chat_context_sessions(세션 재개/신규) ·
  chat_context_rag(RAG 해석) · chat_context_models(모델·mem0 해석) · chat_context_pool(풀 파생) ·
  chat_context_mcp(MCP projection) · chat_context_loader(_load_context 순서 오케스트레이터).
외부의 `from api.chat_context import X` / 파사드 chat.py 재수출은 전부 무변경(재배선 없는 분할
계약). 374 T2의 "typed builder"는 기각(과추상 — codex 자문): ChatContext DTO(스펙 382)가 이미
그 문제를 풀었고, 필요한 것은 순서가 드러나는 얇은 오케스트레이터(chat_context_loader).
"""

from .chat_context_loader import (  # noqa: F401
    _load_context,
    _prepare_cfg,
    _resolve_nodes_for_ctx,
)
from .chat_context_mcp import (  # noqa: F401
    _mcp_server_projection,
    _resolve_mcp_servers,
    _resolve_tool_filter,
)
from .chat_context_models import (  # noqa: F401
    _chat_model_cfg,
    _pinned_model_cfg,
    _resolve_mem_cfg,
    _resolve_model,
    _resolve_node_models,
    resolve_agent_mem_cfg,
)
from .chat_context_overrides import (  # noqa: F401
    _NODE_OVERRIDE_FIELDS,
    _apply_overrides,
    _coerce_history_depth,
    _filter_capabilities,
    _merge_node_overrides,
    _node_patch_fields,
)
from .chat_context_pool import (  # noqa: F401
    _doc_pool,
    _mcp_pool,
    _server_tool_used,
    _used_node_tools,
    derive_pipeline_pool,
)
from .chat_context_rag import _rag_collection_entry, _resolve_rag  # noqa: F401
from .chat_context_sessions import _resolve_session  # noqa: F401
from .chat_context_types import ChatContext, _is_remote  # noqa: F401
from .chat_context_versions import (  # noqa: F401
    _resolve_exec_pins,
    _resolve_prompt_provenance,
    _resolve_version_and_prompt,
)

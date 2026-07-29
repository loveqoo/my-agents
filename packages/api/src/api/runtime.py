"""에이전트 실행 런타임 — **파사드**(스펙 397: 기능별 형제 모듈로 분할, 재수출 계약).

실 MCP 도구 연결(스펙 054)·HIL 승인 리졸버(177)·트레이스 요약/마스킹(086/087/092/320)·
타임라인 조립·RAG 검색(380 선례 재수출)의 공개 표면. 스펙 397 분할(캠페인 392~396 관례 —
평면 형제 + 파사드):
  runtime_trace_safety(마스킹·캡·정규화 — 보안 계약 정본) · runtime_trace(요약·타임라인·조립) ·
  runtime_agent_tools(위임 도구) · runtime_mcp(연결·승인 리졸버·래핑·사양 캐시 371 D1).
외부의 `runtime.X` 속성 접근·`from api.runtime import X`는 전부 무변경(재배선 없는 분할 계약).

지배 스펙: docs/spec/054-mcp-real-runtime-http.md (구: 007 Phase 2)
"""

# RAG 런타임 재수출(스펙 380·캠페인 374 T2) — RAG 검색 도메인은 rag_runtime.py로 분리됐으나 기존
# 소비자는 `runtime.search_collections`/`runtime.build_rag_tool` 속성 접근을 쓰므로 재수출로 무변경.
# rag_runtime의 안전 헬퍼 의존은 runtime_trace_safety로 하강(스펙 397) — 순환 없음.
from .rag_runtime import (  # noqa: F401
    RagSearchError,
    _annotate_cutoffs,
    _hits_detail,
    _norm_min_scores,
    _norm_score,
    build_rag_tool,
    format_rag_hits,
    search_collections,
    used_hits,
)
from .runtime_agent_tools import _wrap_agent_tool, build_agent_tools  # noqa: F401
from .runtime_mcp import (  # noqa: F401
    _APPROVAL_ACTIONS,
    _TOOL_SPEC_CACHE,
    _TOOL_SPEC_CACHE_MAX,
    _TOOL_SPEC_LOCK,
    _prepare_connections,
    _raw_tools_cached,
    _safe_name,
    _tool_spec_cache_key,
    _tools_from_raw,
    _wrap_mcp_tool,
    build_mcp_tools,
    mcp_connection,
    mcp_tool_cache_stats,
    resolve_tool_approval,
    selected_for_server,
)
from .runtime_trace import (  # noqa: F401
    _msg_role,
    _summarize_delta_value,
    _summarize_messages_delta,
    _summarize_node_update,
    _timeline_from_nodes,
    _timeline_from_observations,
    assemble_trace,
    build_graph_path,
    estimate_tokens,
    is_tool_message,
)
from .runtime_trace_safety import (  # noqa: F401
    _ARG_VALUE_CAP,
    _ERR_CAP,
    _FIELD_CAP,
    _MSG_PREVIEW_CAP,
    _MSG_PREVIEW_N,
    _NODE_SUMMARY_CAP,
    _REDACT_MAX_DEPTH,
    _REDACTED,
    _RESULT_CAP,
    _SENSITIVE_KEY,
    _VALUE_SAFE_KEYS,
    _cap,
    _content_text,
    _redact_args,
    _sanitize_preview,
    _sink_from,
)

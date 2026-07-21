# codex 자문 원문 — runtime.py 리팩터 (2026-07-19, 스펙 397 입력)

[단계 5 — Verification] read-only로 직접 읽고 판단했습니다. 수정은 하지 않았습니다.

**핵심 판단**
`runtime.py`는 더 이상 “런타임 구현 파일”이 아니라 이미 파사드입니다. RAG는 [runtime.py](packages/api/src/api/runtime.py:725)에서 재수출되고, 소비자는 `runtime.build_rag_tool`, `runtime.search_collections`, `runtime._safe_name`, private helper까지 속성 접근합니다. 따라서 정답은 “기능별 평면 형제 모듈 + `runtime.py` 재수출 파사드 유지”입니다. 소비자를 새 모듈로 대거 바꾸면 MI는 좋아져도 계약을 부수기 쉽습니다.

**우선순위 결함**
1. [build_mcp_tools](packages/api/src/api/runtime.py:333)가 캐시 miss 판정, allow-host refresh, SSRF 연결, discovery, enabled/selected 필터, 승인 리졸버, wrapper 생성을 한 함수에 압축합니다. 특히 [pending 계산](packages/api/src/api/runtime.py:351)과 [refresh 순서](packages/api/src/api/runtime.py:352)는 스펙 371의 핵심이라 별도 `runtime_mcp_specs.py`/`runtime_mcp.py`로 빼되 순수 이동부터 해야 합니다.
2. [resolve_tool_approval](packages/api/src/api/runtime.py:57)는 정책 정본인데 `tools_meta` 기본값, 레거시 `_APPROVAL_ACTIONS`, `tool_policy` override, approver normalize가 한 블록입니다. `_base_approval_from_meta_or_legacy`, `_apply_approval_override`, `_normalize_approval`로 쪼개면 우선순위가 드러납니다. 단 공개 표면은 `runtime.resolve_tool_approval` 그대로.
3. [_redact_args](packages/api/src/api/runtime.py:509)는 보안 계약입니다. 복잡도보다 이동 위험이 큽니다. `_redact_mapping`, `_redact_sequence`, `_redact_scalar`로만 분해하고, [_SENSITIVE_KEY와 cap 상수군](packages/api/src/api/runtime.py:467)을 같은 모듈에 둬야 합니다.
4. [_summarize_messages_delta](packages/api/src/api/runtime.py:564)는 remove-message 격리, content-block 정규화, sanitize-before-cap, preview count가 섞였습니다. `_split_removed_messages`, `_message_preview`, `_format_message_previews`로 분해가 맞습니다.
5. [_summarize_node_update](packages/api/src/api/runtime.py:616)는 이미 `_summarize_delta_value`가 있으므로 나머지는 dispatch만 남겨야 합니다: sensitive key, `messages`, generic value. 보안상 broad refactor 금지.

**분할 설계**
권장 모듈은 평면 4개입니다.

- `runtime_mcp.py`: `_safe_name`, `_APPROVAL_ACTIONS`, `resolve_tool_approval`, `_TOOL_TIMEOUT_S`, `_wrap_mcp_tool`, `mcp_connection`, `selected_for_server`, tool-spec cache, `build_mcp_tools`.
- `runtime_agent_tools.py`: `_wrap_agent_tool`, `build_agent_tools`. 단 `_safe_name`은 `runtime_mcp`에서 import하거나 더 작게 `runtime_names.py`로 둡니다.
- `runtime_trace_safety.py`: `_content_text`, `_sink_from`, `_sanitize_preview`, `_SENSITIVE_KEY`, cap 상수, `_redact_args`, `_cap`. RAG가 현재 [rag_runtime.py](packages/api/src/api/rag_runtime.py:271)에서 `runtime`을 지연 import하므로, 이 공용 안전 모듈로 의존을 내리면 순환 위험이 줄어듭니다.
- `runtime_trace.py`: `is_tool_message`, `_msg_role`, `_summarize_*`, `_timeline_*`, `build_graph_path`, `estimate_tokens`, `assemble_trace`.

`runtime.py`는 import/re-export만 남기는 파사드로 둡니다. `__all__`를 명시하고, 기존 private 테스트 표면도 재수출해야 합니다. `rag_runtime` 선례처럼 외부 계약만 살리면 부족합니다. 테스트가 `runtime._wrap_mcp_tool`, `runtime._content_text`, `runtime._summarize_node_update`, `runtime._ERR_CAP`까지 직접 씁니다.

**동작보존 함정**
- 승인 우선순위: [tools_meta 기본 > legacy fallback > tool_policy override](packages/api/src/api/runtime.py:75)를 절대 바꾸면 안 됩니다. 브로커도 [같은 리졸버](packages/api/src/api/broker/providers/mcp.py:254)를 씁니다.
- 캐시: key는 `(name, version or 0, auth_fp)`이고 [락 double-check](packages/api/src/api/runtime.py:316)와 stats가 verify 대상입니다. wrapper/calls_sink는 캐시하면 안 됩니다.
- `calls_sink`: [_sink_from](packages/api/src/api/runtime.py:131)의 config 우선/closure fallback 계약은 그래프 캐시 격리의 핵심입니다.
- 예외 경로: [_wrap_mcp_tool](packages/api/src/api/runtime.py:156)는 `handle_tool_error=False`, `asyncio.timeout`, `_sanitize_preview`, `status=error`, 모델-facing 실패 문자열까지 한 계약입니다.
- RAG monkeypatch: [tests/verify_191](tests/verify_191_rag_threshold.py:124)는 `runtime.search_collections`를 패치하지만 `build_rag_tool` 구현은 [rag_runtime.search_collections](packages/api/src/api/rag_runtime.py:312)를 직접 참조합니다. 리팩터 때는 “파사드 패치”가 아니라 정의 모듈 패치로 테스트를 교정해야 합니다.

**권장 순서**
1. 표면 박제: `runtime`의 현재 exported/public+private 이름 목록을 스냅샷하고 `hasattr` 검증 추가.
2. `runtime_trace.py`로 timeline/assemble/estimate 순수 이동.
3. `runtime_agent_tools.py` 이동.
4. `runtime_trace_safety.py` 이동. 이때 RAG의 helper import를 `runtime` 대신 safety 모듈로 낮춤.
5. `runtime_mcp.py` 순수 이동. 그 다음에만 C급 함수 내부 분해.
6. 마지막에 `runtime.py`를 파사드로 축소하고 `rag_runtime` 재수출 유지.

**표적 verify**
최소: `make metrics-fast`, `uv run python tests/verify_177_tool_approval_resolver.py`, `verify_087_mcp_args_redaction.py`, `verify_092_tool_chunk_filter.py`, `verify_086_inspector_per_node_detail.py`, `verify_262_summary.py`, `verify_320_tool_error_reason.py`, `verify_054_mcp_real_runtime.py`, `verify_041_hil_approval_gating.py`, `verify_101_broker_mcp.py`, `verify_318_node_agent_call.py`, `verify_371_graph_cache.py`, `verify_191_rag_threshold.py`.

분할 직후에는 추가로 `rg -n "runtime\\.|from api\\.runtime|from \\.runtime"`로 표면 소비자를 다시 세고, `runtime` 재수출 이름과 테스트 direct import가 전부 살아 있는지 기계 검증해야 합니다.

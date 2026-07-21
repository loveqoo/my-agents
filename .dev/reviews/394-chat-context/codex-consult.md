# codex 자문 원문 — chat_context.py 리팩터 (2026-07-18, 스펙 394 입력)

[단계 6 — Compounding] read-only 리뷰로 닫습니다. 파일 수정·검증 실행은 하지 않았고, 코드/소비자 직접 읽기 기준입니다.

**핵심 판단**
`chat_context.py`는 “나쁜 god file”이라기보다 실행 컨텍스트의 여러 안정화 패치가 한 파일에 누적된 상태입니다. 그래서 1차 리팩터는 새 개념을 크게 만들기보다, `chat_context.py` 경로를 보존한 얇은 파사드/타입 허브로 두고 리졸버 가족을 평면 형제 모듈로 이동하는 게 맞습니다.

`ChatContextBuilder`는 지금 시점에는 과합니다. 374 당시 제안은 dict ctx를 typed DTO로 바꾸기 전의 문제의식인데, 현재는 [ChatContext](packages/api/src/api/chat_context.py:40)가 이미 단일 DTO이고 [_load_context](packages/api/src/api/chat_context.py:768)가 한 번에 생성합니다. 필요한 것은 fluent/mutable builder가 아니라, 순서가 보이는 얇은 오케스트레이터와 작은 결과 DTO입니다.

**구조 결함**
1. [_load_context](packages/api/src/api/chat_context.py:700)가 컨텍스트 계층 전체의 순서 계약을 암묵 지역변수로 들고 있습니다. 버전 해석, 노드 ref 해석, override, pool 재파생, exec pins, 모델/MCP/RAG/session 해석이 한 함수에 직렬 결합되어 있어 순서를 바꾸는 리팩터가 곧 동작 변경입니다.

2. [_resolve_mcp_servers](packages/api/src/api/chat_context.py:497)가 C급 중 가장 위험합니다. DB row 조회, pin overlay, auth 복호화, effective version, runtime dict projection, tool filter 정책을 한 함수가 처리합니다. `McpServerProjection.from_row(row, pinned, pins)`와 `resolve_tool_filter(cfg)`로 분리해야 합니다.

3. [derive_pipeline_pool](packages/api/src/api/chat_context.py:250)는 순수 파생처럼 보이지만 DB 세션을 열고, node ref 해석과 MCP/Collection catalog scan 후 `cfg`를 mutate합니다. `PipelinePoolDeriver.derive(nodes, catalog)` 순수 함수와 `derive_pipeline_pool(cfg)` 호환 wrapper로 갈라야 합니다.

4. [_resolve_model](packages/api/src/api/chat_context.py:413), [_chat_model_cfg](packages/api/src/api/chat_context.py:124), [resolve_agent_mem_cfg](packages/api/src/api/chat_context.py:283)가 같은 model/pin/provider 해석 규칙을 조금씩 다르게 들고 있습니다. `ModelConfigResolver`가 맞지만, “오버라이드 모델 미존재는 400, 저장 모델 미존재는 default fallback” 차이는 반드시 API로 표현해야 합니다.

5. [_merge_node_overrides](packages/api/src/api/chat_context.py:196)는 순수 함수라 좋은 편이지만, public test가 [api.chat_context 직접 임포트](tests/verify_317_code_node.py:91)를 핀합니다. 내부 이동은 가능하되 `_NODE_OVERRIDE_FIELDS`, `_node_patch_fields`, `_merge_node_overrides`는 `chat_context.py`에서 계속 재수출해야 합니다.

**분할 설계**
- `chat_context.py`: `ChatContext`, `_is_remote`, `_load_context` public facade, 기존 테스트/소비자용 재수출 유지. [chat.py 재수출](packages/api/src/api/chat.py:73)도 그대로.
- `chat_context_loader.py`: 실제 `_load_context_impl`와 `assemble_chat_context(...)`. 순서가 드러나는 함수형 오케스트레이터.
- `chat_context_versions.py`: `_resolve_version_and_prompt`, `_resolve_exec_pins`, `_resolve_prompt_provenance`.
- `chat_context_models.py`: `_pinned_model_cfg`, `_chat_model_cfg`, `_resolve_model`, `_resolve_mem_cfg`, `resolve_agent_mem_cfg`, `_resolve_node_models`.
- `chat_context_overrides.py`: override allowlist, historyDepth coercion, node override merge, `OverrideResult`.
- `chat_context_mcp.py`: MCP row projection, pin overlay, auth handling, tool filter.
- `chat_context_rag.py`: RAG collection projection/resolve.
- `chat_context_pipeline_pool.py`: pure pool derivation + DB wrapper `derive_pipeline_pool`.
- `chat_context_sessions.py`: `_resolve_session`.

`ChatContext`는 당분간 `chat_context.py`에 남기는 편이 낫습니다. 소비자가 [chat_graph_build](packages/api/src/api/chat_graph_build.py:17), [chat_approval](packages/api/src/api/chat_approval.py:27), history/persist/trace/A2A 계열에서 직접 가져갑니다. 타입만 다른 파일로 옮겨 재수출하면 가능은 하지만 첫 단계 이득이 작고 표면 회귀만 늘어납니다.

**동작보존 함정**
- 노드 ref는 override 전에 해석됩니다: [_load_context](packages/api/src/api/chat_context.py:727). 이 순서가 바뀌면 세션 patch가 ref 원본에 먹거나, 미해결 ref 실패 시점이 바뀝니다.
- pool 재파생은 override 뒤, model/MCP/RAG 해석 전입니다: [751-766](packages/api/src/api/chat_context.py:751). API 생성/구저장/오버라이드 복구 계약입니다.
- `exec_version = pinned_version or agent.active_version` 뒤에 pins를 읽습니다: [753-759](packages/api/src/api/chat_context.py:753). 승인 재개와 trace의 버전 승계에 영향.
- session ownership `own`은 타인/NULL/추측 session을 새 session으로 접습니다: [_resolve_session](packages/api/src/api/chat_context.py:610), [chat.py 호출부](packages/api/src/api/chat.py:1001).
- approval resume은 `_load_context(approval.agent_pk, approval.session_id)`를 통해 같은 세션을 재발견해야 합니다: [chat_approval.py](packages/api/src/api/chat_approval.py:193). 여기서 소유권 파라미터를 임의로 바꾸면 기존 승인 연속성이 깨질 수 있습니다.
- 그래프 캐시 지문은 `model_cfg`, `mcp_servers`의 `name/version/auth`, `tool_names`, `tool_policy`, `rag_collections`, `rag_min_scores`, `ephemeral`을 소비합니다: [_graph_fingerprint](packages/api/src/api/chat_graph_build.py:110). projection dict의 필드명/값 의미 변경 금지입니다.
- runtime 조립은 `ctx.mcp_servers`, `ctx.tool_names`, `ctx.rag_min_scores`, `ctx.model_cfg`를 직접 씁니다: [_build_turn_runtime](packages/api/src/api/chat.py:264). “동일 데이터, 다른 타입”도 downstream 변환 비용이 생기면 위험합니다.

**권장 순서**
1. 순수 함수/상수 이동: node override 가족을 `chat_context_overrides.py`로 옮기고 `chat_context.py` 재수출 유지. `verify_317_code_node.py`가 즉시 표면을 잡습니다.
2. RAG/session/version/provenance 이동. 상대적으로 외부 dict 계약이 작고 함수 경계가 선명합니다.
3. model resolver 이동. 이때 override-missing 400 vs stored default fallback 테스트를 먼저 핀해야 합니다.
4. pipeline pool을 pure deriver + DB wrapper로 분해. `derive_pipeline_pool` 이름과 mutate 계약은 유지합니다.
5. MCP resolver 분해. 캐시 지문과 `runtime.build_mcp_tools` call site가 많아 가장 늦게 하는 편이 낫습니다.
6. 마지막에 `_load_context`를 `chat_context_loader.py`로 옮기고 `chat_context.py`는 facade가 되게 합니다. 전후 `rg "from .*chat_context import"`와 직접 verify 전판이 필요합니다.

검증은 리팩터 시 최소 `tests/verify_317_code_node.py`, `verify_049_session_retention_policy.py`, `verify_068_live.py`, MCP/RAG 관련 verify, 그리고 `_graph_fingerprint` 캐시 관련 스펙 371 검증을 전후로 돌리는 게 맞습니다.

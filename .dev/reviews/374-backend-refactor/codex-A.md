[단계 5 — Verification]

## packages/api/src/api/chat.py
[chat.py:26] (P2) 파사드 재수출과 실제 `/chat` 라우트 구현이 같은 파일에 공존해 경계가 흐림 → `chat_facade.py`/`chat_route.py` 또는 `__all__` 기반 호환 레이어로 분리
[chat.py:368] (P2) `_build_turn_runtime` 162행이 메모리·히스토리·MCP/RAG·브로커·그래프 캐시·AgentBuildContext 조립을 모두 수행 → `MemoryInputs`, `ToolAssembly`, `GraphFactory` 축으로 쪼개 턴 빌더를 얇게 유지
[chat.py:324] (P2) `_GRAPH_CACHE`/`graph_cache_stats` 전역 상태가 그래프 조립 함수 내부 정책과 강결합되어 테스트 격리와 동시성 검증이 어려움 → 캐시를 주입 가능한 `GraphCache` 객체로 감싸고 빌더 의존성으로 전달
[chat.py:701] (P2) `_ask_frames`, `_form_frames`, `_approval_frames`가 SSE text/trace/done 프레임과 대기 trace 조립 흐름을 각각 복제함 → `PendingTurnEmitter` 공통 헬퍼로 프레임 방출·trace·persist 단계를 통일
[chat.py:1163] (P2) `_final_frames` 96행이 브로커 관측 병합, trace 조립, 영속화, 백그라운드 메모리 저장, trailing SSE까지 맡음 → `TraceFinalizer`, `MessagePersister`, `MemorySaveNotifier`로 분리
[chat.py:1260] (P2) `chat()` 148행이 권한/컨텍스트/런타임/그래프 입력/스트림/체크포인트 정리까지 오케스트레이션 이상을 수행 → 라우트는 `ChatTurnService.run()` 호출과 `StreamingResponse` 생성만 남기도록 축소

## packages/api/src/api/runtime.py
[runtime.py:141] (P2) `_wrap_mcp_tool` 98행이 승인 interrupt, 실제 MCP 실행, 예외 매핑, redaction, trace sink 기록, StructuredTool 생성을 모두 포함 → `ApprovalGate`, `ToolInvoker`, `ToolTraceRecorder`로 분해
[runtime.py:333] (P2) `build_mcp_tools`가 서버 캐시 miss 판정, SSRF refresh, 연결 생성, 디스커버리, enabled/filter/approval/wrap까지 한 루프에 결합 → 서버별 `McpToolResolver`로 연결·디스커버리·필터링 단계를 분리
[runtime.py:400] (P2) RAG 검색 도메인(`RagSearchError`, `search_collections`, formatter, cutoff, RAG tool)이 MCP 런타임/trace redaction 파일에 함께 있음 → `rag_runtime.py`로 검색 코어와 RAG tool adapter를 이동
[runtime.py:414] (P2) `search_collections` 105행이 입력 정규화, 임베딩 호출, DB 쿼리, score 정렬, cutoff annotation을 모두 수행 → `QueryEmbedder`, `ChunkSearcher`, `HitRanker` 단위로 나눠 각 단계 테스트를 독립화
[runtime.py:586] (P2) `_sanitize_preview`가 `.memory._sanitize`를 지연 import하고 `chat.py`도 `memory._sanitize`를 직접 호출해 표시 정화 규칙 경계가 퍼짐 → 공용 `trace_sanitizer` 모듈로 마스킹/캡 정책을 단일 API화
[runtime.py:765] (P3) `build_graph_path`와 `_timeline_from_nodes`가 둘 다 합성 timeline을 만들며 start/end/per-node ms 규칙을 별도로 가짐 → timeline builder 하나로 합쳐 fallback별 입력만 다르게 받기

## packages/api/src/api/chat_context.py
[chat_context.py:38] (P2) 모델 pin 해석, provider 복호화, 기본 모델 fallback이 `_pinned_model_cfg`, `_chat_model_cfg`, `_resolve_model`, `resolve_agent_mem_cfg`에 흩어짐 → `ModelConfigResolver`로 chat/model/pin/mem 설정 해석을 집중
[chat_context.py:189] (P2) `derive_pipeline_pool`이 노드 ref 해석, MCP 서버 스캔, 컬렉션 스캔, memories/capabilities denormalization까지 수행 → 순수 `PipelinePoolDeriver`와 DB-backed catalog loader를 분리
[chat_context.py:302] (P2) `_apply_overrides`가 화이트리스트 병합, historyDepth coercion, systemPrompt 적용, node override merge, passthrough 정책을 한 함수에서 처리 → override key별 작은 reducer와 결과 상태 객체로 분리
[chat_context.py:436] (P2) `_resolve_mcp_servers`가 DB row 조회, pin overlay, token 복호화, version 계산, tool filter 정책까지 묶음 → `McpServerProjection` 생성과 tool-filter 정책 결정을 별도 함수로 분리
[chat_context.py:594] (P2) `_load_context` 136행이 agent/version/prompt/override/pool/model/node/mem/MCP/RAG/session을 순차 조립하는 거대 조립점임 → `ChatContextBuilder` 단계 메서드로 쪼개고 ctx dict 대신 typed context DTO를 반환
[chat_context.py:41] (P3) `.block_versions`, `Prompt`, `AgentVersion`, `agent.nodes` 지연 import가 여러 리졸버 내부에 흩어져 의존 그래프가 코드 검색만으로 잘 안 보임 → 순환 회피가 필요한 import만 남기고 나머지는 모듈 상단 또는 resolver 클래스로 모으기

## 이 그룹 TOP 3
1. `chat.py:1260` 라우트와 스트림 실행을 `ChatTurnService`로 분리 — 현재 라우트가 실패 복구·checkpoint·SSE까지 알아 확장 시 회귀면이 가장 넓음
2. `chat_context.py:594` `_load_context`를 typed builder로 재구성 — ctx dict 키 계약이 3개 파일을 관통해 드리프트와 테스트 누락 위험이 큼
3. `runtime.py:400` RAG 런타임을 별도 모듈로 이동 — MCP 실행, RAG 검색, trace redaction이 한 파일에 섞여 SRP 위반과 변경 충돌 가능성이 큼


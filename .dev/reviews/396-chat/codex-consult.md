# codex 자문 원문 — chat.py 리팩터 (2026-07-19, 스펙 396 입력)

[단계 6 — Compounding] read-only 리뷰 결과입니다. 테스트는 실행하지 않았고, 소스/소비자/verify 계약만 직접 읽었습니다. `phase2_workspace_diff.md`는 워크스페이스에 없었습니다.

**판정**
374의 “chat → ChatTurnService” 처방은 그대로 집행하면 지금은 과합니다. 당시 문제였던 `ctx dict`와 큰 stream 모듈은 382/392로 많이 해소됐고, 371 D3 캐시 때문에 그래프 조립 경계도 더 예민해졌습니다. 다만 “라우트가 턴 오케스트레이션을 너무 많이 안다”는 전제는 여전히 유효합니다.

권장 방향은 `LocalServeTurn`식 Command 클래스를 메인 경로에 통째로 복제하는 것이 아니라, 평면 형제 모듈을 먼저 더 나누고, 마지막에 필요하면 작은 `ChatTurnRunner`만 도입하는 것입니다. 메인 `/chat`은 A2A 서빙보다 공개 SSE 프레임, trace, persist, detached memory, checkpoint retention, approval/form/ask를 동시에 계약으로 갖고 있어 큰 클래스가 새 god-object가 될 가능성이 큽니다.

**구조 결함**
1. `_build_turn_runtime`이 사실상 “턴 준비 서비스”인데 dict로 반환됩니다. 회상, history proxy, MCP/RAG 도구, broker, prompt seed, cache hit/miss, buildMs 계측이 한 함수에 섞여 있습니다. 특히 캐시 hit에서는 `tools`를 재사용하면서 per-turn `calls_sink`만 config로 주입하는 계약이 숨어 있어, 순수 이동 중 의미가 깨지기 쉽습니다. [chat.py](/Users/anthony/Repository/github/loveqoo/my-agents/packages/api/src/api/chat.py:264)

2. `chat()` 라우트가 HTTP 라우트가 아니라 턴 라이프사이클 전체를 소유합니다. 진입 권한, context 로드, 원격 분기, 그래프 입력 결정, seed 구성, `graph.astream`, 오류 프레임, interrupt 디스패치, finalization, checkpoint release가 한 스코프에 있습니다. 내부 `interrupts` 리스트가 finally의 `paused` 판정까지 관통하는 구조는 동작상 맞지만 설계상 매우 취약합니다. [chat.py](/Users/anthony/Repository/github/loveqoo/my-agents/packages/api/src/api/chat.py:997)

3. `_final_frames`는 C급답게 책임이 큽니다. broker 관측 합류, trace 조립, persist, message_id, detached memory task 생성, live-only `memoryPending`, `trace/done/memory` 프레임 순서까지 한 함수가 결정합니다. 이 함수는 리팩터 중 “조금 정리”하면 바로 UI 스피너나 memory 저장 보장이 깨집니다. [chat.py](/Users/anthony/Repository/github/loveqoo/my-agents/packages/api/src/api/chat.py:901)

4. interrupt 프레임 가족은 모양이 비슷하지만 계약이 다릅니다. ask/form은 assistant 메시지로 영속하고 trace+done을 냅니다. approval은 정상 턴을 영속하지 않고 approval row와 pending trace만 냅니다. 단순 공통화는 오히려 위험합니다. [chat.py](/Users/anthony/Repository/github/loveqoo/my-agents/packages/api/src/api/chat.py:595)

5. 파사드 블록은 보존해야 하지만, 활성 로직과 섞여 파일의 방향성을 흐립니다. 실제로 `eval_runner`, verify, `approvals.py`가 `api.chat` 표면을 직접 소비합니다. `main.py`는 `chat.router`만 include합니다. [main.py](/Users/anthony/Repository/github/loveqoo/my-agents/packages/api/src/api/main.py:140), [eval_runner.py](/Users/anthony/Repository/github/loveqoo/my-agents/packages/api/src/api/eval_runner.py:27)

**리팩터 설계**
1. `chat_turn_runtime.py`: `_memory_inputs`, `_build_turn_runtime`, `_resolve_graph_entry`, `_turn_config`, `_seed_and_sent` 이동. 단, 반환은 `dict` 대신 `ChatTurnRuntime` dataclass. `_GRAPH_CACHE`, `graph_cache_stats`는 `chat.py` 파사드에서 재수출하되 정의 모듈은 여기로 옮기는 편이 맞습니다. `verify_371`이 `buildMs.graph/mcp`, 동시 trace 격리, promptless system을 봅니다. [verify_371_graph_cache.py](/Users/anthony/Repository/github/loveqoo/my-agents/tests/verify_371_graph_cache.py:1)

2. `chat_sse_frames.py`: `_stream_text`, `_ingest_update`, `_artifact_wait_trace`, `_ask_frames`, `_form_frames`, `_pending_approval_trace`, `_approval_frames`, `_interrupt_frames` 이동. 단순 공통 base emitter보다 “가족 단위 이동”이 먼저입니다. ask/form/approval 차이는 보존하고 중복 제거는 후속.

3. `chat_final.py`: `_bg_memory_add`, `_final_frames`, `_BG_MEMORY_TASKS`, timeout 상수 이동. 이 모듈은 스펙 314 계약을 소유해야 합니다. 프론트는 `[DONE]` 뒤에도 `event: memory`를 계속 읽습니다. [api.ts](/Users/anthony/Repository/github/loveqoo/my-agents/admin/src/api.ts:794), [Playground.tsx](/Users/anthony/Repository/github/loveqoo/my-agents/admin/src/playground/Playground.tsx:416)

4. `chat.py`: `router`, `chat()`, 파사드 재수출만 남깁니다. `chat()`는 여전히 얇은 오케스트레이터로 두되, 내부 generator는 `run_chat_turn(...)` 함수로 내릴 수 있습니다. 클래스를 도입한다면 여기서만 `thread_id`, `interrupts`, `pending_artifact`, `config`, `turn`을 소유하는 작은 runner가 적절합니다.

**동작보존 함정**
- SSE 순서: `session` 먼저, text/artifact 중간, `message_id`는 persist 뒤, `trace` 뒤 `done`, memory는 done 뒤 trailing입니다. 프론트 파서는 이 순서를 전제합니다. [api.ts](/Users/anthony/Repository/github/loveqoo/my-agents/admin/src/api.ts:800)
- `memoryPending`은 live trace 전용이고 영속 trace에는 없어야 합니다. [chat.py](/Users/anthony/Repository/github/loveqoo/my-agents/packages/api/src/api/chat.py:942)
- done 직후 client abort에서도 memory task는 이미 떠 있어야 합니다. 검증도 이 케이스를 직접 닫습니다. [verify_314_async_memory.py](/Users/anthony/Repository/github/loveqoo/my-agents/tests/verify_314_async_memory.py:176)
- `interrupts`는 checkpoint release의 `paused` 판정 재료입니다. 핀 생성 전 취소 케이스 때문에 이 리스트를 다른 스코프로 숨기면 안 됩니다. [checkpoint_retention.py](/Users/anthony/Repository/github/loveqoo/my-agents/packages/api/src/api/checkpoint_retention.py:69)
- source-text verify가 있습니다. 예: `verify_057`은 `inspect.getsource(chat.chat)`를 봅니다. 이동 전에 이 류는 값/행위 검증으로 갱신하거나, 파사드 wrapper 안에 필요한 문자열을 보존하는 임시책이 필요합니다. [verify_057_connect_classification.py](/Users/anthony/Repository/github/loveqoo/my-agents/tests/verify_057_connect_classification.py:144)

**권장 순서**
1. source-text/파사드 소비자 목록을 먼저 박제: `rg "from api.chat|from .chat|inspect.getsource\\(chat"` 결과를 spec에 고정.
2. `_final_frames` 가족 이동. 검증: `verify_314_async_memory.py`, browser `verify-314-async-memory-ui.mjs`.
3. interrupt/frame 가족 이동. 검증: `tests/suite/run.py`의 approval/form/history 관련 시나리오, `verify_101`, `verify_242`, `verify_237`.
4. runtime/cache 가족 이동. 검증: `verify_371_graph_cache.py`, perf-build, 동시 8 trace 격리.
5. 마지막에 `chat()` 얇게 만들기. 이때만 작은 runner/command 여부 재판정. 실채팅은 직접 `/chat`, Playground direct, approval approve/reject, form 재개, A2A loopback을 같이 봐야 합니다.

요약하면: 374의 “서비스화 필요”는 맞지만 “큰 ChatTurnService”는 지금 기준으로 부정확합니다. 현재 코드베이스의 성공 패턴은 평면 형제+파사드+순수 이동+기계 증명이고, 메인 경로도 그 순서가 더 안전합니다.

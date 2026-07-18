# codex read-only 자문 원문 — chat_stream.py 리팩터 (2026-07-18, 스펙 392 입력)

## 1. 구조적 결함 목록(우선순위순)

1. `state: dict` out-param은 가장 먼저 제거할 결함입니다. `stream_local_reply()`가 `(context_id, gen, state)`를 반환하고, `_serve_chunks()`가 스트림 소진 후 `state["approval"]` 또는 `state["error"]`를 채웁니다: `chat_stream.py:251-263, 285-290, 293-302, 377-390`. 소비자는 반드시 iterator를 끝까지 돈 뒤 같은 dict를 읽어야 합니다: `a2a_server.py:438-446, 451-489`. 시간 순서가 타입에 표현되지 않아 중간 취소, 조기 반환, 병렬 소비에서 깨지기 쉽습니다.

2. `_serve_chunks()` 인자 폭발은 실제 응집도 붕괴 신호입니다. `graph, messages, cfg, ctx, thread_id, user_id, user_text, prompt_chars`와 키워드 `has_ckpt, state`가 한 호출에 묶입니다. 이 함수는 스트리밍, interrupt 수집, 영속, 기억 저장, 결과 상태까지 함께 합니다.

3. 책임 혼재가 명확합니다. 같은 모듈에 SSE 설정 오류, 모델 연결 힌트, 원격 A2A 중계, 로컬 A2A 서빙이 공존합니다(`23-32`, `53-67`, `70-136`, `139-390`). 파일명 `chat_stream`보다 실제 책임이 넓어졌고, spec 388 이후 로컬 서빙 런타임이 사실상 별도 use-case가 됐습니다.

4. 지연 import 순환은 "필요한 응급처치"지만 설계 결함의 증상입니다. `chat.py`가 `chat_stream`을 파사드 재수출(`chat.py:89-95`) → `chat_stream.py`가 `chat.resolve_agent_runtime`·`_rag_tools_for`를 지연 import(`317-318`, `226-237`). `chat_approval.py:268-292`도 같은 지연 import. 공통 그래프/도구 조립 API가 `chat.py` 안에 남아 생긴 순환입니다.

## 2. 리팩토링 설계 제안

1. `@dataclass` 파라미터 객체 먼저: `LocalServeRequest(agent_id, user_text, user_id, context_id)`, `LocalServeRuntime(ctx, impl, tools, graph, thread_id, config, messages, prompt_chars, has_ckpt)`. `_serve_chunks()` 10개 인자를 하나로. 트레이드오프: 타입 파일 증가 < 위치 인자 순서가 계약인 현 상태.

2. out-param 대신 명시적 결과 객체: 최소안 `LocalServeResult(context_id, chunks: AsyncIterator[str], outcome: Awaitable[ServeOutcome])`. `ServeOutcome`은 `Completed | ApprovalRequired | Failed`. 소비자는 스트림 소진 후 `await result.outcome`. 트레이드오프: 내부 Future 관리 필요 < "소진 후 dict를 읽어라"보다 강한 계약.

3. 중기안 async 프로토콜 클래스: `LocalA2AServeRun.prepare()` → `run.stream_text()` → `run.outcome`. 제너레이터 반환값 제약을 클래스 상태로 흡수. 상태ful streaming + 후처리 + approval bridge에 적합.

4. 템플릿 메서드/전략 분리(장기): `GraphStreamRunner` + `ChatSseSink`/`LocalA2ASink`. 메인 chat `_stream_text`·`_ingest_update`·`_interrupt_frames`(chat.py:632-676, 904-928)와 유사 계약. **추상화 과잉 위험 — 첫 단계는 로컬 A2A만 클래스로, 공통화는 중복이 선명해진 뒤.**

5. 모듈 분할은 기능 축: `chat_sse.py`(오류 SSE·힌트) / `chat_a2a_proxy.py`(원격 중계) / `local_a2a_serve.py`(로컬 서빙) / `chat_graph_build.py`(순환 유발 공통 API). 파사드 재수출 계약은 단계적 유지 가능.

## 3. 동작보존 함정

1. SSE 프레이밍 이원: 오류 SSE·원격 중계는 `data:`/`event: trace`/`[DONE]` 직접 생산, 로컬 서빙 `_serve_chunks`는 raw text만(감싸기는 a2a_server:451-490).
2. GeneratorExit 경계: 서빙 기억 저장은 스트림 종료 후 인라인(중간 이탈 시 생략 명시), 메인 chat은 done 전 백그라운드 태스크(chat.py:1073-1083). 리팩터 중 이 차이를 바꾸면 동작 변화.
3. interrupt 턴 미영속 계약(`_serve_interrupt_state` 주석·`_serve_chunks` interrupt return; 메인 chat:862-901 동일 구조).
4. ephemeral → checkpointer 미부착, interrupt는 approval 대신 error state(338-341, 178-195). "승인 재개에는 DB 기록 필요" 계약 보존.
5. contextId 세션 연속성·own=user_id 접힘·pending channel="a2a"(308-323); 대화 로드는 세션 있을 때만+window(364-371).
6. 승인 브리지 소비자 계약: a2a_server가 `state["approval"]`을 send→Task input-required(340-367), stream→final status event(467-489)로 변환.

## 4. 권장 분할 순서(위험 오름차순)

1. 순수 이동: 오류 SSE·힌트 → `chat_sse_errors.py`(상태 없음, 위험 낮음), 파사드 유지.
2. 순수 이동: `_a2a_stream` → `chat_a2a_proxy.py`(ctx.endpoint/card/token만 사용).
3. 타입 추가만: `ServeOutcome`·`LocalServeRequest`·`LocalServeTurn` dataclass, 인자 폭발 제거(이 단계 out-param 유지 가능).
4. out-param 제거: 반환 `(context_id, chunks, outcome)` 또는 `LocalServeRun`, a2a_server 소비를 `await outcome`으로. **가장 계약 변경 위험 큼.**
5. 순환 제거: `_rag_tools_for`·`resolve_agent_runtime` → `chat_graph_build.py`, 지연 import 제거(chat_stream 2곳·chat_approval 1곳).
6. 마지막에 공통 runner 검토 — 행동보존 전판 테스트 준비 후에만. interrupt·memory·SSE 프레이밍 계약이 완전히 같지 않음.

[단계 5 — Verification]
참고 자산: 026/027 RAG 인제스트·검색 회고, 269/270 provider 조립·flow 중복 제거 회고, 152/359 노드형 실행 코드·메커니즘 대칭성 학습

## packages/api/src/api/rag.py
[packages/api/src/api/rag.py:1] (P1) 1,256행 라우터가 컬렉션 CRUD·health·reindex·retrieval·인제스트·편집·배경잡을 모두 짊어짐 → `collections_router`, `documents_router`, `reindex_service`, `ingest_service`, `search_service`로 축 분리.
[packages/api/src/api/rag.py:180] (P1) 임베딩 모델 kind/probe/dims 검증이 생성(`create_collection`)과 재인덱싱 모델 해석(`_resolve_reindex_model`)에 복제됨 → `validate_embedding_model_for_collection()` 단일 서비스로 합쳐 drift 차단.
[packages/api/src/api/rag.py:367] (P2) `_embed_with_model`과 `_embed_chunks`가 provider 복호화·embed_texts 호출·차원 검사를 별도 구현함 → 모델 명시/컬렉션 기반 입력만 다른 공통 `EmbeddingClient.embed_checked()`로 수렴.
[packages/api/src/api/rag.py:419] (P2) `_do_reindex`가 모델만 교체와 재청킹 재구축을 한 함수에서 분기해 DB 읽기·HTTP 임베딩·스왑 트랜잭션을 모두 처리함 → `reembed_existing_chunks`와 `rechunk_from_blobs` 전략 함수로 분리.
[packages/api/src/api/rag.py:709] (P2) API 라우트가 `runtime`을 지연 import하고 검색용 dict에 `embed_base_url`·복호화된 api_key를 직접 조립함 → 라우터는 `RagSearchService.search_collection(cid, query, top_k)`만 호출하게 경계 이동.
[packages/api/src/api/rag.py:883] (P2) `_persist_chunks`가 청크 삽입, 문서 상태 변경, 컬렉션 집계, 재인덱싱 경합 가드를 한 트랜잭션 절차에 결합함 → 저장소 계층 메서드로 옮기고 집계 업데이트/청크 삽입을 명명된 하위 단계로 분해.
[packages/api/src/api/rag.py:950] (P2) `ingest_document`가 권한·락·업로드 크기·엔티티 파싱·문서/blob 저장·배경잡 시작까지 한 엔드포인트에 결합됨 → 동기 접수 유스케이스 객체로 추출하고 라우터는 요청/응답 매핑만 담당.
[packages/api/src/api/rag.py:999] (P2) `_execute_ingest`가 `SessionLocal`, 청킹, 임베딩, 저장, 이벤트 발행, 오류 박제를 직접 소유해 테스트가 전역 상태에 묶임 → 세션 팩토리·이벤트 퍼블리셔·임베더를 주입받는 background job 클래스로 분리.
[packages/api/src/api/rag.py:1155] (P2) `update_document_content`가 편집 가능성, 재청킹, 부분 임베딩, 집계 보정, blob 교체를 100행 이상에서 처리함 → `DocumentEditService`로 옮기고 parse/reuse/swap 단계를 각각 독립 테스트 가능하게 분리.

## packages/agent/src/agent/flows/pipeline.py
[packages/agent/src/agent/flows/pipeline.py:197] (P2) `normalize_nodes`가 code node와 prompt node의 스키마 정규화, 기본값, memory/history 옵션을 untyped dict로 한 번에 만든다 → `CodeNodeConfig`/`PromptNodeConfig` typed config 파서로 분리.
[packages/agent/src/agent/flows/pipeline.py:275] (P1) `build_graph`가 기본 노드 생성, 도구 이름 해석, 코드 노드 레지스트리 조회, 모델 바인딩, 프롬프트 작성, 메모리/히스토리 주입, LangGraph assembly를 모두 담당함 → `PipelineCompiler`, `ToolResolver`, `NodeStepFactory`로 역할 분리.
[packages/agent/src/agent/flows/pipeline.py:290] (P2) 도구 해석이 런타임 이름 규칙 `서버__도구`와 suffix fallback을 flow 내부가 직접 앎 → 도구 네이밍/모호성 정책을 toolbox 쪽 resolver로 옮겨 flow는 추상 이름 매칭만 사용.
[packages/agent/src/agent/flows/pipeline.py:310] (P2) `_make_step`가 120행 넘는 클로저로 모델·도구·JSON 포맷·history·recall·clean/carry·cap 처리를 캡처함 → `PromptNodeStep` 클래스로 추출해 각 정책을 생성자 의존성으로 주입.
[packages/agent/src/agent/flows/pipeline.py:316] (P2) 코드 노드 구현 조회를 `_make_step` 내부 지연 import로 해결해 조립점이 실행 함수 안에 숨어 있음 → node registry를 `AgentBuildContext` 또는 `LinearPipelineAgent` 생성자에 주입.
[packages/agent/src/agent/flows/pipeline.py:374] (P2) JSON 출력 강제와 repair 모델 호출이 노드 실행 클로저 안에 섞여 있어 출력 계약 테스트가 그래프 실행에 묶임 → `OutputFormatter`/`JsonRepairPolicy`로 추출.
[packages/agent/src/agent/flows/pipeline.py:398] (P2) `_step`이 reentry 판정, tool cap, system prompt 합성, recall, clean 모드 message removal, history injection, 모델 호출을 한 번에 수행함 → `build_prompt_context()`와 `invoke_node_model()`을 분리.
[packages/agent/src/agent/flows/pipeline.py:434] (P2) graph assembly가 step 생성 결과의 tuple 구조와 tool loop node naming `<id>__tools`를 직접 맞물림 → `CompiledNodePlan(step, tools_node_id, route)` 같은 중간 계획 객체로 명시화.

## 이 그룹 TOP 3
1. `rag.py` 라우터 분할: 현재 한 파일 변경이 검색·인제스트·편집·재인덱싱 전체를 건드리는 구조라 drift와 회귀 범위가 가장 큼.
2. `pipeline.py`의 `build_graph`/`_make_step` 분해: 노드형 실행의 핵심 정책이 거대한 클로저에 숨어 있어 새 노드 기능 추가 때 결합 비용이 계속 증가함.
3. RAG 임베딩 검증/호출 공통화: 생성·재인덱싱·인제스트가 같은 차원/모델 규칙을 별도 구현해 가장 현실적인 규칙 drift 표면임.


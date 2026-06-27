# 027 — RAG retrieval(스펙 037) 회고

P2-b. 죽어 있던 `vectorTables` 에이전트 설정을 **에이전트 호출형 검색 도구**로 부활:
질의를 **컬렉션 자신의 임베딩 모델**로 임베딩 → pgvector HNSW cosine 검색(컬렉션 필터)
→ 상위 청크 주입 + trace 노드 기록. 프론트는 mem0 게이트에서 분리해 실 컬렉션 피커로 교체.

## 무엇을 했나
- **`runtime.build_rag_tool`**: async `StructuredTool`. `(base_url, model_id)`별 질의 임베딩 캐시(같은
  모델 쓰는 컬렉션은 1회만 호출 — learning [[035-guard-the-source-not-the-copy]] 정신, 인제스트 모델을 직접 따름).
  컬렉션별 `Chunk.embedding.cosine_distance(qvec)` 정렬·limit → 통합 정렬 → 상위 k. 모든 실패(임베딩
  다운·DB 오류)는 graceful 문자열 + `calls_sink status="error"`로 흡수(에이전트 크래시 금지).
- **`chat.py` 배선**: `_load_context`가 `vectorTables`(이름) → Collection select(`selectinload`
  embedding_model→provider, 키 복호화) → 검색 dict. code/external은 비로컬이라 게이트. `chat()`에서
  도구 주입 + `trace["ragCollections"]`.
- **프론트(`AgentsView`)**: 깨진 `blocks.embedding` 소스 + mem0 게이트 뒤에 숨겨졌던 vectorTables
  에디터를 `listCollections()` 실 컬렉션 피커로 교체(ungated).
- **mock 임베딩 결정화**: 상수 `[0.1]*dims`(전부 거리 0)를 sha256 시드 입력의존 벡터로 교체 →
  retrieval 랭킹을 실제로 행사하는 결정적 검증 가능.

## 잘된 것 / 막힌 것
- **유령 버그를 끝까지 팠다(핵심).** verify_037의 [1]=4 vs [5]=2 반환 수 불일치를 처음엔 'pgvector
  HNSW 후필터 starvation'으로 의심하고 4번 재현 시도했으나 재현 실패. 정확한 verify 조건(main 5청크,
  single collection)으로 **실제 도구 출력을 덤프**하니 헤더는 "5건"인데 정규식은 2만 셌다 → 원인은
  pgvector가 **전혀 아니고** `_sims` 정규식 `유사도 ([\d.]+)\)`가 **음수 유사도**(`-0.048` 등)를 못 잡아
  음수 라인을 통째로 누락한 것. 추측 대신 진실(원시 출력)을 본 게 결정타 → learning [[036-...]].
- **타자 양측 수렴 = 비밀 누출 0.** 서브에이전트 + codex 독립 병렬 모두 decrypt 키가 calls_sink/trace/
  반환문/IngestError 어디에도 안 샌다고 수렴(IngestError는 상태코드만 노출하도록 036에서 이미 규율).
- **타자가 수렴 결함 3건을 추가로 줬다**: ①`top_k=int(...)`가 try 밖이라 비정상 인자에 크래시 가능 →
  방어적 강제 ②음수 유사도(반-상관) 청크가 '근거'로 반환됨 → **floor 추가**(직교=0은 수학적 경계라
  양수 매치는 절대 탈락 안 함; 임의 임계 아님) ③미해석 vectorTables가 조용히 도구 0개 → `trace["ragUnresolved"]`
  + log.warning 관측성.

## 남긴 빚(의도적, 이후)
- 양수 구간 관련도 임계 튜닝(예 0.3 미만 컷)은 recall 트레이드오프라 실데이터 기반으로 이후(음수 컷만 v1).
- **멀티모델 통합 정렬**: 다른 임베딩 모델 컬렉션을 한 에이전트가 동시에 쓰면 다른 벡터 공간의 dist를
  단순 비교 → 순위 무의미. 강제 방지(에이전트당 단일 모델) 또는 스코어 정규화는 후속(타자 양측 지적).
- e5 query/passage 프리픽스 미적용(인제스트도 미적용 → 일관).
- trace 인스펙터의 `search_documents` 노출은 브라우저로 미실증 — mock-llm이 툴 호출을 안 함(단일턴).
  계약은 수치검증의 `calls_sink` 단언으로 커버.

## 검증
- 수치: `verify_037_rag_retrieval.py` ✅ ALL PASS(exact-match 1.000+변별, 정렬 불변식, 빈/무매치 graceful,
  top_k 클램프+floor 내 전건, 멀티 컬렉션 통합, 임베딩 실패 graceful, 음수 floor). verify_036 무회귀 확인.
- UI: `shot-agents-037.mjs`(Playwright+시스템 Chrome) — 편집 폼의 '지식 소스 (RAG 컬렉션)' 필드가
  **mem0 미선택에서도** 뜨고 실 컬렉션 4개(모델·청크수) 렌더 → 회귀 해소 눈으로 확인.
- 타자: 적대적 서브에이전트 + codex 독립 병렬 → 비밀 누출 0 수렴 + 수렴 결함 3건 수정.

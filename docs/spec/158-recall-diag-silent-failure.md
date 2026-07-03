# 158 — 회상 진단이 실패를 "정상·0건"으로 위장 (버그)

## 증상 (사용자, 다른 배포본)
- 스코프 `392ef161…`에 기억 **11건 존재**(본문 부분일치 목록엔 전부 보임).
- 회상(유사도 검색) query="Agent" → **0건**. 진단은 **"정상 · 백엔드 준비됨 · error 없음"**.
- 즉 텍스트 목록(SQL)은 되는데 벡터 유사도만 0건, 그런데 진단이 정상이라 사용자는 원인을 모름.

## 근인 (deep-reasoner 적대 검증 — 두 실패 모드가 같은 화면)
**M2(유력) — mem0 숨은 threshold=0.1**: mem0 2.0.7 `Memory.search(threshold=0.1 기본)`. 우리는 이 인자를
안 넘겨(top_k만) **0.1을 상속**. semantic_score=코사인 유사도(pgvector `1-distance`, 0클램프)가 0.1
미만이면 `score_and_rank`가 전부 컷(scoring.py:110). "Agent" 질의에 11건 모두 유사도<0.1이면 **0건·
예외 없음**. 게다가 snowflake-arctic은 **query prefix 요구 비대칭 모델**인데 mem0 OpenAI 임베더가
memory_action을 무시하고 원문 전송(embeddings/openai.py:47) → query 벡터가 passage 공간과 어긋나
유사도가 더 눌림. **UI는 "관련도 내림차순 상위 기억"을 약속하는데 숨은 0.1이 이를 배신**.
list_page/목록은 벡터 스코어링·threshold가 없어(순수 SQL/`vector_store.list()`) 11건이 다 보임 → 비대칭.

**M1(잠재) — 예외 삼킴**: `Mem0Backend.search`(mem0_backend.py:103-125)가 축별 `except: continue`로
전 축 실패해도 `[]` 반환 → recall_diag가 `error=None, backend_ready=True`로 "정상" 판정. mem0.search는
임베더 예외를 자체 삼키지 않음(전파) → 우리 앱의 삼킴이 문제. M2와 **동일 화면**(정상·0건)이라 스크린샷만으론 구별 불가.

**핵심**: A/B/C(예외 표면화)는 M2를 못 고친다(예외 없음). **회상 테스트는 threshold=0으로 top-k를
보여줘야**(UI 약속대로) 사용자가 기억을 보고 낮은 점수로 원인을 자가진단한다. 공유 경로 주의:
`memory.search`(챗)=조용한 견고, `recall_probe`(브로커)=InvokeResult.error로 표면화(None/[] 위장 금지),
`recall_diag`(진단)=표면화.

## 설계 (deep-reasoner 승인/수정점 반영)
- (T) **threshold 파라미터**: `Mem0Backend.search(scope, query, limit, threshold=None)` — None이면 mem0
  기본(0.1), 값 주면 명시 전달. MemoryBackend 계약·InMemory에 param 추가(InMemory는 무시).
- (핵심) **recall_diag는 threshold=0.0으로 top-k 표시**: UI 약속("관련도 내림차순 상위")대로 저장된
  기억을 관련도순으로 보여준다(낮은 점수까지) → 사용자가 회상 결과를 실제로 보고, 낮은 점수로
  "임베더/질의 유사도" 문제를 자가진단. 숨은 0.1이 전부 컷하던 위장 종료.
- (A) `Mem0Backend.search`: 축별 **성공(예외 없이 반환, []도 성공) vs 예외** 분리 추적 → **성공 축
  0(전부 예외)**일 때만 마지막 예외 raise(정직한 0건은 raise 안 함 — M2 오탐 방지, deep-reasoner 수정점).
- (B) 파사드 분리:
  - `memory.search`(챗): try/except → `[]`(조용한 견고, log.warning). 회상 실패가 턴을 안 죽인다.
  - `recall_probe`(브로커): **catch 안 함**(raise 유지) → `broker.invoke`가 잡아 `InvokeResult.error`로
    표면화([]로 접으면 recall_probe가 막으려던 None/[]/실패 위장 재발 — deep-reasoner).
- (C) `recall_diag`: 기존 except(146)가 (A)의 raise를 잡아 `error` 표면화.
- (D) **저장 건수 + 진단**: recall_diag가 스코프 저장 수를 **`list_page(limit=1).total`(count(*))**로 싸게
  잰다(list_all은 최대 1만행 페치 — 금지). MemorySearchDiag에 `stored` 필드, UI 노출. threshold=0에서도
  저장>0·회상0이면 벡터/필터 심층 문제(hint), 결과가 나오되 점수 낮으면 "유사도<임계·임베더 프리픽스
  /질의 어휘 또는 저장 시 임베더 불일치" 안내(원인 귀속 편향 금지 — deep-reasoner).

## 검증
- verify_158: (V1) M1 재현 — search가 전 축 예외면 recall_diag가 error 표면화(정상 위장 안 함).
  (V2) M2 재현(로컬 mock-embed — 독립난수 벡터로 결정적 저유사도) — 기본(0.1)이면 0건이나 diag의
  threshold=0 경로가 top-k 반환·stored>0 표기. (V3) 부분 성공(1축 OK)은 raise 안 함(견고). (V4) 챗
  파사드 실패 시 [](무회귀). (V5) 브로커는 InvokeResult.error 표면화.
- codex 여집합. e2e: RecallPanel에 저장 건수·결과·힌트 표시.

## OUT
- 재인덱싱 도구·arctic query-prefix 주입(임베더 계층 — 후속). chat 회상 threshold 튜닝(제품 결정 —
  이 스펙은 진단/테스트 경로 정직화가 범위, 챗은 기본 유지하되 명시화만).

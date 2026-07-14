# 336 — 게이트 드리프트 3건 정비

## 배경 (사용자 선택, 2026-07-14)

331~335 기능 몰이 후 정비 차례 — 백로그의 게이트 드리프트 3건(수치 게이트가 깨끗해야 자율
루프도 가능). 전부 stash 재현으로 기존 드리프트 확증된 것들.

## 진단 → 처방 (실측 기반)

### ① suite `pipeline-rag-and-tool` flaky → **발화 정렬** (0/5 → 5/5)
- 실측: RAG 호출은 정상, **메아리 노드가 echo 호출을 상습 생략**(구 프롬프트 4/5 실패).
  프롬프트 강화("도구 미호출=임무 실패")로도 **0/6** — qwen3.6은 노드 시스템 프롬프트의 도구
  강제를 무시. toolDiag로 바인딩 정상 확인(bound에 echo 존재 — 코드 아닌 모델 행동).
- 대조 실험: **사용자 발화가 직접 요구하면 결정적으로 호출**(rag+echo 둘 다). 모델의 지시
  가중치는 유저 발화 > 노드 프롬프트.
- 처방: 시나리오 발화를 도구 기대와 정렬("…echo 도구로 그 코드네임을 울려서 결과까지 보여줘").
  **단언 불변**(rag_called·tool_called echo·text — 커버리지 보존). 5/5 통과 실측.

### ② 복잡도 rank D — 2곳 분해 (게이트 초록)
- `rag.py reindex_collection`: 검증 4블록을 헬퍼로 추출(_resolve_reindex_model/_resolve_rechunk/
  _reject_inflight_ingest/_reject_blobless_docs) — 시맨틱 불변, 라우트는 선형 오케스트레이션만.
- `blocks.py test_mcp_tool`(스펙 326산): **제 grep 필터에 가려져 있던 두 번째 D를 발굴** —
  xenon 출력 전체를 봐야지 패턴 grep은 위반을 숨긴다. _validate_tool_testable/_build_test_server
  추출.
- 함정 2회: 헬퍼를 데코레이터와 함수 **사이에** 삽입해 라우트 데코레이터가 헬퍼를 감쌈 —
  blocks는 즉시 잡았지만 rag는 dev 서버 부팅 실패(FastAPIError)로 발현(verify가 침묵 크래시).
  라우트 함수 위에 코드를 넣을 땐 데코레이터 소속을 반드시 확인.

### ③ verify_312 실패 → **검증기 2중 버그** (제품 무결)
- 어제 1건 → 오늘 6건: 5건은 **스펙 334 여파**(업로드 즉시 ready 전제 — 334 때 149/331/332/333만
  갱신하고 312를 누락. "312 무회귀" 주장은 334 이전 실행 기준이었음 — 정직 정정) → ready 폴링.
- 원래 1건: 이력 기록은 정상(재청킹 1건 기록됨). **모델 교체 다리가 rapid-mlx 없으면 스킵되는데
  이력 단언은 고정 2건 기대** — 기대치를 실행된 다리 수에 연동. VERIFY312_OK.

## 검증
- suite 전판 **51/51**(flaky 2 재시도 통과 — 실모델 정상 범위) · verify_312/326 OK ·
  lint/format/mypy/**complexity** 전부 초록 · codex 시맨틱 보존 적대.

## OUT
- rag.py 파일 분할(1,200줄 — 복잡도 게이트는 초록이 됐고, 모듈 분할은 별 스펙 규모) ·
  suite flaky 잔여 2종(bare-session-recall·direct-control-combined — 재시도 통과 수준 유지 관찰).

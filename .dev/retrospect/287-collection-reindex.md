# 287 — 컬렉션 재인덱싱·재청킹 (스펙 312)

## 무엇을 했나
임베딩 모델·청크 정책이 생성 후 불변이던 컬렉션을, **저장된 원본으로 다시 인덱싱/재청킹**할 수
있게 했다. 동기: mock-embed로 심은 movies-demo가 검색이 형편없어도(비의미 벡터) 모델을 못 바꿨다 —
같은 10편을 e5로 다시 심으니 패러프레이즈 질의가 mock 0.056 → e5 0.907로 확연히 개선(실측).

- **백엔드**(커밋 20b1518): 인제스트 시 `document_blobs`에 원본 저장(재청킹 필수) · `POST
  /collections/{id}/reindex {embedding_model_id?, chunk_size?, chunk_overlap?}`(모델만=재임베딩 /
  청크변경=원본서 재청킹, 문서형만, 같은 차원 1024) · **배타 잠금**(status='reindexing' CAS →
  검색·인제스트·수정·삭제·재인덱싱 전부 409) · `collection_reindex_events` 이력 테이블 · 마이그레이션
  f312 · 평가 이력 보존.
- **프론트**: 컬렉션 행에 재인덱싱(↻) 버튼 → `ReindexModal`(모델 Select·문서형 청크 입력·긍정 카피·
  변경분만 전송·이력 Table) · status 'reindexing' 태그 · **EditModal의 "변경 불가—새로 만드세요"
  카피를 재인덱싱 가능으로 교정**(재인덱싱 도입이 그 카피까지 승계).

## 배운 것 / 복리 포인트

- **불변식을 완화하는 기능은 "왜 불변이었나"를 먼저 부수고 들어가야 한다 — 원본 저장이 그 열쇠**.
  청크 정책이 불변(스펙 198)이던 *이유*가 "재청킹은 원본이 필요한데 원본을 안 저장해서"였다. 사용자가
  "청크 크기·겹침도 튜닝하고 싶다"고 하자, 최소 패치(모델만 교체)로 답하려던 걸 멈추고 근본
  제약(원본 미저장)을 부쉈다. 원본을 `document_blobs`에 저장 → 청크 정책 불변이 재인덱싱 경로로
  완화됨. **불변식은 대개 "그때 없던 것" 때문이다 — 그 결핍을 메우면 불변식 자체가 재협상 대상.**
  → [[structure-first-boundary-is-spec]] [[whole-fix-over-minimal-patch]]

- **재인덱싱하면 과거 평가를 지우나? — 아니오. 안전 + 이미 그 방향 + 모델이 런별 박제라 비교가치**.
  사용자 질문에 "지운다 vs 이력"을 즉답하지 않고 스키마를 봤더니, (1)평가 삭제=비가역 파괴(안전 지양)
  (2)eval_runs는 문제집 밑 audit라 컬렉션 변경과 독립 (3)`EvalRun.env`가 실행 시점 임베딩 모델명을
  이미 박제(스펙 240) → mock 옛 런 vs e5 새 런이 그대로 비교. 즉 "이력 보존"이 **이미 설계 방향**이라
  구현이 거의 공짜였다. 재인덱싱+평가=RAG 하이퍼파라미터 튜닝(모델·청크 A/B)의 토대. → [[probe-deeper-before-concluding]]

- **배타 잠금은 "설치"가 아니라 "모든 접근 경로를 덮어야" 성립 — codex가 여집합을 짚었다**. 잠금을
  status CAS로 만들고 검색·인제스트·수정·삭제에 가드를 걸었는데, codex 적대 리뷰가 (F1)인제스트가
  커밋 시점에 status='ready'를 *무조건* 덮어 잠금을 풀고 새 청크를 유실시키는 P0 데이터 손실,
  (F3)`delete_document` 가드 누락, (F6)검색 잠금이 임베딩 호출 *뒤*라 502로 새는 걸 찾았다. F1은
  `_persist_chunks`를 **조건부 UPDATE(`status!='reindexing'`, 컬렉션 행 잠금)**로 봉인 — 인제스트가
  커밋 시점에 잠금을 존중하고 재인덱싱과 DB 행 잠금으로 직렬화된다. **"가드를 설치했다"와 "모든
  진입점을 덮었다"는 다르다 — 검사 지점과 부수효과 지점의 틈을 적대자가 짚는다.** → [[installed-guard-isnt-covering-guard]] [[gate-on-intent-value-not-mutable-baseline]] [[use-codex-for-adversarial-verification]]

- **여집합 공격이 성공해도 다 코드결함은 아니다 — 단일 워커 경계는 정직화가 옳다**. codex의 F2(멀티워커
  stale 회수 경합)·F4(관리 CRUD TOCTOU)·F5(빈 컬렉션 probe-None 우회)·F7(커밋 사이 크래시 이력 누락)은
  개인 단일 워커 배포에선 안전 위반이 아닌 미문서 경계다. 고치는 대신 **주석 명시 + 스펙 OUT 기록 +
  안전 불변식(원자 스왑=데이터 일관) 재확인** 셋을 함께 했다(F5는 create_collection과 동일 관대 정책).
  → [[complement-attack-can-be-honest-boundary]] [[adversarial-review-before-destructive-ship]]

- **불변식 완화는 그 불변식을 말하던 UI 카피까지 승계한다**. 재인덱싱을 넣으니 EditModal의 "모델·청크는
  변경 불가 — 바꾸려면 새로 만드세요"가 즉시 거짓이 됐다. 컨트롤을 추가하면 하위 어포던스(안내 카피·
  페이지 부제)까지 같은 변경에서 고쳐야 한다(놓치면 "가능한데 불가능하다 말하는" UI). 긍정문으로
  ("↻로 바꿀 수 있습니다"). → [[context-control-propagates-to-affordances]] [[prefer-positive-phrasing-in-copy]]

## 검증 (사다리 + 프론트 기능 왕복)
- **백엔드**: 단위+통합 `tests/verify_312_reindex.py` VERIFY312_OK — 모델교체 검색 mock 0.056→e5 0.907·
  재청킹 2→6·배타잠금(검색/인제스트/재인덱싱 409·CAS 이중방지)·**F1 회귀 3건**·평가이력 불변·stale복구·
  계보 기록. codex 적대 7건→3 수정(F1 P0·F3·F6)+4 경계 문서화. ruff/mypy 클린(106 파일).
- **프론트**: tsc 0·vite build ✓·브라우저 기능 왕복 `tests/browser/verify-312-reindex.mjs`
  VERIFY312_UI_OK — 모달 구동→모델 e5 선택→'재인덱싱 실행'→**reindex POST 발화·모델 스왑 실측·
  이력 1건 기록**·콘솔 치명 0(외형 아닌 동작 단언). → [[ui-verification-must-be-functional]]

## 남은 것 / 주의
- **OUT**: 차원 변경(1024↔768, 전역 벡터 저장 구조 재설계) · 무중단 재인덱싱 · RAG 모델·청크 비교 격자 ·
  멀티워커 stale lease(F2) · 관리 CRUD 원자 배타(F4).
- 소급 한계: 이 기능 이전 문서는 원본 미저장 → 재청킹 불가(재업로드). movies-demo도 로더 재실행 시
  원본 저장됨. UI·서버 400 메시지로 안내(no silent).
- 커밋 2분할: 백엔드 20b1518(마일스톤) + 프론트(본 회고 턴). 사용자 지시로 백엔드부터 나눠 진행.
- dev api(8000)·vite(5173) 기동 중.

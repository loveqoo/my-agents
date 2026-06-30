# 076 — 완화를 검증할 땐 실제 비용지표 + 반증(counterfactual)으로: 프록시 단언과 "선택≠강제"를 구분하라

## 상황
스펙 073에서 세션 읽기 저장계층 타이밍 측면채널을 owner-선두 복합 인덱스로 봉합하고, 첫 검증
`verify_073_explain`은 "플래너가 복합을 선택"+"rows_removed_by_filter=0"만 단언해 ALL PASS로 보였다.
적대 codex(rung 3)가 P1 2개를 짚었다: (1) 측정이 한 시드 분포에서 플래너가 *우연히* 복합을 골랐을
뿐 **강제**가 아니다, (2) `rows_removed=0`은 타이밍의 *프록시*일 뿐 실제 지표(buffer)를 단언 안 했다
(heap_touch를 계산해놓고 버림).

## 배운 것 (일반화)
완화책(mitigation)을 "측정으로 검증"한다며 happy-path 초록을 받았을 때, 세 가지를 점검하라:

1. **프록시가 아니라 실제 비용지표를 단언하라.** "타이밍 누출"이면 타이밍에 *직접 대응하는 양*을 재라 —
   여기선 `EXPLAIN (ANALYZE, BUFFERS)`의 `Shared Hit Blocks + Shared Read Blocks`(총 블록 접근수,
   캐시 온도와 무관하게 결정적). `rows_removed_by_filter`·인덱스명은 *정황*이지 누출량이 아니다. 타인행
   heap 1페이지를 더 만지면 total_blocks가 +1 되는 게 곧 타이밍 델타. (계산만 하고 *단언 안 한* 지표는
   검증에 없는 것과 같다 — codex가 버려진 heap_touch를 정확히 짚었다.)

2. **반증(counterfactual)으로 인과 + 민감도를 동시에 입증하라.** "완화책이 동등을 만든다"는 단언은,
   완화책을 *제거*했을 때 델타가 *되돌아오는지*를 보여야 (a) 그 완화책이 동등의 *원인*이고 (b) 테스트가
   델타에 *민감*함(2==2가 우연 아님)이 함께 선다. 비파괴로: 트랜잭션 안에서 인덱스 DROP→EXPLAIN→
   `rollback`. 실측 — 복합 제거 시 타인-존재 3블록 vs 부재 2블록(델타 재출현), 복합 있으면 2==2.

3. **비용기반 선택자에 의존하는 완화는 "감축"이지 "강제"가 아니다 — 정직히 기록하라.** 봉합이 쿼리
   플래너의 *비용 선택*에 달렸다면(복합 vs solo unique), 측정한 분포에서 옳아도 **운영 통계/소규모
   테이블에서 회귀**할 수 있다. "측정으로 봉합 완료"가 아니라 **"감축 + 측정 + 정직 잔존(왜 완전 강제가
   불가한가)"**으로 적는다. 073에선 완전 강제하려면 solo unique 제거가 필요하나 전역 uniqueness가 막아
   불가 → 잔존 명시. (실 악용성 가늠도 같이: `session_id`는 128bit 시크릿이라 추측-probe 불가 → 심층방어.)

## 어떻게 적용하나
완화책 검증 테스트를 쓸 때 체크: **(a)** 단언하는 양이 위협의 *실제 비용지표*인가, 아니면 그 프록시인가?
**(b)** 완화책을 끈 반증이 델타를 되살려 인과·민감도를 박는가? **(c)** 봉합이 *결정적 강제*인가 *비용기반
선택*인가 — 후자면 잔존을 정직 기록(완료 선언 금지). happy-path 초록 + 프록시 단언은 "상상한 실패"만 본다.

## 근거
- 적대 codex(rung 3)가 P1-1(분포·강제), P1-2(프록시 단언) 짚음 → buffer total_blocks 동등 단언 +
  반증 데모(트랜잭션 DROP/rollback)로 봉합. 측정: 복합 R1=R2=2, 강제-solo F1=3≠F2=2.
- 봉합 대상의 본질은 [[timing-oracle-is-layer-specific]](learning 073) — 그 *검증 방법론* 보강이 이 학습.
- 관련: [[probe-deeper-before-concluding]](단정 전 한겹 더), [[verification-ladder-three-rungs]]
  (적대 rung만이 프록시-단언 사각을 잡음), [[adversarial-review-before-destructive-ship]],
  [[cap-the-raw-source-not-the-buffer]](프록시 위 카운트=막은 척과 동형 — raw/실지표에서 재라).

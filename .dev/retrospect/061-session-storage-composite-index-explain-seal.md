# 061 — 세션 읽기 저장계층 타이밍 봉합(070 P2): 복합 인덱스 + EXPLAIN 측정

스펙 073. 070이 앱계층에서 읽기 게이트를 단일화한 뒤 적대 codex가 이월한 P2(저장계층 타이밍 잔존)를
owner-선두 복합 인덱스 2개 + EXPLAIN 실측으로 닫았다. AI 영역 회고.

## 무엇을 했나
- `(user_id, session_id)`(읽기 게이트)·`(user_id, agent_pk, session_id)`(resume) 복합 인덱스 추가
  (models.py `__table_args__` + alembic `f2a3b4c5d6e7`). `session_id` 단독 unique는 전역 uniqueness용
  유지(get-or-create flush 의존).
- `verify_073_explain`로 타인-존재 vs 부재가 동일 복합 인덱스·동일 buffer를 타는지 *실측*.

## 잘된 것
- **측정을 본질로 못 박은 설계.** 스펙이 처음부터 "인덱스 존재 ≠ 완료, 플래너가 *실제로* 복합을 고르나를
  EXPLAIN으로"라고 완료조건을 측정가능하게 적었다(numeric-verification-unlocks-autonomy). 그래서 codex
  지적도 "재설계"가 아니라 "측정 강화"로 흡수됐다.
- **새 probe 입구 없음을 코드로 확인.** codex가 thinking에서 chat get-or-create의 user_id 없는 쿼리를
  의심했으나, else 분기가 `secrets.token_hex(16)` fresh id를 발급 → 그 쿼리는 공격자 입력에 안 닿음을
  읽어 확인. codex도 final findings에서 정확히 뺐다(입구 무누출).

## 아팠던 것 (codex가 잡은 것)
- **프록시 단언으로 초록을 받았다.** 첫 검증은 `rows_removed_by_filter=0`·인덱스명만 봤다. 정작 타이밍의
  실제 지표인 buffer(`Shared Hit+Read Blocks`)는 안 쟀고, `heap_touch`를 계산해놓고 버렸다. codex가
  정확히 "버려진 신호 + 약한 단언"을 짚음. → total_blocks 동등 단언으로 보강(R1=R2=2 실측).
- **"선택"을 "강제"로 과장할 뻔.** 측정이 한 분포에서 플래너가 복합을 골랐을 뿐인데 "봉합 완료"로 적힐 뻔.
  복합을 가린 **반증**(트랜잭션 DROP→rollback)으로 강제-solo 시 델타 재출현(F1=3≠F2=2)을 보여 인과를
  박되, 동시에 "이건 플래너 선택이지 강제가 아님"을 드러내 잔존을 정직 기록.
- **멱등성을 스펙에 적고도 코드에 안 넣었다.** plain create/drop이었다 → `if_not_exists`로 보강, 부분
  드리프트 upgrade 수렴 실증.

## 배운 것 → 자산
- learning **076**(완화 검증: 실제 비용지표 + 반증 + "선택≠강제" 정직). learning 073의 *검증 방법론* 보강.
- 반복된 패턴 재확인: 적대 rung이 단위·라이브가 못 보는 "프록시 단언/과장된 완료선언"을 잡는다
  (verification-ladder-three-rungs, probe-deeper). 이번엔 결함이 *수정*이 아니라 *검증*에 있었다 —
  "코드는 옳은데 검증이 약함"도 적대 rung의 사냥감.

## 다음에 빠르게
완화책 검증 테스트 초안 단계에서 자문: 단언하는 양이 위협의 *실제 비용지표*인가(프록시 아님)? 완화책을 끈
반증이 델타를 되살리나? 봉합이 결정적 강제인가 비용기반 선택인가(후자면 잔존 기록)? — 세 줄을 체크리스트로.

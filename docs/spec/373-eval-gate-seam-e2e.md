# 373 — 평가 게이트 이음매 e2e (실 파이프라인이 쓴 행 == 게이트가 읽는 행)

## 왜 (회고에서 발견)

스펙 372 게이트의 존재 이유는 **"평가한 것 == 배포한 것"**이다. 그런데 그 이음매의 양 절반만
따로 초록이었다:

- **verify_372**: 게이트가 `EvalRun` 행을 읽어 판정 — 그 행을 **SQL로 직접 심음**(게이트가 읽는
  형태를 테스트가 스스로 만듦 = 순환 검증).
- **verify_240**: **실제** 평가가 `agent_version`·`status=ok`를 기록 — 하지만 항상 **활성 버전**만
  (먼저 activate 후 평가).

**한 번도 실행되지 않는 시나리오** = 게이트의 실 UI 흐름 그 자체: *미오픈 스크래치 v2를
`body.agent_version`으로 실제 지정 평가 → 그 실제 행을 게이트가 읽어 첫 오픈*. 이 이음매가
어긋나면(지정 평가가 `active_version`=v1을 태깅하거나 점수 스케일이 0..100로 저장되면) 사용자는
스크래치를 아무리 평가해도 **영원히 못 여는데**, 240·372는 각자 초록이라 못 잡는다. 이는 반복해
밟은 실수 축이다(learning 127 fake-mirrors-real·143 mock-degenerate·359 two-mechanisms·369
explicit-serializer-drops).

## 설계

**테스트 하나** — 새 코드/스키마 변경 없음(이음매는 코드상 이미 정합, 검증만 부재).
`tests/verify_373_eval_gate_e2e.py`(실서버 통합 rung, SQL 시드 없음):

- verify_372의 인증·게이트 설정·정리 + verify_240의 실 `/eval/datasets/{id}/runs` 지정 실행·폴링을 합침.
- 케이스 `no_error` → mock-llm에서 결정적 `status=ok`·`score=1.0`(결정적 통과 점수 불필요하게
  `min_score=0`으로 게이트 설정).

## 완료 조건 (수치)

- **D1** 실 지정 평가가 스크래치 버전으로 태깅(active 아님)·`status=ok`·`score∈[0,1]`(스케일 핀).
- **D2** 게이트 on(runs=1·score=0): 실적 0 스크래치 오픈 **400** → 실 ok 런 1건 후 같은 요청 **200**
  (SQL 시드 아닌 **실 행**을 게이트가 읽음).
- **D3** 버전별 귀속: 실적 있는 v2는 열렸어도, 실적 0인 다음 스크래치 v3는 여전히 **400**(any-run 아님).

## 검증 결과 (2026-07-16 — done, verify_373 ALL PASS)

- **D1** 실 런 `agent_version==v2`(활성 v1 아님)·status=ok·score=1.0∈[0,1] 실측.
- **D2** 실적 0→400·실 ok 런 1건 후→200(실 파이프라인이 쓴 행으로 오픈).
- **D3** 다음 스크래치 v3(실적 0)→400.
- run_suite가 `http` 카테고리로 자동 분류(verify_372와 동일 tier — `make test-all`/`run_suite http`).
  기본 그물엔 상태 오염 취약으로 미포함이나 고아 아님(별도 등록 불요).

## OUT

- 결정적 **통과 점수**로 min_score 임계까지 실측 — mock-llm은 semantic 통과가 비결정적(learning 366),
  score 스케일 핀(D1 `∈[0,1]`)으로 충분. 실 점수 임계는 실 judge 소관(스펙 139).

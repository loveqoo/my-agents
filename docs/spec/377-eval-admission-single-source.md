# 377 — eval 실행 admission 판정 단일 출처 (캠페인 374 Tier 1-3)

## 왜

codex 리뷰 P1(그룹 C): eval 실행 승인 판정이 두 경로에 복제됨 — 수동(`_assert_run_admission`)은
빈 문제집·running 중복을 raise(400/409)로, 자동회귀(`trigger_auto_regression`)는 같은 판정을
인라인으로 두고 조용히 스킵. 한쪽 게이트 규칙이 바뀌면 다른 경로가 드리프트(실모델 비용 사고 축).

## 무엇

**판정은 공유·반응은 각자** — 실패 모드가 다르므로(수동=raise, 자동=스킵) 판정만 반환값으로 뽑는다:

- `_admission_check(session, dataset_id) -> (n_cases, reason)` — 빈 문제집("empty")·running 중복("running")
  게이트 단일 출처. reason은 수동이 HTTP 400/409로, 자동이 `continue`로 각자 반응.
- 경로 고유 게이트는 **제외**(의도된 비대칭): `_active_jobs` 락은 수동만, 버전 dedupe는 자동만.
- 동작 불변 — 게이트 순서·상태코드·스킵 조건 그대로. 순수 추출.

### 덤 — 되살린 verify_241 (drift 교정)

verify_241은 자동회귀 admission의 유일 검증인데 `status=="draft"`(370에서 소멸한 스키마)를 써 활성화
자체가 안 돼 죽어 있었다(verify_240과 같은 드리프트) → 이 변경의 자동 경로가 미검증이었다.
`everOpened==False` 스크래치 조회로 교정(`_activate_scratch`) → **되살린 테스트가 이 변경의 자동 경로를
실측 검증**(learning 366). R4/R5는 제거된 `/revert`(370에서 activate로 대체)라 graceful skip — 범위 밖 잔여.

## 완료 조건 (동작 불변)

- 두 경로가 `_admission_check` 하나를 호출 · ruff 통과.
- make test SUITE_OK · e2e 39/39 · **verify_241 OK(자동 경로)** · verify_372/373 ALL PASS(수동·게이트 경로).

## 검증 결과 (2026-07-16 — done)

전부 초록: SUITE_OK·e2e 39/39·verify_241 R1/R2a/R2b/R2c/R3(자동 런 생성·v2 박제·완주)·
verify_372·373. 수동/자동 admission이 한 판정으로 수렴, 양 경로 실측.

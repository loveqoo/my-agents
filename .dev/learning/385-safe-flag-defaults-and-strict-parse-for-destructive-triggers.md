# 385 — 파괴적 트리거의 안전 플래그: 기본값도 파싱도 위험쪽으로 기울면 안 된다

## 맥락

묶음 A(안전 계약 버그) 조사 → 두 건 중 하나만 진짜였다. **배치 트리거**(`POST /admin/batch/{job}/run`)가
dry_run을 `Query(False)`로만 읽었다 — 배치 잡은 전부 파괴적 삭제 잡(session/checkpoint/token/approval/
history/memory/user, delete-all 가드)인데 (1) body로 보낸 `{"dry_run": true}`는 **선언조차 안 돼 조용히
무시**되고 (2) 기본값이 **위험쪽(false=진짜 실행)**. 흔한 클라이언트 실수가 파괴로 직행. 스펙 383으로
경화: dry_run을 body에서도 읽고, 기본값을 안전쪽(dry-run)으로, 정밀도 body > query > true. codex 적대
리뷰가 P1 하나 추가로 짚음 → body를 StrictBool로. verify_383 10/10.

두 번째 건(verify_233 "위임 갭")은 **오경보**였다 — 단독 실행하면 통과(VERIFY233_OK). test-all 상태
오염이 만든 가짜 실패였고(회고 383 패턴 재현), 격리 사유만 정정.

## 교훈

- **안전 플래그는 기본값도 파싱도 안전쪽으로 기울여야 — 위험쪽 기본은 "설정한 척"이다.** 파괴적 잡의
  dry_run이 `Query(False)`면 "플래그 없음 = 진짜 삭제"다. 안전 플래그의 안전값은 **명시가 아니라 기본**
  이어야 한다(learning 037 "파괴적 노브 바닥"의 계약판). 진짜 실행은 명시적 opt-in(`dry_run=false`)을
  요구하라. [[gate-on-intent-value-not-mutable-baseline]]와 같은 결: 위험은 명시 의도로만.
- **조용한 무시는 파괴로 떨어진다 — 안 읽는 소스로 온 안전 플래그.** FastAPI가 body를 선언 안 하면
  `{"dry_run": true}`는 422도 아니고 조용히 무시→기본값. 클라이언트가 "안전하게 불렀다"고 믿는데 진짜
  실행. **자연스러운 클라이언트 사용(JSON body)을 계약이 존중**하게 하라(body>query>안전기본).
- **파괴적 플래그는 strict 파싱 — 강제변환은 모호값을 조용히 위험쪽으로 바꾼다(codex P1).** Pydantic
  기본 bool은 `"off"·0·"no"·"false"`를 전부 `False`로 coerce → body `{"dry_run":"off"}`가 진짜 실행.
  안전 플래그에서 이건 "모호한 입력을 위험쪽으로 해석"이다. `StrictBool`로 진짜 JSON boolean만 받고
  나머지는 422로 거부. (query는 원래 문자열 관례라 lenient 유지 — 소스별 타입 정책 분리.)
- **"실 안전버그" 묶음도 여집합 검증하면 절반이 오경보다.** 묶음 A 2건 중 233은 [[verify-premise-before-designing]]
  대로 실물 실행하니 통과했다(전제 거짓). "격리 = 제품결함 후보"라는 옛 사유가 조사 없이 붙어 있었다.
  묶음으로 착수해도 **각 건을 실물로 판정**하라 — 오경보는 코드가 아니라 격리 사유를 고친다(정직화).
- **파괴 경로 변경은 소비자 실측이 안전성 근거.** 기본값 뒤집기가 관리자 UI를 깰까? → `triggerBatchJob`이
  **항상 query 명시 전달**(api.ts:207)임을 확인하고서야 안전 판정. cron은 `run_job` 직접 호출이라 무관.
  [[ui-verification-must-be-functional]] — 소비자가 실제로 어떻게 부르는지 보고 계약을 바꾼다.

[[cap-the-raw-source-not-the-buffer]] [[adversarial-review-before-destructive-ship]]

[safe-flag-default-not-explicit, silent-ignore-falls-to-danger, strict-parse-destructive-flags,
bundle-still-needs-per-item-verdict, consumer-measurement-justifies-contract-change]

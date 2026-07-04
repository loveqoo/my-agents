# 147 — 감사 커맨드화 + 상시 루프 (검증 아크 캡스톤) (스펙 169)

축1·2·3 감사(165·166·167·168)를 **한 명령**으로 묶어 "지속적 발견"을 상시화.

## 한 것
- `tests/browser/audit-all.mjs`: 기계 harness 3종(screens·overlays·scenario) 순차 실행 → 종합
  스코어카드 + 종합 종료코드. **프리플라이트**(vite·api 도달 확인, down이면 중단). 카피 축은 에이전트
  구동이라 말미 안내로.
- `.claude/skills/ui-audit/SKILL.md`: `/ui-audit`로 실행 + 트리아지 규율(도구 좁힘·육안 확정·과잉억제
  금지·soft flag 코드추적·clean pass도 정직) 문서화. 테스트 인프라 함정(learning 142) 링크.

## 배운 것
- **감사의 가치는 재실행성에서 복리가 된다**. 한 번 돌린 감사는 스냅샷, 한 명령으로 언제든 도는 감사는
  회귀 게이트다. 축3 카피 수정 후 audit-all로 UI 회귀 0을 즉시 확인했듯, **묶는 순간 서로의 게이트**가 됨.
- **프리플라이트가 정직성의 관문**: 서버 down인데 감사가 빈 화면을 훑으면 "0 FAIL"이 거짓 초록(스펙 158
  계열). 도달 확인 실패 시 exit 2로 중단 — 감사 자신이 "실패≠통과"를 지킨다.
- **수치 판정이 서면 자율이 열린다**([[numeric-verification-unlocks-autonomy]]): 종합 종료코드가 있어
  Ralph/cron에 얹으면 사람 없이 상시 감사(FAIL 시만 개입). 사용자 원 목표 "지속적 발견"의 인프라 완성.
- **기계화 가능/불가의 경계를 정직히**: 오버플로·시나리오는 스크립트, 문구·평이함은 판단형이라 에이전트.
  억지로 다 기계화하지 않고 커맨드에 "카피는 별도" 명시 — 경계를 숨기지 않는 게 정직한 도구.
- **스킬로 절차까지 포장**: 명령만이 아니라 트리아지 규율(과잉억제 금지·육안 페어·soft flag 코드추적)을
  스킬에 담아, 다음에 누가 돌려도 관대해지지 않게. 커맨드=실행, 스킬=실행+판단 규율.

## 검증
audit-all.mjs 실행: 3 harness 전부 구동(screens 42·overlays 14·scenario 7)·종합 exit 0·프리플라이트
서버 up 확인. 종합 스코어카드 정합.

## OUT
- 카피 축 기계화(LLM judge). CI 배선·자율 cron 실제 등록. 병렬 실행(현재 순차 3로그인). 감사 커버리지
  확장(세로 잘림·중첩 드로어).

[audit-command,rerunnable-compounds,preflight-is-honesty-gate,numeric-unlocks-autonomy,honest-mechanization-boundary,skill-packages-discipline]

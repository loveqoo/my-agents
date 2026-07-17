# 392 — A2A 세션 연속성(388 P1): 발명이 아니라 배선 — 리팩터 캠페인의 배당

## 맥락

A2A 서빙에 contextId 세션 연속성+영속을 붙이는 P1. 겁먹을 크기였는데 실제로는 **기존 부품의
배선**으로 끝났다: `_load_context(own=)`(068 소유권)·`_resolve_session`(추측불가 id·에이전트
스코프·오라클 접기)·`_load_session_conversation`(289 재구성)·`_persist`(049 lazy-create·068
소유자 스탬프)·`_window`. 새로 쓴 로직은 contextId 추출·channel 표기·히스토리 주입 조건뿐.
verify_388 10/10·suite 51/51·codex "보안 결함 0".

## 교훈

- **캠페인 리팩터(374)의 배당이 여기서 났다.** chat.py가 신이었으면 서빙에 세션을 붙이는 건
  복붙 아니면 chat() 침습이었다. chat_context/chat_history/chat_persist로 갈라져 있어서 서빙이
  같은 부품을 **import 한 줄**로 재사용 — 소유권·lazy-create·오라클 접기 같은 어려운 보안 성질을
  공짜로 상속했다(codex가 무결 판정한 항목 전부가 재사용 부품의 성질).
- **경계 확장은 "새 보안 설계"보다 "기존 소유권 메커니즘에 태우기"가 정답일 때가 많다.**
  userId 바인딩을 새 검사로 짜지 않고 `_resolve_session`의 own 파라미터(068)에 그대로 태웠다 —
  불일치=새 세션 접기(404/403 구분 없음)라는 열거-오라클 방어까지 자동 상속.
- **스코프 계약을 넓히면 "정확일치" 단언이 형제 테스트에서 깨진다.** 저장 스코프에 run 축을
  추가하자 verify_387의 `s == {"user_id": ...}` 정확일치가 실패 — 계약 진화를 견디려면 단언은
  "관심 키의 값 고정"으로(정확일치는 필드 추가마다 유지보수 폭탄). 시그니처를 바꿀 땐 monkeypatch
  하는 테스트(verify_061)도 소비자다 — grep 범위에 tests/의 패치 지점 포함(codex가 적중).
- **외부 프로토콜 필드는 추출 즉시 타입 가드**(contextId str 검사) — 387 codex P1(비-dict
  metadata)과 같은 결을 처음부터 적용해 이번엔 지적 0.

- **마이그레이션 downgrade도 검증 대상이다** — 새 리비전의 downgrade INSERT가 감사 컬럼
  (created_by NOT NULL, 스펙 343)을 빠뜨려 verify_343 왕복에서 터졌다. 데이터 시드/복원 SQL은
  스키마의 NOT NULL 전수(특히 감사 컬럼)를 채워야 하고, 그걸 잡는 그물이 정확히 343 왕복이다.

[refactor-dividend-at-boundary-extension, ride-existing-ownership-not-new-checks,
assert-keys-not-exact-dict, monkeypatch-tests-are-consumers-too]

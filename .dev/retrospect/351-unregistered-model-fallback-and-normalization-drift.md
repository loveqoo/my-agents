# 351 — 스펙 428 회고: 미등록 모델 폴백 + 정규화 드리프트

## 무엇을 했나

저장 config가 미등록 모델을 가리키면 조용히 기본 폴백하던 걸(learning 092 위반) 정리. 증상("거절vs경고")이
아니라 **깨진 상태를 만드는 두 입구**를 봉함: P1① rename 참조 가드(삭제는 막으면서 rename은 안 막던
형제 구멍), P1② 에이전트 저장 시 미등록 모델명 거절. P2③ resolve도 선언-broken이면 400.

## 배운 것(전이 가능)

### 1. 검증에서 정규화하면 저장·런타임도 같은 정규화를 해야 한다(guard/runtime 드리프트)

내 첫 구현은 `assert_model_registered`가 `.strip()`해서 조회했는데 **저장·런타임은 strip 안 했다**.
결과: `" mock-llm "`은 검증 통과 후 저장 → 런타임이 strip 없이 조회해 400(저장 성공 후 실행 실패),
`"   "`는 검증에선 unset이지만 런타임엔 non-empty라 400. **검증 한 곳만 정규화하면 "저장은 됐는데
못 도는" 유령 상태가 생긴다.** 고침=저장값을 canonical(strip)로 만들고(단일 형태) 런타임도 strip(방어).
[[cap-the-raw-source-not-the-buffer]]의 친척 — "막은 척"이 아니라 **작동·저장하는 그 형태를 검사·정규화**.

### 2. 게이트를 새로 세우면 형제 입구를 grep으로 전수하라

`assert_model_registered`를 create/update엔 붙였지만 **clone은 빠뜨렸다**(원본 config 복사→broken 재생산).
[[installed-guard-isnt-covering-guard]] 그대로 — 가드 설치≠전 입구 덮음. 에이전트-생성 입구(create·
update·clone·remote register)를 grep으로 열거해야 했다([[installed-guard-isnt-covering-guard]]).

### 3. 내 verify는 happy-path를 확인했고, codex가 여집합을 잡았다

verify_428 8/8은 초록이었지만 공백·clone·이름재사용은 **내가 상상한 실패만** 담았다(초록이 결함을
굳힐 뻔). 인가/경계 변경이라 [[use-codex-for-adversarial-verification]]로 여집합을 시켰더니 실버그 2건
+ 정직한 경계 2건이 나왔다. **적대 발견은 그 자리서 테스트로 고정**([[verification-ladder-three-rungs]]) —
공백·clone 케이스를 verify에 승격.

### 4. 여집합 성공이 늘 코드결함은 아니다(정직한 경계)

codex의 "이름 재사용 identity drift"(X→Y 개명 후 X 재등록→옛 버전 롤백이 다른 정체성 실행)는
근인이 **이름 기반 참조**(learning 042, FK 없는 의도적 설계)라 닫으려면 ID 참조 대수술. 안전 위반이나
드문 관리자 조작이고 대안이 대규모라 **경계로 정직화**([[complement-attack-can-be-honest-boundary]]) —
내 스펙의 "롤백→400 안전망" 주장이 이 경우 거짓임을 명시 교정. 메모리 CRUD 폴백도 별개 경로라 OUT.

### 5. 불변식 우선(증상 아닌 원인)

"거절vs경고"는 깨진 상태를 *다루는* 메커니즘. P1이 **깨진 상태를 못 만들게**(쓰기 시점 차단) 하니
P2③은 직접-DB 잔여만 잡는 안전망으로 줄었다([[find-invariant-before-mechanism]]). 착수 전 감사
(라이브29·버전21 전부 0 broken)로 P2 loud-reject가 기존을 안 깬다고 먼저 확인.

## 흠집

정규화 드리프트를 내가 짜면서 못 봤다 — "검증에서 strip"을 적을 때 "그럼 저장·런타임도?"를 같은
호흡에 물었어야 했다. 게이트/정규화는 **읽는 모든 지점**을 한 번에 훑는 습관으로.

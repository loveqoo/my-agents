# 110 — "각 고리 증명" ≠ "체인 증명" / E2E는 실제 principal(인증 컨텍스트)을 재현해야

## 맥락

능력 브로커 전 체인(UI config→build_broker→orchestrate delegate→broker.invoke→trace)의 각 고리는
따로 검증돼 있었다(106 왕복·100–105 소비·102 그래프 레벨). 스펙 110은 이걸 **채팅 엔드포인트로 한 번에
이어** 돌린 첫 실측(백로그 "106 잔여").

## 배운 것

### 1. 각 링크를 개별 증명해도 체인 전체는 미증명 — 이음매는 관통해야 보인다

링크 A·B·C를 각각 초록으로 만들어도 A→B→C를 **한 경로로 실행**하기 전엔 이음매(글루·컨텍스트 전달·
전제)가 미검증이다. 스펙 110에서 첫 E2E 실행이 곧바로 진짜 이음매를 드러냈다: **위임은 유저 세션에서만
되고 머신 토큰은 deny-by-default**다. 단위(102 select 순수함수)·그래프(102 build_graph) 검증엔
principal이 안 나와서 이 의존을 못 봤다 — 오직 **엔드포인트 관통**만이 "누가 호출했나(principal 타입)"를
경로에 넣는다. verification-ladder(learning: 통합 rung만이 요청간 글루를 잡음)의 브로커판.

### 2. E2E는 실제 인증 컨텍스트를 재현해야 한다 — 안 그러면 거짓 음성으로 오진

처음 E2E를 dev **머신 토큰**(Bearer)으로 짰더니 위임이 공집합(`delegated: <0자>`)이라 H1/H2가 FAIL.
"위임이 안 되나?"로 오진하기 직전, 원인은 코드 결함이 아니라 **인증 컨텍스트**였다: `build_broker`의
`rbac_allows`가 string principal(머신 토큰)을 전부 deny한다("능력 오케스트레이션은 유저 세션 대상",
deny-by-default 안전측). 즉 **인증 주체 타입이 계약의 일부** — 같은 요청이라도 principal이 다르면 결과가
다르다. E2E가 프로덕션과 다른 principal로 돌면 초록이든 빨강이든 **거짓 신호**다.

해결: FastAPI `app.dependency_overrides[current_principal] = lambda: <슈퍼유저 스텁>`으로 채팅
엔드포인트만 유저 세션으로 재현(다른 엔드포인트는 Bearer 유지). `is_superuser` 우회로 capability:rag
허용. 실 쿠키 로그인 없이 **실제 유저 세션 경로를 결정적으로** 재현하는 값싼 방법.

### 3. 시연은 결정적 테스트 + 시각 증거 두 겹으로

위임(delegate 노드)은 LLM과 독립이라 **mock-llm으로 결정적**으로 돈다(synthesize만 LLM). 그래서:
- **결정적 테스트**(verify_110): trace에 `broker_invoke:*` 존재 + 무위임 대조 → 반복 가능한 회귀 가드.
- **인스펙터 스샷**: 사용자가 "실제로 일 넘기는지"를 눈으로(LangGraph 경로에 delegate→broker_invoke).
둘 다 있어야 "증명"과 "납득"이 동시에 선다.

## 함정

- `broker.discover`는 **lexical 부분일치**(`q in "name id hook"`) — 문장 질의는 부분문자열이 아니라 발견
  실패. 테스트/데모 질의는 cap id의 부분문자열(예: 컬렉션명)로.
- 플레이그라운드 에이전트 선택기는 커스텀(antd Select 아님) — 헤더 텍스트 클릭으로 목록 열고 이름 클릭.

## 적용

체인을 만들면 **관통 E2E를 한 번은** 돌려라(링크별 초록으로 대체 금지) — 이음매·전제는 거기서만 드러난다.
E2E는 **프로덕션과 같은 인증 컨텍스트**로(principal 타입이 결과를 가름); 다르면 dependency_overrides로
재현하되 실제 경로와 같게. LLM 무관 경로는 mock으로 결정화해 회귀 가드 + 시각 증거를 함께. 관련:
[[verification-ladder-three-rungs]], [[106-config-roundtrip-completeness-and-namespace-as-authoring-layer]].

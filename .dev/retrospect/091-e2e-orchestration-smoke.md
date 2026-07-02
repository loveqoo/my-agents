# 091 — 엔드투엔드 오케스트레이션 시연 (스펙 110)

## 무엇을 / 왜

능력 브로커(100–105)와 UI(106–109)를 다 만들었지만 **채팅 1턴이 전 체인을 관통하는지**는 미실측
(백로그 "106 잔여"). 사용자 선택: "조율형이 실제로 일 넘기는지 확인". 각 고리는 따로 증명됐다
(UI 왕복 106·config→broker 100–105·그래프 레벨 102). 이 작업은 그걸 **한 번에 이어** 돌린 첫 실측.

## 한 일

- **결정적 E2E 테스트**(`tests/verify_110_e2e_orchestrate.py`): UI 저장 경로와 동일 config(impl=
  orchestrate, capabilities=[rag:<col>])로 조율형 생성 → **채팅 엔드포인트** 1턴 → trace에
  `broker_invoke:rag:*` 노드 존재 assert. 무위임 대조(능력 0개→노드 부재)로 위양성 배제. mock-llm.
- **브라우저 시연**(`tests/browser/shot-orchestrate-110.mjs`): 플레이그라운드에서 조율형으로 대화 →
  인스펙터 LangGraph 경로에 `delegate(1093자)`→`broker_invoke:rag:docs_kb` 노드 뜨는 스샷(사용자 눈).

## 잘된 것

- **"각 고리 증명 ≠ 체인 증명"을 실측이 잡음**(learning 110): 첫 실행이 곧바로 진짜 이음매를 드러냄
  — 위임은 **유저 세션에서만** 되고 머신 토큰(string principal)은 deny-by-default("능력 오케스트레이션
  비대상", broker.py rbac_allows). 단위/그래프 검증(102)에선 principal 타입이 안 보였다.
- **`dependency_overrides(current_principal)`로 슈퍼유저 경로를 결정적 재현**: 실 쿠키 없이 채팅
  엔드포인트를 유저 세션으로 돌려 rag 허용. 다른 엔드포인트는 Bearer 유지(오버라이드는 chat만).
- **결정적 + 시각 두 겹**: 반복 가능한 테스트(회귀 가드) + 인스펙터 스샷(사용자 확인). 위임은 LLM과
  독립(delegate 노드)이라 mock-llm으로 결정성 확보.

## 배운 것 / 함정

- **머신 토큰으론 위임이 절대 안 됨**(설계) — E2E를 dev Bearer로 짜면 위임 공집합이 나와 "안 된다"고
  **오진**할 뻔(처음 H1/H2 FAIL이 그거였다). E2E는 **실제 principal**을 재현해야 한다(learning 110).
- **broker.discover는 lexical 부분일치** — 질의가 cap의 `name id hook` 부분문자열이어야 발견. 테스트
  질의를 컬렉션명(cap id 부분문자열)으로 줘 확정 발견.
- 플레이그라운드 에이전트 선택기는 커스텀(antd Select 아님) — 헤더("Doc Translator") 클릭으로 목록
  열고 이름 클릭(override 109 함정 재확인).

## 검증 안 함(사유)

- 다중 위임·랭킹 전략(102 그래프 레벨서 검증). 여기선 단일 위임 1턴 관통만.
- 라이브 모델(qwen) 경로 — mock-llm으로 위임 결정성 충분(synthesize 품질은 이 스펙 범위 밖).

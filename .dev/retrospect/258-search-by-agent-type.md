# 258 — 종류 검색: 검색 축은 사용자 어휘(라벨)로, 내부 키(impl)로가 아니라 (스펙 283)

## 맥락
"에이전트 메뉴에서 '에이전트 종류'로 검색할 수 있어야" — 기존 검색은 이름·설명·모델·소스만.

## 발견과 교훈
- 검색 축에 넣을 값은 내부 키(impl='pipeline')가 아니라 **사용자가 화면에서 배운 어휘**(노드형) —
  `typeLabel(impl)`을 AGENT_TYPES 옆 단일 출처로 export(orchestrate 계열은 isOrchestratorImpl로
  '조율형'에 접음: AGENT_TYPES에 없는 orchestrate_ranked도 포괄). 어휘 매핑이 흩어지면 검색·표시가
  어긋난다(274 ModelFields와 같은 단일 출처 규율).
- placeholder("이름·종류·모델 검색")도 같은 턴에 — 검색 축을 늘리고 placeholder를 안 고치면 기능이
  있어도 발견이 안 된다(어포던스 라벨은 상태 따라, 257 ③의 검색판).

## 조치
typeLabel export + 필터 배열 추가 + placeholder. verify-283 7/7 + tsc 0.

# 283 — 에이전트 목록 검색에 '에이전트 종류' 축 추가

> 사용자 지시: "에이전트 메뉴에서 '에이전트 종류'로 검색할 수 있어야 합니다."
> 현재 검색(AgentsView:275)은 이름·설명·모델·소스만 매칭 — 종류(직접 응답/조율형/산출물형/노드형)
> 미포함.

## 변경
- `typeLabel(impl)` 헬퍼를 AGENT_TYPES 옆(AgentForm)에 단일 출처로 export — orchestrate 계열은
  isOrchestratorImpl로 접어 '조율형'(AGENT_TYPES에 없는 orchestrate_ranked 포함).
- 검색 필터 배열에 `typeLabel(a.impl)` 추가, placeholder "이름·종류·모델 검색"으로 갱신.

## 완료 조건
1. '노드형' 검색 → 노드형 에이전트만(직접형 미노출), '조율형'·'직접' 동작(e2e).
2. 기존 이름 검색 무회귀. tsc 0.

### 검증 결과
- **verify-283-type-search.mjs 7/7 ALL GREEN** — '노드형'→노드형만·'조율형'→조율형만·이름 검색
  무회귀·placeholder 갱신. tsc 0. codex 스킵(검색 축 추가, 표시/저장 무변경).

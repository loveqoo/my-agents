# 202 — 플랜 에이전트 도구-인지 업그레이드 (노코드 계약 "설정=동작" 복원)

## 배경 (사용자 문제 제기, 2026-07-07)
"노코드 에이전트(공통 클래스 구현)는 도구 연결이 되면 동작해야 한다. 직접 응답은 됐는데 plan_execute는
왜 안 됐나? 공통 클래스가 잘못 설계됐나? 도구 있는 플랜 에이전트는 플래닝하면서 도구를 더 영리하게
써야 하지 않나?"

진단(201 후속2에서 이어짐): 계약(AgentBuildContext)은 **이미 도구를 주입**한다(`ctx.tools`,
chat.py가 config.mcps→빌드→주입). 직접 응답(DefaultUiAgent)은 이를 ReAct로 소비하지만
**PlanExecuteAgent 예제가 주입받은 ctx.tools를 안 읽었다** — 계약 설계 결함이 아니라 (a) 예제
구현의 미완 + (b) "주입 설정 소비"를 검사하는 적합성 항목 부재.

## 사용자 결정
- 진행 승인. 단 **"무조건 써야"가 아니라 "써야 할 필요가 있다면 쓸 수 있어야"** — 강제 호출이 아닌
  **가용성**(도구가 그래프에 배선돼 모델이 필요 시 호출 가능) 계약.

## 설계

### A. PlanExecuteAgent 도구-인지 (packages/agent/examples/plan_execute.py)
- **plan(결정적 유지)**: ctx.tools가 있으면 계획에 도구 활용 단계를 포함 —
  "1) 핵심 파악 2) 필요하면 도구(이름들)로 사실 확인 3) 근거 들어 답". 모델 호출 없음(스펙 086 H3
  계약 "plan<execute 실측" 보존, H2 '핵심·근거' 문구 보존).
- **execute**: ctx.tools 있으면 `model.bind_tools(tools)` + 시스템 프롬프트에 도구 목록("필요할 때만
  호출") 명시.
- **tools 노드(신설)**: `ToolNode(ctx.tools)` + 조건 분기(execute 응답에 tool_calls 있으면 tools→
  execute 재진입, 없으면 END) — create_agent와 같은 표준 루프. **도구 없으면 기존 2노드 그대로**
  (무회귀). 루프 상한은 langgraph recursion limit.
- describe/HIL 표기는 유지(supports_hil=False — web-fetch류 무승인 도구 전제, 승인 게이트 도구는
  직접형/조율형 경로 권장. 경계에 명시).

### B. 적합성 검사에 "도구 가용성" 추가 (tests/verify_089_conformance.py)
- T1: ctx.tools 주입 시 컴파일된 그래프에 tools 노드 존재(가용성 — 강제 사용 아님).
- T2: ctx.tools 없으면 tools 노드 없음(2노드 무회귀).
- 앞으로 커스텀 impl이 도구를 버리면 이 rung에서 걸린다(같은 함정 재발 방지).

## 검증
1. 단위: 089 확장 T1/T2 + 기존 C/G/R 전부 무회귀. 086(plan 결정적·핵심/근거 문구) 무회귀.
2. e2e(사용자 재현 경로): plan-execute-demo에 web-fetch 연결(사용자가 했던 그대로) → 플그 질문 →
   plan 노드에 도구 언급 + execute가 wiki_search/wiki_page 실호출(인스펙터) + 답변에 실데이터.
   검증 후 **연결 유지**(사용자 원의도).

## RBAC 경계
- 비트리거: 새 권한/입구 0. ctx.tools는 기존 주입 경로(HIL/트레이스 래핑 포함) 그대로 소비.

## 경계
- plan을 모델 기반 계획으로 승격(진짜 동적 플래닝)은 OUT — 086의 "plan 결정적" 계약 변경이 필요해
  별도 스펙. 지금은 "계획에 도구 반영+실행에서 필요 시 호출"까지.
- 승인 게이트 도구를 이 impl에 연결하는 경우의 HIL 재개는 OUT(supports_hil=False 유지).

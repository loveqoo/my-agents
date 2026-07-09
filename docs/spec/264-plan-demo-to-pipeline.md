# 264 — 플랜 실행 데모를 노드형으로 전환 + 실모델 동작 테스트 (259-263 도그푸딩)

## 배경
사용자 요청(2026-07-09): "플랜 실행 데모를 노드형으로 바꾸고 동작을 테스트해보라." — 하드코딩 flow
(`plan_execute` impl, examples/plan_execute.py)로 돌던 `plan-execute-demo`(v5, 실모델 qwen3.6-35b,
페르소나 methodical-researcher, 도구 web-fetch, 기억 단기)를 노코드 노드형으로 재구성해 실전 검증.

## 전환 설계 (등가 + 승격)
- **노드1 "계획"**(carry·text·도구 없음): 모델이 3단계 이내 계획 수립. 원 plan 노드는 *하드코딩 문자열*
  (모델 호출 없음)이었는데, 노드형에선 **진짜 계획 수립으로 승격**.
- **노드2 "실행"**(carry — 원 질문+계획 둘 다 봐야 하므로): methodical-researcher 페르소나 본문 내장
  (결정 #1 방식) + "위 계획에 따라 답하라" + 도구 wiki_search·wiki_page.
- config: impl=pipeline, mcps=['web-fetch'](노드 도구 합집합), memories·persona 보존(206). v5→v6
  (버전 시스템 = 가역, revert 가능).

## 결과 (실모델 검증, ALL GREEN)
`tests/browser/convert-plan-demo-pipeline.mjs`(전환+chat SSE) + `shot-plan-demo-playground.mjs`(UI):
- 전환: v5→v6 활성, impl=pipeline, nodes 2 (PUT→draft→activate, admin 세션).
- **실모델 실행**: qwen3.6-35b로 4.7~8초, 트레이스 `__start__ → 계획 → 실행 → __end__`. 계획 노드가
  실제 3단계 계획을 생성하고, 실행 노드가 페르소나 스타일(한 줄 선답·인용)로 한 문단 답변.
- 인스펙터: 노드별 실측 시간(+2.4s/+2.3s)·각 노드 출력 프리뷰·실토큰(277/245). 도구 미호출 진단
  안내(125)도 파이프라인과 그대로 합작동.
- wiki 도구는 이 턴에선 미발화(모델 재량 — 강제 아님, 202 결정 그대로).

## 관찰 (정직 기록 — 원 데모와의 행동 차이)
**중간 노드 출력이 응답에 섞인다**: 원 plan 노드는 결정적(무토큰)이라 답만 스트림됐는데, 노드형 계획
노드는 모델 호출이라 계획 텍스트(1.2.3.)가 최종 답 앞에 그대로 보인다. 투명성으로 볼 수도 있으나 최종
사용자 응답으로는 잡음일 수 있음 → **"마지막 노드만 응답으로(중간 노드는 인스펙터만)" 옵션**을 백로그에
(노드형 후속 다듬기 축).

## 가역
v5(plan_execute impl) 보존 — 되돌리려면 revert v5.

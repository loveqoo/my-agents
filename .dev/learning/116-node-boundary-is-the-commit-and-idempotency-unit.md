# 116 — StateGraph에서 노드 경계 = 커밋 단위 = 재개 멱등 단위

스펙 116(다중 위임 재개 시 선행 결과 보존)에서 배운 것.

## 1. 노드는 완주할 때만 커밋한다 — interrupt 이전 값은 노드 경계로만 남긴다

LangGraph StateGraph 노드의 state update는 노드가 **return할 때만** 커밋된다. 노드 안에서 `interrupt()`
하면 그 실행의 (부분) 반환은 통째로 버려지고, 재개 시 노드가 **처음부터 재실행**된다. 그래서 한 노드
안의 loop로 N개 작업을 돌리면, 뒤 작업의 interrupt가 앞 작업의 결과 커밋을 되돌린다(앞 작업 재실행).
"재개돼도 유지돼야 하는 것"은 **interrupt하는 노드보다 앞선(완주하는) 노드에 커밋**하거나, 작업을
쪼개 **작업 하나 = 노드 실행 하나**로 만들어야 한다.

## 2. 재개 멱등 = 각 작업 단위를 체크포인트 경계로 (self-loop)

노드를 자기 자신으로 되돌리는 self-loop로 매 반복을 노드 경계로 만들면, 완료된 단위는 state(리듀서
누적)에 커밋돼 **재개 시 재실행되지 않는다**. 부수효과·비용 있는 작업(외부 호출·읽기)을 순차로 돌리며
중간에 멈출 수 있으면 이 패턴이 정석. `pending`(대기)·`done`(operator.add로 누적) 두 필드로 진행을
표현하고, conditional edge로 `pending` 남으면 자기 루프·비면 다음 단계. interrupt하는 단위 자신만
재실행되며 부수효과는 interrupt-before-sideeffect로 1회 유지.

## 3. interrupt 이전에 확정 안 된 "선택"은 재개 시 재계산돼 뒤바뀔 수 있다

interrupt 이전에 커밋되지 않은 결정(무엇을 할지 고르는 discover/select)이 재개 시 재실행되면, 그 사이
환경(카탈로그·정책·권한)이 바뀌어 **선택이 달라진다** — 사용자가 승인한 A 대신 B가 실행되거나, A가
사라져 승인만 남고 실행이 누락된다. 방어: **선택을 부수효과/interrupt 노드보다 앞선 노드에서 확정·커밋**
(여기선 `plan` 노드가 discover/select→pending을 delegate 이전에 커밋). 재개는 interrupt된 노드에서
이어지므로 앞 노드는 재실행되지 않아 선택이 고정된다. "결정하는 코드"와 "부수효과 내는 코드"를 노드로
가르는 게 핵심 — 결정이 부수효과 노드에 섞이면 재개마다 재결정된다.

## 4. fail-closed(안전)와 완전성은 다르다 — 후자만 OUT일 수 있다

다중 승인 미지원(2번째 gated cap이 승인 row로 안 뜸=고아)은 **완전성** 결함이지 **안전** 결함이 아니다.
interrupt-before-sideeffect가 미승인 부수효과 실행을 막으므로(fail-closed) 무단 실행은 0. 경계를 OUT로
문서화할 때 "안전은 유지(무단 실행 없음), 완전성만 미지원"을 **분리 검증**한다(verify H5가 두 번째
gated의 부수효과 0을 실측). 안전 불변식만 지켜지면 완전성 갭은 정직하게 후속으로 미룰 수 있다.

## 적용
- 재개 도중 유지할 값은 interrupt하는 노드가 아니라 **앞선 완주 노드**에 커밋하거나 self-loop로 쪼갠다.
- 순차·중단 가능 작업은 `pending`/`done`(리듀서) + conditional self-loop = 재개 멱등.
- "무엇을 할지" 선택은 부수효과/interrupt 노드보다 **앞 노드**에서 확정·커밋(재개 시 재결정 방지).
- 경계를 OUT로 낼 땐 안전(fail-closed)과 완전성을 갈라, 안전 불변식을 별도 테스트로 못박는다.

관련: [[unforgeable-boundary-needs-both-sides-clean]] · [[verification-ladder-three-rungs]] ·
[[installed-guard-isnt-covering-guard]]

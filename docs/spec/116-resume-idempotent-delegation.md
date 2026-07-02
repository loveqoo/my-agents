# 116 — 재개 시 선행 위임 결과 보존 (멱등 재개, codex 102 [P1] 봉합)

## 배경 / 왜

스펙 102 codex가 [P1] 경계로 남긴 것: 여러 cap을 순차 위임(delegate 노드가 loop로 invoke)하다 뒤쪽
승인-게이트 cap이 interrupt(스펙 101)하면 **LangGraph가 재개 시 delegate 노드를 처음부터 재실행**한다 →
앞선 read-only cap이 **재호출**된다(중복 읽기; 멱등이라 안전하나 관측상 중복·불필요 비용). 사용자 "1~4
루프"의 4번(마지막).

## 설계

### 각 cap = 자기 노드 실행 = 체크포인트 경계 (self-loop)

**핵심 제약**: StateGraph 노드는 **완주(return)할 때만** state update를 커밋한다. 노드 안에서 interrupt하면
그 노드의 (부분) 반환은 버려진다 → 노드 안 loop로 여러 cap을 돌리면 뒤 cap의 interrupt가 앞 cap의
결과 커밋을 통째로 되돌린다. 그래서 **위임을 `delegate` 자기 루프로 쪼갠다**: 매 실행이 `pending` 앞
하나만 invoke하고 결과를 `state.done`(operator.add 리듀서)에 커밋한 뒤 자기 자신으로 되돌아간다. 이제
**cap 하나 = 노드 실행 하나 = 체크포인트 경계**다. 뒤 cap이 interrupt해 delegate가 재실행돼도, 선행
cap은 이미 done에 커밋돼 **재호출되지 않는다**. interrupt하는 cap 자신만 재실행되나 부수효과는
interrupt-before-sideeffect로 정확히 1회(스펙 101).

### plan 노드 — 위임 대상을 invoke 이전에 확정·커밋 (codex 116 [P1])

discover/select를 delegate 안에 두면, **첫** cap이 interrupt할 때 아직 pending이 커밋 안 돼 재개 시
**재-discover**된다 → 그 사이 카탈로그/정책이 바뀌면 승인 대상이 뒤바뀐다(승인한 A 대신 B 실행, 혹은
A 소멸로 승인만 남고 실행 누락). 그래서 discover/select를 **부수효과·interrupt가 없는 별도 `plan`
노드**로 앞에 뺀다: `analyze→plan→delegate→cond(delegate|synthesize)`. plan은 항상 완주해 pending을
커밋하고, 재개는 interrupt된 delegate에서 이어지므로 plan은 재실행되지 않는다(pending 고정).

## 검증

- **실 그래프 + interrupt/resume**(MemorySaver 체크포인터): H1/H2 [READ, GATED] — 재개 후에도 READ
  invoke 정확히 1회(선행 read-only 재호출 0 = 스펙 116 핵심), GATED 부수효과 1회. H4 첫 cap이 gated여도
  재개 시 discover 1회(재-discover 0, [P1] 봉합). H5 다중 gated [GATED, GATED2] fail-closed — 첫 승인
  재개가 두 번째 gated에서 다시 interrupt, 미승인 부수효과 미실행. verify_100/101/102 무회귀(plan 노드
  추가로 U2·U4 골격 검증 갱신).
- **codex 적대(rung 3)**: 1차 [P1#1] 첫 cap 재-discover·[P1#2] 다중 gated resume 승인 고아·[P2] 커버리지
  → P1#1은 plan 노드로 봉합, 2차 재검증서 P0/P1 없음 확인. P1#2는 아래 OUT.

## 비목표 (OUT)

- **다중 gated cap의 순차 승인 표면화**(codex [P1#2]) — [GATED_A, GATED_B]에서 A 승인 재개가 self-loop로
  B의 interrupt에 도달하지만, 제품 승인 파이프라인(chat.py resume 경로)은 두 번째 interrupt를 **새 Approval
  row로 승격하지 않는다**(B 고아). **101/102의 다중 interrupt OUT** 경계 그대로다. 단 **안전은 유지** —
  B는 interrupt-before-sideeffect에서 멈춰 미승인 부수효과가 실행되지 않는다(fail-closed, verify H5 실측).
  안전(무단 실행 0)과 완전성(모든 승인 표면화)은 별개 — 후자는 후속(다단 승인 큐).
- 위임 결과의 영속 캐시(세션/스레드 간) — 여기 캐시는 **한 스레드의 재개** 범위(체크포인터 state)로 한정.

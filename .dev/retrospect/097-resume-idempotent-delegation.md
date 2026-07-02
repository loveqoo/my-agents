# 097 — 재개 시 선행 위임 결과 보존 (스펙 116)

## 무엇을

102 codex [P1] 봉합: 다중 순차 위임 중 뒤 gated cap이 interrupt하면 재개 시 delegate 노드가 처음부터
재실행돼 앞선 read-only cap이 재호출되던 것을, cap 하나씩 자기 노드 실행으로 소비해 재개 멱등화.
사용자 "1~4 루프"의 4번(마지막).

## 어떻게

- delegate self-loop: `pending`(대기)/`done`(operator.add 누적) 두 필드, conditional edge로 pending
  남으면 자기 루프·비면 synthesize. cap 하나 = 노드 실행 = 체크포인트 경계 → 완료 cap은 재개 시 재호출 0.
- codex 116 [P1] 봉합: discover/select를 invoke 이전 **plan 노드**로 분리 → 첫 cap interrupt에도 pending
  선(先)커밋으로 재-discover 방지(선택 뒤바뀜 차단).

## 잘된 것

- **근본 제약을 정확히 짚음**: "노드는 완주할 때만 커밋 → interrupt는 부분 반환 폐기"를 파악하고,
  해법을 노드 경계로 설계(learning 116 ①②). 부분 캐시를 노드 안에서 시도하는 오답을 피함.
- **codex가 두 번째 축을 잡음**: 1차 [P1#1] 첫 cap 재-discover(선택 뒤바뀜) — self-loop만으론 안 닫힘,
  plan 노드 분리로 봉합(116 ③). 자가검증이면 "read-only 중복만 잡으면 됐다"고 멈췄을 것. 2차 재검증서
  P0/P1 0 확인.
- **안전 vs 완전성 분리**(116 ④): 다중 gated 승인 고아([P1#2])를 안전결함으로 오판하지 않고, fail-closed
  (미승인 부수효과 0)를 verify H5로 실측한 뒤 완전성만 OUT(101/102 다중 interrupt 경계)로 정직 기록.
- **검증**: 실 그래프 interrupt/resume로 재호출 횟수·discover 횟수·부수효과 횟수를 수치 실측(H1/H2/H4/H5).
  plan 노드 추가로 깨진 verify_100 U2·verify_102 U4 골격 검증을 정당 변경으로 갱신(과적합 검증의 정직한 진화).

## 배운 것 / 함정

- **노드 경계 = 커밋 단위 = 멱등 단위**(116 ①②). interrupt 유지값은 앞선 완주 노드/self-loop로.
- **선택은 부수효과 노드 이전에 확정·커밋**(116 ③) — 안 그러면 재개마다 재결정, 환경 변화 시 뒤바뀜.
- **fail-closed ≠ 완전성**(116 ④) — 안전 불변식 지켜지면 완전성 갭은 후속으로.

## 검증 생략 / OUT

- 다중 gated 순차 승인 표면화(승인 큐) — 101/102 다중 interrupt OUT. 안전은 유지(fail-closed 실측).
- 세션/스레드 간 영속 캐시 — 여기 캐시는 한 스레드 재개 범위(체크포인터 state).

→ learning 116

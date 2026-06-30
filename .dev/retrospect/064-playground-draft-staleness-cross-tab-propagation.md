# 064 — Playground 초안 배지 stale 해소(교차 탭 전파 + 포커스 백스톱) 회고

## 무엇을 했나
스펙 078(미반영 초안 배지)의 후속 버그를 닫았다(스펙 080). 사용자 보고: "에이전트 초안을 활성화한
뒤에 플레이그라운드에 반영 안 됨. '미반영 초안'으로 남아있음. 새로고침해도 동일함."

## 핵심 판단 — 행복경로 초록에 속지 말고 진짜 조건을 재현
Context에서 전 계층을 실측하니 백엔드(`activate_version`이 draft→active 전환·draft 비움)와 단일 탭
UI(뷰 전환=remount→재페치)는 *멀쩡*했다. 여기서 "재현 안 됨"이라 멈출 수 있었지만, 사용자 보고를
의심하지 않고 한 겹 더 팠다([[probe-deeper-before-concluding]]). 실측으로 좁힌 진짜 조건:
**Agents와 Playground를 별도 탭/창에 띄워 비교**하면, Playground는 마운트 1회 스냅샷을 들고 외부
activate를 몰라 배지가 stale. 브라우저로 그 stale을 *재현*(신호 없이 배지=1 유지)한 뒤 고쳤다.

## 설계 — 사용자 피드백이 바꾼 방향
초안은 포커스 재페치만 두려 했으나, 사용자가 "SPA니까 변경이 일어나면 다른 컴포넌트에 이벤트를
전달해 갱신해야 하지 않나"를 지적. 핵심 뉘앙스를 분별했다: in-app 이벤트는 *같은 탭*만 닿고, 버그는
*탭 경계*다 → 이벤트가 탭을 넘어야 하므로 `BroadcastChannel`. 사용자가 "BroadcastChannel + 포커스
백스톱"을 선택. 즉시 전파(1차) + 포커스/가시성 재페치(백스톱, 미지원·누락 메시지 커버)의 2층.

## 검증 — 객관 측정, 거짓초록 차단
`tests/browser/shot-draft-staleness-080.mjs` RESULT=PASS:
- PART1(백스톱): API activate(서버 draft=[]) 후 **신호 없이 배지=1**(STALE 재현)→`focus` 디스패치→배지=0.
- PART2(BroadcastChannel): **두 번째 페이지**(다른 JS 컨텍스트=다른 탭 대역)에서 activate+`BroadcastChannel`
  post→pageA는 포커스 없이도 배지=0. BroadcastChannel은 같은 채널 객체엔 자가 미수신이라, 단일 페이지로는
  증명 불가→두 페이지가 필수(아니면 거짓초록).
- PART3(무회귀): 활성만 에이전트=배지0 / draft 에이전트=배지1.
- tsc 무에러. RBAC 무관(표시/조회 전용, 새 입구·쓰기·소유권 경계 변경 0).

## 잘된 것 / 다음에
- 잘됨: "재현 안 됨(단일 탭 초록)"에서 멈추지 않고 보고자 신뢰로 교차 탭 조건을 재현한 것.
- 잘됨: 사용자 피드백("이벤트로")을 그대로 받지 않고 *왜 탭을 넘어야 하나*까지 분별해 수단(BroadcastChannel)을
  정확히 고른 것.
- 잘됨: 거짓초록을 구조로 차단 — PART2를 두 페이지로 짜 BroadcastChannel 자가-미수신 함정을 피함.
- 다음: 소비 표면이 진실원을 스냅샷할 땐 처음부터 "이 표면 밖에서 바뀌나?"를 물어 전파/백스톱을 설계에
  포함(learning 083). 081(공간축)과 083(시간축)을 한 쌍으로 본다.

## 자산
- 스펙: docs/spec/080-playground-agents-refetch-on-focus.md
- learning: 083(소비 표면 신호를 신선하게 — 교차 탭은 교차 컨텍스트 전파로)
- 코드: admin/src/agentsBus.ts(신규), AgentsView.tsx(송신), Playground.tsx(수신+백스톱)
- 테스트: tests/browser/shot-draft-staleness-080.mjs

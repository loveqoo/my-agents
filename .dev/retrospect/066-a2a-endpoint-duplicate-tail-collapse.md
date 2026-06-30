# 066 — A2A endpoint `/a2a/a2a` 중복 collapse(071 누락 케이스) 회고

## 무엇을 했나
사용자: a2a 등록 에이전트가 Playground에서 동작 안 함, endpoint 뒤에 `a2a/a2a`가 붙음. 071이 카드의
루트상대 `/a2a`를 mount prefix 하위로 resolve할 때, **prefix가 이미 `/a2a`로 끝나면** 중복 부착돼
`…/a2a/a2a`가 되던 누락 케이스를 스펙 082로 닫았다(꼬리 정확 매치 시 collapse).

## 핵심 판단 1 — 추측 대신 재현으로 토폴로지 확정
사용자가 "a2a/a2a 붙음"만 줬을 때, 입력 토폴로지를 상상으로 단정하지 않고 `_resolve_card_endpoint`에
6개 후보(kakaopay·prefix=/a2a·bare·base직접·절대·표준root)를 넣어 **어떤 조합에서 중복이 나는지 측정**
했다([[probe-deeper-before-concluding]]). 결과: 중복은 *mount prefix 꼬리 == 카드 상대경로*일 때만.
이로써 고칠 분기와 *건드리면 안 되는 정상 분기*(kakaopay·절대·표준)를 동시에 확정 — 무회귀 경계를 측정으로 그었다.

## 핵심 판단 2 — 모호한 heuristic을 멱등으로 닫되, 보수적으로
071의 prefix-상대 resolution은 같은 `/a2a`가 토폴로지에 따라 origin 기준일 수도 prefix 기준일 수도 있는
**본질적 모호성**을 한쪽으로 고정한 것이었다(learning 085). 닫는 길은 둘: 멱등 collapse, 또는 두 해석을
probe해 도달하는 쪽 채택. 사용자가 동작을 정확히 지정("url 끝이 a2a면 추가 금지")해줘 저비용인 collapse로
충분. 단 **정확 꼬리 매치만**(`prefix==/rel` or `endswith(/rel)`) — 부분겹침(`a2a/rpc`)까지 collapse하면
정상 경로가 깨지므로 보수적으로. codex가 정상 prefix 오collapse 없음·host 불변·`..` 미주입을 확인.

## 핵심 판단 3 — 081과의 시너지
이미 `/a2a/a2a`로 저장된 사용자 행은, 이번 fix 후 **재동기화(081 자가치유)** 1회로 cardUrl에서 재resolve
되어 교정된다(삭제+재연결도 가능). 082(resolution 정확성)와 081(stale 재파생)이 한 쌍으로 동작 —
"규칙을 고쳐도 굳은 재고는 별도 경로로 닦는다"(learning 084)의 실제 적용.

## 검증 — 버그+정상 같은 매트릭스, 3런
- 단위 8: 버그 3 collapse·정상 3 무회귀·다중꼬리 collapse·부분겹침 미collapse(고친 것만 보지 않고 무회귀 동봉).
- 라이브 4: prefix=/a2a 스레드 서버 connect → endpoint `…/a2a`(중복 없음)·probe live·POST 도달.
- 회귀 071/081/045/060 PASS. 적대 codex 신규결함 0.

## 잘된 것 / 다음에
- 잘됨: 증상만으로 단정 않고 매트릭스 재현으로 *고칠 분기 + 보존할 분기*를 동시 확정.
- 잘됨: 모호 heuristic을 멱등으로 닫되 정확 매치로 한정해 과도 collapse(정상 경로 파손)를 회피.
- 다음: prefix-상대·join heuristic을 처음 설계할 때부터 "base가 꼬리를 이미 포함하면?"과 "같은 입력이
  토폴로지마다 다른 정답인가?"를 물어 멱등/probe-disambiguate를 설계에 넣는다(learning 085). 071→082는
  그 질문을 사후에 받은 사례.

## 자산
- 스펙: docs/spec/082-a2a-endpoint-duplicate-tail-collapse.md
- learning: 085(맥락상대 resolution은 꼬리에 멱등 — base가 그 세그먼트로 끝나면 또 붙이지 마라)
- 코드: agent_card.py `_resolve_card_endpoint`(꼬리 collapse)
- 테스트: tests/verify_082_collapse.py

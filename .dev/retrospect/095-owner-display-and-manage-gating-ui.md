# 095 — 화면에 주인 표시 + 비소유 관리 버튼 숨김 (스펙 114)

## 무엇을

112가 백엔드 관리 게이트를 걸었으나 UI는 그대로(못 만지는 항목에도 버튼·소유 정보 없음). 사용자
"1~4 루프"의 2번: 목록에 소유 표시 + 비소유면 관리 버튼 숨김.

## 어떻게

- 백엔드가 판정 소유: `owner_id`+`can_manage`를 AgentOut/CollectionOut/McpServerOut에 추가, list/get
  라우트에서 `ownership.may_manage`(assert의 불리언 형제)로 계산. 프론트는 필드만 읽음(재계산 금지).
- 프론트: `OwnerTag`(shared, null=공유/비관리=다른 사용자) + 관리 버튼을 `can_manage`로 가드
  (AgentsView 목록 액션·상세·버전 패널 / CollectionsView 삭제·업로드 / BlocksView mcp 삭제·편집·발행).

## 잘된 것

- **백엔드 판정 소유 재적용**(learning 113/114 ①): 프론트가 casbin admin을 모르니 백엔드가 can_manage를
  실어 내려 드리프트 0.
- **브라우저 검증이 놓친 렌더 지점을 잡음**(learning 114 ②④): 상세 드로어는 막았는데 **목록 행 삭제
  아이콘을 놓침** — 스샷에서 비소유 행에 휴지통 남은 걸 보고서야 발견·수정. 코드만 봤으면 샜다.
- **응답 인터셉트로 결정적 UI 검증**(114 ③): admin=superuser라 can_manage=false가 자연 발생 안 함 →
  `page.route`로 /agents 한 항목에 owner_id=타인·can_manage=false 주입해 렌더 경로 실측(A/B/C pass).
- **3런**: 백엔드 verify_114(may_manage 동치+list/get 응답) + tsc + 브라우저 shot-owner-114(태그·버튼
  숨김·안내문). codex 생략 합의(순수 표시 파생, 인가 자체는 112/113 rung3 통과·may_manage=assert 동일 술어).

## 배운 것 / 함정

- **게이트된 동작은 모든 렌더 지점 전수 가드**(114 ②) — 112 "입구 열거"의 UI판. 리스트·상세·서브패널.
- **세션서 못 만드는 상태는 응답 인터셉트로 검증**(114 ③) — 한 필드만 변형이 전부 목킹보다 견고.
- **UI 게이팅은 브라우저 눈 검증 필수**(114 ④) — 렌더 누락은 tsc/grep으로 안 잡힘.
- 함정: BlocksView 목록은 `/mcp-servers`가 아니라 `/blocks`가 소스 → can_manage를 `/blocks` mcp 매핑에도
  넣어야 함(둘 다). OwnerTag는 owner 개념 없는 카테고리엔 안 뜨게(mcp만).

## 검증 생략 / OUT

- codex 적대(순수 표시 파생·인가는 112/113서 검증). 소유권 이전 UI(069 금지 기조). owner→display_name
  조인(이메일 노출 회피, "다른 사용자"로 충분). CollectionsView 청크정책 편집·문서 삭제는 백엔드 게이트
  의존(UI 가드는 삭제·업로드까지, 나머지 backend 404).

→ learning 114

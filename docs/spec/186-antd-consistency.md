# 186 — antd 일관성: 토스트 표준화 + 비-antd 재구현 감사

## 배경
사용자 발견: AgentsView가 성공 토스트로 **커스텀 플로팅 Alert**을 쓰는데(antd6 포팅 c9848df 잔재),
앱의 다른 ~10개 뷰는 표준 `message.success`를 쓴다 — 의도 없이 굳은 불일치. 사용자 지시:
① 표준 `message.success`로 통일 ② antd를 안 쓰는 다른 부분도 감사.

## ① 토스트 표준화 — 완료·검증
커스텀 플로팅 토스트(`toast` state + 자동소멸 타이머 + `<Alert>` 렌더)를 **두 뷰**에서 제거하고
표준 antd `message`로 통일:
- **AgentsView**: 13개 `setToast(...)` → `message.success(...)`. 토스트 state·타이머·렌더 삭제. 미사용
  된 `Alert`·`useEffect` import 제거. 684→658줄.
- **ApprovalsView**: 감사 중 **같은 패턴 발견**(승인/거부 토스트). `setToast({type,msg})` →
  `message.success`/`message.warning`. state·타이머·렌더·`Alert` import 제거.
- **검증**: tsc 0 · `verify-useagents-185b.mjs` ALL PASS(생성/삭제 왕복 토스트가 표준 `.ant-message`로
  뜸·list 반영·pageerror 0) · ApprovalsView 렌더 확인(pageerror 0) · 스샷(상단 중앙 표준 토스트).
- **전 앱 잔여 0**: `showIcon message={toast}`·커스텀 플로팅 토스트 패턴 grep 0.

## ② 비-antd 재구현 감사 — 분류
`shared.tsx`는 antd에서 `Tag/Button/Switch/Grid`만 import → 아래는 from-scratch.

### 정당(유지 — 사유 명시)
- **`shared.DataTable`(↔antd Table)·`Drawer`(↔antd Drawer)·`Desc`(↔antd Descriptions)**: 앱의 **자체
  미니 디자인시스템 층**. 커스텀 이유 있음 — DataTable=2줄 subRow(스펙 146)·Drawer=모바일 100%폭+Escape
  거동(스펙 135)·Desc=컴팩트 라벨/값. 전 뷰가 의존해 교체는 대형 결정(범위 밖, 필요 시 별도 스펙).
- **`EvalMatrix` raw `<table>`**: 매트릭스/피벗 레이아웃 — antd Table이 잘 못 하는 형태. 정당.
- **`AdminShell` position:fixed**: 반응형 **모바일 사이드바**(백드롭+패널). 앱 셸 내비, 정당.
- **`OverviewView` `<button>`**: 클릭 가능한 **통계 카드** — 네이티브 button이 오히려 접근성 정답.
- **`PagedMemoryList` `<div onClick=stopPropagation>`**: 버튼 아님, **전파 차단 가드**(행 클릭 오발 방지).
  false positive.

### 사고(불일치 — 수정함)
- **AgentsView·ApprovalsView 커스텀 플로팅 토스트** → ①에서 표준 `message`로 통일 완료.

## 결론
사고성 불일치(커스텀 토스트 2건)는 표준화 완료. 나머지 비-antd는 **의도된 디자인시스템 층/접근성/
레이아웃 한계**로 정당 — 특히 DataTable/Drawer/Desc는 앱 전반의 커스텀 층이라 통일하려면 별도 대형
스펙 필요(현재 판단: 유지). 필요 시 백로그.

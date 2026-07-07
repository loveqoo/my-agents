# admin (React SPA) — 폴더 규칙

## UI 컴포넌트 규칙 (사용자 지시, 2026-07-07 — 강행)
- **모든 UI는 antd 컴포넌트로 작성한다.** 커스텀(손수 만든) 컴포넌트는 antd에 대응물이 없을 때만
  허용하고, 그 경우에도 antd 프리미티브(Layout·Typography·Flex·Splitter 등) 위에 조립한다.
- 새 화면·패널·오버레이를 만들 때 antd 대응물부터 찾는다: 도킹 분할=Splitter, 오버레이=Drawer/Modal,
  목록=Table/List, 상태 표시=Tag/Badge, 접이식=Collapse, 알림=message/notification.
- 기존 커스텀 잔재는 스펙 204(전수 조사·교체)가 기준 목록 — 새 커스텀을 추가하면 그 목록이 다시 늘어난다.
- 관련 선례: 스펙 187(공용 Drawer를 antd로 전환 — 커스텀 95줄 제거), 스펙 204(전수 교체),
  스펙 207(채팅 본문 렌더러 → @ant-design/x-markdown 채택).

## antd/x 대응물이 없어 커스텀을 유지하는 예외 (규칙과 모순 아님 — 근거 기록)
아래는 antd·@ant-design/x·@ant-design/x-markdown에 **대응물이 없어** 커스텀으로 남긴 것들이다.
antd 프리미티브 위에 조립돼 있으며, 대응물이 생기면 재검토한다(스펙 204 보류 정리 → 스펙 207).
- **JsonTree**(`src/playground/JsonTree.tsx`) — 접이식 JSON 트리 뷰어. antd Tree는 선택 위젯이라
  JSON 값 표시에 부적합. 인스펙터/메시지 JSON 분기가 소비.
- **TrendChart**(성적 추이 스파크라인, SVG) — x/antd에 차트 없음(차트는 별개 `@ant-design/plots`).
  plots 도입 시 재검토(현재는 미도입 — 의존성 최소).
- **DataTable 모바일 카드 스택**(`shared.tsx`) — Flex + antd `Card`(Panel) 조립. antd `List`는 **v6에서
  deprecated(제거 예정)**라 목록이어도 List로 옮기지 않는다(Flex+Card가 규칙 부합이자 미래지향).

## antd v6 deprecation 백로그 (전면 마이그레이션은 별건)
v6 콘솔 경고 관측: `List` 컴포넌트 deprecated · `Drawer` width→size · `Alert` message→title.
개별 스펙에서 새로 쓸 때는 피하되, 기존 사용처 전면 교체는 별도 스펙(`.dev/backlog.md`).

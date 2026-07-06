# admin (React SPA) — 폴더 규칙

## UI 컴포넌트 규칙 (사용자 지시, 2026-07-07 — 강행)
- **모든 UI는 antd 컴포넌트로 작성한다.** 커스텀(손수 만든) 컴포넌트는 antd에 대응물이 없을 때만
  허용하고, 그 경우에도 antd 프리미티브(Layout·Typography·Flex·Splitter 등) 위에 조립한다.
- 새 화면·패널·오버레이를 만들 때 antd 대응물부터 찾는다: 도킹 분할=Splitter, 오버레이=Drawer/Modal,
  목록=Table/List, 상태 표시=Tag/Badge, 접이식=Collapse, 알림=message/notification.
- 기존 커스텀 잔재는 스펙 204(전수 조사·교체)가 기준 목록 — 새 커스텀을 추가하면 그 목록이 다시 늘어난다.
- 관련 선례: 스펙 187(공용 Drawer를 antd로 전환 — 커스텀 95줄 제거), 스펙 204(전수 교체).

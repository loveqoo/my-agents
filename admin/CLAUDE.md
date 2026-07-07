# admin (React SPA) — 폴더 규칙

## UI 컴포넌트 규칙 (사용자 지시, 2026-07-07 — 강행)
- **모든 UI는 antd 컴포넌트로 작성한다.** 커스텀(손수 만든) 컴포넌트는 antd에 대응물이 없을 때만
  허용하고, 그 경우에도 antd 프리미티브(Layout·Typography·Flex·Splitter 등) 위에 조립한다.
- 새 화면·패널·오버레이를 만들 때 antd 대응물부터 찾는다: 도킹 분할=Splitter, 오버레이=Drawer/Modal,
  목록=**Table**(또는 Flex+행 조립 — `List`는 v6 deprecated, 스펙 208), 상태 표시=Tag/Badge,
  접이식=Collapse, 알림=message/notification.
- 기존 커스텀 잔재는 스펙 204(전수 조사·교체)가 기준 목록 — 새 커스텀을 추가하면 그 목록이 다시 늘어난다.
- 관련 선례: 스펙 187(공용 Drawer를 antd로 전환 — 커스텀 95줄 제거), 스펙 204(전수 교체),
  스펙 207(채팅 본문 렌더러 → @ant-design/x-markdown 채택).

## 탭/세그먼트 선택 규칙 (스펙 212)
- **데이터 집합 전환**(내용 자체가 바뀜, 예: 대기/처리·에이전트/유저 메모리·문제집/격자/이력) → antd `Tabs`.
- **같은 목록의 필터·모드**(부분집합·표현만 바뀜, 예: 세션 상태 필터·일치/유사도 검색) → antd `Segmented`.
- `Radio.Group`을 탭/필터 용도로 쓰지 않는다(스펙 212서 세션 필터를 Segmented로 이관).

## antd/x 대응물이 없어 커스텀을 유지하는 예외 (규칙과 모순 아님 — 근거 기록)
아래는 antd·@ant-design/x·@ant-design/x-markdown에 **대응물이 없어** 커스텀으로 남긴 것들이다.
antd 프리미티브 위에 조립돼 있으며, 대응물이 생기면 재검토한다(스펙 204 보류 정리 → 스펙 207).
- **JsonTree**(`src/playground/JsonTree.tsx`) — 접이식 JSON 트리 뷰어. antd Tree는 선택 위젯이라
  JSON 값 표시에 부적합. 인스펙터/메시지 JSON 분기가 소비.
- **TrendChart**(성적 추이 스파크라인, SVG) — x/antd에 차트 없음(차트는 별개 `@ant-design/plots`).
  plots 도입 시 재검토(현재는 미도입 — 의존성 최소).
- **DataTable 모바일 카드 스택**(`shared.tsx`) — Flex + antd `Card`(Panel) 조립. antd `List`는 **v6에서
  deprecated(제거 예정)**라 목록이어도 List로 옮기지 않는다(Flex+Card가 규칙 부합이자 미래지향).

## antd v6 deprecation (스펙 208서 마이그레이션 완료)
관측된 3종 전수 처리(스펙 208): `Alert` `message`→`title`(30건)·`Drawer` `width`→`size`(13건, 공용 래퍼는
내부에서 size 전달·공개 API는 width 유지)·`List` 컴포넌트→Flex+행 조립(4건, drop-in 없음). 완료 기준=
콘솔 antd deprecation 경고 0건. **새 코드는 위 deprecated prop/컴포넌트를 쓰지 않는다.** 이후 새 v6
deprecation이 감사에 뜨면 후속(`.dev/backlog.md`).

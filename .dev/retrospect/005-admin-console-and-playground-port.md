# 005 — Admin 콘솔 + Playground 이식 루프 회고

날짜: 2026-06-22
지배 스펙: [docs/spec/006-admin-console-port.md](../../docs/spec/006-admin-console-port.md)

## 루프 개요
- **목표:** claude.ai/design handoff 번들(자체구현 antd-look 컴포넌트)을 디자인 명세로 삼아, 진짜 antd 6 + @ant-design/x로 admin 콘솔(5뷰) + agent-debug Playground를 재현. 데이터는 mock, 실 백엔드는 이후.
- **계기:** 텍스트로 디자인을 주고받기 어려워 전문 디자인 툴(claude.ai/design)을 경유. A 방식(번들 직접 사용 아님 — 명세로만, 진짜 antd 재현) 채택.
- **단계 흐름:**
  - 1 Scaffolding — `.dev/design-refs/`에 번들 보관, `admin/src/{admin,playground}` 구조
  - 2 Context — 번들 전 파일 정독(데이터·5뷰·agent-debug 4파일)
  - 3 Planning — `docs/spec/006`(초안→승인)
  - 4 Execution — 기반(theme/icons/mockData/shared) 직접 → 5뷰 **병렬 서브에이전트** → Playington 1 서브에이전트
  - 5 Verification — tsc 0 / build ✓ / **codex GATE PASS**(P2 5건 중 2건 수정)
  - 6 Compounding — 본 회고 + 학습 008
- **중간 방향 전환:** 1단계(셸) 확인 후 사용자가 "각 메뉴 상세 기능 모두 mock으로라도 옮겨달라" → 단계 분할 대신 전 뷰 일괄 이식.
- **개정 반영:** `handoff2`(에이전트 출처 UI/Code) 도착 → diff로 변경 범위(AgentsView+데이터)만 파악해 적용, codex 재검증 후 별도 커밋.

## 무엇이 잘못됐나 / 배운 것
- **antd Sider flex 함정:** `Layout.Sider`에 flex를 줘도 antd가 children을 `.ant-layout-sider-children`로 한 번 감싸 안 먹음 → 하단 칩이 바닥에 안 붙음. 안쪽에 flex column 한 겹을 더 둬야 함. (사용자가 "완벽하게 복사 못했다"고 가장 먼저 지적한 부분)
- **@ant-design/x v2 API 차이:** 번들의 `BubbleList`는 자체구현이라 혼합 콘텐츠(승인카드·A2UI)에 안 맞음 → flex column으로 직접 렌더. `Prompts.icon`은 문자열이 아니라 ReactNode, `onItemClick`은 `{data}` 형태. → [[008]]
- **번들 전용 컴포넌트는 대체 구현:** `A2UISurface`는 antd-x에 없음 → command-stream 해석기를 직접 작성.
- **codex가 잡은 mock 라이프사이클 함정:** 언마운트 후 setState(스트리밍 interval 정리 누락), 유일 active 버전 revert 시 상태 붕괴, 등록 모달 stale in-flight 테스트. 자가검증으론 놓쳤을 것.

## 잘된 것
- **기반 먼저 → 병렬 팬아웃:** theme/icons/mockData/shared를 먼저 안정화한 뒤 5뷰를 병렬 서브에이전트로 이식 → 일관성 유지하며 속도 확보. tsc 제약(인터페이스↔Record) 같은 공통 함정을 기반에서 선제 차단. → [[008]]
- **개정은 diff부터:** handoff2를 통째로 다시 안 하고, 기존 번들과 diff로 **변경 2파일만** 식별해 적용 — 범위·리스크 최소화.
- **타자 검증 일관:** 매 산출물 codex GATE 통과 후 커밋. 실제 React 버그만 골라 수정, mock 충실 항목은 기록.

## 다음에 다르게 할 것
- UI 셸은 빌드 통과만 믿지 말고 **레이아웃 검증을 더 일찍**(antd 컴포넌트 래핑 구조 확인). 헤드리스 렌더/스크린샷 수단 도입 검토.
- 병렬 서브에이전트 이식 시 **공유 타입/헬퍼 계약을 프롬프트에 명시**(이번에 DataTable 제네릭 제약을 미리 풀어둔 게 5건 동시 함정을 막음).

## 관련 기록
- [[008]] handoff 번들을 진짜 antd로 이식하는 플레이북 + antd-x v2 함정
- 이전 회고: [004-admin-web-ui-chat](./004-admin-web-ui-chat.md)

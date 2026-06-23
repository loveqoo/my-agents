# 004 — 어드민 UI 죽은 버튼 전수 감사

날짜: 2026-06-24
맥락: 페르소나 "편집" 버튼이 onClick 없이 렌더되던 버그(014) 발견 후,
사용자 요청 — "같은 부류(미연결 핸들러/미완성 폼) 버튼을 전부 찾아 리스트업하라.
테스트가 어려운 환경이라 정적 분석으로." → 병렬 에이전트 4기로 전 뷰 감사.

판정 기준:
- **DEAD**: 클릭 가능해 보이나 onClick 핸들러 자체가 없음(=과거 페르소나 편집 버그와 동류).
- **PARTIAL**: 폼/모달을 열지만 미완성(빈 껍데기 생성·가짜 데이터 등).
- **DISABLED**: 항상 비활성 + 활성화 경로 없음.

## 발견 (수정 후보)

### DEAD — 핸들러 미연결 (클릭해도 무동작)
1. `SessionsView.tsx:155` — **"세션 종료"** danger 버튼. onClick 없음. api.ts에 세션 종료
   엔드포인트도 부재. active/running/idle 세션 상세 Drawer에서만 노출.
2. `AdminShell.tsx:177` — **헤더 "검색" Input**. onChange/onSearch/onPressEnter 전무. 순수 장식.
3. `DebugChat.tsx:446` — Sender **클립(paper-clip) 아이콘** 버튼. onClick 없음. 첨부 시늉만.

### PARTIAL — 열리지만 미완성
4. `AgentsView.tsx:452` — 코드 에이전트 등록의 **"연결 테스트"**. 실제 HTTP fetch 없이
   `setTimeout(850ms)` + `Math.random` 으로 **가짜 Agent Card** 생성. 등록 플로우가
   이 목 매니페스트에 의존(엔드포인트 slug만 이름에 반영).
5. `BlocksView.tsx` createCurrent — **memory "새 항목"**. `{name:'새 항목'}` 껍데기만 생성,
   이후 편집 폼 없음(아래 8번과 한 쌍).
6. `BlocksView.tsx` createCurrent — **embedding "새 항목"**. 동일.
7. `BlocksView.tsx` createCurrent — **permission "새 항목"**. 동일.

### DISABLED — 항상 비활성 + 활성 경로 없음
8. `BlocksView.tsx:698` — memory/embedding/permission **"편집"** 버튼. 하드코딩 disabled,
   전용 편집 폼 없음. **페르소나 버그와 정확히 같은 계열** (persona·mcp만 폼 구현됨).

## 의도된 동작 (버그 아님)
- `AgentsView.tsx:1353` — 코드 에이전트 행 **잠금(lock) 아이콘**. 코드 관리 에이전트의
  편집 잠금 표시. 의도적 disabled.
- `ApprovalsView` 승인/거부 `disabled={!!busy}` — 처리 중 일시 비활성(정상).

## 검증 범위
4기 병렬 감사: AgentsView / Blocks+Models / Sessions+Overview+Approvals+Shell+shared /
Playground+DebugChat+Inspector+Chat+App. 헤드라인 2건(1·2)은 직접 재확인.
ModelsView·OverviewView·ApprovalsView·Inspector·Playground는 DEAD/PARTIAL 0건.

## 분류 요약
- 같은 부류(미완성 작성/편집)의 **본질 버그**: 5·6·7·8 (Blocks.memory/embedding/permission 작성·편집).
- 독립 DEAD: 1(세션 종료)·2(검색)·3(클립).
- 백엔드까지 필요한 항목: 1(세션 종료 API), 4(실제 Agent Card fetch).

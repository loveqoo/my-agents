# 187 — 커스텀 컴포넌트를 antd로 통일 (단계별)

## 배경
스펙 186 감사에서 `shared.tsx`의 `DataTable`·`Drawer`·`Desc`가 antd 미사용 from-scratch 재구현임을
확인. 사용자 결정(2026-07-05): antd로 통일 — **antd가 오랫동안 다듬은 스타일·접근성·키보드·반응형
동작을 그대로 취하고, 우리가 재구현·유지보수하지 않기 위해**. 커스텀 층은 그 노력을 안 쓰고 재발명한 셈.

## 규모(실측)
- **Drawer**: 9파일·10곳, 커스텀 95줄. antd 이점 큼(포커스 트랩·Escape·스크롤락·애니메이션 다 수동 재구현). 난이도 낮음.
- **DataTable**: 8파일·10곳, 커스텀 199줄. antd 이점 중(정렬·a11y). 난이도 높음(2줄 subRow·커스텀 컬럼 매핑).
- **Desc**: 8파일·50곳, 커스텀 28줄. antd 이점 작음(단순 라벨/값, Descriptions는 그리드 패러다임이라 호출부 재구성).

## 전략
**shared 구현만 antd로 바꾸고 prop API는 유지** → 70곳 호출부를 안 건드리고 antd 렌더로 교체(위험 최소).
단계마다 브라우저 전수 검증. 순서: **Drawer → DataTable → Desc**(사용자 선택, 이득·안전 큰 것부터).

## Phase 1 — Drawer → antd Drawer · 완료·검증
`shared.Drawer`를 antd `Drawer` 래퍼로 교체. prop API(open/title/width/onClose/footer/children) 유지.
- antd가 제공: 포커스 트랩·Escape(keyboard)·마스크(maskClosable)·스크롤락·슬라이드 애니메이션 → 커스텀
  95줄 재구현 삭제(shared.tsx 575→480줄). 미사용 `CloseOutlined` import 제거.
- 보존: 모바일 100% 폭(`Grid.useBreakpoint`), footer 우측 정렬(flex wrap), `destroyOnHidden`(구
  `{open && ...}` = 닫힘 시 body 언마운트 동치).
- **변화(의도된 antd 채택 결과)**: 닫기 X가 헤더 우측→**좌측**(antd 기본 레이아웃).
- **검증**: tsc 0 · 드로어 6사이트 전수 브라우저 회귀 — 에이전트 3종(`verify-agentsview-decomp-185`
  ALL PASS) + 컬렉션·세션·블록(`verify-antd-drawer-187` ALL PASS) 열림·내용·pageerror 0 · 스샷 시각 확인
  (antd 표준 크롬·footer 우측정렬). 부수효과: 166 회고의 "커스텀 Drawer 셀렉터 함정"도 해소(이제 표준 `.ant-drawer`).

## Phase 2 — DataTable → antd Table · 완료·검증
데스크톱 표 분기(커스텀 ~110줄: sticky·ResizeObserver·수동 hover·행별 tbody)를 antd `Table`로 교체.
**모바일 카드 분기(<lg)는 유지** — 표가 아니라 카드 레이아웃(스펙 145의 의도된 설계)이라 antd Table
대상이 아님. prop API(columns/rows/onRowClick/rowKey/empty/subRow) 유지 → 호출부 8파일 무변경.
- 매핑: `Column<T>`→antd columns(key/title/width/align/render 래핑) · `hideBelow`→기존 필터 유지(호출부
  무변경) · `onRowClick`→`onRow` · `empty`→`locale.emptyText` · **subRow(스펙 146)→`expandable`**
  (controlled `expandedRowKeys`=전 행 — defaultExpandAllRows는 최초 렌더만이라 생성 행 누락,
  `showExpandColumn:false`, 보조줄 클릭도 onRowClick 배선).
- theme.css: `.dt-table`→`.dt-antd` 셀렉터 갱신(Tag 줄바꿈, 스펙 145) + `.dt-antd-sub` 규칙(본행
  하단 경계 제거·확장행 배경/패딩 본행과 통일)으로 "두 줄이 한 몸" 룩 보존.
- 제거: sticky/overflow ResizeObserver·수동 hover 로직. shared.tsx 480→409줄(누적 575→409).
  antd가 제공: hover·헤더 스타일·빈 상태(Empty)·a11y.
- **검증**: tsc 0 · 브라우저 3종 전수 ALL PASS(에이전트 리스트+드로어3+폼 / 생성→삭제 왕복+토스트 /
  컬렉션·세션·블록 행클릭→드로어) · 스샷 시각(에이전트 2줄 행 한 몸 유지·컬렉션 표·모바일 카드 분기 렌더).

## Phase 3 — Desc → antd Descriptions/Form · 완료·검증(사용자 "전환" 선택)
50곳 전수 조사에서 Desc가 **두 용도**로 쓰임을 발견 — 용도별로 옳은 antd 컴포넌트가 다름:
- **표시용 42곳**(세션 6·평가 1·AgentDetail 8·CodeAgentDetail 9·ExternalAgentDetail 3·블록 15) →
  antd `Descriptions`(column=1·size=small·items 배열). 연속 그룹=하나의 Descriptions, 조건부 행=items
  스프레드(`...(cond ? [{...}] : [])`), `width={84}` 커스텀은 제거(Descriptions는 내부가 표라 라벨
  정렬 자동). PersonaStaleNote 등 비-Desc 요소가 낀 그룹은 그 지점에서 분할.
- **폼 행 8곳**(허용호스트 2·배치 6 — 라벨+Input/InputNumber) → antd `Form`/`Form.Item`
  **레이아웃 전용**(layout=vertical·component="div"·name 미지정 — 입력 상태는 기존 controlled 그대로,
  로직 무변경). Descriptions에 입력을 넣는 건 의미론 위반이라 배제.
- `shared.Desc`(28줄)+고아 주석 삭제. shared.tsx **384줄**(스펙 187 누적 575→384, −191줄).
- **검증**: tsc 0 · 브라우저 3종 전수 ALL PASS · 스샷 시각(코드 드로어 Descriptions 콜론 라벨·배치
  Form 수직 레이아웃·힌트 인라인 보존).

## 실행 결과
- **Phase 1·2·3 전부 완료·커밋** — shared.tsx의 from-scratch 재구현(Drawer 95줄·DataTable 데스크톱
  분기·Desc 28줄)이 antd(Drawer·Table·Descriptions/Form)로 통일. 남은 커스텀은 전부 정당:
  모바일 카드 분기(antd 대응물 없는 레이아웃)·Page/Panel/StatusPill/OwnerTag(도메인·토큰 래퍼)·
  VersionHistory/ExposeSwitch(도메인 컴포넌트).

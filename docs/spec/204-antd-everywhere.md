# 204 — admin 전면 antd 전환 (커스텀 UI 전수 교체)

## 배경 (사용자 지시, 2026-07-07 — 강행 규칙)
"이 프로젝트는 모두 antd 컴포넌트로 작성해야 합니다. 하나하나 지시하지 않도록 일괄 조사·교체." +
"최대한 antd로 고민하고, 안 될 경우 논의." 규칙은 `admin/CLAUDE.md`에 명문화(2026-07-07). 선례:
스펙 187(커스텀 Drawer→antd, 버그 소멸+95줄 제거).

## 조사 결과 (Explore 전수 — 실측 파일:줄)
- **A. 교체 대상 18건**(antd 대응물 있음) · **B. 이미 antd 래퍼**(Drawer·DataTable 데스크톱·
  PickerGroups·AdminShell 골격·OverridePanel 등 — 무변경) · **C. 대응물 없음 4건** · **D. 애매 4건**.
- 부수 발견: `admin/src/components/Chat.tsx` = 죽은 코드(전역 import 0건).

## 교체 계획 (난이도 오름차순 — 매 배치 후 tsc+ui-audit 3종+스샷 회귀)

### Batch 1 — 난이도 하 (11건)
| 대상 | → antd |
|---|---|
| Inspector `Section`(수제 접이식) | Collapse |
| Inspector `MemoryRow` 유사도 바 | Progress |
| DebugChat `ModelBadge` 수제 pill | Tag |
| shared `StatusPill`(색점+라벨) | Badge |
| shared `Panel`(테두리 카드) | Card (styles.body 조정 — 광범위 사용, 시각 회귀 주의) |
| EvalTrend CompareDrawer 수제 아코디언 | Collapse |
| EvalView 성적추이 클릭 행 | List |
| primitives `IdRow` 수제 복사 | Typography.Text copyable |
| Overview `StatTile`(수동 hover) | Card hoverable + Statistic |
| Overview 최근 목록 2종 | List |
| shared `VersionHistory` 수제 행 | List |

### Batch 2 — 난이도 중 (4건)
- Playground 좁은폭 인스펙터 fixed 오버레이 → **Drawer**(width 100%).
- AdminShell 모바일 수제 백드롭+fixed Sider → **Drawer**(모바일 내비, 자체 mask).
- EvalMatrix 생 HTML table → **Table**(모델별 동적 컬럼+합계행).
- DebugChat `Chip`/`TraceChips` 컨테이너 pill → Tag/Badge(도메인 내용은 유지).

### Batch 3 — 난이도 상 (3건)
- Inspector **도킹 패널 → Splitter**(채팅‖인스펙터, 폭 드래그 덤) — 질문의 발단.
- DebugChat `AgentCombo`/`SessionCombo` 수제 드롭다운 2종 → **Dropdown**(popupRender로 리치 콘텐츠,
  바깥클릭·포지셔닝·접근성을 antd에 이양).

### 논의 항목 (C/D) — **사용자 결정(2026-07-07): 전부 보류, 교체 18건만 먼저**
1. **TrendChart**(생 SVG 라인차트): antd 코어엔 차트 없음. 권고=유지(또는 @ant-design/plots 도입은 별 스펙).
2. **MessageContent/JsonTree**(마크다운·JSON 렌더): 대응물 없음. 권고=유지(JsonTree를 Tree로 옮기면
   커스텀 렌더 노드만 늘어남).
3. **DataTable 모바일 카드 분기**: 권고=antd List로 교체(카드 UX 유지+antd化 — 스펙 145 "카드가 정답"
   판단 존중).
4. **InlineFormPanel/트레이스 카드들(McpCall 등)**: 내부 컨트롤은 이미 antd. 권고=겉면을 Card/Form으로
   표준화(가벼운 수준).
5. **components/Chat.tsx 죽은 코드**: 권고=삭제.

## 검증
- 배치마다: tsc0 · ui-audit(screens 42·overlays 20·scenario 7) · 기존 e2e 스모크(200·197·플그) ·
  전후 스샷 육안 페어(회고 133 — 정량이 못 잡는 압착).
- 마감: 커스텀 잔재 재카운트(조사 스크립트 재실행)로 A목록 0건 측정.

## RBAC 경계
- 비트리거: 표시층 전환만, 라우트/권한/데이터 무접촉.

## 경계
- @ant-design/plots 등 신규 라이브러리 도입은 OUT(별 스펙).
- admin 밖(가이드 정적 HTML 등)은 OUT.

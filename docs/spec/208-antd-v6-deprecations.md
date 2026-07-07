# 208 — antd v6 deprecation 마이그레이션 (List·Drawer width·Alert message)

## 배경 (사용자 "antd 마이그레이션 가시죠")
스펙 207 검증 중 콘솔에 antd v6 deprecation 경고 3종 관측: `List` 컴포넌트 deprecated(제거 예정)·
`Drawer` `width`→`size`·`Alert` `message`→`title`. 동작은 정상(경고만)이나 다음 메이저(v7)에서 제거 예정.
사용자 지시로 지금 마이그레이션한다. **완료 기준=측정 가능**: 콘솔 antd deprecation 경고 0건.

## 대체 API (antd 6.4 타입으로 검증 — 추측 아님)
- **Alert `message`→`title`**: `Alert.d.ts:50 @deprecated please use title instead`. `message` prop만 리네임,
  `description`·`type`·`showIcon`은 그대로. 순수 기계적 치환(~30 사이트).
- **Drawer `width={N}`→`size={N}`**: `Drawer.d.ts:17 size?: sizeType | number | string` — size가 **숫자 허용**
  이라 `width={640}`→`size={640}` 직결(프리셋 제약 없음). **실측 13 사이트**(초기 4는 오측 — 같은 줄
  grep이 멀티라인 Drawer를 놓침. 견고한 스캔=`<Drawer`부터 opening tag 닫힘까지 width 탐색).
  **두 종류 Drawer**: (a) antd 직접 사용 5곳=`size`로 직접 교체, (b) 공용 래퍼 `shared.Drawer`(스펙 187)
  8곳=래퍼 **내부**(shared.tsx AntDrawer)를 `size`로 고쳐 소비자 무변경(공개 API `width` 유지)—한 곳
  수리로 8 소비자 커버. tsc가 (b) 오교체를 잡음(래퍼는 `width`만 받음).
- **List → drop-in 없음**: `list/index.js:199` 런타임 dev 경고. 사용처별 재작성(Flex/div 조립). 4 인스턴스.

## List 대체 설계 (사용처별 인라인 — 4개뿐, 새 추상화 불필요)
List.Item 스타일이 이미 인라인이라 시각 무회귀로 옮긴다.
1. **OverviewView "최근 에이전트"**(98) — `List.Item.Meta`(avatar+title+desc)+StatusPill. → `div` 행 스택,
   각 행=`Flex(space-between)`[ `Flex(avatar + Typography 제목/설명)` · StatusPill ], 패딩 11/18 보존.
2. **OverviewView "라이브 세션"**(125) — Badge+code+desc+Tag. 동일 패턴.
3. **shared.tsx VersionHistory**(293) — `List bordered` + 상태별 배경 커스텀 행. → 테두리 컨테이너 div +
   행 스택(각 행 하단 구분선), 기존 인라인 스타일·버튼 그대로.
4. **EvalView**(394) — `size=small split=false` 클릭 행. → `div` 스택, 행=클릭 가능 flex(스타일 보존).

## 실행
- **Phase 1(기계적, fast-worker 위임 + 전후 카운트 측정)**: Alert `message=`→`title=`(단, `message`가
  변수명·다른 컴포넌트인 오탐 제외 — `<Alert ... message` 문맥만)·Drawer `width={`→`size={`(Drawer JSX만).
- **Phase 2(메인 직접, 설계 필요)**: List 4개 재작성.
- **admin/CLAUDE.md 규칙 갱신**: "목록=Table/List" → "목록=Table 또는 Flex+행 조립(List는 v6 deprecated)".

## 검증 (수치 — 자가선언 금지)
1. **tsc0**.
2. **ui-audit 3종 FAIL 0**(화면 42·오버레이 20·시나리오) — 시각 무회귀.
3. **콘솔 deprecation 경고 0건**(핵심 완료 기준): 감사 CONSOLE 출력에서 `List`·`Drawer width`·`Alert message`
   deprecated 문자열이 사라졌는지 grep. 이 3문자열 0 = 완료.
4. 육안 스샷: Overview(2 리스트)·에이전트 편집(버전 이력)·평가(런 목록) 무회귀.

## 검증 결과 (2026-07-07)
- **tsc0**. **ui-audit 3종**: 화면 42/42 FAIL 0 · 오버레이 20/20 FAIL 0(audit-all서 NAV 실패 1 떴으나
  overlays 단독 2회 연속 NAV 0 = 동시부하 플레이크 확정, 회귀 아님) · 시나리오 통과.
- **핵심 완료 기준 충족: 콘솔 antd deprecation 경고 0건**(List·Drawer width·Alert message grep 0).
- **육안**: Overview 2목록=MetaRow로 옛 List와 동일(아바타·제목/설명·후행·행 구분선) · Alert=title로
  정상(외부에이전트 안내·평가 공개 안내) · 외부에이전트 Drawer 480px 정상 개폐(래퍼 무회귀).
- 실측 카운트: Alert message→title 30·Drawer width→size 13(래퍼 1+antd직접 5+래퍼소비자 8은 width 유지)·
  List→Flex 4. 미사용 List import 2곳(shared·EvalView) 제거, OverviewView는 MetaRow 헬퍼 신설.

## 경계
- 관측된 3종만 대상. 다른 v6 deprecation(bodyStyle·destroyOnClose 등)이 감사에 새로 뜨면 후속.
- OverviewView는 동일 패턴 2회라 로컬 MetaRow 헬퍼 도입(DRY), 나머지 3개는 인라인(단발 — 과설계 회피).

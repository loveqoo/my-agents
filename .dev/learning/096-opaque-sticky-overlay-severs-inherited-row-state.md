# 096 — 불투명 오버레이는 밑 요소가 배경으로 전하던 상태를 끊는다 / 공용 렌더가 레이아웃 불변식의 단일 레버

> 스펙 095, retrospect 077. 프런트 레이아웃. 참고: learning 069/070(covering-guard).

## 상황

커스텀 `DataTable`에 sticky-right 액션 컬럼을 넣으며, 스크롤된 셀이 비치지 않게 sticky td에
**불투명 배경**(`var(--color-bg-container)`)을 깔았다. 그런데 행 hover는 tr에 JS로
`style.background`를 칠하는 방식 → sticky td의 불투명 배경이 그 위를 덮어 **그 셀만 hover
하이라이트가 안 됐다**. codex가 P2로 표면화.

## 배운 것

### 1. 불투명 오버레이는 밑 요소가 *그 프로퍼티로* 전하던 상태를 전부 끊는다

셀을 안 비치게 하려고 `background`를 불투명으로 덮는 순간, **밑(tr)이 `background`로 전달하던 모든
상태**(hover·selected·zebra·drag 등)와의 연결이 끊긴다. 오버레이는 "가림"만 한 게 아니라 그
채널로 오던 정보를 *가로챈* 것. → **오버레이가 그 상태를 스스로 다시 유도(re-derive)해야 한다.**
여기선 `data-sticky` 마커를 달고 tr `onMouseEnter/Leave`에서 sticky 셀 배경도 hover색↔컨테이너색으로
함께 갱신. antd의 `fixed` 컬럼도 내부적으로 CSS로 같은 재유도를 한다(`.ant-table-cell-fix-right`에
hover 규칙) — 불투명으로 가리는 모든 고정 셀의 공통 과제.

일반화: **A를 안 비치게 B로 덮으면, A가 B와 같은 프로퍼티로 신호하던 상태 목록을 세고 오버레이에
재배선하라.** 안 그러면 "가장 자주 보는 상태(hover)만 조용히 빠진" happy-path 초록이 된다.

### 2. 공용 렌더 컴포넌트 = 레이아웃 불변식의 단일 레버 (covering-guard의 프런트판)

overflow의 원천은 뷰가 아니라 공용 `DataTable`의 `minWidth:max-content` 한 줄. 그래서 sticky+숨김을
`DataTable` 한 곳에 넣으면 **현재 안 넘치는 표까지 포함해 전 표면**을 한 번에 커버. 레이아웃 규칙을
뷰마다 반복하면 새 뷰에서 빠지지만(드리프트), 공용 렌더에 규칙을 두면 새 뷰가 그 컴포넌트를 쓰는 순간
자동 상속. learning 069/070의 covering-guard가 백엔드 가드뿐 아니라 **프런트 레이아웃 불변식에도** 적용.

### 3. 반응형 숨김 임계는 자가판정 말고 측정으로

"어느 폭에서 어느 컬럼을 숨기면 0이 되나"는 눈대중 불가. `survey-overflow` 같은 스크립트로 폭별
`table.scrollWidth - wrap.clientWidth`를 재고, 잔여가 남으면 `hideBelow` 브레이크포인트를 한 단계
내려 재측정(measure-then-tune). 완료 조건을 픽셀 수치로 두면 튜닝이 결정적이 된다.

## 훅

- 불투명 sticky/고정 셀 → 밑 행이 배경으로 신호하는 상태(hover/selected/zebra) 재배선 필수, 아니면 그 셀만 빠짐.
- 레이아웃 규칙은 뷰 반복 말고 공용 렌더 컴포넌트에(covering-guard 프런트판).
- 반응형 숨김 임계는 폭별 overflow 픽셀 측정으로 결정(measure-then-tune).

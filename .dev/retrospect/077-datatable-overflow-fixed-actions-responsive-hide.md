# 077 — DataTable 가로 overflow: 액션 컬럼 고정 + 반응형 숨김 (제안 #6)

> 스펙: docs/spec/095. 상태: 완료(Verification GREEN + Compounding).
> 참고 자산: retrospect 069/070·learning 069/070(covering-guard — 공용 컴포넌트 한 곳 수정으로 전
> 표면 커버), tests/browser/measure-collections-table.mjs(이 저장소 "overflow" 정의), spec 062(string detail).

## 무엇을 했나

Admin의 커스텀 `DataTable<T>`(antd Table 아님, `shared.tsx`)가 데스크톱 경로에서
`<div overflowX:auto><table minWidth:max-content>`로 렌더 → 내용이 컨테이너보다 넓으면 래퍼 안에서
가로 스크롤이 생기고 **액션 버튼(편집·삭제)이 오른쪽으로 밀려 화면 밖**으로 나가는 문제. 사용자
승인 접근 **"둘 다"** = (1) 액션 컬럼 **sticky-right 고정** + (2) 좁은 폭에서 저우선 컬럼 **반응형 숨김**.

- `Column<T>`에 `hideBelow?: Breakpoint`(데스크톱 전용 숨김)·`fixed?: 'right'`(sticky) 추가.
- `isStickyRight(c,i) = c.fixed==='right' || (!c.title && i===lastIdx)` → 무제목 마지막 컬럼(=액션) 자동 고정.
- 훅(useRef/useState/useEffect+ResizeObserver로 overflow 감지)을 **모바일 early-return 앞에** 무조건 호출.
- 4개 뷰(Agents/Collections/Sessions/Batch) 컬럼에 `hideBelow` 주석. 모바일 카드 경로는 전체 컬럼 유지.

## 잘된 점 / 배운 점

1. **근본 원인이 공용 컴포넌트 한 곳** → covering-guard. `minWidth:max-content`가 전 표면의 공통
   overflow 원천이라 `DataTable` 한 곳 수정이 *현재 안 넘치는 표(유저·허용호스트)까지* 커버. 뷰별 반복 수정 회피.

2. **측정→튜닝 루프(Ralph식)로 완료 조건 수렴.** 처음 Agents @1024가 160px 잔여(xxl 숨김만으론 부족) →
   `survey-overflow-093.mjs` 재측정 → source·exposed에 `hideBelow:'xl'` 추가 → 재측정 0. 자가판정 아닌
   *수치*가 "몇 개 컬럼을 어느 폭에서 숨길지"를 결정. 완료 조건을 처음부터 measurable로 설계한 덕.

3. **codex rung③이 내가 "허용"으로 적어둔 잔존을 실제로 닫게 밀었다.** §5에 "sticky 셀 hover 미세
   불일치 — 허용"으로 자기면죄했는데, codex가 P2로 정확히 짚음: 불투명 배경 sticky td가 tr hover색
   위를 덮어 그 셀만 하이라이트 안 됨. **싸게 닫히면 "허용"으로 적어둔 잔존도 닫아라**(probe-deeper의
   자기주장판) — `data-sticky` 마커 + hover 핸들러에서 그 셀 배경 동시 갱신(진입=hover색·이탈=컨테이너색).
   브라우저 `hover-sticky-095.mjs`로 `HOVER_OK` 검증.

4. **UX 의존 결정은 추측 말고 AskUserQuestion.** "고정 vs 숨김 vs 둘 다"는 취향/트레이드오프라 코드로
   결정 불가 → 물어서 "둘 다" 확정. (이 세션 전반의 결정.)

5. **브라우저 선제 검증.** 사용자 스샷 기다리지 않고 Playwright+시스템 Chrome으로 overflow 수치·sticky
   도달성·hover까지 직접 캡처. 880px 스샷 육안으로 sticky 그림자·숨김 레이아웃 확인.

## 다음에 주의

- 새 뷰가 `DataTable`에 무제목 마지막 컬럼을 두면 자동 sticky된다(의도). 무제목인데 액션 아닌 컬럼을
  마지막에 두지 말 것 — 필요하면 `fixed` 명시로 제어.
- `hideBelow`는 데스크톱 경로만. 모바일(md=false) 카드엔 전 필드 나오므로 카드 밀도는 별개 관리.

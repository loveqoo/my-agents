# 308 — useAsyncData 뷰 이관(단발 페치 관용구 정본화)

## 배경
스펙 184가 `useAsyncData`(단발 페치+로딩+에러+stale-race 가드)·`runWithToast`(mutation 토스트) 훅을
신설하고 3곳(Memory·AllowedHosts·useAgents) 변환. 남은 **useAsyncData 대상 11 사이트(8 파일)**를 이관해
뷰마다 복붙되던 `useState+useEffect+alive 가드+.then(set).catch(message.error)` 관용구를 단일화한다
(backlog:329 "~11개 뷰"). 서브에이전트 전수 인벤토리로 대상·비대상을 확정.

## 이관 대상 (11 사이트 / 8 파일)
1. `OverviewView.tsx` — `Promise.all([listAgents, listSessions, getBlocks])`→4 상태 파생(병렬).
2. `SessionsView.tsx` — `getSessionMessages(detail.id)`, detail 조건부, **에러 무음**(→ onError no-op).
3. `EvalMatrix.tsx`(MatrixView) — list→병렬 detail 체인, 계산 deps.
4. `EvalTrend.tsx`(CompareDrawer) — `Promise.all([getEvalRun,getEvalRun])`+정렬 로직, 두 상태.
5. `BlocksView.tsx`(loadBlocks) — `getBlocks()`, 성공경로 `syncDetail` 재싱크 → **data 후속 effect**로.
6. `BlocksView.tsx`(PersonaForm loadUsage) — `listPersonaAgents`, edit 모드, 성공 파생 setSelected.
7. `ProviderModelView.tsx`(loadProviders) — regModels 선페치+선택 부수효과.
8. `ProviderModelView.tsx`(loadAvail) — `listAvailableModels(selectedId)`, 조건부 null 클리어.
9. `CollectionsView.tsx`(load) — `Promise.all([listCollections,listModels])`+loaded 플래그+docsFor 재싱크.
10. `EvalView.tsx`(RunDrawer) — `getEvalRun(runId)`, 조건부·가장 깨끗.
11. `EvalView.tsx`(DatasetDrawer load) — `listEvalCases`+dsRuns 2차 페치, 폴링과 병존.

## 원칙(계약 보존)
- 병렬/체인 페치는 `useAsyncData(() => Promise.all([...]) / chain, deps)`로 두고 **파생 값은 data에서 계산**
  (다중 setState → 단일 data + 파생). 성공경로 부수효과(드로어 재싱크 syncDetail·docsFor)는 **`data`에
  걸린 후속 effect**로 옮긴다(reload()가 곧 재페치→data 갱신→effect 발화).
- 에러 표면 다양성 보존: 토스트 기본(errorMsg), 무음은 `onError` no-op, 지속 Alert은 `onError`.
- mutation 후 `loadX()` 호출부는 `reload()`로 치환. 폴링·리셋·form-seed effect는 **건드리지 않음**(비대상).
- 조건부 페치(runId/detail/selectedId null)는 fetcher 내부 분기(널이면 빈/널 반환)로 표현.

## OUT
- **runWithToast 이관(~26 사이트/10 파일)** — 별개 큰 표면, 별도 후속 스펙(309 후보). 이번은 useAsyncData만.
- `AgentsView.tsx`+`agents/`(커스텀 플로팅 토스트 보존)·`PagedListShell`(페이지네이션 엔진)·form-seed
  (Settings·Batch load)·`UsersView` 목록(in-place 낙관 갱신, reload 계약과 상충) — 비대상(인벤토리 확정).
- EvalView 메인 4-베스트에포트 페치·filenames AutoComplete 피더 — 단발 관용구 아님(저가치), 보류.

## 검증
- **정적**: `tsc --noEmit` 0(11 사이트 이관 후 타입·훅 규칙 무붕괴)·`vite build` ✓.
- **기능(UI 왕복)**: 브라우저로 각 이관 화면이 실제 로드·재조회 동작하는지 확인(외형 아닌 동작 —
  Overview 카운트·Sessions 메시지·Eval 드로어·Provider 목록·Blocks/Collections 로드). 사용자 미감상
  정돈까지(로딩 스피너·에러 토스트 계약 보존). learning: UI 검증은 기능 왕복으로(외형만 금지).
- **적대**: 순수 프론트 리팩터(백엔드 무변경)라 codex 트리거 약함 — stale-race 가드 보존(alive→훅 내부)과
  성공경로 부수효과 누락 여부를 이관 전후 동작 대조로 self-check.

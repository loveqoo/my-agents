# 283 — useAsyncData 뷰 이관(스펙 308)

## 무엇을 했나
스펙 184가 신설한 `useAsyncData`(단발 페치+로딩+에러+stale-race 가드)로 뷰마다 복붙되던
`useState+useEffect+alive 가드+.then(set).catch(message.error)` 관용구를 단일화. 인벤토리로 확정한
11 사이트/8 파일 중 **10건 이관, 1건(SessionsView) 정당 skip**. fast-worker에 자기완결 per-site
레시피로 위임, 메인이 diff 전수 리뷰 + tsc/build + 브라우저 기능 왕복(네트워크 페치)으로 검증.

## 배운 것 / 복리 포인트

- **"공유 훅으로 이관"은 균일 기계작업이 아니다 — 로컬 낙관 뮤테이션 상태는 훅 계약 밖**. SessionsView의
  `messages`는 fetch 외에 `applyFeedback`이 `setMessages`로 개별 메시지 `feedback`을 in-place 갱신하는데,
  `useAsyncData`는 setter를 노출 안 해 그대로 옮기면 낙관 갱신이 조용히 소실된다(재조회 전까지 UI 미반영).
  같은 레포 `useAgents.ts`에 이미 같은 사유의 선례 주석("prepend/filter/replace 로컬 뮤테이션 필요→
  useAsyncData 불가")이 있었다. **위임받은 fast-worker가 오버레이를 발명하지 않고 선례 근거로 skip+보고**한
  게 옳은 처리다 — "지시가 코드와 안 맞으면 추측 말고 보고"가 실제로 작동. 인터페이스=계약, 소비자가
  setter를 요구하면 다른 도구다. → [[structure-first-boundary-is-spec]] [[whole-fix-over-minimal-patch]]

- **훅 이관의 기능 검증은 "네가 바꾼 코드경로"=네트워크 페치를 단언한다, DOM 부수물이 아니라**. #11
  DatasetDrawer 검증에서 `.ant-drawer-content` DOM 카운트는 shared Drawer 래퍼의 클래스 불일치로 0(오탐)인데
  같은 순간 `listEvalCases` 네트워크 페치는 발화했다 — 드로어가 열리고 이관한 useAsyncData가 돈 **권위 있는
  증거는 페치**다. 외형(DOM 존재)이 아니라 동작(fetch 발생)을 겨눠야 이관 자체를 검증한다. → [[ui-verification-must-be-functional]]

- **keyed-fetch 훅은 마운트에서도 발화한다 — "N클릭=N페치" 단언은 오탐**. Provider 화면은 마운트 시
  `selectedId: null→providers[0]` effect가 돌아 첫 프로바이더의 avail을 **클릭 전에 이미** 페치한다. 그래서
  이미 선택된 'Mock LLM'을 클릭하면 `selectedId` 불변→재페치 없음(=올바름)인데, 내 첫 테스트는 "각 클릭이
  페치를 유발"을 기대해 거짓 FAIL. 고침: **deps 반응성은 페치 *횟수*가 아니라 *서로 다른 fetch 키*로 증명**
  (available-models가 고유 provider id 2종으로 나감=selectedId 반응 입증). 초기 선택 side-effect를 계산에
  넣어야 한다. → [[probe-deeper-before-concluding]]

- **useAsyncData 기본값을 effect deps에 넣으면 매 렌더 재실행(참조 신선)**. 렌더용 `data ?? []`를 그대로
  `useEffect([data])` dep로 쓰면 로딩 중 매 렌더 새 배열/객체 참조라 원치 않는 재발화(예 #5 syncDetail·#7
  선택동기화·#9 docsFor 재싱크). **defaulting 전의 raw `data`(undefined-until-resolved)를 dep으로, 기본값은
  렌더에만** 적용해 우회. 폴링 effect의 `reload`도 매 렌더 새 함수라 deps서 빼고 안정 콜백(onChanged)만
  추적(기존 컨벤션 eslint-disable). → [[context-control-propagates-to-affordances]]

- **clear-on-key-change는 `loading ? null : data`로 계약 보존**. 원본이 키(runId/group) 변경 시 이전 값을
  `setX(null)` 선행해 리페치 중 blank를 보였다면, 훅에선 `const shown = loading ? null : data`로 파생해 같은
  "전환 중 비움"을 재현(#3 EvalMatrix·#10 RunDrawer). 조건부 페치(널 키)는 fetcher 내부 분기(`runId ?
  get(runId) : Promise.resolve(null)`)로 표현.

## 검증 (사다리)
- **정적**: `tsc --noEmit` clean·`vite build` ✓(7파일 이관 후 타입·훅 규칙 무붕괴).
- **기능(브라우저 왕복, tests/browser/verify-308-useasyncdata.mjs)**: 8/11 사이트를 **네트워크 페치로
  실증** — #1 개요 카운트(5/15/130/1 숫자)·#5 블록 getBlocks→탭+카운트·탭전환·#9 컬렉션 Promise.all
  정착(5행)·#7 프로바이더 체인 페치·#8 selectedId 전환→available-models 고유 id 2종·#10 getEvalRun 발화·
  #11 listEvalCases 발화. 로딩 스피너 잔류 0·콘솔 치명 에러 0.
- **리뷰+정적만(브라우저 미실증, 정직 기록)**: #3 EvalMatrix·#4 EvalTrend(비교드로어)·#6 PersonaForm
  loadUsage는 다단 상호작용 필요라 브라우저 미실행 — diff 전수 리뷰 + tsc/build + 동일 패턴으로 커버.
- **적대**: 순수 프론트(백엔드 무변경)라 codex 트리거 약함 — stale-race 가드(alive→훅 내부)·성공경로
  부수효과 누락을 diff 전수 대조로 self-check.

## 남은 것 / 주의
- **runWithToast 이관(~26 사이트/10 파일)** OUT — 별개 큰 표면, 별도 후속(309 후보).
- **SessionsView messages** 는 로컬 낙관 뮤테이션이라 useAsyncData 부적합(선례 useAgents). 이관하려면 훅에
  setter/뮤테이터 확장이 선행(별건).
- #3/#4/#6 브라우저 미실증 — 여유 시 격자 그룹선택·비교드로어·페르소나 편집으로 왕복 보강 가능.
- dev api(8000)·vite(5173) 기동해 둠(정상 dev 상태).

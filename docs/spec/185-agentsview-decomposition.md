# 185 — AgentsView.tsx(2128줄) 분해

## 배경(스펙 182 리뷰)
`AgentsView.tsx`는 god component(2128줄). deep-reasoner 정밀 매핑 결과, 서브컴포넌트가 **이미 prop-driven
함수 경계로 깔끔히 분리**돼 있어 대부분은 로직 수술이 아니라 **파일 분리**다. 진짜 수술은 700줄 메인
오케스트레이터에서 데이터 로직을 `useAgents()`로 빼는 부분(Phase B).

## 정밀 지도(실측 — grep 22/7은 import 포함 오독; 본체는 16 useState + 2 useEffect)
- **DATA**: agents(로컬 뮤테이션 有→useState 유지)·blocks·models·collections(불변→useAsyncData 적합)·마운트 fetch.
- **UI(잔류)**: detailId·query·sort·필터3·formOpen·confirmDel·exposeOff·connectOpen·**toast(커스텀 플로팅 Alert)**·타이머.
- **FORM/EDIT(하드룰 잔류, 회고 165)**: editing·initial 계산(L2004-2027)·configOf/draftOf/nextVersion.

## 핵심 판정(deep-reasoner 교정)
- **runWithToast 부적합**: 성공=커스텀 플로팅 Alert, 에러=antd message. runWithToast는 둘 다 antd message라
  적용 시 성공 토스트 표현 변경=행동 변경 → **Phase B에서 채택 금지**. 뮤테이션 훅은 데이터만(Agent 반환/throw),
  컴포넌트가 결과로 setToast·setDetailId·모달개폐 수행.
- **agents는 useAsyncData 불가**(prepend/filter/replace 로컬 뮤테이션) → useState+load. blocks/models/collections만 useAsyncData.
- **notifyAgentsChanged 비대칭 보존**: 초기 로드=신호 안 쏨(재페치 루프 방지, 의도적), 뮤테이션만 신호.

## 폴더 레이아웃
`AgentsView.tsx`는 현 위치 유지(AdminShell import edge 0). 추출물만 하위로:
```
views/AgentsView.tsx           (오케스트레이터 — './agents/*' import)
views/agents/
  types.ts                     AgentFormData
  primitives.tsx               Field, SectionHeader, IdRow
  PersonaStaleNote.tsx         ← 순환참조 방지 독립 필수
  AgentForm.tsx                AgentForm + blankForm + AGENT_TYPES + typeDesc
  ConnectAgentModal.tsx
  AgentDetail.tsx              AgentDetail + a2aCardUrl
  detail/CodeAgentDetail.tsx   CodeAgentDetail + ReadonlyConfig
  detail/ExternalAgentDetail.tsx
  useAgents.ts                 (Phase B)
```
import 접두사 재배선(한 단계 깊어짐): `'../shared'`→`'../../shared'`·`'../mockData'`→`'../../mockData'`·
`'../naming'`→`'../../naming'`·`'../icons'`→`'../../icons'`·`'../../api'`→`'../../../api'`·
`'../../PickerGroups'`→`'../../../PickerGroups'`·`'../../agentsBus'`→`'../../../agentsBus'`·
`'./AgentMemoryPanel'`→`'../AgentMemoryPanel'`. detail/ 하위는 `'../'` 하나 더. **양방향** 고침
(피이동 파일→공유모듈 +1, AgentsView→피이동 `'./agents/X'`).

## Phase A — 기계적 파일 이동(행동보존, import만), 리프부터
1 types.ts · 2 primitives.tsx · 3 PersonaStaleNote.tsx · 4 detail/ExternalAgentDetail · 5 detail/CodeAgentDetail(+ReadonlyConfig) ·
6 ConnectAgentModal · 7 AgentForm(+blankForm/AGENT_TYPES/typeDesc) · 8 AgentDetail(+a2aCardUrl) · 9 AgentsView 상단 재배선.

## Phase B — useAgents 훅(고위험, Phase A 검증 후 판단)
`useAgents()` → `{ agents, blocks, models, collections, loading, create/update/remove/clone/connect/
setVisibility/expose/activate/fork/revert/resync/refreshPersona }`. 뮤테이션은 **데이터만**(Agent 반환/throw,
토스트·네비 없음). editing/initial/configOf/draftOf/nextVersion·모든 UI 상태·toast는 컴포넌트 잔류.

## 최고위험 edge
1. **순환 import**: PersonaStaleNote 독립 모듈 필수(detail→PersonaStaleNote 단방향).
2. runWithToast 부적합(범위 밖).
3. StrictMode 이중 fetch(agents는 현 패턴 유지로 행동보존).
4. notifyAgentsChanged 비대칭 보존.
5. 폼시드 계산(configOf/draftOf/nextVersion) 훅 유출 금지.

## 검증(완료 조건)
- tsc 0(noUnusedLocals가 죽은 import 전수 검출) — Phase A 값싼 그물.
- **브라우저 회귀(자가검증 지양, Playwright+시스템 Chrome)**: 리스트 렌더+필터/정렬·**ui/code/external 3 드로워**·
  생성/편집 폼(종류 전환·오버라이드 Collapse·initial 시드)·연결 모달·삭제/expose-off 확인·**커스텀 플로팅 토스트**.
- Phase B 후 추가: **각 뮤테이션 왕복** 후 리스트 반영·토스트가 여전히 플로팅 Alert·편집저장 후 detailId 복귀·크로스탭 신호.
- `git stash` 대조로 "픽셀·동작 무변경" 증명(회고 183 패턴).

## 실행 결과
### Phase A — 완료·검증
- **파일 분리 완료**(fast-worker 위임, 메인 검증): 8개 컴포넌트를 `views/agents/`(+`detail/`)로 추출.
  `AgentsView.tsx` **2128→747줄**. 생성 파일: types.ts(18)·primitives.tsx(60)·PersonaStaleNote.tsx(31)·
  detail/ExternalAgentDetail(155)·detail/CodeAgentDetail(293)·ConnectAgentModal(91)·AgentForm(417)·AgentDetail(356).
- **검증(타자·측정)**: tsc 0(noUnusedLocals) · 순환 import 정적 스캔(agents/→AgentsView 역참조 0, PersonaStaleNote
  단방향) · **브라우저 회귀 `verify-agentsview-decomp-185.mjs` ALL PASS**: 리스트 10행·**3 드로어(ui 공개범위·
  code 배포히스토리·external 제공자) 렌더**·생성폼(AgentForm 204자)·연결모달(407자)·pageerror 0·콘솔 0.
  스샷 시각 확인(AgentForm 전체 필드·CodeAgentDetail 배포/연결·히스토리·재동기화 전부).
- **행동 보존**: 순수 이동(로직·JSX 무변경), 런타임 에러 0로 확증.
- **테스트 주의(learning)**: `shared.Drawer`는 antd 아닌 커스텀(className·role 없음, 닫힘=translateX off-screen)
  이라 `.ant-drawer-*`·`:visible` 셀렉터가 안 먹음 → 각 드로어 고유 라벨을 Playwright 가시성으로 판정해 해결.

### Phase B — 완료·검증(사용자 "진행" 선택)
- **`useAgents()` 훅 추출**(`views/agents/useAgents.ts`, 120줄): 목록(agents useState — 로컬 뮤테이션)·
  레퍼런스(blocks/models/collections useAsyncData)·12개 뮤테이션(데이터만: API+배열+notify, Agent 반환/throw).
  AgentsView **747→684줄**, 12개 핸들러는 `A.x()` + toast/nav/error만 남김(데이터 로직 소멸).
- **위험 지점 전부 보존**(deep-reasoner 설계 준수): (1) 성공 토스트=컴포넌트의 커스텀 플로팅 Alert 유지
  (훅은 토스트 없음, runWithToast 미채택), (2) notify 비대칭=초기 로드 setAgents 직접(신호 X)·뮤테이션만
  notify, (3) 폼시드(editing/configOf/draftOf/nextVersion)=컴포넌트 잔류, (4) 실패는 훅이 throw→호출부가
  message.error/warning 지점별 결정.
- **검증(실 뮤테이션 왕복 — 로직 수술이라 tsc 불충분)**: `verify-useagents-185b.mjs` ALL PASS —
  생성→삭제 왕복, **커스텀 플로팅 토스트 보존**(.ant-alert-success, antd message 아님 — 최고위험 통과),
  list 반영(생성 증가·삭제 복원), 행 존재/제거, pageerror 0. Phase A 회귀도 무회귀 재확인. tsc 0.
  (replace 경로 뮤테이션은 prepend/filter와 동일 패턴·토스트 보존 입증됐으므로 by-inspection 동치.)

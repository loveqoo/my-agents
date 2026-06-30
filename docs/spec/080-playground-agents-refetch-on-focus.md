# 080 — Playground 에이전트 변경 전파(BroadcastChannel + 포커스 백스톱) (스펙 078 후속 버그)

## 배경

사용자 보고: "에이전트 초안을 활성화한 뒤에 플레이그라운드에 반영 안 됨. '미반영 초안'으로
남아있음. 새로고침해도 동일함."

스펙 078이 단 "미반영 초안" 배지(`hasDraft(agent) = versions.some(v => v.status==='draft')`)는
*로직은 정확*하다. 문제는 그 진실원을 **언제 다시 읽느냐**다.

## 현 배선 (실측 — 추측 금지)

- `Playground.tsx`는 **마운트 시 1회만** `listAgents()`를 부른다(Playground.tsx:63-77). 이후
  `agents` 상태는 그 스냅샷에 고정된다. 배지는 `activeAgent = agents.find(id)`의 versions로 계산.
- `listAgents = () => j<Agent[]>('/agents')` — mock 폴백 없는 순수 fetch(api.ts:278).
- 응답 헤더에 `Cache-Control`/`Last-Modified`/`ETag`/`Expires` **전무**(실측) → HTTP 캐시 아님.
- 같은 탭에서 Agents→Playground 뷰 전환은 `AdminShell`이 활성 뷰만 마운트(`{views[view]}`,
  AdminShell.tsx:317)하므로 **remount→재페치**라 자연히 해소된다(단일 탭 정상, UI 재현 확인).
- **그러나 별도 탭/창**(Agents와 Playground를 나란히 띄워 비교)에서 activate하면, Playground 탭은
  remount되지 않아 마운트 시점 스냅샷(draft 포함)을 계속 들고 → 서버가 draft를 비웠는데도 배지가
  남는다. 사용자의 "draft 없는데 배지만 뜸"(콘솔 스니펫으로 서버 draft 0 확인)·"새로고침해도 동일"
  (그 탭의 풀 리로드가 아니었을 개연)과 정합.

### 루트원인 재현 (브라우저 측정)

```
draft 생성        → server draft=v5
STEP2 배지=1      (draft 있음 → 정상 점등)
API activate      → server draft=[]   (서버 깨끗)
STEP4 배지=1      ← STALE. Playground in-memory agents가 외부 activate를 모름 (버그)
STEP5 배지=0      (풀 리로드 = 신선 fetch → 해소)
```

→ 갭은 배지 로직이 아니라 **소비 표면이 진실원을 재조회하지 않음**. 스펙 078은 *신호를 소비
표면에 두었고*(learning 081), 080은 그 신호를 *신선하게 유지*한다 — 같은 원리의 시간축.

### 설계 선택 — 왜 이벤트 전파인가 (사용자 피드백)

초안은 포커스 재페치만 두었으나, 사용자가 *"SPA니까 변경이 일어나면 다른 컴포넌트에 이벤트를
전달해 갱신해야 하지 않나"*를 지적. 핵심 뉘앙스: **같은 탭 안**은 AdminShell이 활성 뷰만 마운트해
뷰 전환=remount→재페치라 이미 정합되고, in-app 이벤트도 닿는다. 그러나 **버그는 별도 탭/창**(JS
컨텍스트 분리)이라 in-app 이벤트/공유 store가 *건너가지 않는다*. 따라서 이벤트는 탭 경계를 넘어야
하고 그 수단이 **`BroadcastChannel`**(동일 출처 다른 컨텍스트로 메시지 전달)이다. 즉시 전파가 1차
경로, 포커스/가시성 재페치는 미지원 환경·놓친 메시지를 메우는 **백스톱**.

## 목표 (완료 조건 — 측정 가능)

1. **이벤트 전파**: Agents 뷰가 활성화·편집·생성·삭제 등 변경 직후 `notifyAgentsChanged()`를 쏘면,
   다른 탭/창의 Playground가 `onAgentsChanged`로 받아 목록을 재페치 → 배지가 즉시 정합된다.
2. **백스톱**: Playground 탭이 다시 보이거나(visibilitychange→visible) 포커스를 얻으면 재페치 →
   BroadcastChannel 미지원 환경·놓친 신호를 탭 복귀 시 메운다.
3. 재페치는 **목록 메타만** 갱신한다 — 선택(`activeId`)·대화(`convos`)·스트리밍은 보존(무회귀).
4. 회귀 없음: 단일 탭 마운트 동작·정상 배지 점등/소거는 그대로.

## 조치

### 프론트 — agentsBus.ts (신규)

탭 간 신호 버스. `BroadcastChannel('agents')` 하나로 송신(`notifyAgentsChanged`)·수신
(`onAgentsChanged`). 미지원 환경은 no-op(백스톱이 커버). 포스트한 그 컨텍스트엔 안 오지만
송신=Agents, 수신=Playground라 무방.

### 프론트 — AgentsView.tsx (송신)

변경 직후 신호 발사. 공통 단일변이 경로 `replaceAgent`(활성화·초안저장·되돌리기·포크·재동기·노출토글)에
한 줄, 그리고 `save`의 생성 분기·`doDelete`·`connectAgent`에 각각 `notifyAgentsChanged()`. 초기 로드는
신호 없음(자기 자신만 채움).

### 프론트 — Playground.tsx (수신 + 백스톱)

마운트 1회 fetch 옆에 구독+포커스/가시성 useEffect 추가:

```jsx
// 소비 표면 자가정합(스펙 080): 다른 탭/뷰의 편집·활성화를 Playground가 모른 채 마운트 스냅샷을
// 들고 있으면 '미반영 초안' 배지(078)가 stale하게 남는다. 목록만 재페치해 서버 진실원과 정합.
// (1) BroadcastChannel 즉시 전파, (2) 포커스/가시성 백스톱. 선택·대화 보존(목록 메타만 setAgents).
useEffect(() => {
  const refetch = () => {
    listAgents().then(setAgents).catch(() => {})
  }
  const onVisible = () => {
    if (document.visibilityState === 'visible') refetch()
  }
  const unsub = onAgentsChanged(refetch)
  document.addEventListener('visibilitychange', onVisible)
  window.addEventListener('focus', refetch)
  return () => {
    unsub()
    document.removeEventListener('visibilitychange', onVisible)
    window.removeEventListener('focus', refetch)
  }
}, [])
```

`activeId`는 건드리지 않으므로 `activeAgent = agents.find(id)`가 신선 versions로 재계산 →
배지만 갱신. 에이전트가 외부에서 삭제됐으면 자연히 null(허용, 기존과 동일 위험도).

## 검증

- **타입**: `tsc --noEmit`(admin) 무에러.
- **브라우저(Playwright + 시스템 Chrome)**: 루트원인 재현에 *신호*를 끼워 수정 증명 —
  ① draft 생성→Playground TARGET 선택→배지=1, ② API activate(서버 draft 0)→배지 여전히 1(stale),
  ③ `BroadcastChannel('agents').postMessage` 또는 `window` focus 디스패치→재페치→**배지=0**(수정
  동작). 셀렉터 0개=측정실패(learning 080).
- **무회귀**: 정상 배지 점등(draft 있는 에이전트 선택 시 1)·소거(활성만이면 0) 유지.

## RBAC 체크리스트 적용 여부

**관련 없음(표시/조회 전용)** — 기존 `GET /agents`를 한 번 더 부를 뿐, 새 입구·쓰기·소유권 경계
변경 없음. 트리거(유저별 데이터 쓰기·user_id 컬럼·소유 헬퍼) 미해당. 스펙 078과 동일하게 표시층.

## 완료 체크
- [x] agentsBus.ts(BroadcastChannel 송수신, 미지원 no-op)
- [x] AgentsView.tsx 송신(replaceAgent·생성·삭제·connect 후 notifyAgentsChanged)
- [x] Playground.tsx 수신+백스톱 useEffect(목록 메타만, 선택·대화 보존)
- [x] tsc 무에러 + 브라우저(stale 재현→신호→배지 0, 정상 점등/소거 무회귀)
      → `tests/browser/shot-draft-staleness-080.mjs` RESULT=PASS:
      PART1 STALE 재현(신호 없이 배지 1)→포커스 백스톱 배지 0,
      PART2 두 페이지 BroadcastChannel 전파(포커스 없이) 배지 0,
      PART3 무회귀(활성만=0 / draft=1).

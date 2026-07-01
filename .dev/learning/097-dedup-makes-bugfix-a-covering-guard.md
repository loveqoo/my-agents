# 097 — 중복을 없애면 버그 수정도 covering-guard가 된다 / 비동기 결과 setState엔 요청-시퀀스 가드

> 스펙 097, retrospect 078. 프런트 리팩터. 참고: learning 069/070/096(covering-guard), 093(비동기 리스트 stale-idx 경합).

## 상황

컬렉션 "검색 시험"(072)과 메모리 "조회 시험"(084) 드로어가 ~90% 동일한데 두 벌로 존재(084가 072를 수동
미러링)해 라벨·구조가 갈렸다. 공유 제네릭 셸 `RetrievalTestDrawer<H>`로 통합하고 두 드로어를 얇은 어댑터로
축소. codex 적대 리뷰가 통합 셸에서 P1 하나를 표면화했다.

## 배운 것

### 1. 중복 제거 = 버그 수정의 covering-guard

codex가 짚은 P1: `const res = await onSearch(q,l); setOut(res)` — 스코프 A로 검색을 띄운 채 B로 전환하면,
늦게 도착한 A의 응답이 B 화면에 얹힌다(stale-async 스코프 유출). 결정적인 사실: **이건 통합이 만든 회귀가
아니라 원본 072·084 두 드로어에 *각각* 잠복하던 동일 결함**이었다(`git show HEAD:…RecallDrawer.tsx`로 확인 —
원본도 무가드 `setOut(res)`).

두 벌이었다면 두 곳을 따로 고쳐야 했고 한 곳을 빠뜨리면 드리프트. 공유 셸이 된 순간 `reqSeq` ref 가드
**한 번**으로 양쪽이 덮인다. covering-guard(learning 069/070/096)는 "새 기능이 규칙을 자동 상속"으로만
알려졌지만, **기존의 숨은 공통 결함을 한 번에 고치는 레버**이기도 하다. 일반화: *중복을 단일 컴포넌트로
접으면 그 컴포넌트에 대한 모든 미래 수정(기능·버그·성능)이 전 사용처에 자동 적용된다.* 리팩터의 배당은
"코드 줄 감소"가 아니라 "수정 지점 = 1".

### 2. 비동기 결과를 상태에 쓰는 UI엔 요청-시퀀스 가드가 기본값

`await` 뒤 `setState(result)`는 항상 "이 응답이 아직 최신 요청인가?"를 물어야 한다. 스코프(질의 대상)가
전환되거나 후속 요청이 겹치면 늦은 응답이 남의 화면을 덮는다. 최소 관용구:

```tsx
const reqSeq = useRef(0)
useEffect(() => { reqSeq.current++; /* 스코프 전환 시 in-flight 무효화 */ }, [scopeKey])
const run = async () => {
  const seq = ++reqSeq.current
  const res = await onSearch(...)
  if (seq !== reqSeq.current) return   // 밀림 — 늦은 결과 폐기
  setOut(res); /* finally도 seq===reqSeq.current일 때만 searching=false */
}
```

learning 093(비동기 재계산 리스트의 stale 인덱스)과 같은 뿌리 — **"이벤트 발생 시점 ≠ 관찰값 확정 시점"**.
happy-path(한 스코프에서 한 번 검색)에선 절대 안 보이고, 스코프 전환·연타에서만 샌다. 적대 타자(codex)가
"보장 목록의 여집합"을 봐야 잡힌다.

### 3. antd 6 검증 셀렉터 실측 함정 두 개

브라우저 검증에서 "요소는 DOM에 있는데 Playwright 셀렉터가 못 잡아 조용히 30s 타임아웃"이 두 번:
- **아이콘+텍스트 버튼**: `<Button icon=<Icon/>>검색</Button>`의 접근성 이름이 `검색`과 정확히 안 맞음 →
  `getByRole('button',{name:'검색',exact:true})=0`. loose(`{name:'검색'}` 또는 `hasText`)로 매칭.
- **드로어 본문 클래스**: antd6는 `.ant-drawer-content`가 아니라 `.ant-drawer-section`(루트는
  `.ant-drawer.ant-drawer-open`). content 클래스로 스캔하면 항상 null.

둘 다 "실패가 조용함"(빈 결과·타임아웃)이라 스크립트 초록/무응답으로 위장. **추측 말고 DOM 덤프로 실측**
(버튼 aria-label·클래스 나열, `boundingBox`, 클릭 후 `.ant-drawer` 계열 클래스 전수)하면 즉시 드러난다.

## 훅

- 중복을 공유 컴포넌트로 접으면 그 컴포넌트의 버그 수정 1회가 전 사용처를 덮는다(covering-guard의 버그판).
  리팩터 중 적대 리뷰를 붙이면 "원본들에 잠복하던 공통 결함"을 통합 지점에서 한 번에 봉합할 수 있다.
- `await` 뒤 `setState`엔 요청-시퀀스(또는 scopeKey 캡처) 가드를 기본으로 — 스코프 전환/연타에서만 새는
  stale-async 유출을 막는다(learning 093과 동근).
- 브라우저 검증이 "요소 있는데 못 잡음"으로 조용히 실패하면 DOM을 실측하라: 아이콘버튼=loose 매칭,
  antd6 드로어 본문=`.ant-drawer-section`/`.ant-drawer.ant-drawer-open`.

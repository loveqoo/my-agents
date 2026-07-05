# 184 — useAsyncData/runWithToast 공용 훅(프론트 복붙 흡수)

## 배경(스펙 182 리뷰)
PagedListShell을 안 쓰는 ~14개 뷰가 `listX().then(setState).catch(message.error)` + `alive` 가드 +
로딩 state를 **뷰마다 손으로** 반복(.catch 34곳·message.error 83곳). mutation도 try/catch/토스트 51곳
반복. 공유되는 건 렌더 트리가 아니라 **state+effect 로직** → HoC가 아니라 **훅**이 맞다(리뷰 결론:
HoC 니치는 AuthGate render-prop·PagedListShell 제네릭이 이미 덮음, 권한 게이트는 표현 분기).

## 설계
`admin/src/hooks.ts`:
- `useAsyncData<T>(fetcher, deps?, opts?)` → `{ data, loading, error, reload }`. 단발 페치+로딩+에러+
  **stale-race 가드**(alive)를 흡수. deps/reload로 재조회. **에러 표면은 소비자 소유**(onError 위임 —
  없으면 기본 토스트) → 지속 Alert vs 토스트 계약 다양성 보존(주입식 HoC는 이 다양성을 죽인다).
- `runWithToast(fn, {success?, error?})` → `Promise<boolean>`. mutation을 성공/실패 토스트로 감싸고
  성공 여부 반환(모달 닫기·폼 초기화·reload 분기용). 버튼 로딩 state는 호출자 소유(관심사 분리).

## 검증(완료 조건)
- 추상 무누수: **최소 2개 이질 소비자**로 증명(코드베이스 "둘째 구현으로 누수 측정" 규율).
- tsc 0(noUnusedLocals 포함) + 브라우저 렌더·데이터 로드 확인(사용자 지시: 적극 브라우저 검증).

## 실행 결과
- **완료**: 훅 2개 추가. 소비자 **3곳** 변환으로 추상 검증:
  - `AllowedHostsView` — mutation(add/delete)+reload 소비자(runWithToast+useAsyncData 둘 다).
  - `MemoryView` 2탭 — 표시-페치 소비자(하나는 fetcher에서 `.filter` 파생 — 변환 스트레스 테스트).
- **검증**: tsc 0 · `tests/browser/verify-hooks-183.mjs` ALL PASS(A1~3 허용호스트 렌더·로드·reload버튼,
  M1~2 메모리 탭/Select 렌더·로딩 안멈춤, Z 훅유발 콘솔에러 0) · 스샷 2장 시각 확인(테이블 2행 로드·
  메모리 탭 정상). 사전 노이즈(배경 401·antd6 Alert deprecated 경고)는 훅과 무관 — 필터 명시.
- **남은 것(별도 단위)**: 나머지 ~11개 뷰 점진 이관(기계적—fast-worker 위임 후보)·**AgentsView.tsx
  2128줄 분해**(→`useAgents()` 훅=useAsyncData 첫 대형 소비자). 대형·고위험이라 전용 패스 권장(백로그).

## 왜 HoC가 아닌가(사용자 질문 "HoC 필요한 곳" 답)
리뷰 결론=**불필요**. 이유: (1) 공유 대상이 로직(state/effect)이지 렌더 래핑이 아님→훅. (2) HoC 니치
(조건부 렌더·권한 게이트)는 AuthGate(render-prop)·PagedListShell(제네릭)·`<IfCan>` 인라인이 이미 덮음.
(3) HoC를 넣으면 에러 표면·권한 분기의 다양성을 주입식으로 획일화→과설계=신념("구조가 당장보다") 배신.

# 078 — 검색시험 드로어 통합(컬렉션·메모리) + 통합이 드러낸 잠복 레이스

> 스펙 097(제안 #7). learning 097. 참고: spec 072(RAG 검색시험 shared-core)·084(메모리 회상시험=072 수동 미러)·
> covering-guard(learning 069/070/096).

## 무엇을

메모리 뷰 "조회 시험"(RecallDrawer, 084)이 컬렉션 "검색 시험"(SearchDrawer, 072)을 **손으로 미러링**한
탓에 UI가 갈렸다(top_k/limit·검색/조회·유사도/관련도·결과/회상·filename vs scope·type). 072가 백엔드에만
적용한 "shared core"를 UI로 확장 — 공유 제네릭 셸 `RetrievalTestDrawer<H>`를 추출하고 두 드로어를 얇은
어댑터로 축소(각 도메인 라벨·renderMeta·enabled 계약만 props 주입). 어댑터 순증가 **-147줄**(중복 셸 제거).

## 잘된 것

- **covering-guard UI판**: 셸 1개 = 라벨/구조/동작의 단일 레버. 이후 한 곳 수정이 양쪽 반영, drift 0.
  95번(레이아웃 불변식을 공용 DataTable에)의 형제 — "규칙을 뷰마다 반복 말고 공용 렌더에".
- **정직성 계약(084)을 어댑터 경계로 보존**: 셸은 onSearch가 돌려준 `{results, enabled}`를 불투명하게
  받아 `!enabled`→disabledAlert / `enabled&&빈`→인라인 "회상 없음"으로 분기. 메모리 어댑터는 `out.enabled`를
  그대로 통과, 컬렉션 어댑터는 상수 `true` 반환(→disabledAlert 미주입 안전, 비활성 안내는 !ready preAlert로).
  None≠[]가 통합에서 안 깨짐. 브라우저에서 0건 결과가 인라인(alertTitle=null)으로 렌더돼 실증.
- **브라우저 실검증까지 밀어붙임**: 시드 데이터(docs_kb ready 컬렉션·Personal Secretary 에이전트)로 두
  드로어를 실제로 열어 도메인 라벨·결과카드·카운트·스코프리셋을 눈으로+구조 데이터로 확인.

## 아팠던 것 / 배운 것

- **통합이 "숨은 공통 결함"을 한 번에 고칠 기회를 줬다.** codex rung③이 P1을 짚음: `await onSearch` 후
  무가드 `setOut(res)` — 스코프 A 검색 중 B로 전환하면 늦게 온 A 결과가 B 화면에 뜨는 stale-async
  스코프 유출. **이건 회귀가 아니라 원본 072·084 두 드로어에 *각각* 잠복하던 결함**이었다(git show로 확인).
  두 벌일 땐 양쪽 다 고쳐야 했을 것을, 공유 셸이라 `reqSeq` ref 가드 한 번으로 양쪽 봉합. → **중복을
  없애면 버그 수정도 covering-guard가 된다**(learning 097).
- **antd 6 검증 셀렉터 함정 두 개**(learning 097): (1) 아이콘+텍스트 버튼은 접근성 이름이 `검색`과
  정확히 안 맞아 `getByRole(name,{exact:true})=0` — loose 매칭 필요. (2) 드로어 본문 클래스가
  `.ant-drawer-content`가 아니라 `.ant-drawer-section`(antd6). 둘 다 "요소는 있는데 셀렉터가 못 잡는"
  형태라 happy-path 스크립트가 조용히 타임아웃 → DOM 덤프로 실측하고 고침(추측 말고 측정).
- **스크래치 다수 생성**: probe/dbg 스크립트를 5개 만들며 셀렉터를 좁혀갔다. 회고 전 tests/browser에서
  정리하고 최종 `verify-drawers-097.mjs` 한 개만 자산으로 남김.

## 다음에

- 브라우저 검증 스크립트에 **antd6 드로어 헬퍼**(루트=`.ant-drawer.ant-drawer-open`, 본문 텍스트 스캔)와
  **아이콘버튼 loose 매칭** 관용구를 재사용. tests/browser에 공용 헬퍼로 뽑을지 검토(반복되면).
- 레이스 가드(`reqSeq`)는 "비동기 결과를 상태에 setState하는 모든 드로어/패널"의 공통 과제 — 새 검색류
  UI 추가 시 셸을 재사용하면 자동 상속.

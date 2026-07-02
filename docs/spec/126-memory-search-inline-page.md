# 126 — 메모리 조회(검색)를 드로어 → 상세 페이지 인라인으로

## 배경 / 왜
사용자: "드로워 말고 상세 페이지로 만들어 영역을 넓게 활용하자." 메모리 "조회 시험"이 640px 드로어에
갇혀 넓은 질의·결과·진단(125)을 좁게 봤다. 레이아웃 선택: **위아래 스택(검색이 위)**.

## 설계
검색시험 공유 셸(`RetrievalTestDrawer`, 097)은 **컬렉션 검색과 공유**된다. 컬렉션은 드로어 유지,
메모리만 인라인으로 바꾸려면 알맹이를 분리한다:

- **`RetrievalTestPanel`(신설)** — 드로어에서 본문(질의 입력·결과·진단·지속오류·stale-async reqSeq)만
  분리한 공용 알맹이. 타입(`RetrievalHit`·`SearchDiag`·`RetrievalOut`·`RetrievalTestPanelProps`)도 이리로.
- **`RetrievalTestDrawer`** — 이제 `RetrievalTestPanel`을 antd Drawer로 감싼 **얇은 래퍼**(open/title/
  onClose만 추가). 타입 재노출로 기존 import 경로 보존 → **컬렉션(CollectionsView) 무변경**.
- **`RecallPanel`(신설, `RecallDrawer` 대체)** — 메모리 어댑터(hint·disabledAlert·라벨·renderMeta·diag
  통과)를 `RetrievalTestPanel`에 주입한 인라인 패널. `RecallDrawer.tsx` 삭제.
- **`UserMemoryPanel`·`AgentMemoryPanel`** — "조회 시험" 버튼+드로어 제거, 대신 **상단 Card("회상 시험")에
  `RecallPanel` 전체 폭**, 아래 기억 목록(유저=조회/교정/삭제, 에이전트=+추가). recall 상태 제거.

## 검증
- **브라우저(shot-memory-search-page-126)**: 유저 선택 시 (i) 드로어 없음, (ii) "회상 시험" 카드가 페이지
  상단 인라인, (iii) 질의→조회→진단 패널 지속 표시, (iv) 비밀 미노출. (125 드로어 shot 대체.)
- **tsc**: 프롭 드리프트 0(RetrievalTestPanelProps로 드로어·인라인 공유 계약 고정).
- **무회귀**: 컬렉션 검색 드로어는 같은 알맹이라 UI drift 0(래퍼만 추가). 메모리 검색 로직(125 diag·
  실패≠0건·stale-async)은 알맹이째 이동 — 무변경.
- **적대(codex)**: 알맹이 추출이 동작을 바꿨나·드로어 래퍼가 컬렉션 계약(open/title/onClose·enabled 항상
  true) 보존하나·reqSeq stale-async 여전한가·prop 누락 없나.

## 비목표 (OUT)
- 컬렉션 검색도 페이지화 — 사용자는 메모리만 요청. 컬렉션은 드로어 유지(문서 관리 드로어 맥락).
- 좌우 2단 레이아웃 — 사용자가 위아래 스택 선택.

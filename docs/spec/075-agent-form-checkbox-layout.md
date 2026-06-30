# 075 — 에이전트 생성/수정 폼 체크박스 행 레이아웃 깨짐 (이슈 4)

## 배경

사용자 보고: "에이전트 생성 드로어에서 레이아웃 깨짐". 브라우저 캡처(데스크탑 1280·모바일 390)로
확정: **메모리 타입**의 "단기(세션)" 라벨이 **글자 단위로 세로 줄바꿈**("단/기/(세/션)")된다.

원인은 두 겹(추측 아님 — 캡처+코드로 확정):

1. **flex 폭 경쟁** — `AgentsView.tsx:170-182` 각 행이 외부 `<label style={display:flex}>` 안에
   antd `Checkbox`(이름 라벨 포함)와 설명 `<span>`을 형제로 둔다. 둘이 같은 행에서 폭을 다투고
   Checkbox 래퍼가 `flex-shrink:1`(기본)로 줄어들며, 이름 span이 최소폭까지 눌려 글자단위 세로 래핑.
   짧은 이름(RAG `docs_kb`)은 안 깨졌을 뿐 **같은 잠재버그**(193-206 RAG, 244-266 권한 동일 구조).
2. **중첩 `<label>`** — 외부 `<label>` 안에 antd Checkbox가 자체 `<label class=ant-checkbox-wrapper>`를
   렌더 → 중첩 label(invalid HTML, 클릭 이중토글 위험).

## 목표 (완료 조건 — 측정 가능)

생성 폼 데스크탑 1280·모바일 390에서 모든 체크박스 행의 이름이 **한 줄**(글자단위 세로 래핑 0).
중첩 `<label>` 제거(행당 `<label>` 1개). 토글·기존 동작 무회귀, 타입체크 통과.

## 조치 (AgentsView.tsx — AgentForm)

3개 체크박스 행 그룹(메모리 170-182 / RAG 191-218 / 권한 244-266)을 동일 패턴으로 재구조화:

- 외부 `<label>` 제거. **이름·설명을 antd `Checkbox`의 children 안에 세로 스택**으로 넣는다
  (`<Checkbox><span flexColumn><span 이름/><span 설명/></span></Checkbox>`). flex 경쟁·중첩 label 동시 해소.
- Checkbox 래퍼 `style={{ alignItems: 'flex-start' }}`로 멀티라인 설명에서 박스가 상단 정렬.
- 권한 행은 설명 대신 승인자 Tag → 이름+Tag를 children 안에 배치.

## 검증 (브라우저 실측 — verify-ui-in-browser)

- `tests/browser/shot-agent-create.mjs`(신규) — 생성 모달 캡처(데스크탑/모바일) + 메모리 라벨
  `boundingRect.height`로 세로래핑 검출(1줄 ≈ 한 줄 높이). 토글 후 체크 반영 확인.
- 타입체크(tsc --noEmit) 통과.

## RBAC 체크리스트 적용 여부

**관련 없음** — 순수 표현(presentational) 변경. 소유권/권한 경계 불변.

## 완료 체크
- [x] 메모리·RAG·권한 행 재구조화(이름+설명 children 스택, 외부 label 제거)
- [x] 데스크탑 1280·모바일 390 캡처 — 이름 한 줄(단기(세션) h 62→22), VERTICAL_WRAP_BROKEN=[]
- [x] 토글 무회귀(changed=true), 타입체크 통과

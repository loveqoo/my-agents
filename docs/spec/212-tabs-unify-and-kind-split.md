# 스펙 212 — 탭 UI 통일 + RAG/평가 kind 탭 분리

## 배경 (사용자 요청 2026-07-07, 항목 8·9·10)

탭 패턴 3종 혼재(메모리=Tabs, 승인=Segmented, 세션=Radio.Group). RAG는 문서/엔티티가 한 리스트에
섞임(kind 배지뿐). 평가도 에이전트/RAG 문제집이 한 리스트(kind 태그뿐).

사용자 결정(AskUserQuestion): **역할별 2종** — "다른 데이터 집합 전환"=**Tabs**, "같은 목록의
필터"=**Segmented**.

## 기준 (admin/CLAUDE.md에 추가할 규칙)
- 데이터 집합 전환(내용 자체가 바뀜) → `Tabs`.
- 같은 목록의 필터/모드(부분집합·표현만 바뀜) → `Segmented`.
- Radio.Group을 탭/필터 용도로 쓰지 않는다.

## 변경

### A. 기존 화면 정렬 (항목 9)
- 승인(ApprovalsView) 대기 중/처리됨: Segmented → **Tabs**(다른 데이터 집합).
- 세션(SessionsView) status 필터: Radio.Group → **Segmented**(같은 목록의 필터, counts 배지 유지).
- 전수 감사: UsersView(Tabs+Segmented)·DebugChat·Inspector·메모리 하위 검색모드(Segmented)를
  기준에 대조 — 어긋나는 곳만 정렬, 부합하면 무변경(목록 명시).

### B. RAG kind 탭 (항목 8)
- CollectionsView에 **Tabs: 문서 임베딩 / 엔티티 임베딩**(kind=document|entity, 생성 후 불변이라
  데이터 집합 전환에 해당). 리스트·생성 버튼은 현재 탭의 kind 컨텍스트를 따름(생성 모달 kind 프리셀렉트).

### C. 평가 kind 탭 (항목 10)
- EvalView 문제집 리스트를 **에이전트 평가 / RAG 평가** 탭으로 분리. 상위 Tabs(문제집/격자/이력)가
  이미 있어 중첩이 됨 — 구현 시 시각 확인 후 하위 레벨 표현(child Tabs vs 재편)을 스샷으로 사용자
  확인 1회. kind 컬럼 태그는 탭 분리 후 제거.

## 완료 기준
1. 브라우저 e2e: 승인=Tabs·세션=Segmented·RAG 2탭·평가 kind 분리 각 동작(전환·counts·생성 컨텍스트).
2. 감사 목록: 화면별 패턴이 기준 2종 중 하나로 분류됨(예외 0 또는 사유 기록).
3. tsc 0, ui-audit(screens) 무회귀.

## OUT
- 백엔드 무변경(전부 프론트).
- 평가 상위 정보구조 재설계(격자 탭 위치 등)는 시각 확인에서 필요 판단 시 별도.

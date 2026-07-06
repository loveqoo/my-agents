# 회고 179 — 평가 UX 개선 3건: RAG 컬렉션 고정 · 성적 추이 구분 · 생성 로딩 (스펙 193)

## 무엇을 했나
실사용 문의 3건: (1) RAG 문제집 실행 시 컬렉션을 매번 고르는 게 이상(모델을 고르게 해달라), (2) 성적
추이가 문제 카드와 UI가 비슷해 구분 안 됨, (3) 문제 자동 생성 중임을 유저가 모름. → (1) `EvalDataset.
collection_id` 고정(마이그레이션+생성 저장+실행 UI 칩+구버전 lazy 저장), (2) 성적 추이 박스 옅은 배경
+강조 바+아이콘, (3) `generating` 신호+목록 배지+드로어 antd `Skeleton`+2.5s 폴링. 단위 9/9·e2e 15/15·
무회귀(격리 확인).

## 배운 것

### 1. 사용자 요구의 "전제"를 도메인 코드로 검증한 뒤 방향을 맞춘다 — 문자 그대로 구현 금지
요구는 "실행 시 컬렉션 말고 **모델**을 고르게"였다. 그대로 만들려다 코드를 확인하니 전제가 둘 다 어긋났다:
(a) 문제집은 컬렉션을 **저장조차 안 했다**(실행마다 param) — "이미 지정"이 시스템엔 없었다. (b) RAG 러너는
`search_collections([collection], query)`뿐이라 **챗 모델 축이 없다** — 검색 정확도는 컬렉션(문서+임베딩)이
정한다. 사용자에게 이 사실을 그대로 전하고 물으니 "컬렉션 고정"으로 수렴했고, 보충("임베딩 모델은 한 번
정하면 수정 안 함")이 방향을 확증했다. **교훈: "X를 Y로 바꿔달라"는 요구를 받으면, X/Y가 그 도메인에서
실제 어떤 축인지 먼저 코드로 확인한다. 전제(여기선 "문제집이 컬렉션을 안다"·"RAG에 모델 축이 있다")가
틀리면 요구를 그대로 만들지 말고 사실을 공유하고 방향을 재합의한다.** ([[probe-deeper-before-concluding]]의
요구-검증판 — 측정 대상이 내 결론이 아니라 사용자 전제)

### 2. 마이그레이션 적용 경로는 CLI가 아니라 앱 부팅(임베디드 upgrade)일 수 있다
`alembic heads`/`revision`이 순환 import(마이그레이션 파일의 `from api.models import …`가 CLI 컨텍스트서
fastapi_users 부분초기화와 충돌)로 **전부 실패**했다. CLI를 고치려 삽질하다, 앱은 `db.py`가 부팅 시
`command.upgrade(cfg, "head")`(임베디드)로 마이그레이션을 **정상 적용**함을 발견 — 앱이 멀쩡한 이유였다.
그래서 CLI 대신 **손수 마이그레이션(고유 hex ID + `Revises`=파싱으로 찾은 단일 head) + 앱 재시작**으로
적용하고, 검증은 alembic이 아니라 **파싱 헤더 그래프**(단일 head·중복 0·고아 0)로 했다. 적용 후 DB에
`collection_id uuid`+`alembic_version=c193…` 실측. **교훈: 마이그레이션이 안 도는 것 같으면 "어떻게
적용되나"를 먼저 찾아라 — CLI가 죽어도 앱 부팅 경로가 진실이면 그 경로로 적용하고, 검증은 대체 수단(파싱)
으로. 손수 리비전은 순번 금지·고유 ID·단일 head 연결 규율.** ([[hand-authored-migration-ids-collide-silently]]
재확인 — 이번엔 충돌이 아니라 CLABI 자체 불능이 계기)

### 3. 폴링으로 목록을 갱신하면 그 목록에서 파생된 "열린 상세뷰"도 동기화해야 한다
generating 종료를 목록은 폴링으로 알지만, 이미 열린 드로어(detail)는 **stale 객체**를 잡고 있어 Skeleton이
안 사라졌다. `setDetail((cur)=> datasets.find(d=>d.id===cur.id) ?? cur)`로 폴링마다 상세를 재바인딩해 봉합.
**교훈: 폴링이 갱신하는 리스트에서 파생된 열린 모달/드로어가 있으면, 그 상세도 같은 소스에서 재조회해
동기화한다 — 안 하면 상태 전이(생성 완료·고정 반영)가 상세뷰에만 안 보인다.**

### 4. e2e "요소는 있는데 not visible"은 실측으로 원인을 가른 뒤 대기 전략을 맞춘다
행 클릭이 "not visible"로 반복 실패했다. 셀렉터를 measure row 제외로 좁혀도 그대로. **디버그 evaluate로
실측**하니 행은 w=1118·h=58·`visibility:visible`로 **실제 보였다** → 원인은 (a) 실행 후 UI가 '실행 이력'
탭으로 전환돼 목록이 사라짐, (b) 폴링 리렌더로 not-stable. 탭 복귀 + `waitFor({state:'visible'})` + force
폴백으로 봉합. **교훈: "있는데 not visible"은 추측 말고 `getComputedStyle`/`getBoundingClientRect`로
실측해 (탭 이동/폴링 not-stable/measure 복제) 중 무엇인지 가른 뒤, 그에 맞는 대기(탭 복귀·visible 대기)를
건다.** ([[verify-ui-in-browser-proactively]]·[[probe-deeper-before-concluding]])

## 다음에 적용
- 요구의 전제(용어가 그 도메인의 실제 축인가)를 코드로 검증 후 재합의(1).
- 마이그레이션 적용 경로(CLI vs 앱 부팅)를 먼저 찾고, 손수 시 고유 ID+단일 head+파싱 검증(2).
- 폴링 리스트에서 파생된 열린 상세는 같은 소스로 재바인딩(3).
- e2e "not visible"은 evaluate 실측으로 원인 가른 뒤 대기 전략(4).

관련: [[177-rag-inspector-and-threshold]](같은 RAG 도메인) · [[hand-authored-migration-ids-collide-silently]] ·
[[probe-deeper-before-concluding]] · [[verify-ui-in-browser-proactively]] · [[index-layer-for-context-recall]]

# 127 — 메모리 목록: 서버 페이지네이션 + 일치/유사도 통합 검색 (안 B)

## 배경 / 왜

사용자 요구 4가지: (1) 메모리는 **계속 증가** — 전량 렌더는 무거움, (2) **일치 검색과 유사도 검색 둘 다**,
(3) **디버깅 정보**를 편하게, (4) 여기가 잘 되면 **다른 메뉴의 모범**. 사용자 결정: **안 B — 서버가
찾아서 조금씩**(deep-reasoner 조사 리포트 기반, A/B 트레이드오프 설명 후 선택).

### 조사로 확정된 사실 (deep-reasoner + 실측)
- **숨은 버그: 목록이 20건에서 조용히 잘림.** `Mem0Backend.list_all`이 `get_all`을 top_k 없이 호출 →
  mem0 기본 20. **21번째 기억부터 화면에 안 보인다**(정합성 버그, UI 이전 문제).
- **mem0 공개 API에는 offset/정렬이 없다**(pgvector `list` = LIMIT만). 진짜 페이지네이션은 mem0를 우회해
  `mem0_memories` 테이블 raw SQL만이 길.
- **실측(도커 pg, 12건)**: payload JSONB 키 = `data`(본문)·`created_at`·`updated_at`·`user_id`·`run_id`·
  `attributed_to`·`hash`·`text_lemmatized`. 결정적 정렬 가능(`created_at` DESC, id tiebreak).
- 유사도 검색+진단(125 diag)은 완비 — `RetrievalTestPanel`/`RecallPanel` 그대로 재사용.
- 확장 목록의 확립 패턴 = SessionsView(DataTable+Pagination+디바운스 서버검색).

## 설계

### 백엔드
1. **`MemoryBackend.list_page(scope, q, limit, offset) -> {items, total}`** — **추상 계약(Protocol)에
   추가하고 하위에서 구현**(사용자 확정 설계: 페이징을 추상 레이어에, 구현은 백엔드별로).
   - **inmemory 구현**: 자기 저장 목록을 필터·정렬·슬라이스(실DB 없는 페이징 계약 테스트 가능).
   - **graceful 예외**: 기존 계약(실패=빈값 흡수)과 달리 list_page 실패는 **빈 목록으로 위장하지 않고**
     라우트가 오류로 표면화(learning 125 "실패≠0건"). 챗 회상 경로는 무관(무변경).
   - mem0 구현: `mem0_memories`를 raw SQL(psycopg, `_sync_dsn` 재사용)로 조회.
     `WHERE payload->>'<axis>' = %s [AND payload->>'data' ILIKE %s] ORDER BY payload->>'created_at' DESC, id
     LIMIT %s OFFSET %s` + 같은 WHERE로 `count(*)` → total. **전부 파라미터 바인딩**(문자열 조립 금지).
     ILIKE 특수문자(`% _ \`)는 이스케이프. axis는 `user_id`/`agent_id` 화이트리스트만(임의 키 금지).
   - items = `{id, text(=payload->>'data'), created_at, updated_at}`.
   - mem0 스키마 결합은 **이 한 파일(mem0_backend)에 격리** + 주석으로 결합 명시(기존 `_MEM_TABLE` 선례).
2. **라우트**: `GET /memory/user/{user_id}/page?q=&limit=&offset=`, `GET /agents/{agent_id}/memory/page?...`
   응답 `{items, total, limit, offset}`. limit 스키마 상한(1–100), offset ≥ 0.
3. **20건 잘림 버그 수정**: `list_all`에 `top_k` 파라미터를 추가해 기존 소비처가 명시 상한으로 부르게.
   특히 **`user_owns`(소유권 술어)가 잘린 목록 위에서 대조하면 21번째 기억의 수정/삭제가 오거부**될 수
   있다 — 실행 시 `user_owns` 경로를 확인해 잘림 영향 있으면 함께 수정(스코프+id 직접 대조 SQL 또는
   충분 상한). 이건 정합성 수정이라 페이지네이션과 독립으로도 필요.
4. 기존 `list`(GET /memory/user/{id})·search·update·delete·챗 회상 경로는 **무변경**(당장 소비처 이관은
   프론트 메모리 패널만).

### 소유권 경계 체크리스트 (docs/spec/CLAUDE.md — user_id 데이터 접촉이라 적용)
1. **입구 열거(닫힌 집합)**: 신규 = paged list 2개(user/agent). 기존 list/search/update/delete/챗 회상은
   무변경. lazy-create·resume·외부 프로토콜 입구 없음(읽기 전용 조회).
2. **입구별 소유권**: 읽기 — 스코프를 **SQL WHERE에** 민다(`payload->>'user_id' = %s`; fetch-then-check
   아님). user 라우트는 `_assert_principal_may_access(principal, user_id)`(기존 단일 헬퍼) 선행 —
   비-어드민은 자기 user_id만. agent 라우트는 기존 agent-memory CRUD와 동일한 router-auth.
3. **단일 헬퍼**: `_assert_principal_may_access` 재사용(신규 판정 로직 안 만듦).
4. **존재 비노출**: 목록은 스코프 내재라 열거 오라클 없음. q 필터도 스코프 안에서만.
5. **검증 3런**: ① 단위(ILIKE 이스케이프·axis 화이트리스트·경계값), ② **실 인프라**(시드 25건+로 20건 캡
   해소·2페이지·total 정확·타 유저 불가시 확인), ③ **적대(codex)**: SQL 인젝션·스코프 우회·q로 타 유저
   내용 유추 가능성의 여집합.
6. **자가-잠금 핀**: 비-어드민이 자기 user_id 페이지 조회는 통과하는 테스트.

### 프론트
1. **`PagedMemoryList`**(메모리 전용으로 먼저, 공유 추출 가능한 경계로 설계 — props: fetchPage/columns/
   actions): DataTable + antd Pagination + 300ms 디바운스 검색 Input. SessionsView 패턴 이식.
2. **모드 전환 `Segmented` [일치 | 유사도]** 를 검색창 옆에:
   - **일치**: 서버 ILIKE 페이지 목록(위 API). 총 N건 표기. 행 액션 = 기존 수정/삭제(현 update/delete API).
   - **유사도**: 기존 `RecallPanel`(관련도 점수+진단 diag) 그대로.
3. **디버깅 정보**: 유사도 모드 = diag 패널(현행). 일치 모드 = "스코프·총 N건·현재 페이지" 상시 한 줄
   (0건이어도 총량·스코프가 보여 "왜 없지"의 1차 진단).
4. UserMemoryPanel·AgentMemoryPanel 둘 다 이 구조로(에이전트는 +추가 입력 유지).
5. **125/126의 회상 카드 상단 배치는 이 통합 UI로 대체**된다(검색이 하나의 표면으로 합쳐짐).

## 실행 계획 (협업 분담)
- 메인: 백엔드 계약·SQL·라우트(보안 판단 필요), 프론트 모드 통합.
- fast-worker: 시드 스크립트(테스트 유저 25건+), 반복 테스트 보일러플레이트.
- 검증: verify_127(3런) + 브라우저 shot + codex 적대 + tsc/ruff.

## 완료 기준 (측정)
- 시드 25건에서: 목록 total=25(캡 버그 해소), 2페이지 이동 정상, ILIKE 검색이 전체 대상, 21번째 기억
  수정/삭제 정상(user_owns 확인), 타 유저 403/빈, 브라우저에서 모드 전환·페이지·진단 렌더 확인.

## 비목표 (OUT)
- SessionsView/CollectionsView를 공유 셸로 이관 — 메모리에서 패턴 확립 후 **후속 스펙**(모범 적용).
- 유사도 검색의 페이지네이션(mem0 search는 top-k 구조, 1–10 유지).
- mem0 업그레이드 대응 자동화 — 결합은 mem0_backend 한 파일에 격리+주석으로만.

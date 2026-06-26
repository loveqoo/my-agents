# 030 — 메모리 관리 화면 (에이전트·유저 통합 큐레이션)

상태: **완료 (검증·비판리뷰 PASS — 2026-06-26)** · main 미머지(브랜치 보존)
날짜: 2026-06-26
브랜치: `feat/agent-service` — **main 머지·push 금지**(사용자가 직접 브랜치 테스트)
지배 스펙: [018 메모리 유저 스코핑](./018-memory-user-scoping.md)("메모리 관리/삭제 UI"를 범위
밖으로 미룬 후속분), [020 다층 스코프](./020-mem0-multi-scope-and-catalog-realign.md),
[029 에이전트 전용 메모리](./029-agent-scoped-memory-self-write-and-admin-curation.md)
참고: `.dev/learning/031`(의도적 쓰기 채널), `.dev/retrospect/020`, 016(읽기전용=타입 카탈로그 한정)

## 배경 / 문제 (사용자 지적)

> 사용자: *"에이전트 메모리, 유저 메모리를 검색, 수정할 수 있는 메뉴, 화면이 없네."*

- **에이전트 메모리(agent_id)**: 029가 CRUD를 넣었으나 **에이전트 상세 패널에만** 노출 —
  전용 관리 화면이 없다.
- **유저 메모리(user_id)**: 018이 유저 스코프를 배선했으나 **관리 UI를 명시적으로 범위 밖**으로
  미뤘다(018 §범위 밖). 백엔드 조회/수정 엔드포인트도 없다.
- 016의 "읽기전용"은 **메모리 *타입 카탈로그*(enum)** 한정이고 **저장된 메모리 콘텐츠**가
  아니다 → 콘텐츠 큐레이션과 충돌하지 않는다.

## 결정 (사용자 승인 2026-06-26)

- **통합 "메모리" 메뉴** — 새 상위 메뉴 1개, 탭 2개(에이전트 / 유저).
- **검색 = 목록 + 텍스트 필터**(의미검색 아님) — 전체를 나열하고 클라이언트에서 부분일치 필터.
  백엔드는 `get_all`(필터 기반, 임베딩 불요)만 쓰므로 단순·빠름.
- **029 에이전트 상세 패널 유지** — 상세에도, 새 화면에도(공유 컴포넌트, 중복 비용 적음).

## 누출 안전성

- 유저 메모리는 **user_id 축 한정**이라 교차-유저 누출 위험이 없다(자기 사실만 조회·교정).
- 에이전트 메모리는 029의 `_assert_owns`(path agent_id 소유권 강제)를 그대로 따른다.
- 유저 메모리 변조도 동형 가드: `mem_id`가 그 userId의 목록에 속할 때만 수정·삭제(타 유저/타
  에이전트 행 변조 차단). 공유 pgvector라 id-only mem0 op를 path 스코프로 가둔다(029 비판리뷰 교훈).

## 변경 범위

### A. 공유 mem_cfg 빌더 — `chat.py` (029 비판리뷰 MED 정리)
- `_build_mem_cfg(chat_model, emb_model) -> dict` 추출(llm+embedder dict 조립, 복호화 포함).
- `resolve_agent_mem_cfg`는 이 빌더를 호출하도록 리팩터(동작 동일·무회귀).
- **`default_mem_cfg(db) -> dict | None`** 신규 — **기본 chat + 기본 embedding**으로 mem_cfg 조립.
  유저 메모리는 특정 에이전트에 안 묶이므로(공유 pgvector·user_id 키) 기본 설정으로 충분.
  (get_all/update/delete는 llm 미사용·embedder만 의미; llm은 mem0 인스턴스화용 자리.)

### B. 유저 메모리 엔드포인트 — 신규 `packages/api/src/api/memory_routes.py` (`/memory`)
- `GET /memory/user/{user_id}` → `list_memories({"user_id": user_id}, default_mem_cfg)`. mem0
  미가용이면 `[]`(graceful).
- `PATCH /memory/user/{user_id}/{mem_id}` `{text}` → 소유권 가드 후 `update_memory`.
- `DELETE /memory/user/{user_id}/{mem_id}` → 소유권 가드 후 `delete_memory`.
- 소유권 가드 `_assert_user_owns(user_id, mem_id, mem_cfg)` — `mem_id ∈ list_memories(user_id)`
  아니면 404. (029 `_assert_owns`의 user_id 판.)
- `main.py`에 라우터 마운트(`dependencies=_auth`).
- 유저 목록은 기존 `GET /sessions/users`(distinct userId) 재사용 — 신규 불요.
- **유저 메모리는 add 미제공** — 관리자는 유저 사실을 *저작*하지 않고 *교정*만 한다(조회·수정·삭제).

### C. Admin API 클라이언트 — `admin/src/api.ts`
- `listUserMemory(userId)` / `updateUserMemory(userId, memId, text)` / `deleteUserMemory(userId, memId)`.
- 유저 목록은 기존 `listUserIds()` 재사용.

### D. Admin UI — 새 "메모리" 메뉴 + `MemoryView`
- `AdminShell.tsx`: 메뉴에 `{ key:'memory', label:'메모리' }` + `memory: <MemoryView/>` 라우팅.
- `admin/src/admin/views/MemoryView.tsx`(신규): antd `Tabs` [에이전트 / 유저].
  - **에이전트 탭**: `Select`(source==='ui' & '장기 기억 (mem0)' 에이전트) → 선택 시
    `AgentMemoryPanel`(029 재사용) 렌더.
  - **유저 탭**: `Select`(listUserIds) → `UserMemoryPanel`(신규): 목록 + 텍스트 필터 + 수정 + 삭제.
- **텍스트 필터**: 두 패널 상단에 작은 `Input` — 렌더 목록을 부분일치로 거른다(클라이언트).
  `AgentMemoryPanel`에 필터 입력을 추가(상세 뷰에도 동일 적용 — 029 동작 유지·향상).

### E. `UserMemoryPanel.tsx`(신규)
- `AgentMemoryPanel`과 동형이되 **add 없음**(교정 전용). 안내문: "유저가 대화 중 남긴 장기 기억.
  이 유저에게만 회상됩니다. 잘못/민감 정보는 여기서 교정·삭제하세요." 인라인 수정 + Popconfirm 삭제.

## 실행 단계 (순서)

1. **백엔드**(A·B) → API 레벨 라운드트립 + 소유권 가드 테스트.
2. **API 클라이언트**(C).
3. **UI**(D·E) → 브라우저 검증.

## 검증 (측정 가능 · 자가검증 지양)

1. **유저 메모리 라운드트립**(라이브 qwen + 공유 pgvector):
   - chat(userId=alice)로 사실 적재 → `GET /memory/user/alice`에 목록 노출.
   - `PATCH`/`DELETE` 라운드트립(본문 반영·삭제 확인).
   - **소유권 가드**: alice의 mem_id를 `bob` 경로로 PATCH/DELETE → **404**, alice 행 무사.
2. **에이전트 탭**: 기존 029 CRUD가 새 화면에서도 동작(회귀 없음).
3. **공유 빌더 무회귀**: `resolve_agent_mem_cfg` 리팩터 후 029 단위테스트 29/29 유지.
4. **브라우저**: "메모리" 메뉴 → 두 탭 렌더, 에이전트/유저 선택→목록·필터·수정·삭제 동작
   (Playwright + 시스템 Chrome, `tests/browser/`). UI는 내가 먼저 브라우저로 확인.
5. **서브에이전트/codex 비판 리뷰**: 유저 소유권 가드(누출/변조 차단), `default_mem_cfg` graceful,
   공유 빌더 리팩터 무회귀, 클라이언트 필터 정확.

## 완료 조건

- [x] 공유 `_build_mem_cfg` 추출 + `default_mem_cfg`(기본 chat+embedding) — 029 테스트 31 어서션 전부 PASS
- [x] 유저 메모리 엔드포인트 3개(list/update/delete) + `_assert_user_owns` 가드, main.py 마운트(`dependencies=_auth`)
- [x] api.ts 유저 메모리 클라이언트 3종(user_id·mem_id 모두 `encodeURIComponent`)
- [x] 새 "메모리" 메뉴 + `MemoryView`(탭: 에이전트/유저)
- [x] `UserMemoryPanel`(목록+필터+수정+삭제, add 없음) + `AgentMemoryPanel` 필터 추가
- [x] 유저 라운드트립(alice 적재→list→PATCH 200→DELETE 204) + 소유권 가드(bob 경로 PATCH/DELETE → 404, alice 행 무사) 라이브 검증
- [x] 브라우저 검증(메뉴→두 탭·선택·목록·필터 빈상태/매칭·수정/삭제 버튼, Playwright+시스템 Chrome) + 서브에이전트 비판 리뷰 PASS(CRITICAL/HIGH/MED 0, LOW 2건 보강)
- [x] **main 머지 금지** — 브랜치 보존

## 검증 요약 (2026-06-26)

- **라이브**(qwen + 공유 pgvector): chat(userId=alice)→`User's name is Alice.`/`...favorite color is purple.` 적재 →
  `GET /memory/user/alice` 노출 → `PATCH`(teal) 200 → `DELETE`(name) 204 → 잔여 1행. 소유권 가드:
  alice mem_id를 `bob` 경로로 PATCH/DELETE → **404**(alice 행 무사). empty-text PATCH(`"   "`) → **400**.
- **무회귀**: `chat.py` 리팩터 후 029 `verify_029_agent_memory.py` 전부 PASS. `api.main` import OK, admin `tsc --noEmit` 0.
- **브라우저**(`tests/browser/shot-memory-view.mjs`): 메모리 메뉴→에이전트 탭(Research Assistant→AgentMemoryPanel,
  필터·추가 인풋) / 유저 탭(alice→UserMemoryPanel, **add 없음**, 필터 빈상태 "필터에 맞는 기억이 없습니다"·매칭 동작).
- **비판 리뷰**(서브에이전트 적대 검증): 핵심 불변식(유저 update/delete 전 `_assert_user_owns`) 견고,
  mem_cfg None graceful, auth 적용, mem0 to_thread, chat.py 무회귀 확인. LOW 2건(mem_id 인코딩·empty-text 가드)
  보강 완료(둘 다 029 패턴 상속·fail-safe였음).

## 범위 밖

- 의미 검색(mem0 query 박스) — 이번은 텍스트 필터. 필요 시 후속.
- 세션 단기(run_id) 메모리 관리 — 휘발성이라 제외.
- 유저 메모리 관리자 *저작*(add) — 교정만. 필요 시 후속.
- 에이전트 자가기록 누출 하드닝(제안 풀/승인 게이트) — 029 결정대로 현행 유지.

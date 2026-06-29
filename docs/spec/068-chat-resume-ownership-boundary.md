# 068 — chat resume 소유권 경계 (067 게이트 우회로 봉인)

## 배경 / 문제 (스펙 067 적대 rung에서 도출 — 검증된 P1)
067이 `/sessions` **읽기 엔드포인트**를 유저별로 스코핑했으나, codex 적대 rung이 **067 게이트를
무력화하는 다른 입구**를 짚었다 — chat resume(`POST /agents/{id}/chat`). 같은 `Session` 행을 만지는데
소유권을 안 건다:
- `_load_context`(`chat.py:210-220`)가 세션을 `session_id AND agent_pk`로만 바인딩 — **소유자 무검사**.
- SSE 첫 프레임이 `ctx["session_id"]`를 에코 → *추측 적중* id가 *새 id*(`sess-`+`token_hex(3)`=24비트,
  `chat.py:229`)와 구별됨 = **열거 오라클**.
- `_persist`(`chat.py:332-333`) `if user_id: sess.user_id = user_id` → member가 타인 세션 resume 시
  **소유자를 attacker로 무조건 덮어씀** → 이후 067이 막 게이트한 `GET /sessions/{id}/messages`가
  "본인 소유"로 통과해 **피해자 전사 누출**(2차).

learning 069(읽기 경로 스코핑 ↔ 같은 데이터의 쓰기/resume 입구) / installed-guard-isnt-covering-guard의
표본이다 — "sessions를 스코핑했다"는 *그 엔드포인트군의 가시성*일 뿐, 데이터의 *모든 입구*가 아니다.
*주의*: 모델 컨텍스트는 클라 요청 본문(`chat.py:458,525`)으로 구성 → resume 응답 자체로 히스토리는
안 샘. 누출은 *탈취 후* 읽기 게이트 통과로 발생(2차).

## 목표 (사용자 결정: 지금 스펙 068로 수정 — 067과 같은 루프)
chat resume 입구가 067 읽기 게이트와 **동일한 소유권 결정**을 따르게 한다. 단일 출처(`_own_scope`)를
공유해 읽기 게이트와 resume 게이트가 *같은 데이터에 대해 같은 판정*을 내리도록(069 drift 방지).
- 비-admin member는 **자기 소유 세션만 resume**. 타인/NULL session_id는 *새 세션과 구별 안 되게*
  처리(오라클 제거). admin/머신은 전체(현행 유지).
- 소유권은 *생성 시 1회*만 부여 — 기존 non-null 소유자를 다른 유저로 *덮어쓰지 않음*(이전 금지).
- 추측 가능한 session_id 엔트로피 상향.

## 비목표
- 067 읽기 스코핑 재변경(`sessions.py`는 무변경 — 068은 chat.py 입구만).
- 세션 소유권 *이전*·공유 기능(불변식상 명시적으로 금지).
- `resume_approval`(HIL)·`stream_local_reply`(A2A 내부) 동작 변경 — 이들은 서버-신뢰 session_id라
  스코프 미적용(default `own=None`)으로 무회귀 보존.

## 위협 모델 (067 게이트 우회 봉인 — 타자 적대 필수)
- **T1 열거 오라클**: member가 타인/추측 session_id로 chat → **새 세션 발급**(응답 session_id ≠ 추측값),
  적중과 부재가 *구별 안 됨*. (068의 D1 소유자 스코프 resume → 매칭 실패 → 새 id 발급.)
- **T2 소유권 탈취**: member가 타인 세션을 resume해도 (a) D1로 애초 바인딩 안 됨 (b) D3 불변식으로
  설령 바인딩돼도 소유자 무변경 — *방어 다중화*.
- **T3 admin 덮어쓰기**: admin(own=None)이 타인 세션 resume 시 그래프는 이어 달리되 `_persist`가
  소유자를 admin으로 *바꾸지 않음*(D3 불변식이 admin 경로에도 적용 — 읽기≠소유권 강탈).
- **T4 NULL-owner**: 머신/익명 발 세션(user_id=NULL)을 member가 주장 → D1 `== own`이 NULL 자연 배제
  → 새 세션. NULL 세션 행 무변경.
- **T5 엔트로피**: session_id `token_hex(3)`(24비트, brute 사정거리) → `token_hex(16)`(128비트).
  게이트는 엔트로피에 *기대지 않되*(D1이 1차) 같이 올림(방어 다중화).
- **T6 무회귀**: 본인 세션 resume(session_id 에코)·0턴 새 세션·`resume_approval`·`stream_local_reply`
  전부 현행 유지.

## 설계
### D1 — `_load_context`에 소유자 스코프 주입 (T1/T4)
- 시그니처: `_load_context(agent_id, session_str_id, overrides=None, own=None)`.
- resume 바인딩 select(`chat.py:213-220`)에 `own is not None`이면 `Session.user_id == own` 추가.
- 매칭 실패 → 기존 else 분기(line 229)가 새 id 발급 → *타인/NULL/추측 = 새 세션*(오라클 제거).
- `own=None`(admin/머신·내부 호출) → 무필터(현행).

### D2 — `chat()`가 스코프 전달 (T1)
- `from .sessions import _own_scope` (067의 단일 출처 재사용 — 읽기/resume 동일 판정, 069 drift 방지).
- `own = _own_scope(principal)` 계산 후 `_load_context(agent_id, body.sessionId, body.overrides, own=own)`.
- principal은 이미 `chat()` 파라미터(line 466) → user_id 계산(472)과 같은 출처.

### D3 — `_persist` 소유권 무덮어쓰기 불변식 (T2/T3) — 순수 헬퍼로 단위검증
- `_next_owner(current, incoming) -> str | None`:
  - `incoming` 빈 값 → `current` 보존(기존 동작).
  - `current is None`(미소유) 또는 `current == incoming` → `incoming`(생성 시 1회 부여).
  - 그 외(다른 유저) → `current` 유지(**이전 거부**).
- `chat.py:332-333` `if user_id: sess.user_id = user_id` → `sess.user_id = _next_owner(sess.user_id, user_id)`.

### D4 — session_id 엔트로피 상향 (T5)
- `chat.py:229` `secrets.token_hex(3)` → `secrets.token_hex(16)`. `"sess-"+32hex`=37자 ≤ String(80).
- 기존 세션 id 불변(클라 에코 호환). thread_id 접미(line 521)·approval id(640)는 별개 — 무변경.

### D5 — 내부/HIL 경로 무회귀 (T6)
- `resume_approval`(line 718)·`stream_local_reply`(474)는 `own` 미전달(default None) → 스코프 미적용.
  approval.session_id는 `_create_approval`이 서버측 생성·066 인가 후 resolve → 신뢰. A2A 내부는 session=None.

### D6 — 승인 생성 세션 소유자 스탬프 (codex 적대 P3-2 — D1이 부른 무회귀 갭)
- **문제**: `_create_approval`(chat.py:674)이 세션 행을 lazy-create하면서 `sess.user_id`를 *안 박았다*.
  D1 도입 전엔 무해(resume 무스코프)했으나, D1 후엔 그 NULL-owned 행을 *시작한 member가* 자기
  세션을 못 이어간다(`own == NULL` 매칭 실패 → 새 세션). 즉 D1이 부른 무회귀 갭(happy-path가 못 잡음).
- **수정**: 세션 resolve 직후 `sess.user_id = _next_owner(sess.user_id, user_id)`(같은 트랜잭션 커밋).
  소유권을 *생성 시점*에 박아 067/D1 게이트와 정합. `_next_owner`라 기존 소유자 보존·머신(None) NULL
  유지(066 fail-closed 불변)·066의 `Approval.user_id`(별도 컬럼)와 직교 → 자가승인 무영향(codex 확인).

## 검증 사다리 (비겹침 — 067 게이트 우회 봉인이라 적대 codex 필수)
- **단위**(`verify_068_owner.py`): `_next_owner` 불변식 매트릭스(None/동일/다른유저/빈값) 순수 검증 —
  생성 1회 부여·이전 거부·빈값 보존. 실 DB 불요.
- **라이브**(`verify_068_live.py`, 실 HTTP+DB): 던짐용 member B + 합성 피해자 세션(owner A)+메시지.
  - T1: B가 A의 session_id로 chat → 응답 session_id ≠ A의 것(새 세션 발급, 오라클 제거).
  - T2: 위 후 A 세션의 user_id 무변경 + 메시지 수 무변경(탈취·오염 0).
  - T4: NULL-owner 머신 세션 → B가 주장 → 새 세션, NULL 행 무변경.
  - T6: A가 자기 session_id resume → 같은 session_id 에코(무회귀).
- **적대 codex**: 오라클 잔존(응답·타이밍·에러 분기), 탈취 잔존, admin 덮어쓰기, `_own_scope` 공유
  정합(읽기/resume 동일 판정), resume_approval/stream_local_reply 우회, 엔트로피. installed-guard /
  069 / verification-ladder.
- **브라우저 rung 미적용(사유)**: resume-탈취는 API 레벨 우회로 *별도 UI 어포던스가 없다*(플레이그라운드는
  항상 *자기* 세션 id만 전송). 라이브 rung이 UI가 칠 바로 그 HTTP 경로를 구동하므로 브라우저는 비겹침
  가치가 낮음 → 단위·라이브·codex 3 rung으로 충분(verification-ladder: 3 rung 비겹침). 플레이그라운드
  본인 세션 무회귀는 라이브 T6가 커버.

## 완료 조건
- [x] D1 `_load_context(own=None)` 소유자 스코프 — 타인/NULL/추측 → 새 세션(오라클 제거). — `chat.py:35-50,218-228`.
- [x] D2 `chat()`가 `_own_scope(principal)`로 스코프 전달(067 단일 출처 공유). — `chat.py:30(import),493-496`.
- [x] D3 `_next_owner` 불변식 — 생성 1회 부여·기존 다른소유자 이전 거부·빈값 보존, `_persist` 배선. — `chat.py:323-339,358-359`.
- [x] D4 session_id 엔트로피 `token_hex(16)`(128비트). — `chat.py:238`(라이브서 `sess-`+32hex 실측).
- [x] D5 `resume_approval`·`stream_local_reply` 무회귀(own=None default). — `chat.py:718,474`(미전달=default None).
- [x] D6 승인 생성 세션 소유자 스탬프(codex P3-2, D1 무회귀 갭 봉인). — `chat.py:675-680`.
- [x] 검증 3 rung(단위·라이브·codex 적대), 특히 **"member가 타인 session_id chat → 새 세션·소유자
  무변경·메시지 미추가"** + **"본인 세션 resume → id 에코(무회귀)"** 핀. 브라우저 미적용(사유 명시).
  - **단위** `verify_068_owner.py` — 8/8 PASS(`_next_owner`: N1 생성부여·N2 멱등·N3★이전거부·N4빈값보존·N5 NULL유지).
  - **라이브** `verify_068_live.py` — 14/14 PASS(실 HTTP+mock-llm 턴+실 DB: T1★타인id→새세션(에코≠피해자)·
    T2★소유자/메시지 무변경·T4 NULL주장차단·T6 본인resume 에코·소유자유지·D6★승인세션 시작주체소유+resume 무회귀).
  - **적대 codex** — VERDICT **PASS**(메인): 잔존 오라클·탈취·admin재소유·스코프drift·resume_approval/stream_local_reply
    우회·엔트로피/타입 전부 None. D6 델타 재검 VERDICT **PASS**(P3-2 봉인·066 자가승인 무영향·신규 클레임경로 0).

## 적대 검증 잔여(068 범위 밖, 후속 후보)
- **[P3-1] sessions.py 읽기 라우트 타이밍 측면채널** — detail/messages/end가 `session_id`로 *먼저 fetch*
  후 `_visible_or_404` 적용(sessions.py:173)이라, 타인-존재행(로드 후 거부) vs 부재행(즉시) 사이 *타이밍*
  차이가 남는다. 상태/본문 오라클은 없고(둘 다 404) 전사 읽기·탈취 불가 → **비-블로킹**. 067 영역 정제
  (비-admin은 owner 스코프를 SELECT에 밀어넣기)로 후속 검토 가능. 068(쓰기/resume 입구)의 범위 밖.

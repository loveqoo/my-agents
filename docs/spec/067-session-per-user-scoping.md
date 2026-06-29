# 067 — 세션 라우터 유저별 스코핑 (대화 전사 교차열람 차단)

## 배경 / 문제 (RBAC 감사에서 도출)
spec 066이 approvals를, spec 052가 memory를 **유저별로 스코핑**(비-admin은 자기 user_id만,
admin/머신은 전체)한 반면, **`sessions.py`는 `current_principal`을 전혀 받지 않는다.** 그 결과
로그인한 일반 유저(member)가 다음을 전부 할 수 있다(라이브 실증 — `tests/verify_rbac_audit.py`
계열 프로브):
- `GET /sessions` — **모든** 유저의 대화 목록 + 첫 메시지 미리보기(스펙 055)
- `GET /sessions/{id}/messages` — **소유하지 않은 세션의 전체 전사** 열람
- `GET /sessions/users` — 전체 chat user_id 목록(스펙 021)
- `POST /sessions/{id}/end` — 타인 세션 강제 종료
- 사이드바 배지 `counts` — 전역 세션 수 누설

라우터 자체는 `dependencies=_auth`로 무인증은 401이나(감사 ②), **인증된 member 사이의
스코핑이 없다.** 카탈로그(agents/blocks/models/collections)를 모든 로그인 유저가 다루는 건 단일
워크스페이스 모델(spec 011)상 의도된 설계지만, sessions는 **개인 대화 데이터**라 성격이 다르다 —
learning 068(list 스코핑이 형제 item 엔드포인트로 전파되지 않음)이 *라우터 단위*로 재현된 사례.

## 목표 (사용자 결정: 유저별 스코핑 — memory/approvals 패턴 이식)
- **member** → 자기 user_id 세션만(목록·상세·메시지·종료·배지).
- **admin/머신** → 전체(현행 유지).
- `Session.user_id`는 이미 *서버가 도출*한 값이다(`chat.py:472` `user_id = None if isinstance(
  principal, str) else str(principal.id)`) — approvals.user_id와 **동일 축**(쿠키 유저=auth UUID,
  머신/익명=NULL). 요청 본문 무관 → 위조 불가(T7). 그래서 066의 `_own_scope`+가시성 404 패턴을
  **그대로 미러링**한다.

## 비목표
- 프론트 Sessions 메뉴를 admin 전용으로 이동(사용자가 "유저별 스코핑"을 택함 — 메뉴는 공통 유지).
- 세션 *소유권 이전*·공유 기능. 본 스펙은 읽기/종료 가시성 스코핑에 한정.
- `Session.user_id`의 NULL(머신/익명 발) 행을 member에게 보이기 — NULL은 부재와 동일 취급(숨김).

## 위협 모델 (개인 대화 데이터 기밀 경계 — 타자 적대 필수)
- **T1 교차유저 목록**: member가 타인 세션 list → 숨김(`WHERE user_id == 본인`, NULL 제외).
- **T2 교차유저 항목(열거 오라클)**: member가 타인/추측 session_id로 detail·messages → **404**
  (부재와 동일, 존재 은폐). **403 금지** — 404↔403이 갈리면 목록이 숨긴 세션 존재가 샌다(learning 068).
- **T3 NULL-owner 탈취**: 머신/익명 발 세션(user_id=NULL)을 member가 주장 → 숨김/404
  (SQL `== str(id)`가 NULL을 자연 배제; item 게이트도 `s.user_id != own` → 404).
- **T4 머신/admin**: 전체 접근 유지(머신 센티넬·superuser·`enforce(id,"sessions","read")`).
- **T5 종료 변조**: member가 타인 세션 `POST /{id}/end` → 404(가시성 게이트 선적용).
- **T6 배지 누설**: `counts`가 전역이면 member가 타인 세션 총수를 추정 → counts도 본인 스코핑.
- **T7 user_id 위조**: 비교는 *서버가 쥔* `principal.id` 대 *DB의* `Session.user_id`로만(요청 무관).

## 설계
### D1 — `_is_admin` / `_own_scope` 헬퍼 (sessions 로컬, 066 미러)
- `_is_admin(principal)`: 머신 센티넬 OR `is_superuser` OR `enforce(str(id), "sessions", "read")`.
  (obj/act가 approvals와 달라 공유 대신 로컬 미러 — 라우터 독립성 유지, 기존 per-router 관례.
  추후 `authz.principal_is_admin(principal, obj, act)`로 추출 가능 — 빚으로 명시.)
- `_own_scope(principal)`: `None` if `_is_admin` else `str(principal.id)`.

### D2 — `list_sessions` 스코핑
- `principal=Depends(current_principal)` 주입. `own = _own_scope(principal)`.
- `own is not None` → `base = base.where(Session.user_id == own)`(본인 것만, NULL 자동 제외).
- admin/머신 → 무필터(현행).

### D3 — `_badge_counts` 스코핑 (T6)
- `_badge_counts(session, own)` — `own is not None`이면 `WHERE Session.user_id == own` 추가.
  member의 배지는 자기 세션만 집계. admin/머신은 전역(현행).

### D4 — item 엔드포인트 가시성 404 게이트 (T2/T3/T5, learning 068)
- `_get_session_or_404` 후 **공통 가시성 게이트**: `own is not None and s.user_id != own` → **404**.
- 적용: `get_session_detail`, `list_session_messages`, `end_session`. 작은 헬퍼
  `_visible_or_404(s, principal)`로 일원화(부재 404와 *동일 응답*으로 존재 은폐).

### D5 — `list_user_ids` 스코핑 (T1)
- 비-admin → 자기 user_id만(본인 세션이 있으면 `[own]`, 없으면 `[]`). admin/머신 → 전체 distinct.
  (memory `list_memory_users`가 비-curator에게 자기 신원만 주는 것과 동형.)

### D6 — 프론트(무변경 목표)
- Sessions 메뉴 공통 유지. API가 스코핑된 데이터만 반환하므로 SessionsView·Playground는 자동 반영.
- 검증으로 *breakage 없음* 확인(빈 목록·자기 것만 렌더, Playground user 피커가 본인만이어도 무해).

## 검증 사다리 (비겹침 — 기밀 경계라 적대 codex 필수)
- **단위**(`verify_067_scope.py`, FakeEnforcer): `_is_admin`/`_own_scope`/`_visible_or_404` 분기
  격리 — member/super/머신 × own/타인/NULL. 실 DB/쿠키 없이 결정 로직.
- **라이브**(`verify_067_live.py`, 실 HTTP+DB): 던짐용 member/super + 합성 Session 3종(own·타인·
  NULL-owner, 각 메시지 1건) 삽입. member: list=own만·타인/NULL list 숨김·detail/messages 타인→**404**·
  own→200·badge counts=own수·end 타인→404. admin/머신: 전체 200. (verify_rbac_audit 매트릭스도
  여전히 통과 — GET /sessions는 스코핑돼도 200.)
- **브라우저**(`shot-session-scope-067.mjs`): member 로그인 → Sessions 뷰가 자기 것만/빈 표시,
  타인 session_id URL 직접 접근 차단(404 토스트/빈 상세).
- **적대 codex**: 열거 오라클(404 vs 403 누설), 배지 전역 누설, NULL-owner 탈취, user_id 위조,
  종료 변조. installed-guard / verification-ladder / list-vs-item-scoping(068).

## 완료 조건
- [x] D1 `_is_admin`/`_own_scope` 헬퍼(sessions 로컬, 머신·superuser·`sessions:read`). — `sessions.py:21-47`.
- [x] D2 `list_sessions` 본인 스코핑(NULL 숨김), admin/머신 전체. — `sessions.py:133-138`.
- [x] D3 `_badge_counts` 본인 스코핑(배지 누설 차단). — `sessions.py:74-90`.
- [x] D4 item 가시성 404 게이트(detail·messages·end) — 타인/NULL/추측 → 404(존재 은폐, 403 아님). — `sessions.py:215,227,246`.
- [x] D5 `list_user_ids` 본인 스코핑. — `sessions.py:196-205`.
- [x] D6 프론트 무변경·무breakage 확인. — `SessionsView.tsx` 무변경, 브라우저 rung에서 자기 것만/배지 `전체 (1)` 확인.
- [x] 검증 4 rung(단위·라이브·브라우저·codex 적대), 특히 **"member가 타인 session messages → 404"**
  + **"member 배지 counts=본인 세션 수"** 핀.
  - **단위** `verify_067_scope.py` — 17/17 PASS(`_is_admin`/`_own_scope`/`_visible_or_404` 분기, member/super/머신×own/타인/NULL).
  - **라이브** `verify_067_live.py` — 23/23 PASS(member list=own만·타인/NULL→404·badge all=1·super all=전체, `/sessions/users`=본인만, 타인 end→404+status 무변경).
  - **브라우저** `shot-session-scope-067.mjs` — PASS(member 로그인 → OWN 노출·OTHER 숨김·배지 `전체 (1)`).
  - **codex 적대** — *067 범위 4점 모두 통과 확인*: `/users` 정적 라우트가 `/{session_id}`보다 선언 우선, 배지 스코핑, detail/messages/end 404 은폐, UUID-vs-str 비교 정합(`chat.py`가 `str(principal.id)` 저장). **단, 범위 밖 P1 발견 → 아래 잔여 갭.**

## 적대 검증 결과 — 잔여 갭 (067 범위 밖, 후속 스펙 필요)
067은 `/sessions` **읽기 엔드포인트** 축을 정확히 봉인했고 4 rung 모두 통과했다. 그러나 codex 적대
rung이 **067로 막을 수 없는 우회로**를 짚었다 — chat resume 경로(`POST /agents/{id}/chat`):

- **[P1 검증됨] chat resume 소유권 탈취 + 열거 오라클** — `_load_context`(`chat.py:210-220`)가
  세션을 `session_id AND agent_pk`로만 바인딩(소유자 무검사). SSE 첫 프레임이 `ctx["session_id"]`를
  돌려줘 *추측 적중 id*가 *새 id*(`sess-`+`token_hex(3)`=24비트, `chat.py:229`)와 구별됨(오라클).
  이어 `_persist`(`chat.py:332-333`)가 `if user_id: sess.user_id = user_id`로 **소유자를 무조건
  덮어씀** → member가 타인 세션을 resume하면 그 행의 소유자가 attacker로 바뀌고, 이후 067이 막 게이트한
  `GET /sessions/{id}/messages`가 "본인 소유"로 통과해 **피해자 전사를 읽음**. 즉 067 게이트가 이
  옆문으로 무력화된다(memory: installed-guard-isnt-covering-guard / move-breaks-references).
  - *주의*: 모델 컨텍스트는 클라 요청 본문(`chat.py:458,525`)으로 구성 → resume 응답 자체로 피해자
    히스토리가 새지는 않음. 누출은 *탈취 후* `/sessions/{id}/messages` 읽기로 발생(2차).
  - **권장 수정(후속 스펙)**: ① `_load_context`에 principal 스코프 주입 — 비-admin은
    `Session.user_id == str(principal.id)`만 resume, 타인/NULL은 *새 세션과 구별 안 되게* 부재 취급.
    ② `_persist`는 *기존 non-null 소유자를 다른 유저로 덮어쓰지 않음*(소유권 이전 불변식).
    ③ session_id 엔트로피 상향(24비트 → 충분히 큰 값).
- **[P2] 회귀 테스트 갭** — 067 테스트는 `/sessions/*`만 덮고 chat resume 탈취 경로는 미검증.
  후속 스펙에서 "타인 세션 id로 member가 chat → 오라클 없음·메시지 미추가·소유자 무변경" 핀 추가.

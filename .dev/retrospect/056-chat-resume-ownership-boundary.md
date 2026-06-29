# 056 — chat resume 소유권 경계 회고 (스펙 068)

## 무엇을 했나
067(세션 읽기 스코핑) 적대 rung이 짚은 **검증된 P1**(chat resume가 067 게이트를 우회)을 닫았다.
공격 사슬: member가 (1) resume 응답의 session_id 에코로 추측 적중을 새 id(24비트)와 구별 = 열거
오라클, (2) 타인 세션 resume → `_persist`의 `if user_id: sess.user_id = user_id`가 소유자를 attacker로
무조건 덮어씀 = 소유권 탈취, (3) 이후 067이 막 게이트한 `/sessions/{id}/messages`가 "본인 소유"로
통과 = 전사 누출. 처방 4점 + 적대가 부른 1점:
- **D1** `_load_context(own)` — 비-admin resume 바인딩에 `Session.user_id == own` 주입(067 단일 출처
  `_own_scope` 재사용). 타인/NULL/추측 → 매칭 실패 → 새 세션 발급(부재와 구별 불가 = 오라클 제거).
- **D2** `chat()`가 `own = _own_scope(principal)` 전달 — 읽기 게이트와 *같은 판정*(drift 0).
- **D3** `_next_owner(current, incoming)` 순수 불변식 — 생성 시 1회 부여·기존 다른소유자 이전 거부·
  빈값 보존. `_persist`의 무조건 덮어쓰기를 대체(방어 다중화: D1로 애초 바인딩도 안 됨).
- **D4** session_id 엔트로피 `token_hex(3)`(24비트) → `token_hex(16)`(128비트).
- **D6** (codex P3-2) `_create_approval`이 세션을 NULL-owned로 만들던 것을 생성 시점 owner 스탬프로.

## 가장 큰 수확 — 적대 rung이 *내 수정이 부른* 무회귀 갭을 짚었다 (D6)
D1~D4는 happy-path(본인 resume·타인 차단) 라이브 12/12로 다 초록이었다. 그런데 codex가 **D1이
새로 만든** 무회귀 갬을 짚었다: `_create_approval`은 승인 게이트에 도달한 턴의 세션 행을 lazy-create
하면서 `sess.user_id`를 *안 박는다*. D1 이전엔 무해(resume 무스코프)했으나, D1 후엔 그 NULL-owned
행을 **시작한 member가 자기 세션을 못 이어간다**(`own == NULL` 매칭 실패 → 새 세션, 연속성 소실).
즉 *게이트를 조이면, 정당히 소유돼야 하나 아직 스탬프 안 된 행이 고아가 된다* — 069(쓰기 입구가
소유자를 덮어씀=탈취)의 **거울상**(생성 입구가 소유자를 안 박음=자가-잠금). → learning 070으로 추출.

이건 probe-deeper / adversarial-before-ship의 재현이다: 내 라이브 rung은 *내가 상상한* 실패
(타인 탈취)만 확인했고, 적대자가 "보장 목록의 여집합"(같은 데이터의 *또 다른 생성 입구*)을 던졌다.

## 핵심 통찰
1. **읽기/resume 게이트는 단일 출처를 공유해야 drift가 0이다.** D2가 067의 `_own_scope`를 그대로
   import — 만약 chat이 자기 사본을 들었으면 067과 판정이 갈리는 순간 또 우회로가 생긴다. codex가
   "scope consistent"를 명시 확인. 같은 데이터의 모든 입구는 *같은 판정 함수*를 불러야 한다.
2. **소유권은 *모든 생성 입구*에서 박아야 한다, 주 경로 하나가 아니라.** `_persist`(주 영속)만 owner를
   박고 `_create_approval`(부 생성 입구)은 빠뜨리면, 게이트를 조인 순간 그 입구가 만든 행이 고아.
   "이 행을 *만드는* 경로가 몇 개인가? 각각 owner를 박나?"를 위협모델 축에 넣어야 했다.
3. **방어 다중화가 실제로 값을 했다.** D1(바인딩 차단)이 1차지만 D3(`_next_owner`)이 2차로, codex가
   "bad context가 _persist에 닿아도 덮어쓰기 안 됨"을 독립 보장으로 확인. admin 재소유도 D3가 막음.

## 검증 (3 rung, 비겹침)
- 단위 `verify_068_owner.py` 8/8 — `_next_owner` 불변식 매트릭스(순수).
- 라이브 `verify_068_live.py` 14/14 — 실 HTTP+mock-llm 턴+실 DB. T1 오라클제거·T2 탈취/오염0·
  T4 NULL차단·T6 본인resume 무회귀·D6 승인세션 소유+resume.
- 적대 codex — 메인 VERDICT PASS(잔존 오라클·탈취·admin재소유·drift·내부경로 우회·엔트로피 전부
  None), D6 델타 재검 VERDICT PASS(P3-2 봉인·066 자가승인 무영향).
- 브라우저 미적용(합의·사유): resume-탈취는 별도 UI 어포던스 없음(플그는 자기 세션 id만 전송),
  라이브가 UI가 칠 바로 그 HTTP 경로를 구동 → 비겹침 가치 낮음. 3 rung으로 충분.

## 잔여 / 다음에 더
- **[P3-1 비블로킹]** sessions.py 읽기 라우트(detail/messages/end)가 `session_id`로 *먼저 fetch* 후
  `_visible_or_404` → 타인-존재행 vs 부재행 *타이밍* 차이가 남음(상태/본문 오라클은 없음). 067 영역
  정제(비-admin owner 스코프를 SELECT에 밀어넣기)로 후속 검토 가능. 068(쓰기/resume)의 범위 밖.
- 위협모델에 "같은 데이터의 *생성* 입구 열거" 축이 처음엔 빠져 D6를 적대 rung에서야 잡았다.
  069는 "쓰기 입구가 owner를 덮어씀"만 봤고, "생성 입구가 owner를 안 박음"은 070에서 보강.

## 자산
- 스펙: `docs/spec/068-chat-resume-ownership-boundary.md`(완료조건 [x]+D6+검증결과+P3-1).
- 067 back-ref: `docs/spec/067-*.md` 잔여갭 섹션에 "→ 해결: spec 068" 명시.
- 검증: `tests/verify_068_owner.py`·`tests/verify_068_live.py`.
- learning 070(생성 입구가 owner를 안 박으면 게이트 조일 때 자가-잠금 — 069의 거울상). 짝=055(067).

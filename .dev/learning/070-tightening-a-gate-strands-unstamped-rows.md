# 070 — 읽기/resume 게이트를 조이면 *소유자 미스탬프* 행이 고아가 된다 (069의 거울상)

## 한 줄
같은 데이터에 owner 스코프 게이트를 새로 거는 순간, 그 데이터를 **만드는 모든 입구**가
소유자를 박지 않으면 — 주 영속 경로만 박고 부 생성 경로(lazy-create 등)를 빠뜨리면 —
*정당히 소유돼야 할 행이 NULL-owned로 남아 시작한 본인조차 못 잇는 자가-잠금(self-lockout)*이 생긴다.

## 맥락
- 069: **읽기 경로 스코핑은 같은 데이터의 쓰기/resume 입구가 소유권을 안 걸면 무력화** — 그 입구가
  존재 오라클·소유권 *탈취*가 된다(스펙 068 D1/D3가 봉인).
- 070(이번): 그 입구를 owner 스코프로 조이고 나니, **데이터를 생성하는 또 다른 입구**가 owner를
  *안 박던* 게 드러났다(스펙 068 D6). 069는 "입구가 owner를 **덮어씀** = 탈취", 070은 "입구가
  owner를 **안 박음** = 자가-잠금". 같은 동전의 양면 — *모든 입구가 같은 소유권 규약을 따라야 한다*.

## 구체 (스펙 068)
- D1이 chat resume를 `Session.user_id == own`로 스코프 → 비-admin은 자기 소유 세션만 이음.
- 그런데 `_create_approval`(승인 게이트 도달 턴의 세션을 lazy-create)이 `sess.user_id`를 안 박았다.
  D1 이전엔 무해(resume 무스코프)했으나, D1 후엔 그 NULL-owned 행을 **시작한 member가 resume 못 함**
  (`own == NULL` 매칭 실패 → 새 세션, 연속성 소실). = D1이 *부른* 무회귀 갭.
- happy-path 라이브(본인 resume·타인 차단)는 12/12 초록이었고, **적대 codex가 이 갭을 짚었다**.
- 봉인: 세션 resolve 직후 `sess.user_id = _next_owner(sess.user_id, user_id)` — *생성 시점*에 owner 스탬프.
  `_next_owner`라 기존 소유자 보존·머신(None) NULL 유지(fail-closed) → 멱등·안전.

## 다음에 이렇게
1. **owner 스코프 게이트를 새로 걸 땐, 그 데이터의 *생성/쓰기 입구를 전부 열거*하라.** "이 행을
   만드는 경로가 몇 개인가? 각각 owner를 박나?"를 위협모델 축으로. 주 영속 경로 하나만 보면 샌다.
2. **소유권은 *생성 시 1회* 박고, 모든 입구가 *같은 헬퍼*를 쓰게 하라**(드리프트 0). 068은
   `_next_owner`(불변식) + `_own_scope`(읽기/resume 단일 판정)로 통일.
3. **happy-path 테스트는 *내가 상상한* 실패만 본다.** 게이트를 조였으면 "조임이 *정당한* 접근을
   막진 않나"(자가-잠금)를 별도로 핀하라 — 그리고 적대자에게 "보장 목록의 여집합"(다른 입구·다른
   방향)을 던져라. probe-deeper / adversarial-before-ship / installed-guard-isnt-covering-guard와 동류.

## 연결
- 짝: 069(읽기↔쓰기/resume 입구, 탈취). 같은 스펙(068)에서 D1/D3가 069를, D6가 070을 봉인.
- memory: installed-guard-isnt-covering-guard, move-breaks-references-both-directions(이동/조임은
  양방향을 깸 — 단방향만 보는 검증은 green이지만 깨짐), verification-ladder-three-rungs.
- 회고: `.dev/retrospect/056-chat-resume-ownership-boundary.md`.

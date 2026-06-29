# 055 — 세션 라우터 유저별 스코핑 회고 (스펙 067)

## 무엇을 했나
RBAC 재감사("메뉴·버튼·기능이 권한에 맞게 적용됐나 다시 검토")에서 출발해, `sessions.py`가
`current_principal`을 *전혀* 받지 않아 로그인한 member가 **타인 대화 전사를 교차열람**할 수 있던
갭을 막았다. memory(052)·approvals(066)의 `_own_scope`+가시성-404 패턴을 라우터에 미러링:
- D1 `_is_admin`/`_own_scope`/`_visible_or_404` 헬퍼(머신·superuser·`sessions:read`=전체).
- D2 list 본인 스코핑(NULL-owner 자동 제외), D3 배지 counts 스코핑(T6 전역누설 차단),
  D4 item 404 게이트(detail·messages·end — 타인/NULL/추측 → 404 존재은폐), D5 `/sessions/users` 본인만.
- 검증 4 rung: 단위 17/17, 라이브 23/23, 브라우저 PASS, codex 적대.

## 감사 단정의 교정 (probe-deeper)
Explore 에이전트가 "백엔드 86% 무보호"라고 보고했으나, 이는 `main.py`의 라우터 레벨
`dependencies=_auth`(`app.include_router(X, dependencies=_auth)`)를 못 본 *읽기 추정치*였다.
실측(무인증 `GET /agents`→401, 50/50 매트릭스 `verify_rbac_audit.py`)으로 교정 — **"내 측정이
사용자 보고/실태와 어긋나면 측정을 의심"**. 무보호가 아니라, *인증된 member 사이의 스코핑*이
빠진 게 진짜 갭이었다. 감사는 "전부 뚫림"이 아니라 "한 자원(sessions)만 스코핑 누락"으로 좁혀졌다.

## 핵심 통찰
1. **단일 워크스페이스 모델(011)이 자원 성격을 가른다.** 카탈로그(agents/blocks/models/collections)는
   모든 로그인 유저가 다루는 게 *의도된 설계*(config, 공용). 개인 데이터(memory/approvals/sessions)는
   유저별 스코핑이 맞다. sessions는 이 중 *유일하게 스코핑이 빠진* 개인-데이터 자원이었다 —
   "어떤 자원이 personal이고 어떤 게 config인가"를 먼저 분별하면 어디에 스코핑이 필요한지 자명.
2. **list 스코핑은 item 엔드포인트로 자동전파 안 된다(068 재현).** list만 `WHERE user_id==me`
   걸고 detail/messages/end를 그냥 두면, 404(부재) vs 403(있지만 내것아님)이 갈려 *목록이 숨긴
   세션의 존재*가 id 추측으로 샌다(열거 오라클). 그래서 비가시행=404로 통일(`_visible_or_404`).
   list에 스코프 거는 *순간* 같은 스코프를 item에도 동시 설계해야 한다.
3. **`user_id`는 서버가 쥔 값이라 위조 불가(T7).** 비교는 *클라가 못 바꾸는* `principal.id` 대
   *DB의* `Session.user_id`로만. `chat.py`가 `str(principal.id)`로 저장 → UUID-vs-str 비교 정합.

## 가장 큰 수확 — 적대 rung이 067 *밖*의 우회로를 짚었다
4 rung 중 codex 적대가 **067 범위 4점 모두 통과**를 확인하면서, 동시에 067의 게이트를 무력화하는
**범위 밖 P1**을 발견했다: chat resume(`POST /agents/{id}/chat`)이 세션을 `session_id+agent_pk`로만
바인딩(소유자 무검사)하고, `_persist`가 `if user_id: sess.user_id = user_id`로 **소유자를 무조건
덮어쓴다**. member가 타인 세션을 resume하면 그 행 소유자가 attacker로 바뀌고, 이후 067이 막 게이트한
`/sessions/{id}/messages`가 "본인 소유"로 통과해 피해자 전사를 읽는다. + SSE 첫 프레임의 session_id
에코가 추측 적중을 새 id(24비트 `token_hex(3)`)와 구별시키는 열거 오라클.

이건 정확히 **installed-guard-isnt-covering-guard / move-breaks-references**의 재현이다 —
067은 `/sessions` 읽기 입구를 봉인했지만, *같은 데이터를 만지는 다른 입구*(chat resume)는 안 덮었다.
"sessions를 스코핑했다"는 한 엔드포인트군의 가시성일 뿐, 데이터의 *모든 입구*가 아니다.

## 판단: 067은 정직하게 닫고, P1은 합의 후 후속 스펙
067의 읽기-경로 축은 정확하고 4 rung 통과 → 완료 처리하되, 스펙에 **잔여 갭(chat resume 우회)을
명시**해 기밀 보장을 과대선언하지 않았다(report-outcomes-faithfully). chat resume 수정은 core
`chat.py`의 resume 시맨틱을 건드리고 *설계 분기*(타인 세션 resume 시 404-as-new vs 거부 vs 새세션
분기, 소유권 불변식, 엔트로피 상향)가 있어 **큰 결정사항** → 사용자 합의 후 별도 스펙으로.

## 아쉬움 / 다음에 더
- 067 위협모델에 "같은 데이터의 *다른 입구*(write/resume 경로)" 축이 빠져 있었다. 읽기 스코핑을
  설계할 때 "이 데이터를 *생성·변경*하는 경로는 소유권을 어떻게 다루나"를 같은 표에 넣었다면 P1을
  적대 rung 전에 잡았을 것. → learning 069로 추출.
- 브라우저 rung 시드 시 `_provision_super.py`가 authz 미초기화 서브프로세스라 member role 부여가
  실패(무해 — member가 정책 0개=정확히 비-admin). 노이즈지만 테스트 결과엔 영향 없음.

## 자산
- 스펙: `docs/spec/067-session-per-user-scoping.md`(완료조건 [x]+잔여갭 섹션).
- 검증: `tests/verify_067_scope.py`·`verify_067_live.py`·`browser/shot-session-scope-067.mjs`·
  `_seed_session_067.py`·`verify_rbac_audit.py`(50/50 RBAC 매트릭스).
- learning 069(같은 데이터의 다른 입구). 짝 회고=054(066, 열거오라클 형제).

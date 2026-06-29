# 054 — 유저 self-승인: permission 기반 RBAC 3-way 회고

스펙 066. HIL 승인(spec 041)의 resolve가 admin 전용이던 것을 **action 민감도(=`Approval.permission`)
+ Casbin RBAC**로 3분할: admin/머신=무엇이든, owner=자기 것 중 `self_approve` 정책이 열린
permission만, 그 외 403. 기본 fail-closed(self_approve 정책 0개 → data.delete 영구 admin 전용).
이미 카드 표시용으로만 쓰이던 `permission`을 인가에 *배선*하고, Approval 행에 요청 주체(`user_id`)를
처음으로 기록했다.

## 무엇을 했나
- **D1** `Approval.user_id`(nullable, NULL=머신/레거시=admin 전용) + alembic `e1f2a3b4c5d6`(백필 없음,
  레거시 NULL=fail-closed). 라이브 DB 적용 확인.
- **D2** `_create_approval(…, user_id)` — 단일 생성 경로(main `chat()`)에서 이미 도출된 주체 전달.
- **D3** `_may_resolve(approval, principal)` 3-way + 라우트에 가시성 404 게이트(아래 핵심 통찰 2).
- **D4** `authz.can_self_approve` = `enforce(sub, permission, "self_approve")`, 기본 정책에 self_approve 0개.
- **D5** `list_approvals` `_own_scope` 스코핑(비-admin=본인 user_id, NULL/타인 숨김).
- **D6** 프론트 *무변경* — 기존 `httpError`+`message.error`가 403 detail을 토스트로 노출(050 자산 재사용).
- 검증 4 rung: 단위 `verify_066_resolve_authz.py`(24/24)·라이브 `verify_066_live.py`(15/15)·브라우저
  `shot-user-approval-066.mjs`(PASS)·codex 적대(VERDICT PASS, Low 1건 수정).

## 핵심 통찰
1. **표시용 필드를 인가에 배선할 때, "그 값이 어디서 오는가"가 보안 전부다.** `permission`은 041부터
   카드에 떠 있었지만 *클라가 못 바꾸는 서버 상태*(DB의 `Approval.permission`)였기에 인가축으로 승격해도
   위조 불가(T3/T6). 만약 resolve 요청 본문에서 perm/user_id를 받았다면 그대로 권한상승. 인가 판정의
   모든 입력은 `current_principal`(서버가 쥔 것) 대 DB 행으로만 — `ResolveIn`은 `decision`만 받는다.
   codex가 "request body cannot spoof"를 가장 먼저 verified-safe로 확인한 것도 이 축.
2. **list를 스코핑해도 item 엔드포인트를 스코핑 안 하면 열거 오라클이 남는다(적대 rung이 잡음).** 내
   초안은 resolve에서 비가시 행도 `_may_resolve`=False → **403**. 목록은 `_own_scope`로 타인·NULL
   행을 숨겼는데, resolve는 404(부재)와 403(있지만 내 것 아님)을 갈라 *목록이 숨긴 바로 그 행들의
   존재*를 approval_id 추측으로 캐낼 수 있었다(codex Low#1). 처방=`_may_resolve` 앞에 가시성 게이트
   — 비-admin이 못 보는 행은 404로 통일(부재와 동일). 단 *자기* 행의 민감-perm-거부는 403 유지
   (이미 목록에 보여 존재는 알려진 상태). **컬렉션 뷰의 스코핑은 항목 엔드포인트로 자동 전파되지
   않는다** → learning 068로 자산화.
3. **기능의 핵심 값(owner+self_approve→200)이 기본 상태에서 한 번도 안 밟힌다는 정직성.** data.delete가
   유일 위험 도구이고 admin 전용이라, owner self-승인 분기는 *인프라로 완성하되 기본 노출 0*. 스펙 가치는
   "즉각 UX 변화"가 아니라 "3-way 인가 인프라 + owner+data.delete→403 회귀 핀". 이 정직성을 스펙·완료조건에
   명시(저위험 도구가 생기면 `(member,<perm>,self_approve)` 정책 한 줄로 열림).

## 검증 사다리 — rung별 비겹침(verification-ladder 실천)
- **단위**(FakeEnforcer): `_may_resolve` 분기 로직만 격리 — 실 casbin/DB/쿠키 없이 3-way·T1/T2/T6/T7.
  owner+self_approve→**True**(허용 200 분기)를 권위 있게 덮음(라이브가 못 시드하는 분기).
- **라이브**(실 HTTP+DB): 글루 — 쿠키 principal 해석(member/super)·머신 Bearer·DB list 스코핑이
  실제 필터·`enforce()`가 *실제 소비*(member가 자기 data.read도 403=정책 부재 fail-closed, 게이트가
  perm 무시했다면 200이었을 것). **owner+self_approve→200의 라이브 양성은 의도적 미수행** — 별 프로세스라
  정책 주입에 서버 재기동 필요, 단위가 권위 있게 덮으므로 라이브는 fail-closed로 배선만 증명(공유 enforcer
  변형 리스크 회피).
- **브라우저**: D6 무변경이라 고유 값은 "403 detail이 실제 UI 토스트로 *도달*하는가" — member가 자기
  data.delete 카드를 보고(스코핑) resolve→빨간 토스트 "이 승인을 결정할 권한이 없습니다"+카드 잔존(미실행).
- **적대 codex**: happy-green 사각을 메움 — 열거 오라클(Low#1)은 정상 흐름에선 안 보이고(목록은 이미
  스코핑) 적대자가 approval_id 추측 시나리오를 던져야 드러난다. VERDICT PASS, verified-safe 11항 열거.

## 아쉬움 / 개선
- 위협 모델 초안에 "404-vs-403 열거" 축이 빠져 있었다(적대 rung이 메움). 스코핑을 list에 건 순간 같은
  스코프를 item 엔드포인트에도 *동시에* 설계했어야 — learning 068로 다음 작업 Context에서 핀.
- owner+200 라이브 양성을 seed+restart 절차로 한 번은 밟아두면 casbin 그룹핑(g) 해석까지 라이브로 닫힌다
  (현재는 라이브러리 보장 + 단위로 갈음). 저위험 도구 추가 작업 때 함께.

retrospect 054 · spec 066 · learning 068.

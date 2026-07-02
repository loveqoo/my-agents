# 112 — 소유권은 "관리(수정/삭제)"를 막지 "사용"을 막지 않는다 / 게이트 추가가 기존 열린 문을 드러낸다

스펙 112(공유 카탈로그 소유권 + per-cap 인가)에서 배운 것.

## 1. "누가 쓰나" ≠ "누가 관리하나" — 소유권으로 *invoke*를 막으면 공유가 깨진다

owner_id를 붙이고 처음 든 직관은 "브로커 invoke를 소유자로 막자"였는데 **틀렸다**: admin이 모두를
위해 만든 공유 에이전트를 member가 못 쓰게 되어 **공유 자원이 깨진다**. 사용(채팅에서 그 에이전트를
쓰는 것)과 관리(그 에이전트를 편집/삭제하는 것)는 **다른 축**이다.

- **사용 인가** = 브로커 per-cap RBAC(축 A, `capability:{kind}:{name}`) — 누가 어떤 능력을 호출하나.
- **관리 인가** = 소유권(`assert_may_manage`) — 누가 카탈로그 항목을 편집/삭제하나.

소유권을 사용에 걸려는 충동이 들면 멈춰라: 공유 자원이면 사용은 RBAC(공유 가능)로, 소유권은 관리에만.
codex가 짚었던 "member가 kind allowlist 전부 호출" 빚은 **사용 축**이라 per-cap RBAC가 갚았고, 소유권은
애초에 그 빚과 무관했다. **틀린 축에 도구를 대면 멀쩡한 공유가 깨진다.**

## 2. 게이트를 새로 다는 순간, 기존에 *열려 있던 문*이 드러난다 — 모든 입구를 다시 센다

관리 게이트를 달려고 라우트를 보니 카탈로그 변경 라우트가 `_auth=[Depends(current_principal)]`(**인증만**)
이었다 — 로그인한 아무 member나 남의 에이전트/도구/문서를 수정·삭제할 수 있는 **현존 구멍**. 소유권 작업이
이걸 드러냈고 닫았다. 교훈: **owner-scoping을 추가할 땐 자원을 만지는 *모든* 변경 입구를 닫힌 집합으로
다시 열거**(체크리스트 §1). 주 CRUD만 보면 샌다 — codex가 내가 빠뜨린 **에이전트 메모리 변조 3라우트**
(add/update/delete `/agents/{id}/memory`)를 P1로 잡았다(빠뜨린 입구=P1, 066→068의 재판).

## 3. 404-fold는 같은 status가 아니라 **같은 body**라야 성립한다

비소유 거부를 404로 접어도, 미존재가 `{"detail":"agent not found"}`이고 비소유가 `{"detail":"not found"}`
면 **body 차이로 존재가 샌다**(068 위반, codex P1). 게이트 헬퍼에 `not_found_detail`을 받아 **그 라우트의
존재-404 detail과 정확히 일치**시켜야 한다. "404 반환"만 확인하는 테스트는 통과하고도 누출한다 — body까지
단언하라(H7=미존재 detail == 비소유 detail).

## 4. 인자로 즉시 평가하면 지연 단락이 무력화된다

`assert_may_manage(x, principal, authz.get_enforcer())`처럼 enforcer를 **인자로 넘기면** Python이 호출
*전에* `get_enforcer()`를 평가한다 → 머신·superuser라 casbin이 불필요한 경우에도 실행되고, ASGI 테스트
(lifespan 미가동으로 authz 미초기화)에서 `RuntimeError`. 해결: 인자로 넘기지 말고 **헬퍼가 지연 로드**
(특권은 casbin 미접촉으로 먼저 단락, 미초기화면 비특권 안전측 폴백). **비싼/실패가능한 값은 필요한 분기
안에서만 지연 획득**하라 — 인자 위치는 항상 평가된다.

## 5. 머신 토큰의 특권은 맥락마다 다르다

브로커 **오케스트레이션**에선 머신 토큰(str principal)을 deny했다(유저 세션 대상). 카탈로그 **관리**에선
반대로 특권으로 뒀다(신뢰 서비스/CI 자격, 무회귀). **같은 principal이라도 "무엇에 대한 권한이냐"에 따라
판정이 갈린다** — `is_privileged`(관리)와 `build_broker.rbac_allows`(오케스트레이션)가 str principal을
정반대로 처리하는 게 정상이다. 위협 모델(로그인 member)을 기준으로 각 맥락에서 판정.

## 적용
- 공유 자원에 소유권을 붙일 때: **사용은 RBAC, 소유권은 관리에만**. invoke를 소유권으로 막고 싶으면 그게
  공유를 깨는지 먼저 물어라.
- 게이트 추가 = 모든 변경 입구 재열거(주 CRUD + 서브리소스 + lazy-create + 외부 프로토콜). 자가검증 말고
  적대 타자에 "빠뜨린 입구"를 시켜라.
- 404-fold는 status+body 둘 다 통일. body를 테스트로 단언.
- 비싼/실패가능 값은 인자로 즉시 평가 말고 분기 안 지연 획득.

관련: [[verify-load-bearing-assumption-not-just-the-guard]] · [[installed-guard-isnt-a-covering-guard]] ·
[[move-breaks-references-both-directions]] · [[complement-attack-can-be-honest-boundary]]

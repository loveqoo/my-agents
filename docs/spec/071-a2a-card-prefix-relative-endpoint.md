# 071 — A2A 카드의 prefix-상대 endpoint 구제 + probe 404 정직화

## 배경 (실제 장애)

다른 디바이스에서 카카오페이 sandbox A2A 에이전트를 connect 등록 → **등록은 성공하는데 채팅 때 404**.

근본 원인 (측정·A2A 스펙으로 확정):

```
카드 위치 : https://sandbox-ai-core.kakaopaycorp.com/ai-core/ccab-weekly-report/.well-known/agent.json
카드 url  : "/a2a"            ← 루트상대 (A2A 스펙은 절대 URL 강제 → 비표준 카드)
현재 resolve: urljoin(candidate, "/a2a") = https://…kakaopaycorp.com/a2a   ← 404 (prefix 탈락)
의도       : https://…kakaopaycorp.com/ai-core/ccab-weekly-report/a2a       ← 200
```

RFC 3986상 leading-slash 경로는 base의 path를 버리고 origin 루트로 resolve된다. 프록시 path-prefix
배포(원격 앱은 자기를 root로 착각해 `/a2a` 발행, 외부 경로는 `/ai-core/ccab-weekly-report/*`)에서
prefix가 탈락한다. 커뮤니티 [a2aproject/A2A#160](https://github.com/google/A2A/issues/160)이 요청하는
"카드를 가져온 위치 기준 resolve"가 정확히 이 케이스.

**3단 메커니즘** (셋의 합 = "등록되는데 채팅 404"):
1. `agent_card.py:81` — resolve 시 prefix 탈락 → 저장 endpoint = `…/a2a`
2. `probe_endpoint:111` — `status_code < 600`이라 **404도 live로 통과** → 등록이 online으로 성공(못 걸러짐)
3. `a2a_client.py:149~166` — 채팅 때 그 endpoint로 POST → 404

## 목표 (완료 조건 — 측정 가능)

**P1. prefix-상대 resolution** — 카드가 광고한 상대/루트상대 url을 *카드가 마운트된 prefix* 기준으로
절대화한다. mount_prefix = 카드를 가져온 candidate URL에서 well-known 접미를 제거한 path.

- `_resolve_card_endpoint("/a2a", "https://h/ai-core/ccab-weekly-report/.well-known/agent.json")`
  == `"https://h/ai-core/ccab-weekly-report/a2a"`
- 절대 url(`http(s)://…`)·스킴상대(`//host/…`)·스킴보유는 **기존과 동일**하게 `normalize_http_url`에 위임(prefix 무관).
- origin 루트 카드(prefix 없음, `https://h/.well-known/agent.json`)의 `/a2a` → `https://h/a2a`(회귀 없음).
- 두 well-known 변형(`agent-card.json`·`agent.json`)·base-직접 candidate 모두 동일 prefix 추출.

**P2. probe 404 정직화** — `probe_endpoint`가 GET **404/410(경로 부재)을 dead**로, 그 외(200/3xx/401/403/405)는
live로 본다. 근거: A2A JSON-RPC endpoint는 GET에 405(Method Not Allowed)를 주지 404를 주지 않는다 —
404는 라우트 부재 = 잘못된 endpoint 신호(이번 오resolve 증상과 정확히 일치). 잘못된 endpoint가 online으로
등록되어 사용자가 못 알아채던 공백을 닫는다(여전히 등록은 허용, status만 정직 — 기존 045 #2 철학 유지).

## 설계

### 경계 격리 (learning 066)
- `normalize_http_url`(net_guard)은 **순수 RFC 정규화·SSRF/userinfo/port 거부**로 유지(무변경).
  prefix 의미론은 A2A 카드 고유라 다른 호출자(a2a_client 등)에 새지 않게 **agent_card 계층에만** 둔다.
- `_resolve_card_endpoint`는 prefix를 붙여 절대 URL을 만든 뒤 **그 결과를 `normalize_http_url`에 통과**시켜
  SSRF/userinfo/port 검증을 그대로 받는다(보안 불변: 절대화·검증은 한 곳).

### `agent_card.py`
- `_resolve_card_endpoint(raw, candidate)` 신설:
  - 절대/스킴상대/스킴보유(`"://" in s` 등) → `normalize_http_url(s)` (위임).
  - 그 외(루트상대 `/x` · bare 상대 `x`) → `mount = candidate`에서 `WELL_KNOWN_PATHS` 접미 제거,
    `prefix = urlparse(mount).path.rstrip("/")`, `origin = scheme://netloc`;
    루트상대면 `origin+prefix+s`, bare면 `origin+prefix+"/"+s` → `normalize_http_url(결과)`.
  - 부수효과(보안 plus): bare `evil.com/x`가 이전엔 `http://evil.com/x`(타host!)로 갔으나 이제 prefix
    하위 path로 묶여 **host 혼동이 좁아진다**(host 불변).
- 81행 `data["url"] = normalize_http_url(data["url"], base=candidate)` → `_resolve_card_endpoint(...)`.

### `probe_endpoint`
- `return resp.status_code < 600` → `return resp.status_code not in (404, 410)`. 주석에 405-vs-404 근거 명시.

## 검증 사다리 3런 (069 항목 5, 비겹침)

1. **단위 시맨틱** (`tests/verify_071_card_endpoint.py`): resolution 매트릭스(루트상대+prefix / bare / 절대
   passthrough / origin루트 회귀 / 두 well-known 변형 / base-직접) + probe 술어(404·410→dead, 405/200/401/403/3xx→live).
2. **실 인프라 통합**: `mock_remote`에 prefix 하위 well-known + 루트상대 `/a2a` 카드를 추가하고 connect →
   저장 endpoint가 prefix 보존 → probe live → A2A 호출 도달까지 확인(가능 범위). 실패 시 단위+적대로 대체하고 사유 기록.
3. **적대 codex** (rung 3): prefix-상대 resolution이 SSRF/host-confusion/오픈리다이렉트를 여는가? "보장 목록의
   여집합". host 불변·결과 normalize 통과·bare가 좁아짐을 반증 시도.

## RBAC 체크리스트 적용 여부
**미적용** — 트리거 객관신호(user_id·테넌트 컬럼·`_own_scope`/`_visible_or_404`/`_assert_*owns`) 없음.
순수 네트워크 endpoint resolution + liveness probe라 소유권 경계 무관(self-judgment 아닌 신호 기준 — 069 트리거).

## 적대 검증 결과 (rung 3 — codex gpt-5.5)

P1 없음. 발견 5건 triage:
- **F4 (P2, 채택·봉합)**: 문자열 concat이라 루트상대 `/../../admin`이 `…/prefix/../../admin`으로 stored
  endpoint에 **literal `..`가 잔존** → 프록시 path 정규화로 prefix 탈출 가능. → resolver를 **`urljoin`으로
  전환**해 dot-segment canonical화 + origin clamp(`https://h/admin`, `..` 미잔존). 단위 R11 추가.
- **F1 (by-design·무회귀)**: 절대/스킴상대 raw는 카드와 *다른* host 가능 — 그러나 옛 코드도 동일(절대 url
  위임 불변)이고 call-time `guard_url`이 사설/루프백 차단 유지. docstring 과장("host 항상 동일")만 정정
  (상대 분기만 host-pinned임을 명시).
- **F3 (수용·정직화)**: 일부 프레임워크가 method-mismatch에 404 → 정상 endpoint를 dead 오판 가능. 단
  **status 라벨만** 좌우(저장·실호출 무관) → docstring에 tradeoff 명시.
- **F2(스킴 트릭)·F5(userinfo)**: fail-closed 확인(normalize가 거부). query/`#`는 over-reject 위험으로 통과 유지.

검증 사다리 비겹침 재확인: 단위·라이브는 **clean input**만 봐 dot-segment 사각이 있었고, **적대 rung만**
F4를 잡음(learning 073·072의 동형 — 적대 타자가 단위·라이브 못 보는 입력공간을 짚음).

## 완료 체크
- [x] P1 `_resolve_card_endpoint` — prefix 보존 resolution(urljoin·dot-segment clamp), 절대/origin루트 회귀 없음
- [x] P2 probe 404/410 → dead
- [x] 단위 매트릭스 그린(resolution 12 + probe 7, verify_071)
- [x] 라이브 통합 e2e 그린(verify_071_live — 카카오페이 시나리오 재현) + 045/057/060/063 무회귀
- [x] 적대 codex P1 없음, F4 봉합·F1/F3 정직 기록

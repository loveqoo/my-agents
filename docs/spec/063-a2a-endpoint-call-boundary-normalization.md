# 063 — A2A endpoint 호출 경계 정규화 + 빌더 하드닝 + stale 데이터 마이그레이션

> 상태: 초안(AI) → 인간 검토. 짝: 060(등록 시점 정규화)·061(A2A 노출). 선행 자산:
> learning 065(큐레이션/계약은 경로 전체에서 유지 — 한 홉이 stale값 신뢰하면 깸)·042(SSRF 가드)·
> retrospect 050. 실버그 레포트(사용자 스샷): A2A 에이전트 채팅 시 버블에
> "[오류] URL은 http(s) 절대 URL이어야 합니다"만 반복.

## 1. 문제 (실제 버그 레포트 — 코드재현으로 확정)

Playground에서 A2A 에이전트("사내 정보 검색 어시스턴트")와 대화하면 응답 버블에
**"[오류] URL은 http(s) 절대 URL이어야 합니다"**가 뜨고 대화가 안 된다.

확정 연쇄(probe-deeper, 추측 금지 — 로컬 재현 완료):
- source=`external`/`code` 에이전트 채팅 → `chat._a2a_stream` → `a2a_client.a2a_stream`
  → `net_guard.guard_url(endpoint)`.
- 저장된 `agent.endpoint`에 `http(s)://` 스킴이 없으면 `guard_url`이 정확히
  `SsrfBlocked("URL은 http(s) 절대 URL이어야 합니다")`를 던진다(net_guard.py:124). → 스샷 그대로.
- spec 060의 `normalize_http_url`은 **등록 시점에만** 걸린다(fetch_card·register). 정규화 도입
  **이전에 만든 에이전트(stale 행)**나 정규화를 건너뛴 경로는 endpoint가 스킴 없는 채로 남고,
  **호출 경계가 저장값을 재정규화 없이 신뢰**해 매 호출 깨진다.

**learning 065 패턴 그 자체**: 계약(절대 URL)이 등록 홉에선 지켜지나 *저장→호출* 홉이 stale 값을
신뢰. 한 홉이라도 계약을 안 지키면 양끝이 옳아도 깨진다. 견고한 픽스 위치는 **소비(호출) 경계**.

재현(로컬, 서버 불요): scheme-less endpoint 3종이 현행에선 전부 "절대 URL" 에러 →
호출 경계에서 `normalize_http_url → guard_url`하면 절대화 후 통과(allowlist) 또는 **조치 가능한
SSRF 메시지**(A2A_ALLOWED_HOSTS 추가 안내)로 업그레이드. `127.0.0.1`은 정규화 후에도 **여전히
차단**(보안 불변 유지 확인).

## 2. 목표 / 비목표

- 목표: stale/스킴누락 endpoint를 가진 기존 에이전트도 채팅·표시가 **자가치유**되어 동작한다.
  사설 대상이면 모호한 "절대 URL"이 아니라 **조치 가능한 SSRF 안내**가 뜬다.
- 비목표: SSRF 정책 자체 변경(가드는 그대로). A2A 프로토콜/카드 스키마 변경. 등록 UX 변경.
- **분리(사용자 합의)**: allowlist를 env→DB로 옮기고(`A2A_ALLOWED_HOSTS`→`ALLOWED_HOSTS`, 무재시작,
  Admin UI+API) MCP/A2A 공용으로 일반화하는 작업은 **spec 064로 분리**. 본 스펙은 채팅 버그(스킴 누락
  endpoint) 자가치유에 집중 — 064에 의존하지 않고 단독으로 막힘을 푼다.

## 3. 보안 불변 (변경 없음 — 적대 검증 대상)

정규화는 **절대화만** 한다(스킴 없는 host→`http://` 전치, 스킴-상대→`http:` 전치). 사설/루프백/
메타데이터 판정은 **여전히 `guard_url`**이 정규화된 URL에 그대로 돌아 수행한다. 즉 정규화는 가드를
**우회시키지 않는다** — 오히려 가드가 *판정할 수 있는 형태*로 만들어 준다. 비-http 스킴(`ftp://`)·
절대화 불가는 `normalize_http_url`이 `ValueError`로 거부(가드 전에 차단). **codex 적대 리뷰로 이
불변을 점검**: 호출 시점 정규화가 어떤 우회(스킴 혼동·리다이렉트·DNS)를 여는지.

## 4. 처방

### D1 — 호출 경계 정규화 (핵심·자가치유)
`a2a_client.a2a_stream`: `guard_url(endpoint)` **앞에** `endpoint = normalize_http_url(endpoint)`.
둘 다 `ValueError`(SsrfBlocked 포함)를 던지고 이미 error 프레임으로 잡으므로 추가 처리 불요.
정규화된 `endpoint`가 이후 실 httpx 호출(`_stream_sse`/`_send_single`)에도 그대로 전달된다.
이 한 점이 **모든 outbound A2A 호출의 단일 chokepoint**(chat._a2a_stream가 여기로 모임).

### D2 — 빌더 하드닝 (저장 데이터 청결)
`agents.py` `_build_external_agent`·`_build_code_agent_from_card`: `endpoint=_clip(card.get("url"),400)`
를 `endpoint=_norm_endpoint(card.get("url"))`로. `_norm_endpoint`=clip 후 `normalize_http_url` 시도,
실패하면 raw 보존(등록을 500내지 않음 — 호출 경계 D1이 2차 방어). fetch_card가 이미 정규화하므로
정상 경로는 idempotent, fetch_card 우회 미래 경로엔 방어.

### D3 — stale 데이터 일괄 마이그레이션 (비가역 — dry-run + 적대 필수)
`tests/migrate_063_normalize_endpoints.py`: source∈(code,external)·endpoint가 `http(s)://`로
시작하지 않는 행을 골라 `normalize_http_url`로 절대화해 UPDATE. **기본 dry-run**(바뀔 행만 출력),
`--apply`로만 실제 쓰기. 정규화 불가(빈 값·비-http)는 건드리지 않고 보고만(호출 경계가 처리).
표시/probe(`probe_endpoint`)는 같은(이제 청결한) endpoint를 읽으므로 함께 정합.

## 5. 검증 (사다리 — 자가검증 지양, 비겹침)

- **단위(시맨틱)**: a2a_stream가 scheme-less endpoint에 "절대 URL" 에러를 더는 안 냄(정규화 경유)·
  `_norm_endpoint`(스킴없음→http전치, 절대→유지, 비-http→raw보존)·마이그레이션 선별 로직(순수부).
- **라이브 통합(실 인프라)**: 로컬 DB에 **scheme-less endpoint(127.0.0.1 mock)**를 가진 stale 행을
  주입 → API 부팅(A2A_ALLOWED_HOSTS=127.0.0.1) → 채팅 → 더는 "절대 URL" 에러 아님, mock 응답 수신.
  마이그레이션 dry-run이 그 행을 정확히 집고 `--apply` 후 endpoint가 절대화됨을 재조회로 확인.
- **적대(codex)**: D1 호출 시점 정규화가 SSRF 가드를 우회시키지 않는지(스킴 혼동·`//`·`\`·유니코드
  호스트·포트 트릭), D3 마이그레이션이 안전 행만 건드리고 멱등·비파괴인지(중복 실행·부분 실패).

## 6. 완료 조건

- [x] scheme-less endpoint 에이전트 채팅이 "절대 URL" 에러 없이 동작(또는 사설이면 조치 가능 SSRF 안내).
  → D1: `a2a_client.a2a_stream`이 `guard_url` 앞에서 `normalize_http_url` 적용(net_guard 단일 chokepoint).
  → 라이브 `verify_063_live.py` PASS: 주입한 stale 행(endpoint=`127.0.0.1:PORT`, scheme 없음) 채팅이
    "절대 URL" 에러 없이 mock A2A 응답 수신. 단위 U3: scheme-less가 "절대 URL" 아닌 조치 가능 메시지.
- [x] `_build_*` 빌더가 endpoint를 정규화해 저장(정상 경로 무회귀).
  → D2: `agents.py` `_norm_endpoint`(clip→normalize 시도, 실패 시 raw 보존)를 `_build_external_agent`·
    `_build_code_agent_from_card`에 적용. 단위 U4 PASS(스킴없음→http·절대 유지·비-http→raw·None→None).
- [x] 마이그레이션이 dry-run 기본·`--apply`만 쓰기·안전 행만·멱등.
  → D3: `tests/migrate_063_normalize_endpoints.py` 기본 dry-run, source∈(code,external)·scheme 없는 행만
    선별, compare-and-set UPDATE. 라이브 왕복 PASS(dry-run 집음→apply 절대화→재실행 0건 멱등). 단위 U5 PASS.
- [x] codex 적대 통과(정규화가 SSRF 우회 안 함, 마이그레이션 비파괴).
  → codex 1차 [P1] SSRF(colon-form userinfo 둔갑: `mailto:user@example.com`→공인 host 우회)+[P2]
    lost-update 적발 → 수정(normalize가 userinfo/비숫자포트 fail-closed·migration compare-and-set) →
    재점검 "P1 closed"(전 벡터 ValueError, encoded-@는 guard_url 차단, 잔여 우회 없음). 회귀 U1b/U1c 고정.
- [x] 무회귀: 이미 절대 endpoint인 에이전트(seed Doc Translator 등)·로컬(ui) 채팅 경로.
  → U1 멱등(이미 절대→유지)·060 정규화 무회귀 PASS·IPv6(`http://[::1]`) false-reject 회귀 수정 확인.
    ui source는 endpoint 호출 경로 자체를 안 타므로(마이그레이션 선별서도 제외) 영향 없음.

## 7. 회고·자산 (Compounding)

- AI 회고: `.dev/retrospect/051-a2a-endpoint-call-boundary-normalization.md`
- learning: `.dev/learning/066-normalize-at-boundary-can-reopen-guard-rejected-input.md`
  (가드 앞 관대 정규화는 가드의 *입력 분포*를 바꿔 스킴으로 거부되던 입력을 둔갑시켜 통과시킬 수 있다)
- 분리된 후속: spec 064(allowlist env→DB, `A2A_ALLOWED_HOSTS`→`ALLOWED_HOSTS`, 무재시작, Admin UI+API).

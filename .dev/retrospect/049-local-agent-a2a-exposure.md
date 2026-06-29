# 049 — 로컬(ui) 에이전트를 A2A로 노출해 플레이그라운드에서 dogfood (스펙 060+061)

> 짝 스펙. 060=A2A 등록 에이전트를 플그서 테스트 가능하게(URL 정규화 + 로컬테스트 UX),
> 061=`exposed.a2a` 플래그 실동작화(무력 플래그 → 실 서빙). 한 세션에 둘을 함께 만들었다.

## 무엇을 했나

사용자 버그: "A2A로 등록한 에이전트를 플레이그라운드에서 테스트하려는데 잘 안 됩니다." 코드
재현으로 **두 실패모드**를 확정(추측 금지·메모리 probe-deeper):

- **모드1(060)**: `validate_card`가 서비스 `url`의 *절대성*을 검사하지 않아, 스킴 없는
  `host:port/path` 카드가 *등록은 통과*하고 채팅 시점 `guard_url`에서 "URL은 http(s) 절대
  URL이어야 합니다"로 **늦게·모호하게** 깨졌다. → `net_guard.normalize_http_url`(관대 정규화:
  이미 http(s)→그대로 / `//host`→http전치 / `/path`+base→urljoin / 스킴없는 host:port→http전치,
  결과 scheme·hostname 단언 못하면 ValueError)을 `fetch_card`·`register_code_agent`·`expose_agent`에
  적용해 **등록 시점에 절대화**. 보안 불변: 정규화 url에 `guard_url`이 그대로 돌아 사설/루프백은
  여전히 차단(정규화는 가드를 우회시키지 않는다).
- **모드2(060)**: 루프백/사설 대상은 SSRF 기본 차단(스펙 042) → `A2A_ALLOWED_HOSTS` 필요.
  로컬테스트 UX로 보강(B1 차단메시지 host echo+복붙예시[learning 063], B2 연결모달 allowlist 힌트).

그런데 사용자의 정제 요구 — "임시로 로컬 에이전트도 A2A로 오픈하여 등록하고 플레이그라운드에서
테스트하면 어떨까요?" — 가 **더 깊은 공백**을 드러냈다: `exposed.a2a` 플래그가 **무력**이었다
(저장만 되고, 그걸 읽어 서빙하는 엔드포인트가 없음; JSON-RPC A2A 서버는 canned `mock_remote`
하나뿐). 즉 "로컬 에이전트를 A2A로 열어 등록·테스트"할 *대상 자체가 없었다*. → 061: 무력 플래그를
실동작화.

## 핵심 통찰

1. **무력 플래그(inert flag)는 false-green이다.** `exposed.a2a`는 PUT으로 저장되고 UI 스위치가
   돌고 "저장됨"이 떴다 — 토글의 happy-path는 전부 초록인데 *그 플래그를 소비하는 코드가 없어서*
   기능은 부재했다. 설정이 영속되는 것과 그 설정이 *작동*하는 것은 별개. (→ learning 064는 이
   가족의 *보안판*=self-base 신뢰경계를 다룬다. 무력-플래그 자체는 이 회고에 남기고 별도 learning은
   안 만든다 — 패딩 금지.)

2. **self-fetch가 새 인증 위상을 강제했다.** 등록(`POST /agents/connect`)은 서버가 *자기 카드를*
   fetch한다 — `fetch_card`는 인증 헤더를 보내지 않는다. 카드가 전역 `_auth` 뒤에 있으면 self-fetch가
   401로 깨진다. 그래서 `a2a_server.router`는 **무인증 마운트**(mock_remote와 동일 패턴), 카드는
   공개, **JSON-RPC 호출만 라우트 단위 인증**(`current_principal`). 게이트(존재+source==ui+exposed.a2a)는
   양 라우트 공통, 아니면 404로 *노출 안 된 에이전트의 존재조차 누출 안 함*(fail-closed).

3. **dogfood 왕복이 클라이언트 경로를 자기 테스트 하니스로 재사용한다.** 노출 ui 에이전트 →
   공개 A2A 카드 → connect(self-fetch, x-my-agents 없음 → **external 분류**) → external 사본 채팅 →
   `_a2a_stream` → `POST …/a2a`(머신토큰 인증) → `chat.stream_local_reply`가 원본 ui 에이전트의 실
   LangGraph 런타임 실행 → 실 LLM 텍스트가 되돌아온다. 인바운드(서버) 표면을 테스트하려고 우리가
   이미 가진 아웃바운드(클라) 경로로 자신에게 connect하니, **한 왕복이 클라+서버 양쪽을 동시에
   운동**시킨다. 실측 응답을 실제로 받았다(verify_061_live_e2e green).

4. **스펙이 *예상*한 위험도 적대리뷰가 *구체화*하면 싸게 고친다.** 061 §5는 self_base 오염 가능성을
   이미 적었지만 폴백을 `request.base_url`(Host 파생) 그대로 뒀다. codex가 **H1(High, Host-header
   poisoning)**으로 구체화: `Host: attacker.example` → 카드 url을 공격자 호스트로 돌려 이후 A2A
   호출의 프롬프트·Bearer 토큰을 탈취. 막연한 "가능성 있음"과 적대자가 짚은 "이 입력으로 이렇게
   샌다"는 다르다 — 후자가 오면 *그 자리에서* 고친다. `_self_base`를 `net_guard.host_is_private(host)`로
   제약(루프백/사설 Host에만 폴백 허용, 공인 Host는 503 fail-closed로 `A2A_SELF_BASE_URL` 명시 강제).
   라이브 검증: 오염 Host→503, 루프백→200.

## 검증 사다리(3-rung 비겹침, 메모리 verification-ladder)

- **단위(시맨틱)**: verify_060(C1~C5 정규화·SSRF불변·무회귀) + verify_061(D1~D6 카드 스키마·게이트·
  send/stream 프레임·미지원 메서드·비에코) + H1 단위(공인 Host→503 / env설정→Host 무시).
- **라이브 통합(실 인프라·요청간 글루)**: verify_061_live_e2e — 부팅된 API(127.0.0.1:8000)+실 DB에
  노출 ON→공개 카드 200(절대 url `/a2a`로 끝·x-my-agents 없음)→무인증 POST→401→connect 실 왕복
  채팅(실 LLM 텍스트)→노출 OFF→카드+a2a 둘 다 404→원복. H1 라이브(오염 Host 503·루프백 200).
- **적대(타자, codex)**: 새 인바운드 표면(인증우회·게이트회피·self_base 오염·자원캡·자격증명에코)
  적대리뷰. 결과: **명시적 no-bypass 평결** + H1(고침) + H2(Medium, 미분류 MCP 도구는 승인 없이
  실행 — checkpointer=None은 interrupt() 호출 도구만 fail-close). H2는 *기존 chat() 행동·인증게이트
  뒤·권한상승 없음*이라 v1 한계로 문서화(스펙 §6 HIL scope-out과 일관). 분류된 위험 도구는
  fail-closed.
- **브라우저(D7)**: shot-a2a-card-061.mjs — 노출 토글 ON 시 admin에 *실* 카드 URL
  (`…/agents/<pk>/.well-known/agent-card.json`)이 복사 노출, 가짜 `a2a://my-agents.` 부재,
  allowlist 힌트 존재. 캡처+단언 green(D7_OK).

## 절차에서 배운 것(메타)

- **짝 스펙은 첫 스펙을 *시작 전에* 커밋했어야 한다.** 060을 짓고 바로 061로 넘어가며 `net_guard.py`·
  `AgentsView.tsx`·`docs/spec/INDEX.md`가 두 스펙 변경으로 엉켰다 — 회고 시점에 헌크/라인 분리 곡예가
  필요했다(메모리 compounding-ends-with-commit이 경고한 바로 그 상황). 다행히 헌크가 비인접이라
  깔끔히 갈렸지만, *교훈은 전향적*: 한 스펙 끝나면 다음 스펙 손대기 전에 그 스펙만 커밋한다.
- **추측 대신 코드 재현으로 실패모드를 못 박았다**(probe-deeper). "URL 에러"라는 한 증상이
  실은 두 독립 모드(정규화 부재 / SSRF 차단)였고, 둘은 다른 처방을 받았다.

## 자산

- 스펙: docs/spec/060-a2a-playground-endpoint-normalization.md, docs/spec/061-local-agent-a2a-exposure.md
- 코드: net_guard.py(normalize_http_url·host_is_private), agent_card.py·agents.py(정규화 적용),
  a2a_server.py(신규 무인증 라우터), chat.py(stream_local_reply), main.py(라우터 마운트),
  AgentsView.tsx(B2 힌트·D7 카드 URL)
- 검증: verify_060_url_normalization.py, verify_061_a2a_exposure.py(+H1), verify_061_live_e2e.py,
  tests/browser/shot-a2a-card-061.mjs
- learning 064(self-advertised-address 신뢰경계)

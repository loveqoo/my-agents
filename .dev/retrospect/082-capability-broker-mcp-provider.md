# 082 — 능력 브로커 kind 확장: MCP provider (Phase 2-a) + 서브스텝 HIL

스펙: `docs/spec/101-capability-broker-mcp-provider.md`
관련: retrospect 081(브로커 Phase 1), learning 100(채널 격리·인가 입도), learning 101(이번 학습)

## 무엇을 했나

스펙 100의 "1개 시임(discover/describe/invoke)으로 여러 kind"라는 주장을 **두 번째 provider(MCP)**로
실증했다. `broker.py` 안에 내부 `_CapabilityProvider` 시임을 도입해 **정책은 브로커 단일 지점에
유지**(allowlist∩RBAC·deny-by-default·존재 비노출·단일 `_permitted`)하고 **kind별 메커닉만 provider로**
분리했다 — `AgentProvider`(A2A 행위보존 이관) + `McpProvider`(신규). MCP 능력 입도는 **툴 단위**
(`mcp:<server>/<tool>`), 네임스페이싱 `<kind>:<id>`(bare=agent 하위호환, `mcp:<server>`=서버 전체).
전송은 기존 `MultiServerMCPClient`+`net_guard`를 공유 헬퍼(`runtime.mcp_connection`)로 뽑아 재사용
(build_mcp_tools와 드리프트 0). 데모 flow `orchestrate`는 코드 0 재사용.

**서브스텝 HIL**(사용자 요청): 위임 MCP 툴이 승인을 요구하면(`local-tools/delete_record`)
`broker.invoke`가 **전송 이전** `interrupt()`로 부모 그래프를 pause → 기존 Approval/resume 파이프라인을
그대로 재사용(새 배선 0). 승인 정책은 `_APPROVAL_ACTIONS` 단일 소스(그래프-tools와 드리프트 0),
interrupt는 부수효과 이전이라 멱등, `supports_hil→True` 정직화.

## 검증 (3-rung 사다리 — verify_101_broker_mcp.py)

- **[U] 단위(순수)**: 네임스페이스 파싱·`_mcp_allow` 도미넌스(서버 전체가 툴 덮음, 순서 독립)·
  `_permitted` mcp 의미론(툴/서버전체/교차거부)·`approval_for`(mcp delete→payload, echo/agent→None)·
  `_adapt_args`·provider 라우팅·드리프트0 + deny-by-default DB 미접촉.
- **[H] 통합(실 mock MCP + 실 DB)**: discover/describe/invoke echo 왕복(untrusted·broker_invoke:mcp
  노드)·툴 단위/서버 전체/교차 서버 deny-by-default·orchestrate 플로우(HTTP super 쿠키)·HIL 왕복 **2결**
  (그래프 레벨 invocations 실측 pre=0/approve=1/reject=0 + 풀 HTTP chat→approval→resolve).
- **무회귀**: verify_100(행위보존 게이트)·054·041·085·089 전부 green.
- **적대(codex)**: 파일시스템 경계 프리픽스로 리뷰. 0 actionable P0/P1(아래 정직 분류).

## 아팠던 것 (integration rung이 아니면 못 잡았을 두 결함)

### 1. 설정 지속 경로 누락 — 시드가 write-schema를 우회해 드리프트를 숨김
`AgentConfig`(schemas.py) Pydantic 모델에 **`capabilities` 필드가 없어** `body.config.model_dump()`가
allowlist를 **조용히 버렸다**. `chat.py:139`는 `cfg.get("capabilities", [])`를 읽지만 지속 경로가 끊겨
항상 `[]`(deny-by-default) → 브로커가 아무것도 발견 못 함. **단위·그래프 레벨 테스트는 초록**이었는데,
allowlist를 직접 주입(`lambda k:True`·시드 행)하기 때문. verify_100의 HTTP 하네스마저 Agent 행을 DB에
**직접 시드**해 create-엔드포인트(실 스키마)를 안 탔다. **풀 HTTP 통합 rung**(실 스키마로 생성 → 실
principal로 chat)만이 이 틈을 잡았다. 고침 = `AgentConfig.capabilities` 필드 한 줄 추가(스펙 100 §69가
`config["capabilities"]`를 출처로 명시). → learning 101.

### 2. 스테일 --reload 서버 — 같은 테스트 파일이 두 코드베이스를 검증
`--reload` 개발 서버가 이전 세션 편집을 안 물어 **구 브로커**(pre-McpProvider)가 돌았다. in-process
테스트(신 코드)는 통과, HTTP 테스트(구 코드)는 실패 — 같은 로직의 split-brain. **추측 대신 서버 로그의
*부재*로 진단**: chat 중 `/_remote/mcp/` 호출이 0 = 서버가 MCP discovery를 시도조차 안 함. 재기동
(사용자 원격 → 호스트 로컬 작업 직접 수행). 재기동 후에도 실패가 남아 #1(진짜 스키마 결함)로 좁혀짐.

## codex 적대 리뷰 — 3-verdict 정직 분류 (0 actionable)

- **[P1] #3 untrusted→SystemMessage = 오탐(false positive).** codex가 `orchestrate.py:104-117`을 인용
  했으나 그건 `describe()`다 — 실제 `build_synthesis_messages`(81-100)는 delegated를 **HumanMessage**
  (데이터 채널)에 넣고 system엔 지침만. 채널 격리(learning 100)는 present·verify_100 단위 단언됨.
  **소스 라인 직독으로 기각.** → 리뷰어도 검증하라(라인 인용이 틀릴 수 있다).
- **[P1] #1 kind-단위 RBAC + #2 borrowable allowlist = 이미 수용된 명시 경계.** 스펙 100 §6(130-135)이
  *"per-cap·per-user 인가 + 에이전트 소유권(codex 100 [P1] #1/#2 수용, 명시 경계)"*로 이미 문서화.
  Agent엔 owner 없어 공유 카탈로그, RBAC은 `capability:{kind}` 단위. 기본 정책 admin-only라 실경계는
  "admin만 오케스트레이션". **우회 아님·입도 한계**, 스펙 101 §비목표 재이연. 신규 결함 아님.
- **[P2] #4 스테일 스냅샷** = 위험 경로(HIL) 비적용: `resume_approval`이 재개 시 `_load_context`로 현재
  config를 다시 읽어 `_build_resume_broker`에 넣으므로 재개 시점 revocation 반영. 단일 동기 턴만 스냅샷
  (무시 가능). **수용.**
- **[P2] #5 in-process 타이밍 오라클** = 이미 신뢰된 in-process 코드(impl=레지스트리 키, eval 없음
  085)만 악용 가능. 교차 스코프 존재 비노출은 유지. **수용.**

## 잘된 것

- provider 시임이 정책을 안 건드리고 kind만 확장 — verify_100 무회귀가 행위보존을 게이트.
- HIL이 새 배선 0으로 붙음(interrupt 전파가 `_wrap_mcp_tool`과 동일, resume 파이프라인 재사용).
- 099 순수함수 규약이 또 벌어줌(`_mcp_allow`·`_permitted`·`_adapt_args`를 모델 없이 단위 단언).
- RBAC 체크리스트가 또 작동 — codex가 우회는 못 찾고 이미 문서화된 입도 한계만 재확인.

## 다음 후보

로드맵·8항목 소진 상태(memory 참조). 브로커 축의 자연스러운 다음은 **능력 브로커 discovery
오케스트레이션**(memory: agent-source-three-way §"다음 축은 능력 브로커")이거나, RAG/memory provider
(kind 확장 후속), 또는 admin UI capabilities 편집(Phase 2-d, 지속 경로가 이제 열렸으니 UI만 남음).
`.dev/backlog.md`에서 Scaffolding으로 논의.

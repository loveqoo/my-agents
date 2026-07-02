# 117 — A2A 협업 실증 + 위임 승인 게이트

## 배경 / 왜

플랫폼을 만든 **핵심 이유**가 "다양한 에이전트를 만들어 재사용하고 **A2A로 협업**"인데(memory
why-build-multi-agent-platform), 브로커 `AgentProvider`(kind=agent)는 discover/invoke까지 배선돼 실제
`a2a_stream` 원격 호출을 하지만 — **에이전트가 다른 에이전트에게 위임하는 전 경로를 한 번도 관통
실증한 적이 없다**(스펙 110은 RAG판만). 또 `AgentProvider.approval_for`는 `None`(스펙 100에서 "A2A
위임 승인 정책 소스 없음 — 후속"으로 남김). 방향 1(사용자 "모두 차례대로")의 첫 항목.

교훈(learning 110): **링크별 초록 ≠ 체인 증명** — 각 고리가 따로 초록이어도 한 경로를 실제로 관통하기
전엔 이음매(글루·principal 전달)가 미검증. 첫 E2E가 곧바로 진짜 이음매를 드러낸다.

## Part A — A2A 협업 엔드투엔드 실증 (주(主) 산출물)

조율형(orchestrate) 에이전트가 **등록된 A2A 에이전트에게 위임**하는 채팅 1턴을 관통시킨다. 스펙 110의
RAG판(`broker_invoke:rag:*`)을 **agent판**(`broker_invoke:agent:*`)으로.

- **결정적 검증**: 위임 경로(broker discover → AgentProvider.invoke)는 LLM 독립. `a2a_client.a2a_stream`을
  결정적 프레임을 yield하도록 **패치**(네트워크 없이 관통 — SSRF/net_guard 하위 경계는 042/060/063이
  이미 검증)하고, chat EP → 브로커 → AgentProvider → fold(115 nonce 펜스) → synthesize(mock-llm) 전
  경로를 실행. `verify_117`이 trace에 `broker_invoke:agent:<name>` 노드 존재 + 무위임 대조(회귀가드)를 단언.
- **실제 principal 재현**(learning 110 필수): 위임은 유저 세션만(머신토큰 deny-by-default). chat EP만
  `app.dependency_overrides[current_principal]=슈퍼유저 스텁`으로 유저 세션 재현, 다른 EP는 Bearer 유지.
- **위임 타깃**: 등록된 원격(A2A) Agent 행(`source=remote/external`, `endpoint` 있음)을 시드. 카드
  streaming 여부는 config.card 재사용.
- **시각 증거**(선택, learning 110 "테스트+시각 두 겹"): 플레이그라운드 인스펙터에서 `broker_invoke:agent`
  노드 스샷 — 실 원격이 필요하면 도그푸드(로컬 ui-agent를 A2A로 노출, 스펙 061)로. 자동 검증은 Part A의
  결정적 verify가 하한, 스샷은 사용자 납득용.

## Part B — A2A 위임 승인 게이트 (opt-in, 무회귀)

`AgentProvider.approval_for`를 **옵트인**으로 채운다: A2A 위임은 **아웃바운드 호출**(원격 제3자에 사용자
질의를 전송 — 비용·유출 가능)이라 승인 게이트가 정당하나, 조율형의 상시 위임을 매번 막으면 흐름이
깨진다. 그래서 **위임 대상 Agent 행의 opt-in 플래그**로 게이트한다:

- 정책 소스 = 대상 Agent config의 `requires_approval`(불리언, 기본 **부재/False = 게이트 없음 = 현동작
  보존·무회귀**). MCP의 `_APPROVAL_ACTIONS` 옵트인(툴 단위)의 **에이전트 단위 형제**.
- 플래그 True면 `approval_for`가 non-None payload 반환 → 브로커가 전송(a2a_stream) **이전** `interrupt`로
  pause → 기존 Approval/resume(스펙 101·031) 재사용(새 배선 0). approve면 1회 전송, reject면 미전송.
- `approval_for`와 `invoke`가 **동일 정규화**(같은 user_text)로 "승인한 것 == 전송되는 것" 보장(105 처방).
- 소유권/RBAC 체크리스트: 승인 게이트는 기존 Approval 인프라(031/101)를 재사용하며 **새 per-user 데이터
  입구를 만들지 않는다**(승인 행 소유권은 기존 그대로). 옵트인 플래그는 대상 Agent 관리(수정) 권한
  안에서만 설정 → 스펙 112 관리 게이트가 이미 커버. → **본 스펙은 새 소유권 경계를 열지 않음**(명시).

## 검증 (3런)

- **단위**: `AgentProvider.approval_for` — 플래그 부재→None(무회귀), True→non-None payload(대상·질의 표기);
  `approval_for`/`invoke` 정규화 일치(승인=전송).
- **통합(실 그래프 + interrupt/resume)**: 옵트인 True 대상 위임 → 전송 이전 interrupt(a2a_stream 호출 0),
  approve 후 정확히 1회 전송, reject 후 0회(fail-closed). Part A의 결정적 관통(broker_invoke:agent 노드).
- **적대(codex rung 3)**: 3판정 모두 처리 —
  - **[P1] requires_approval가 AgentConfig 스키마에 없어 API 라운드트립서 드롭**(seed 직삽 테스트만 초록,
    learning 101 재현) → `AgentConfig.requires_approval: bool = False` 추가 + **B0 라운드트립 가드**(create→DB
    config 보존 실측). 봉합.
  - **[P1] "승인한 것==전송되는 것"이 재개 재실행 사이 args 비결정이면 깨짐** → 기본 orchestrate 경로는
    `state["query"]`(스펙 116으로 pending 커밋=재개 간 안정)라 **안전**. 일반 브로커 호출자가 재실행마다
    달라지는 args를 만들면 미보장 — **문서화 경계**(아래 OUT). `_a2a_text` 공유는 *현재 args* 정규화 드리프트만 닫음.
  - **[P2] 비-dict config → `.get` AttributeError**(오염 데이터) → `isinstance(cfg, dict)` 방어.
- **무회귀**: verify_100/101/102/110/115/116(브로커·오케스트레이션·fold·재개).

## 비목표 (OUT)

- **다중 A2A 위임의 순차 승인 표면화** — 스펙 116 OUT(101/102 다중 interrupt)과 동일. 안전은 fail-closed 유지.
- A2A 위임 결과의 신뢰 승격 — 결과는 영구 untrusted(데이터 채널, 스펙 100). 변경 없음.
- 승인 정책의 세밀화(호출당 비용·레이트리밋 기반 자동 게이트) — 후속. 여기선 소유자 opt-in 불리언 하나.
- 실 네트워크 A2A를 CI 테스트에 포함 — 전송 하위 경계는 042/060/063 검증분 재사용, 여기선 패치로 관통.
- **"승인한 것==전송되는 것"의 일반 브로커 보장** — 이 등식은 **재실행 간 args 안정**을 전제(codex [P1#2]).
  기본 orchestrate 경로는 `state["query"]`(스펙 116 pending 커밋)라 성립하나, 재실행마다 args를 새로
  만드는 임의 브로커 호출자엔 미보장. 완전 보장은 승인 payload에 args 스냅샷/해시를 바인딩해야 — 후속.
- **a2a.delegate self-approve 시드** — 현재 이 permission은 self-approve 정책에 없어 admin/superuser만 승인
  (fail-closed·안전). 소유자 self-승인(memwrite 105 선례)이 필요하면 시드 추가 — 후속(opt-in 기본 off라 저위험).

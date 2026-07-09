# 스펙 256 — 조율형의 로컬 에이전트 위임 (인프로세스)

## 배경 (사용자 지시, 2026-07-09)

조율형의 agent 위임은 Phase 1 경계로 원격(A2A: code/external)만 지원 — 같은 서버의 ui 에이전트끼리는
연결 불가. 사용자 방향: **내부 에이전트끼리는 A2A(HTTP 왕복)가 아니라 직접 호출** — I/O 최소화.
플랫폼의 근본 목적(다중 에이전트 협업)의 핵심 조각.

## 설계

### 실행 프리미티브 = 평가 러너 재사용 (eval_run_agent)
이미 갖춘 성질이 위임 의미론과 정확히 일치:
- **인프로세스**: _load_context→resolve_agent_runtime→astream (HTTP 0회).
- **무오염**: 세션 lazy-create 없음·memory.add 없음(회상 읽기는 수행) — 위임 실행은 하위 에이전트에
  흔적을 남기지 않는다(평가와 동일 계약).
- **승인 = 정직 실패**: 하위 실행이 HIL interrupt에 걸리면 error obs로 접힘 — 위임은 단발이므로
  "하위 승인 대기"는 위임 실패로 보고(대기 전파는 중첩 interrupt 복잡도 — 채택 안 함).
- **로컬 전용 게이트** 내장(비로컬이면 error).

### 브로커 — LocalAgentProvider (kind=agent 확장)
- candidates/load: allowlist의 agent:* 중 **로컬 ui + 활성 버전 보유**를 후보에 추가(기존
  AgentProvider의 원격 후보와 병존). 가시성은 호출자 principal 기준(공개 or 소유 — 존재 비노출 fold).
- invoke: eval_run_agent(대상, text, principal) → output을 위임 결과로(기존 채널 격리 fence·
  resultPreview 캡·trace broker_invoke:agent:* 그대로).
- **하위 트레이스 관통(사용자 결정 — 트레이싱 관점)**: 하위 실행의 canonical 노드(rag:X·mcp:s/t·
  memory:used …)를 brokerCalls.subTraceNodes로 조율형 턴 트레이스에 실어, 인스펙터 위임 카드에서
  "하위 실행 흐름"으로 열람(상한 캡). 비영속이되 관측은 온전 — 인프로세스 위임의 고유 가치.
- **순환 방지 = 깊이 1**: 위임받은 하위 실행에서는 agent-kind 능력을 제거(조율형 하위가 다시
  에이전트 위임 불가) — A→B→A 순환을 구조로 차단. eval_run_agent에 deny_agent_delegation 플래그.
- 원격 위임과의 구분: 트레이스/카드에 로컬 표식(호출 방식이 다름을 정직하게).

### UI
- 생성 폼·오버라이드 "다른 에이전트" 목록에 로컬 ui(활성 버전 보유, 자기 자신 제외) 포함 —
  '로컬'/'A2A' 태그로 구분.

### 채택한 경계 (근거 기록)
- 하위 실행 비영속(평가 계약 재사용) — 하위 에이전트의 세션·기억을 오염시키지 않음.
- 승인 필요 시 위임 실패(정직 에러) — 스펙 117의 A2A opt-in 승인축은 원격 전용 유지, 로컬은
  같은 신뢰 도메인이라 대상 opt-in 생략.
- 깊이 1 — 다단 위임은 필요가 증명되면 체인 캡으로 확장.

## 검증
- e2e: 조율형(mock)이 로컬 ui 에이전트에 위임 → 인스펙터 위임 카드(로컬 표식)·결과 합성.
  자기 자신 미노출·비활성(초안만) 미노출. 순환: 조율형→조율형 위임 시 하위에서 agent 능력 부재.
  하위 승인 도구 → 위임 실패 정직 보고. 무오염: 하위 에이전트 세션·메모리 Δ0.
- 단위: eval_runner deny_agent_delegation 필터.

## 검증 결과 (2026-07-09)
- **e2e 6/6**: 위임 노드(위임 · agent:이름)·"로컬 · 인프로세스" 태그·하위 실행 흐름 접기·하위
  트레이스에 rag 노드·하위 에이전트 세션 무오염(Δ0)·폼 "맡길 것"에 "· 로컬" 노출.
- **순환 방지 실증**: 조율형 A↔B 상호 참조 상태에서 A 실행 → B에 위임 1회, B의 하위 흐름
  (analyze·plan·delegate·synthesize)에 재위임 없음 — 0초 종료(무한루프 없음).
- **API 스모크**: broker_invoke:agent:*, local:true, subTraceNodes(["model","tools","model",
  "rag:search_documents"]) 관통 확인.
- 기존 스위트(칩·경로·오버라이드 단계) 무회귀. tsc 0.

## 시공 중 잡은 잠복 버그 (보너스)
- **A2A 위임 카드 미표시 잠복 버그**: brokerCalls 매칭이 `broker_invoke:<cap_id>`인데 agent kind의
  노드명은 `broker_invoke:agent:<이름>` — cap_id(agt_…)와 달라 **원격 A2A 위임 카드도 상세가 안
  붙고 있었음**(rag/mcp만 우연히 일치). inv의 node 필드를 chat 통과 필터에 추가+node 우선 매칭으로
  수정 — 이번 로컬 위임 검증이 기존 원격 위임의 표시 결함까지 드러냄.
- eval_run_agent principal 관통(하위 브로커 RBAC 주체=호출자) — None이면 하위 조율형에서 크래시.

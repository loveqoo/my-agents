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
- **순환 방지 = 방문 집합(깊이 N — v2, 사용자 결정 "깊이 1은 조율형의 존재 가치를 떨어뜨림")**:
  실행 경로의 agent_id 체인(루트 포함)을 chat→브로커→하위 eval_run_agent로 관통. 체인에 있는
  에이전트만 후보·호출에서 제외(재방문=순환 차단), **새 에이전트로는 무제한 하강**(종료는 유한
  에이전트 수로 보장). 비용 폭주 여유 캡 DELEGATION_MAX_DEPTH=8. discover와 invoke 양쪽 게이트
  (호출 시점 재검증).
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

## 수용 기준 확정 (사용자 — "첫 에이전트 세션에서 인스펙터로 하위 호출 이력")
- 실시간 턴: 위임 카드(로컬 태그·하위 실행 흐름·결과 본문) — D1~D4.
- **이력 재생**: 새 대화로 나갔다가 세션을 다시 열어도(저장된 trace 재생) 하위 호출 이력이
  인스펙터에 그대로 — D7 검증 추가, 7/7. 하위 에이전트 쪽은 무기록(무오염)이 설계 그대로 —
  이력의 단일 소유자 = 호출한(첫) 에이전트의 세션.


## codex 적대 리뷰 후속 (2026-07-09) — P1 1건·P2 3건 트리아지

`codex exec --sandbox read-only`로 `git diff 2114833..HEAD`(위임 256/257) 적대 검토. 4건 발견 →
전부 코드 대조로 검증(검증자 검증), 확정 결함 수정·나머지 판정 기록.

- **[P1 확정·수정] 브로커 로컬 위임에 `may_use_agent` 게이트 누락** (broker.py candidates/load).
  공격: member가 자기 조율형 config/override의 `capabilities`에 **타인 private 로컬 에이전트** agt_id를
  심고 RBAC `capability:agent`가 있으면, `AgentProvider.candidates/load`가 사용 게이트 없이 row를 로드 →
  discover에 이름/hook 노출·invoke로 **실행**·미존재/비활성 시 `not found` 접힘으로 존재 오라클. chat
  본경로는 `may_use_agent`로 404-fold하는데 **브로커 경로만 정합이 깨져 있었음**(스펙 147 위반, 정직한
  경계 아님 — 본경로와의 불일치). **수정**: candidates·load 양쪽에 `may_use_agent(a, self._principal)`
  게이트(external=항상·public=모두·private=소유자/특권만). principal None(재개 유실)이면 private 자동
  제외(fail-closed). 원격 A2A도 동일 게이트 적용(external은 무회귀, private code 에이전트 정합).
- **[P2 확정·수정] 승인 재개 경로가 delegation_chain·principal 유실** (chat.py `_build_resume_broker`).
  로컬 에이전트도 `config.requires_approval`면 `approval_for`가 승인 인터럽트를 만든다(로컬/원격 구분
  없음). 승인 후 `resume_approval`이 재구성한 브로커는 **principal도 chain도 안 넘겨** →
  `eval_run_agent(... principal=None, chain=())`: (a) `build_broker(None)`이 `str(principal.id)`에서
  **즉시 크래시** → 승인된 로컬 위임이 조용히 미실행(approved-but-not-executed = 거부 방향 오류),
  (b) 루트 agent_id가 체인에서 빠져 재개 후 재위임의 순환 불변식 약화. **수정**: `_build_resume_broker`가
  원 요청자 User를 로드해 principal로 관통 + 루트 agent_id로 chain 시작(chat 신규 경로와 대칭).
  방어: `AgentProvider.invoke`가 principal None 로컬 위임에서 크래시 대신 정직 에러로 접음.
- **[P2 확정·수정] 깊이 캡만 있고 위임 총량 예산 부재 → breadth 폭주** (orchestrate delegate 루프).
  방문 집합은 *깊이*만 막고 *너비*는 안 막아, 새 에이전트로의 팬아웃 곱(최악 분기^깊이=3^8)으로 모델
  호출 폭주 가능(순환 아님). **수정**: 턴 단위 공유 카운터(`delegation_budget={"n":…}`)를 루트→하위
  브로커까지 참조로 관통, `DELEGATION_MAX_TOTAL=32` 초과 시 정직 에러로 접음. 원격 A2A는 HTTP 왕복
  자연 상한이라 제외. eval 경로(admin 단발)는 예산 미주입 = 깊이 캡만(무회귀).
- **[P2 P1에 종속·별도 수정 불요] resultPreview/subTraceNodes 누출**. codex도 "P1을 먼저 닫으라"고
  명시 — 사용 게이트가 서면 위임 대상은 public/자기 소유뿐이라 preview/trace가 남의 것이 아니게 된다.
  P1 봉합으로 소멸(잔여 = public 에이전트를 내 입력으로 실행한 내 trace, 누출 아님).

**검증**: `tests/verify_256_delegation_gate.py` 9/9(P1 후보·로드 게이트·principal None fail-closed·
principal None invoke 정직 에러·예산 초과 정직 에러). 기존 스위트 무회귀 — 147(16/16)·117 A2A·116 재개
위임·101 브로커 전부 통과(외부 A2A 게이트 무회귀 확인). codex가 큰 구멍 아니라 본 것: discover→invoke
TOCTOU(load가 active/depth 재검증)·DelegationGraph 프론트 누출(백엔드 /agents가 이미 may_use_agent 필터).

## v2 — 깊이 N (사용자 결정, 2026-07-09)
- 깊이 1 폐기 → 호출 체인(방문 집합) 방식: chat이 루트 id로 체인 시작, 하위 실행마다 자기 id를
  덧붙여 관통. 체인 내 재방문만 금지 — A→B→C→… 다단 협업 가능.
- **검증**: 3단 체인 A(조율)→B(조율)→C(직접·rag) 성공 — A의 인스펙터에서 B 위임 카드, B의
  subTraceNodes 안에 broker_invoke:agent:chain-c(B→C 재위임)까지 관측. 상호 참조 A↔B는 여전히
  0초 종료(Y의 하위 흐름에 재위임 없음). UI e2e D1~D7·칩 스위트 무회귀.

# 스펙 258 — agent-flow 스킬 두 저작 모드 (사용자 지시)

## 배경 (2026-07-09, 사용자 보고)

agent-flow 스킬이 "정상 동작 안 함" 보고 — 사용자 진단: "source=ui가 아니라 code로, doc-translator처럼
만들어야 한다". 조사 결과 **개념 충돌**이 드러났다:

- **인프로세스 flow(agent-flow 현재 산출물)** = `source=ui` + `config.impl`. 우리 런타임이 그래프를
  실행(config·checkpointer 주입, 플레이그라운드 실 노드열). 신뢰 레지스트리 코드젠(스펙 099·085·089).
  seed `plan-execute-demo`가 그 정본 — 주석에 "source=ui(로컬 실행)이되 impl로 그래프를 가리킨다".
- **doc-translator** = `source=code`. **원격 A2A 서비스**(endpoint·token·배포메타 필수). `resolve_agent_runtime`이
  code/external은 무조건 None→`_a2a_stream` 릴레이로 보낸다. impl 무시.

즉 agent-flow flow를 source=code로 만들면 런타임이 원격으로 빠져 **flow가 실행조차 안 된다**(endpoint
없으면 깨짐). 지시를 그대로 적용하면 기능이 망가진다.

**사용자 결정(AskUserQuestion, 2026-07-09)**: "두 가지 버전을 모두 지원하자. 유저에게 의도를 묻고 분기."

## 설계 — 스킬이 모드를 먼저 가른다

agent-flow SKILL.md에 **0단계(모드 가르기)**를 추가하고 두 절차로 분기한다. API·런타임 변경 없음
(두 경로가 이미 존재) — **스킬 문서(저작 절차)만** 개정한다.

### 모드 A — 인프로세스 flow (source=ui + impl) [기존, 보존]
현재 SKILL.md 절차 그대로: `flows/<key>.py` 저작(CustomAgent) → `_bootstrap_builtins` 신뢰 등록 →
verify_099 → conformance("conforming") → API 재기동. 우리 서버 안에서 실행.

### 모드 B — SDK 배포형 code 에이전트 (source=code) [신규]
에이전트 로직은 **별도 서비스**(my-agents-sdk 배포)로 살고 A2A 카드를 노출, my-agents가 endpoint로
등록해 A2A 릴레이로 중계. 이 레포 안 산출물은 **등록 + (개발용) mock 엔드포인트**뿐.
- **카드 계약**: Agent Card에 `x-my-agents` 확장 = `manifest`(model·persona·memories·mcps·historyDepth)
  + `deploy`(repo·commit·runtime·versions). 이 확장 유무가 connect의 code/external 판정.
- **등록 두 경로**: `POST /agents/register`(RegisterCodeAgentIn: endpoint·token·model·persona·repo·
  commit·runtime·mcps·historyDepth 직접) 또는 `POST /agents/connect`(카드 url — x-my-agents 있으면
  자동 code). 실 호출은 `_a2a_stream`.
- **개발/데모**: 실 배포 서비스가 없으면 `mock_remote.py`의 SDK 카드(`/sdk/.well-known/agent-card.json`)
  + `/_remote/a2a` JSON-RPC 재사용/추가로 endpoint를 채워 테스트 가능(seed 방식).
- **검증**: `classify_runtime(source="code")=="non_conforming"`(정상 — 원격 다른 런타임, 에러 아님).
  템플릿=verify_057(connect 분류)·154(custom a2a)·117(a2a 위임/승인). 채팅 SSE가 릴레이로 원격 응답 중계.

### 경계 (둘 다 불변, 스킬에 명시)
- source=code는 원격 A2A → **endpoint 필수·impl 무시**. source=ui+impl은 인프로세스 → endpoint 없음.
- 섞으면 안 돈다: impl만 단 code(무시됨·원격 릴레이), endpoint 없는 code(채팅 시 깨짐). 스킬이 방지.

## 검증
- 스킬 문서가 코드 사실과 일치(엔드포인트·필드·conformance 상태·카드 계약 실존) — 작성 중 교차 확인.
- 비자명하니 deep-reasoner 적대 검토(두 분기가 정확한가·경계 누락 없나·모드 오선택 유발 없나).

## 결과 (2026-07-09)

SKILL.md를 두 모드로 개정: 0단계(모드 가르기 표+의도 질문+경계)+모드A(인프로세스, 기존 절차 보존,
A접두)+모드B(SDK code, 신규, B접두)+공통 커밋. 프론트매터 description도 두 모드 명시.

**시공 중 잡은 유령 참조 버그(보너스)**: 기존 스킬 모드 A가 검증 게이트로 **존재하지 않는 함수**
`classify_conformance(source="ui", impl=...)`를 참조하고 있었다 — 실제 함수는 `classify_runtime`(runtime.py:203).
verify_099_route.py는 처음부터 `classify_runtime`을 썼는데 스킬만 유령 이름을 들고 있었다. 스킬대로
따라 하면 그 지점에서 실패 → "정상 동작 안 함" 보고의 일부였을 개연성. `classify_runtime`으로 교정.

**검증(deep-reasoner 적대 문서 검토)**: 개정 스킬이 코드와 정확히 일치(유령 참조 0·모드 분기 정확·두
모드 다 실제로 도는 에이전트 산출·mock_remote 경로 성립을 코드 사슬로 확인). P1 없음. P3 2건 반영
(connect 판정 게이트를 "확장 유무"→"`x-my-agents.manifest`(dict) 유무"로 정밀화·디스패치 함수 위치 표기).

**남긴 것**: 두 모드는 이미 있는 API/런타임 경로(register_code_agent·connect·신뢰 레지스트리)를 쓰므로
코드 변경 0 — 스킬 문서만 개정. 실제 에이전트 저작은 사용자가 스킬을 호출할 때 수행.

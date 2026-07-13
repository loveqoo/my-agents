---
name: agent-flow
description: 에이전트 플로우를 저작한다 — 두 모드. (A) 우리 서버 안에서 도는 인프로세스 LangGraph flow(source=ui+impl, 신뢰 레지스트리 코드젠) 또는 (B) 별도 서비스로 배포돼 A2A로 연결되는 code 에이전트(source=code, doc-translator처럼). "에이전트 플로우 만들어줘", "새 flow/impl 추가", "그래프 에이전트 스캐폴드", "code/SDK 에이전트 만들어줘"에 사용.
---

# 에이전트 플로우 스캐폴드 (스펙 099 + 258 — 두 저작 모드)

에이전트를 저작하는 길은 **근본적으로 다른 두 모드**가 있다. 시각 빌더 없이 코드로 저작하되, 먼저
**어느 모드인지 갈라야** 절차·source·검증이 정해진다.

## 0. 먼저 모드를 가른다 (사용자 의도 질문 — 필수)

> **왜 먼저 묻나**: 두 모드는 source·런타임·검증이 전부 다르다. 잘못 고르면 안 돈다 — 인프로세스
> 로직에 `source=code`를 달면 런타임이 원격 릴레이(`_a2a_stream`)로 빠져 그 그래프가 **실행조차 안
> 되고**, code 에이전트에 endpoint를 안 주면 채팅 시 깨진다. 그래서 **저작 전에 반드시 확정**한다.

| | **모드 A — 인프로세스 flow** | **모드 B — SDK 배포형 code 에이전트** |
|---|---|---|
| 실행 위치 | 우리 서버 **안**(LangGraph 인프로세스) | 별도 서비스로 **밖**(A2A 릴레이 중계) |
| source | `ui` + `config.impl=<key>` | `code` (endpoint·token·배포메타) |
| 런타임 | `resolve_agent_runtime`이 그래프 실행 | None → `_a2a_stream` 원격 릴레이 |
| 로직 위치 | **이 레포** `flows/<key>.py` | **레포 밖**(my-agents-sdk 배포 서비스) |
| 정본 예시 | `route` impl(flows/route.py — 코드젠 산출물)·`plan_execute` impl(SDK 수기) | seed `doc-translator` |
| 신규 보안표면 | 0(저작시점 코드젠, 스펙 099) | 0(원격 등록, 기존 A2A 경로) |

**질문(모호하면 그대로 물어 확정)**: "이 에이전트를 **우리 서버 안에서 직접 실행**하나요(인프로세스
flow — 그래프를 이 레포에 코드로 짬)? 아니면 **별도 서비스로 배포해 A2A로 연결**하나요(SDK code
에이전트 — doc-translator처럼)?"

- **안에서 직접** → **모드 A**(아래 A절).
- **밖에서 배포·연결** → **모드 B**(아래 B절).

**경계(둘 다 불변)**: `source=code`는 원격 A2A라 **endpoint 필수·impl 무시**. `source=ui+impl`은
인프로세스라 **endpoint 없음**. 섞지 않는다(impl만 단 code=무시·원격 릴레이, endpoint 없는 code=채팅
시 깨짐).

---

# 모드 A — 인프로세스 flow (source=ui + impl)

시각 그래프 빌더 대신, **이미 검증된 확장 시임** 위에 새 에이전트 플로우를 **코드로 저작**한다.
런타임은 `CustomAgent` Protocol에 적합한 어떤 그래프든 동일하게 스트림하고(085), 등록은 dict 조회만
하는 **신뢰 레지스트리**로 닫힌다(089). 이 스킬은 그 플로우 모듈을 생성하고 배선·검증까지 잇는다.

> **불변식(절대 위반 금지)**: 등록은 **저작 시점 코드**로만 한다. 사용자 입력 문자열을 런타임에
> `import`/`eval`하는 경로를 만들지 않는다(085 §보안경계: `os.system`·`__import__` 문자열 → None).
> 새 flow는 커밋·리뷰를 거치고, 반영에는 **API 재기동 1회**가 필요하다.

## A-참조 (생성 전 반드시 읽기)

- 인터페이스 계약: `packages/agent/src/agent/runtime.py` — `AgentBuildContext`(persona·model_cfg·tools·
  checkpointer·params), `AgentManifest`(name·description·accepts_overrides·supports_hil),
  `CustomAgent` Protocol(`describe()`·`build_graph(ctx)`), `register_agent`, `_bootstrap_builtins`.
- 참조 구현: `packages/agent/src/agent/examples/plan_execute.py`(선형 2노드),
  `packages/agent/src/agent/flows/route.py`(조건분기 — 이 스킬의 첫 산출물, 일반 경로 템플릿).
- **오케스트레이션 전략** 참조: `packages/agent/src/agent/flows/orchestrate.py` —
  `OrchestrationAgentBase`(ABC, 골격·불변식 소유) + `FirstMatchOrchestrateAgent`/`RankedOrchestrateAgent`
  (자식은 `select`만 구현). 전략 경로의 템플릿 기준(스펙 102).

## A-절차 (4단계)

### A1. 의도 수집

**먼저 물어 경로를 가른다** — "이 플로우가 **오케스트레이션 전략**인가(능력 브로커로 능력을 발견·조합,
후보를 *어떻게 고르나*가 핵심)?"
- **아니오** → 일반 경로(아래 그대로 — `route.py` 템플릿, `CustomAgent`를 처음부터 구현).
- **예** → **오케스트레이션 전략 경로**(§A2-오케스트레이션). 이땐 골격·불변식(채널 격리·HIL·정책)을
  **처음부터 쓰지 않는다** — 조상 `OrchestrationAgentBase`가 이미 소유하므로 `select`만 저작한다.

사용자에게 확정한다(모호하면 질문):
- **key**: 레지스트리 키(snake_case, 예 `route`·`summarize`·`triage`·`orchestrate_ranked`). `list_agent_impls()`와 충돌 금지.
- **클래스명**: PascalCase + `Agent` 접미(예 `RouteAgent`).
- **노드 구성**: 노드 이름과 흐름(선형? 조건분기? 루프?). 어떤 노드가 **모델을 호출**하고 어떤 노드가
  **결정적**(모델 없음)인지 명시.
- **HIL**: 위험 도구 게이트/`interrupt`가 있는가 → `supports_hil` 값 결정(없으면 반드시 `False`).
- **도구/페르소나**: `ctx.tools`를 바인딩하는가, `ctx.persona`를 어느 노드 system에 합치는가.

### A2. 모듈 생성 — `packages/agent/src/agent/flows/<key>.py`

`route.py`를 템플릿으로 `CustomAgent`를 구현한다. **규칙**:
- `_model_from_cfg(ctx)`를 그대로 재사용(모델은 주입 `model_cfg`만 — env·DB 직접 조회 금지).
- `build_graph(ctx)`는 **주입 ctx만** 읽는다(`ctx.persona`·`ctx.model_cfg`·`ctx.tools`·`ctx.params`·
  `ctx.checkpointer`). 자기 설정을 DB에서 다시 읽지 않는다(주입 단일 출처, 085 U2).
- 결정적 노드는 모델을 호출하지 않는다(추적 타임라인에 결정적으로 1줄). 분기 로직은 **모듈 수준 순수
  함수**로 빼 단위 테스트가 모델 없이 검증하게 한다(route.py의 `classify_route`처럼).
- `g.compile(checkpointer=ctx.checkpointer)`로 컴파일(HIL 배선 보존).
- `describe()`의 `AgentManifest`는 **정직**하게 — 그래프에 `interrupt`가 없으면 `supports_hil=False`.
  상상 능력을 선언하지 않는다.

### A2-오케스트레이션. 전략 경로 — `OrchestrationAgentBase`를 상속, `select`만 저작 (스펙 102)

전략 경로면 `orchestrate.py`를 템플릿으로 **조상을 상속**하고 **`select`만** 구현한다. **규칙(위반=드리프트)**:
- `class <Cls>(OrchestrationAgentBase)`로 상속하고 `@abstractmethod select(query, candidates)`만 override.
  클래스 상수 `NAME`(=impl 키)·`DESCRIPTION`·`DISCOVER_LIMIT`(랭킹 대상 후보 상한)·필요시 `TOP_K`만 설정.
- **`build_graph`·`describe`·`build_synthesis_messages`(채널 격리)·HIL 배선을 작성하지 않는다** — 전부
  조상이 소유한다. 자식이 이를 재정의하면 **override 홀**(불변식 우회)이 되어 금지다. 자식은 상속으로
  채널 격리·HIL·정책 재검증을 뺄 수 없다(이게 조상을 두는 이유).
- `select`는 **모듈 순수 함수**(`rank_candidates`류)에 위임한다 — 모델 없이 결정성을 단위 검증
  (스펙 099 규약). 후보를 어떻게 고르나만 여기서 갈린다.
- 반환 순서대로 **순차 위임**된다(조상 delegate 루프). 각 결과는 조상이 데이터 채널로 fold하므로 자식은
  신뢰 경계를 신경 쓸 필요가 없다.

### A3. 신뢰 등록 — `runtime.py` `_bootstrap_builtins()`

`_bootstrap_builtins()` 안에 **두 줄**을 추가한다(late-import 규약 유지):
```python
    from .flows.<key> import <ClassName>
    register_agent("<key>", <ClassName>)
```
이것이 유일한 등록 경로다. 동적 로딩/문자열 해석을 도입하지 않는다.

> **코드젠 에이전트는 UI 편집 대상이 아니다(스펙 327)** — 범용 impl 5종(``·orchestrate·
> orchestrate_ranked·artifact_form·pipeline) 밖의 impl을 쓰는 에이전트는 어드민 상세에서 읽기 전용
> ("구성은 코드가 소유")으로 표시되고, 동작 확인은 **플레이그라운드**에서 한다. 새 flow의 구성 수정은
> 코드(이 스킬)로만 — UI 편집 지원을 새로 만들지 않는다.

### A4. 검증 스크립트 생성 — `tests/verify_099_<key>.py`

`tests/verify_099_route.py`를 템플릿으로, mock `model_cfg`(실 LLM 없이)로 아래를 단언한다:
- **단위**: Protocol 적합(`get_agent_impl("<key>") is not None`), `build_graph(mock ctx)` 컴파일,
  `get_graph().nodes`가 선언 노드 집합과 일치, `describe()` 매니페스트 정직, 분기 순수함수 결정성,
  `list_agent_impls()`에 `<key>` 포함(드리프트 0).
- **통합**(in-process ASGI + 실 그래프): `ui+impl=<key>` 에이전트 생성→chat SSE → 토큰 + **실 노드
  타임라인**(합성 call_model 아님). 조건분기면 실행된 분기만 타임라인에 뜨는지 확인. 생성 에이전트 정리.

**오케스트레이션 전략 경로**면 `tests/verify_102_orchestration_strategy.py`를 템플릿으로 삼되 **`select`만**
검증한다(조상 불변식은 조상 테스트가 이미 커버 — 재검증 아님): `select` 결정성(순수함수)·골격 드리프트0
(`get_graph().nodes`가 조상 노드집합 `{analyze,delegate,synthesize}`와 동일)·conformance·채널 격리 상속.

## A-검증 (수용 게이트 — 새로 발명하지 않음)

생성 flow는 아래를 **모두** 통과해야 "완료"다:
- `classify_runtime(source="ui", impl="<key>") == "conforming"` (089 — 함수는 `classify_runtime`,
  `agent.runtime`에서 import; verify_099_route.py가 이 술어를 그대로 쓴다).
- `tests/verify_099_<key>.py` 전부 통과.
- **무회귀**: `tests/verify_085_runtime_interface.py`·`tests/verify_089_*.py` 전부 통과(신뢰 불변식·
  드리프트 0 유지).
- 비자명하면 **codex 적대 리뷰**: "생성 코드가 ctx 외 상태를 읽는가 / 매니페스트를 과대선언하는가 /
  등록이 eval 경로를 여는가"를 여집합으로 검토.
- **오케스트레이션 전략 경로 추가 게이트**: 자식이 `build_graph`/`describe`/`build_synthesis_messages`를
  **재정의하지 않았는가**(override 홀 없음 — 있으면 채널 격리·HIL 우회). 자식 본문은 `select`(+ 순수함수)와
  클래스 상수뿐이어야 한다.

통합 검증은 API 서버가 떠 있어야 한다(`uv run --project packages/api ...`). 새 flow 등록은 import
시점이므로 **서버 재기동 후** 반영된다.

---

# 모드 B — SDK 배포형 code 에이전트 (source=code, doc-translator처럼)

에이전트 로직은 **이 레포 밖의 별도 서비스**로 산다(my-agents-sdk로 배포). 그 서비스는 A2A Agent
Card를 노출하고, my-agents는 그 카드/endpoint를 **등록**해 채팅을 `_a2a_stream`으로 원격 중계한다.
런타임 그래프를 이 레포에 짜지 않는다 — 여기 산출물은 **등록 + (개발용) mock 엔드포인트**뿐이다.

> **불변식**: source=code는 in-process 인터페이스(085)의 *대상이 아니다* — `resolve_agent_runtime`이
> None을 반환하고 `_a2a_stream`이 원격으로 보낸다. 그래서 **endpoint가 반드시 있어야** 하고, `impl`은
> 무시된다(달지 않는다). `classify_runtime(source="code")=="non_conforming"`은 **정상**이다(원격은
> 정당한 다른 런타임 — 에러 아님, 스펙 089).

## B-참조 (생성 전 반드시 읽기)

- 정본 예시: `packages/api/src/api/seed.py`의 `doc-translator`(source=code, card·endpoint·배포메타).
- 카드 계약: `packages/api/src/api/mock_remote.py`의 `/sdk/.well-known/agent-card.json`(제1자 SDK 카드
  — `x-my-agents` 확장 = manifest+deploy)와 `/_remote/a2a` JSON-RPC(실 호출 스탠드인).
- 등록 경로: `packages/api/src/api/agents.py` — `register_code_agent`(`POST /agents/register`,
  `RegisterCodeAgentIn`) + connect(`POST /agents/connect`, 카드 url 자동분류).
- 분류 술어: `packages/agent/src/agent/runtime.py` `is_remote_source`·`is_first_party`(code=제1자 원격).
- 디스패치(편집 대상 아님, 이해용): `packages/api/src/api/chat.py`의 `resolve_agent_runtime`(원격→None)·
  `_a2a_stream`(원격 릴레이). 두 모드 어느 쪽도 chat.py를 편집하지 않는다.

## B-절차 (3단계)

### B1. 카드 계약 확정 — Agent Card + `x-my-agents` 확장

code 에이전트 = **제1자 A2A 서비스**. 그 서비스가 노출하는 Agent Card
(`/.well-known/agent-card.json`)에 `x-my-agents` 확장을 실어 **우리가 SDK로 배포한 에이전트임을
자기선언**한다(정확한 판정 게이트 = `x-my-agents.manifest`가 **객체(dict)로 존재**하면 connect가
`code`로 분류, 없거나 dict 아니면 `external` — `agent_card.py`의 `extract_my_agents`):
```json
{
  "name": "...", "description": "...", "url": "<A2A JSON-RPC endpoint>",
  "version": "1.0.0", "provider": {"organization": "...", "url": "..."},
  "capabilities": {"streaming": true, "pushNotifications": false},
  "defaultInputModes": ["text/plain"], "defaultOutputModes": ["text/plain"],
  "skills": [{"id": "...", "name": "...", "description": "...", "tags": ["..."]}],
  "x-my-agents": {
    "manifest": {"model": "...", "persona": "...", "memories": [], "mcps": [], "historyDepth": 10},
    "deploy": {"repo": "...", "commit": "...", "runtime": "my-agents-sdk · ...",
               "versions": [{"version": "...", "status": "active", "note": "..."}]}
  }
}
```
- `manifest` = 표시·설정 메타(model·persona·memories·mcps·historyDepth) — 우리 admin이 카드에서 채운다.
- `deploy` = provenance(repo·commit·runtime·versions). `manifest`가 없으면(또는 확장 자체가 없으면)
  connect는 `external`로 분류한다(제3자). code로 만들려면 **반드시 `x-my-agents.manifest`(객체)가
  있어야** 한다.

### B2. 등록 — 두 경로 중 하나

- **직접 등록**: `POST /agents/register`(`RegisterCodeAgentIn`) — endpoint·token(필수) + name·model·
  persona·repo·commit·runtime·mcps·historyDepth. SDK가 배포 후 자기 endpoint를 직접 등록하는 경로.
- **카드 연결**: `POST /agents/connect`(카드 url) — 카드를 fetch해 `x-my-agents` 있으면 `source=code`,
  없으면 `external`로 자동분류. admin UI "연결" 흐름의 백엔드.

둘 다 `owner_id`를 생성 시 1회 스탬프(스펙 112)하고, 실행은 `_a2a_stream`이 endpoint로 릴레이한다.

### B3. 개발·데모용 endpoint (실 배포 서비스가 없을 때)

실제 배포 서비스 없이 이 레포에서 code 에이전트를 시연·테스트하려면 `mock_remote.py`를 쓴다:
- SDK 카드 스탠드인(`/sdk/.well-known/agent-card.json`, `x-my-agents` 포함)로 connect → `source=code`.
- 실 호출은 `/_remote/a2a` JSON-RPC가 결정적 mock 응답을 돌려준다.
- 새 데모 에이전트가 필요하면 이 두 스탠드인을 템플릿으로 카드/스킬만 바꿔 추가한다(런타임은 동일
  `_a2a_stream`·`/_remote/a2a` 재사용). seed의 `doc-translator`가 이 방식의 스냅샷.

## B-검증 (수용 게이트 — 새로 발명하지 않음)

- `classify_runtime(source="code", impl=None) == "non_conforming"` (정상 — 원격 다른 런타임, 089).
- 등록 왕복: `POST /agents/register`(또는 connect) → `GET /agents/{id}`에 source=code·endpoint·card·
  배포메타 보존. connect면 `x-my-agents` 유무로 code/external 분류가 갈리는지(verify_057 템플릿).
- **채팅 릴레이**: 등록 에이전트로 chat SSE → `_a2a_stream`이 원격 endpoint로 중계해 응답을 스트림
  (mock endpoint면 결정적 mock 응답). 템플릿=`verify_154_custom_a2a.py`·`verify_155_playground_a2a.py`.
- 위임까지 시연하면 `verify_117_a2a_collaboration_and_approval.py`(조율형이 code 에이전트에 A2A 위임·승인).
- **경계 회귀 금지**: code 에이전트에 `impl`을 달지 않았는가(무시되지만 혼란 유발)·endpoint가 비지
  않았는가(채팅 시 깨짐). `register_code_agent`가 endpoint 정규화로 등록 시점 400을 이미 건다.

---

## 공통 — 산출물 커밋 (Compounding)

저작이 끝나면 그 관련 파일만 stage해 per-spec 커밋한다(스펙 099·258 규약). 모드 A는 flow 모듈+등록+
verify, 모드 B는 mock_remote/등록 스크립트+verify. 푸시·머지는 사용자 명시 시에만.

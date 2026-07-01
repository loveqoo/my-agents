---
name: agent-flow
description: 공통 인터페이스(CustomAgent Protocol)를 기반으로 LangGraph 에이전트 플로우를 저작(코드젠)하고 신뢰 레지스트리에 등록한다. "에이전트 플로우 만들어줘", "새 flow/impl 추가", "그래프 에이전트 스캐폴드"에 사용.
---

# 에이전트 플로우 스캐폴드 (스펙 099 — 그래프 빌더 대체)

시각 그래프 빌더 대신, **이미 검증된 확장 시임** 위에 새 에이전트 플로우를 **코드로 저작**한다.
런타임은 `CustomAgent` Protocol에 적합한 어떤 그래프든 동일하게 스트림하고(085), 등록은 dict 조회만
하는 **신뢰 레지스트리**로 닫힌다(089). 이 스킬은 그 플로우 모듈을 생성하고 배선·검증까지 잇는다.

> **불변식(절대 위반 금지)**: 등록은 **저작 시점 코드**로만 한다. 사용자 입력 문자열을 런타임에
> `import`/`eval`하는 경로를 만들지 않는다(085 §보안경계: `os.system`·`__import__` 문자열 → None).
> 새 flow는 커밋·리뷰를 거치고, 반영에는 **API 재기동 1회**가 필요하다.

## 참조 (생성 전 반드시 읽기)

- 인터페이스 계약: `packages/agent/src/agent/runtime.py` — `AgentBuildContext`(persona·model_cfg·tools·
  checkpointer·params), `AgentManifest`(name·description·accepts_overrides·supports_hil),
  `CustomAgent` Protocol(`describe()`·`build_graph(ctx)`), `register_agent`, `_bootstrap_builtins`.
- 참조 구현: `packages/agent/src/agent/examples/plan_execute.py`(선형 2노드),
  `packages/agent/src/agent/flows/route.py`(조건분기 — 이 스킬의 첫 산출물, 일반 경로 템플릿).
- **오케스트레이션 전략** 참조: `packages/agent/src/agent/flows/orchestrate.py` —
  `OrchestrationAgentBase`(ABC, 골격·불변식 소유) + `FirstMatchOrchestrateAgent`/`RankedOrchestrateAgent`
  (자식은 `select`만 구현). 전략 경로의 템플릿 기준(스펙 102).

## 절차 (4단계)

### 1. 의도 수집

**먼저 물어 경로를 가른다** — "이 플로우가 **오케스트레이션 전략**인가(능력 브로커로 능력을 발견·조합,
후보를 *어떻게 고르나*가 핵심)?"
- **아니오** → 일반 경로(아래 그대로 — `route.py` 템플릿, `CustomAgent`를 처음부터 구현).
- **예** → **오케스트레이션 전략 경로**(§2-오케스트레이션). 이땐 골격·불변식(채널 격리·HIL·정책)을
  **처음부터 쓰지 않는다** — 조상 `OrchestrationAgentBase`가 이미 소유하므로 `select`만 저작한다.

사용자에게 확정한다(모호하면 질문):
- **key**: 레지스트리 키(snake_case, 예 `route`·`summarize`·`triage`·`orchestrate_ranked`). `list_agent_impls()`와 충돌 금지.
- **클래스명**: PascalCase + `Agent` 접미(예 `RouteAgent`).
- **노드 구성**: 노드 이름과 흐름(선형? 조건분기? 루프?). 어떤 노드가 **모델을 호출**하고 어떤 노드가
  **결정적**(모델 없음)인지 명시.
- **HIL**: 위험 도구 게이트/`interrupt`가 있는가 → `supports_hil` 값 결정(없으면 반드시 `False`).
- **도구/페르소나**: `ctx.tools`를 바인딩하는가, `ctx.persona`를 어느 노드 system에 합치는가.

### 2. 모듈 생성 — `packages/agent/src/agent/flows/<key>.py`

`route.py`를 템플릿으로 `CustomAgent`를 구현한다. **규칙**:
- `_model_from_cfg(ctx)`를 그대로 재사용(모델은 주입 `model_cfg`만 — env·DB 직접 조회 금지).
- `build_graph(ctx)`는 **주입 ctx만** 읽는다(`ctx.persona`·`ctx.model_cfg`·`ctx.tools`·`ctx.params`·
  `ctx.checkpointer`). 자기 설정을 DB에서 다시 읽지 않는다(주입 단일 출처, 085 U2).
- 결정적 노드는 모델을 호출하지 않는다(추적 타임라인에 결정적으로 1줄). 분기 로직은 **모듈 수준 순수
  함수**로 빼 단위 테스트가 모델 없이 검증하게 한다(route.py의 `classify_route`처럼).
- `g.compile(checkpointer=ctx.checkpointer)`로 컴파일(HIL 배선 보존).
- `describe()`의 `AgentManifest`는 **정직**하게 — 그래프에 `interrupt`가 없으면 `supports_hil=False`.
  상상 능력을 선언하지 않는다.

### 2-오케스트레이션. 전략 경로 — `OrchestrationAgentBase`를 상속, `select`만 저작 (스펙 102)

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

### 3. 신뢰 등록 — `runtime.py` `_bootstrap_builtins()`

`_bootstrap_builtins()` 안에 **두 줄**을 추가한다(late-import 규약 유지):
```python
    from .flows.<key> import <ClassName>
    register_agent("<key>", <ClassName>)
```
이것이 유일한 등록 경로다. 동적 로딩/문자열 해석을 도입하지 않는다.

### 4. 검증 스크립트 생성 — `tests/verify_099_<key>.py`

`tests/verify_099_route.py`를 템플릿으로, mock `model_cfg`(실 LLM 없이)로 아래를 단언한다:
- **단위**: Protocol 적합(`get_agent_impl("<key>") is not None`), `build_graph(mock ctx)` 컴파일,
  `get_graph().nodes`가 선언 노드 집합과 일치, `describe()` 매니페스트 정직, 분기 순수함수 결정성,
  `list_agent_impls()`에 `<key>` 포함(드리프트 0).
- **통합**(in-process ASGI + 실 그래프): `ui+impl=<key>` 에이전트 생성→chat SSE → 토큰 + **실 노드
  타임라인**(합성 call_model 아님). 조건분기면 실행된 분기만 타임라인에 뜨는지 확인. 생성 에이전트 정리.

**오케스트레이션 전략 경로**면 `tests/verify_102_orchestration_strategy.py`를 템플릿으로 삼되 **`select`만**
검증한다(조상 불변식은 조상 테스트가 이미 커버 — 재검증 아님): `select` 결정성(순수함수)·골격 드리프트0
(`get_graph().nodes`가 조상 노드집합 `{analyze,delegate,synthesize}`와 동일)·conformance·채널 격리 상속.

## 검증 (수용 게이트 — 새로 발명하지 않음)

생성 flow는 아래를 **모두** 통과해야 "완료"다:
- `classify_conformance(source="ui", impl="<key>") == "conforming"` (089).
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

## 산출물 커밋 (Compounding)

flow 생성이 끝나면 그 flow 관련 파일만 stage해 per-spec 커밋한다(스펙 099 규약). 푸시·머지는 사용자
명시 시에만.

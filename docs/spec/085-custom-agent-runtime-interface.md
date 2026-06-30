# 085 — 커스텀 에이전트 런타임 인터페이스 (in-process SDK)

## 배경 — 무엇이 문제인가

오늘 에이전트는 `source` 문자열(`ui`/`code`/`external`)로만 갈린다. 공통 추상(Protocol/ABC)이
**없고**, 분기 술어(`agent.source in ("code","external")`)가 chat.py 7곳에 반복된다(60·87·181·256·
480·511·736). 결과:

| | `ui` | `code`(SDK)·`external` |
|---|---|---|
| 실행 | **in-process LangGraph**(`build_agent`, agent/main.py:22) | **원격 A2A 프록시(블랙박스)** |
| 플레이그라운드 오버라이드(spec 025) | 적용 | **무시**(chat.py:60 게이트) |
| LangGraph 호출 스택 추적 | 수공 trace dict(`assemble_trace`) | **불가**(원격이라 내부 안 보임) |

즉 **"커스텀 에이전트(SDK)"는 2등 시민**이다 — 런타임 밖 원격 블랙박스라 설정 주입도 그래프
추적도 못 받는다. 사용자 요구: *우리 서비스를 지원하는 공통 인터페이스를 정의하고, 이를 구현한
커스텀 에이전트는 플레이그라운드 설정 주입·LangGraph 호출 스택 추적을 1급으로 받게 한다. 단,
인터페이스를 구현하지 않은 에이전트도 지금처럼 테스트 가능해야 한다(graceful fallback).*

## 결정 (사용자 합의)

- **런타임 모델: in-process SDK 인터페이스.** 커스텀 에이전트를 우리 런타임에 로드해 공통
  인터페이스를 구현하면, 플랫폼이 `astream` 루프를 소유 → 오버라이드 주입·실 LangGraph 호출
  스택 추적이 ui와 동일하게 1급. (대가: 코드 신뢰경계·플러그인 로딩 — 아래 §보안경계.)
- **첫 컷 범위: 인터페이스 + 2구현 + 추적 배선 풀세트.** learning 039("drop-in은 둘째 구현을
  *출하*해야 측정")에 따라 단일 구현으로 끝내지 않는다.

## 핵심 통찰 — 왜 in-process 인터페이스가 "공짜로" 주입·추적을 준다

오늘 `build_agent`는 *하드코딩된 단일 그래프 빌더*(`create_agent(model, tools, system_prompt)`)다.
**오버라이드 주입·추적은 그래프의 속성이 아니라 그것을 돌리는 *루프*의 속성**이다 —
`_load_context`가 오버라이드를 병합하고, `graph.astream(stream_mode=["messages","updates"])`가
토큰·노드 이벤트를 뱉는다. 그러므로 *그래프를 공통 인터페이스 뒤로 들어내 플랫폼이 그 루프를
소유*하면, **어떤 적합 그래프든** 주입·추적을 자동으로 받는다. 커스텀 에이전트는 "그래프를
어떻게 만들지"만 책임지고, "어떻게 주입·추적·스트림할지"는 플랫폼이 책임진다.

## 설계

### 1. 공통 인터페이스 (Protocol)

`packages/agent/src/agent/runtime.py`(신규) 또는 기존 모듈에 정의:

```python
@dataclass
class AgentBuildContext:
    """플랫폼이 커스텀 에이전트에 *주입*하는 모든 것. 오버라이드는 이미 병합된 상태로 도착."""
    persona: str                 # 오버라이드 병합 후 system_prompt
    model_cfg: dict              # 레지스트리 해석 + 오버라이드 후 {base_url, model_id, api_key, params}
    tools: list                  # 플랫폼이 빌드한 MCP + RAG 도구
    checkpointer: object | None  # HIL durable 체크포인터(spec 041)
    params: dict                 # temperature 등
    memories: list               # 회상 핸들
    overrides: dict | None       # 원본 오버라이드(에이전트가 추가 키를 읽고 싶을 때)

class CustomAgent(Protocol):
    def describe(self) -> AgentManifest: ...           # 이름·수용 키·capabilities(추적/HIL 지원 여부)
    def build_graph(self, ctx: AgentBuildContext): ...  # 컴파일된 LangGraph 그래프 반환
```

계약: `build_graph`가 돌려준 그래프는 **기존 호출 계약**(`astream(messages/updates)`·`__interrupt__`·
`ainvoke(Command)`)을 만족해야 한다(verify_041이 증명하는 그 계약). 플랫폼은 그래프 *내부*를 모른
채 루프만 돌린다.

### 2. 디스패치 + graceful fallback

chat.py에 런타임 해석 함수 신설:

```python
def resolve_agent_runtime(agent) -> CustomAgent | None:
    """적합 in-process 구현이 있으면 반환, 없으면 None(=fallback)."""
    # ui → DefaultUiAgent(레퍼런스 구현)
    # config["impl"]에 등록된 레지스트리 키 → 해당 팩토리(신뢰집합서만)
    # 그 외(원격 code/external) → None
```

chat 본문:
```python
runtime = resolve_agent_runtime(agent)
if runtime is None:                       # 인터페이스 미구현 → 지금처럼(원격 A2A 불투명)
    return StreamingResponse(_a2a_stream(...))   # 기존 경로 무변경 (fallback 게이트)
graph = runtime.build_graph(ctx)          # in-process — 주입된 ctx로 그래프 생성
# 이하 기존 astream 루프(토큰·interrupt·trace) — 모든 적합 그래프 공통
```

이 한 게이트가 사용자 요구 "구현 안 해도 지금처럼 테스트"를 만족한다 — None이면 기존 원격 경로.
learning 060: 통합은 폐기경로 행동을 자동승계 안 한다 → `_a2a_stream` 경로는 **삭제·변경하지 않고
그대로 보존**(차집합 누락 방지).

### 3. 두 레퍼런스 구현 (learning 039 "≥2로 측정")

1. **`DefaultUiAgent`** — 현 `build_agent`(create_agent)를 인터페이스로 감싼다. ui 경로가 인터페이스에
   적합함을 증명. 무회귀(같은 그래프·같은 계약).
2. **예제 커스텀 에이전트**(`examples/plan_execute` 등) — `create_agent`가 아닌 **손수 만든 다노드
   LangGraph 그래프**(예: plan→execute 2노드). 인터페이스가 `create_agent`에 *과적합(누수)되지
   않았음*을 측정. 둘 다 같은 플랫폼 루프로 스트림되고 둘 다 주입·추적을 받으면 추상화가 *증명*된다.

### 4. 추적 배선 (풀세트)

현 trace의 `graph` 타임라인은 손으로 채운다(예 a2a: `[__start__, a2a_call, __end__]`, chat.py:452).
**적합 그래프는 `updates` 스트림이 노드 발화를 실제로 실어오므로**, 하드코딩 대신 `updates`
이벤트에서 **실 노드 이름을 누적**해 호출 스택 타임라인을 구성한다 → 어떤 적합 그래프든 진짜
호출 스택이 같은 인스펙터 화면에 뜬다. `assemble_trace`(runtime.py:373)에 노드 타임라인 입력을
하드코딩 리스트 → 수집된 실 노드열로 교체.

### 5. source/config 처리

- `source`는 **provenance로 유지**(057 불변) — 새 분기축을 source에 욱여넣지 않는다. 대신
  `config["impl"]`(레지스트리 키)로 in-process 구현을 가리킨다. `ui`는 암묵적으로 `DefaultUiAgent`.
- 오버라이드 게이트(chat.py:60)는 "`source not in (code,external)`" → "`resolve_agent_runtime(agent)
  is not None`"으로 일반화(원격이면 여전히 bypass, in-process 커스텀이면 주입 적용). **반복 술어
  7곳을 이 단일 판정으로 수렴**(learning 060: 행동 열거 후 이식, 무회귀 단언).

### 6. 보안경계 (in-process 선택의 대가)

- in-process 구현은 **우리 코드베이스/검증된 신뢰 레지스트리에서만** 로드한다. 임의 업로드·원격
  페이로드 eval 금지 — `config["impl"]`은 *키*일 뿐, 코드가 아니다. 알 수 없는 키 → 적합 구현
  없음 → fallback(None). (임의 비신뢰 코드 샌드박싱은 **비목표**.)
- `config["impl"]` 설정은 에이전트 설정 편집 권한(이미 어드민 게이트)에 종속. 키가 신뢰집합 밖이면
  무시(열거 오라클 없음). 비밀값은 절대 로그·trace에 싣지 않음(기존 규칙).

## RBAC/소유권 체크리스트 — 적용 여부

**트리거 객관 판정**: 이 스펙은 *런타임 디스패치 리팩터*다 — `user_id`/테넌트 컬럼을 새로 읽거나,
`_own_scope`/`_visible_or_404`/`_assert_*owns` 헬퍼를 건드리지 않는다. chat 경로의 기존 `own`
게이트(세션 소유)는 **그대로 보존**(디스패치 위치 불변). impl 레지스트리는 **전역 신뢰집합**(per-user
소유 아님). → **RBAC 체크리스트 미적용** (사유: 새 소유경계 0). 단 §보안경계의 신뢰-로딩 불변식은
별도 단언으로 검증한다(설정 자체를 단언 — "installed guard ≠ covering guard" 교훈).

## 검증 사다리 (3런 — 비겹침)

- **① 단위**: Protocol 적합(DefaultUiAgent·예제 둘 다 `build_graph`가 적합 그래프 반환); `ctx` 주입
  병합(오버라이드 화이트리스트가 persona/model/params에 실제 반영); `resolve_agent_runtime`이
  ui→DefaultUiAgent·예제키→예제·원격/미지키→None; 추적 타임라인이 `updates` 노드열에서 파생(하드코딩
  아님); 신뢰-로딩(미등록 impl 키→None, eval 경로 없음 단언).
- **② 실인프라 통합(in-process ASGI + 실 그래프)**: ui 에이전트·예제 커스텀 에이전트 둘 다 chat
  스트림 → 토큰 + **실 노드 타임라인** trace; 오버라이드 주입이 실제 응답/모델을 바꿈; 비적합(원격)
  에이전트는 `_a2a_stream`로 fallback(mock 원격)·기존 동작 무회귀(verify_041 계약 보존 재확인).
- **③ 적대 codex**: 인터페이스 누수(create_agent 과적합), 보안(비신뢰 로딩·impl 키 주입), 추적
  정확성, fallback 완전성(learning 060 — 폐기경로 행동 차집합 누락?), 술어 수렴 무회귀.

## 완료 체크
- [x] 공통 인터페이스(`CustomAgent` Protocol + `AgentBuildContext`) 정의, 호출 계약 문서화 — `packages/agent/src/agent/runtime.py`
- [x] `DefaultUiAgent`(build_agent 래핑) + 예제 다노드 커스텀 에이전트(`examples/plan_execute`) — 둘 다 같은 루프로 스트림
- [x] `resolve_agent_runtime` 디스패치 + None→`_a2a_stream` fallback 게이트(기존 원격 경로 무변경)
- [x] 오버라이드 주입을 적합 in-process 커스텀에 적용(술어 단일 판정으로 수렴, 무회귀) — 원본 오버라이드도 `ctx.overrides`로 전달(F4)
- [x] 추적: `updates` 노드열에서 실 호출 스택 타임라인 파생(하드코딩 대체) — `_timeline_from_nodes`
- [x] 보안: in-process 로딩은 신뢰 레지스트리 키만(eval 없음), 설정 단언으로 검증(U5)
- [x] 단위 + 실인프라 통합(ui·예제 둘 다 추적·주입, 원격 fallback) + 적대 codex 그린, verify_041 무회귀

## 검증 결과 (3런 + 회귀 가드)

- **① 단위(verify_085 [U])**: 26 체크 그린 — Protocol 적합·ctx 주입·`resolve_agent_runtime`
  디스패치·추적 타임라인 `updates` 파생·신뢰-로딩(미등록/점경로/dunder 키 → None, eval 경로 없음).
- **② 실인프라 통합(verify_085 [H], in-process ASGI + 실 그래프)**: 16 체크 그린 — ui·plan_execute
  둘 다 토큰 스트림 + **실 노드 타임라인**(`[__start__, plan, execute, __end__]`, 하드코딩 아님);
  impl 라운드트립; 원격 code/external → 디스패치 None(fallback 경로 보존); **H5 = F1 회귀 가드**
  (impl 없는 편집 PUT→활성화 후에도 impl·타임라인 보존).
- **②.5 브라우저(Playwright, 시스템 Chrome)**: 플레이그라운드에서 'Plan-Execute Demo' 선택 → 실
  모델 출력 + 인스펙터 트레이스 DOM에 `["__start__","plan","execute","__end__"]`(원격 fallback 아닌
  실 4노드). 스크린샷 사용자 송부.
- **③ 적대 codex(read-only, rung3)**: 판정 **SHIP-WITH-FIXES** — 4건 지적 전부 처분(아래 §검증 후 보강).
- **회귀 가드(verify_041)**: HIL 게이트 시맨틱 21 체크 그린 — F2 가드(`resume`가 HIL 미지원 런타임
  거부)가 기본 HIL 흐름(DefaultUiAgent `supports_hil=True`)을 깨지 않음 확인.

## 검증 후 보강 (codex 적대 리뷰 F1–F4)

코덱스가 SHIP-WITH-FIXES로 4건을 지적했고, 출하 전 모두 처분했다. (learning 023 "비가역·파괴 경로는
출하 전 적대 리뷰" — 여기선 *silent 되돌림*이 그 비가역에 해당: 사용자가 모른 채 커스텀이 기본으로 격하.)

- **F1 (impl silent drop) — 코드 수정 + 회귀 테스트.** `update_agent`(PUT)가 `body.config.model_dump()`로
  draft config를 통째 교체 → SPA 편집 폼이 `impl`을 안 보내면 Pydantic 기본 `None`이 덮어써, 편집→활성화가
  커스텀 에이전트를 `DefaultUiAgent`로 silent 되돌렸다. 수정: `model_fields_set`에 `impl`이 없으면 편집
  베이스(초안→활성 config)의 `impl`을 이어받음(명시 전송이면 클리어 포함 존중). verify_085 H5가 회귀 가드.
  (내가 처음 "이점 없음"류로 오판했던 건 — probe-deeper 교훈: 단정 전 한 겹 더.)
- **F4 (dead overrides 계약) — 코드 수정.** `AgentBuildContext.overrides`를 설계했지만 `_load_context`가
  `ctx`에 안 실어 항상 `None`이었다(죽은 계약). 수정: `ctx["overrides"]`에 원본 오버라이드를 싣고(원격은
  `None`으로 bypass 보존) 3개 build 사이트(a2a expose·main chat·resume)에 `overrides=ctx.get("overrides")`
  배선.
- **F2 (resume config drift) — 가드 + 잔여경계 문서화.** approval은 어떤 그래프 topology로 checkpoint를
  만드는데, 그 사이 admin이 impl을 HIL 미지원 구현으로 바꿔 활성화하면 stale checkpoint resume이 깨진다.
  수정: `resume_approval`에서 현 런타임이 `supports_hil=False`면 graceful 거부(approval은 이미 결재됨,
  세션 무파손). **잔여 경계**: impl-A→impl-B(둘 다 HIL) 교체는 못 잡는다 — Approval에 런타임 키 스냅샷을
  박아 그걸로 재개해야 완전(후속 스펙). 현 출하엔 HIL 커스텀 구현이 없어 미발생.
- **F3 (병렬 superstep 추적 순서) — 정직 문서화.** `_timeline_from_nodes`는 `updates` 관측 순서로
  타임라인을 만드는데, 병렬 superstep에서는 관측 순서 ≠ 엄밀 호출 스택 순서이고 ms는 균등분할 추정치다.
  현 두 구현(default 단일·plan_execute 직렬)은 직렬이라 미발생. docstring에 한계를 정직 표기(no silent cap).

## 비목표
- 임의 비신뢰/업로드 코드 샌드박싱(권한 격리·seccomp 등) — 신뢰 레지스트리 로딩만.
- 원격 `code`/`external` 에이전트를 in-process로 재편입(057 되돌리기) — 그들은 fallback 경로 유지.
- langfuse/OpenTelemetry 도입 — 추적은 기존 수공 trace dict를 실 노드열로 강화하는 선까지.

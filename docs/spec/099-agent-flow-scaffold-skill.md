# 099 — 에이전트 플로우 스캐폴드 스킬 (그래프 빌더 대체)

> 상태: **초안(AI 작성, 인간 검토 대기)**. 제안 #4(트리노드 그래프 빌더)를 **폐기**하고, 그 목적을
> **Claude Code 스킬 기반 코드젠**으로 대체하는 스펙. 사용자 결정(2026-07-01): 폴더=신규 `agent/flows/`,
> 스코프=코드젠+검증까지(admin UI impl 선택 노출은 별도 스펙).
>
> 참고 자산:
> - spec 085(커스텀 에이전트 런타임 인터페이스 — `CustomAgent` Protocol·`build_graph`·`describe`·실 노드
>   타임라인) → 생성물이 준수할 **공통 인터페이스**의 계약.
> - spec 089(conformance 3-state 분류 — `isinstance` 게이트로 085 갭 봉합) → 생성 impl의 **수용 게이트**.
> - `agent/runtime.py`(`_REGISTRY`·`register_agent`·`_bootstrap_builtins` late-import) → **신뢰 등록** 배선점.
> - [[agent-source-three-way-a2a-external]] → `impl`(인프로세스)은 `code`/`external`(원격 A2A)과 다른 갈래.
> - **RBAC 체크리스트: 비트리거** — 이 스펙은 유저별/테넌트 데이터(세션·메모리·승인)를 만지지 않고
>   `user_id`·소유권 헬퍼에 닿지 않는다. 에이전트 *플로우 코드 저작*이 대상.

## 1. 배경 / 문제

제안 #4 "트리노드 그래프 빌더"는 다중 에이전트 플로우를 **시각 편집기**로 조립하려는 안이었다. 시각
편집기는 그래프 직렬화/역직렬화·렌더 계층을 **새로** 세워야 하고, 런타임이 그 산출물을 안전하게
로드하는 경로(문자열→클래스 해석)를 요구해 **신뢰 레지스트리 불변식(085 U5: eval/import 경로 없음)**과
충돌한다. 폐기한다.

대신 **이미 검증된 확장 시임** 위에 저작 워크플로우를 얹는다:
- 런타임은 `CustomAgent` Protocol(`describe()→AgentManifest`, `build_graph(ctx)→컴파일 그래프`)에 적합한
  **어떤 그래프든 동일하게** 스트림한다(085 불변식 — 단일노드 `DefaultUiAgent`도 다노드 `PlanExecuteAgent`도
  같은 루프·같은 ctx 주입·실 노드 타임라인).
- 등록은 `agent/runtime.py`의 **신뢰 레지스트리**(`_REGISTRY` dict + `register_agent(key, cls)`)로 닫힌다.
  `get_agent_impl`은 dict 조회 + `isinstance(CustomAgent)` 게이트만 — **문자열→import 경로 없음**(089).

따라서 "그래프 빌더"의 목적(새 에이전트 플로우를 만들어 재사용)은 **`plan_execute` 옆에 새 `impl`을
하나 더 저작하는 일**로 환원된다. 이 저작을 **Claude Code 스킬**로 자동화한다 — 핵심 가치 "저마찰
생성"에 직결되며, 신규 런타임 표면이 거의 없다.

## 2. 설계 결정

**결정 A — 생성 플로우 전용 폴더 `packages/agent/src/agent/flows/`.**
`agent/examples/`(현 `plan_execute`)는 **인터페이스 참조 2종**(default·plan_execute)만 유지하고, 스킬이
생성하는 실사용 플로우는 `agent/flows/<key>.py`에 둔다('examples'라는 이름이 실사용 플로우와 안 맞음).
`flows/__init__.py` 추가. 참조와 생성물의 관심사 분리.

**결정 B — 신뢰 등록만(런타임 eval 금지).** 스킬은 **저작 시점 코드 생성기**다. 등록 = `runtime.py`의
`_bootstrap_builtins()`에 두 줄 추가(late-import 규약 유지 — 순환 회피):
```python
    from .flows.<key> import <ClassName>
    register_agent("<key>", <ClassName>)
```
사용자 입력 문자열을 런타임에 import/eval하지 **않는다** → 085 U5 불변식(`os.system`·`__import__` 문자열
→ None) 보존. 생성 코드와 이 배선은 **커밋·리뷰**를 거친다. (등록은 모듈 import 시점 1회이므로 새 flow
반영에는 **API 재기동 1회** 필요 — 저작 워크플로우로 허용.)

**결정 C — 스킬 위치·형태: 프로젝트 스킬 `.claude/skills/agent-flow/SKILL.md`.**
현재 `.claude/`는 비어 있음(`.gitkeep`). 대화형 스캐폴딩 절차:
1. **의도 수집** — 플로우 key(레지스트리 키, snake_case)·클래스명·노드 구성(예: plan→execute, route→a/b,
   단일 model 노드)·HIL 인터럽트 필요 여부·도구 사용 여부·페르소나 사용점.
2. **모듈 생성** `agent/flows/<key>.py` — `CustomAgent` 구현:
   - `describe()`가 **정직한** `AgentManifest`(그래프 구조에서 `supports_hil` 등 판단 — plan_execute가
     False로 표기하듯 상상 능력 금지).
   - `build_graph(ctx)`가 **주입 ctx만** 읽는다(`ctx.persona`·`ctx.model_cfg`·`ctx.tools`) — 자기 DB·전역
     설정 직접 조회 금지(085 U2: 빌드는 ctx만 받음). 컴파일된 그래프 반환(`.astream`/`.get_graph().nodes` 보유).
3. **레지스트리 배선** — 결정 B의 두 줄을 `_bootstrap_builtins()`에 추가.
4. **검증 스크립트 생성** `tests/verify_099_<key>.py`(085 패턴 재사용) — mock `model_cfg`로 실 LLM 없이:
   구조(선언 노드열 == `build_graph` 노드), Protocol 적합(`get_agent_impl(key) is not None`), 매니페스트
   정직성, ui+impl chat 통합(실 노드 타임라인).

**결정 D — conformance/구조 검증이 수용 게이트.** 새 게이트를 발명하지 않는다. 생성 impl은 반드시:
`classify_conformance(source="ui", impl="<key>") == "conforming"`(089) **그리고** `build_graph(mock ctx)`가
컴파일되고 노드열이 선언과 일치(085)해야 "완료". 실패 시 스킬은 서빙 거부(config_error)로 표면화.

## 3. 구현

- `packages/agent/src/agent/flows/__init__.py` 신규(빈 패키지 앵커 + 도크스트링).
- `packages/agent/src/agent/runtime.py`: `_bootstrap_builtins()`는 기존 그대로 두되, **스킬이** 생성 시
  flows import + `register_agent` 두 줄을 추가하는 규약을 확립(이 스펙에서는 배선 지점만 확정; 실제
  등록 줄은 각 flow 생성 턴에 추가).
- `.claude/skills/agent-flow/SKILL.md` 신규: 위 4단계 스캐폴딩 절차서(의도 수집 질문·모듈 템플릿·배선
  규약·검증 스크립트 템플릿·재기동 안내).
- **참조 데모 플로우 = `route`(분기 라우터)** 를 이 스펙의 산출물로 스킬을 통해 생성해 **엔드투엔드
  실증**한다(사용자 결정 2026-07-01). 입력을 분류해 두 분기 노드(`classify → answer_a`/`answer_b`) 중
  하나로 라우팅하는 다노드 그래프 — `plan_execute`와 구조가 달라(조건분기) 인터페이스 과적합 없음을
  노드열로 측정한다. 이는 스킬이 실제로 conforming impl을 만들어냄을 측정 가능하게 한다(스펙 완료 조건).

## 4. 완료 조건 (측정가능) — 전부 충족 ✅

- [x] **스킬 산출물이 conforming**: 스킬로 데모 flow `route` 생성 → `agent/flows/route.py` 존재 +
      `_bootstrap_builtins`에 배선 2줄 + `classify_runtime("ui", "route") == "conforming"`(verify_099 U3).
      `list_agent_impls() == ["plan_execute", "route"]`.
- [x] **구조 검증(085 패턴)**: `verify_099_route.py` U1~U5 — mock ctx로 `build_graph` 컴파일,
      노드 == {classify, answer_a, answer_b}(plan 노드 없음 = 과적합 아님), `describe().supports_hil==False`
      (인터럽트 없음 — 정직), 분기 순수함수 `classify_route` 결정성('?'→a / 평서문→b).
- [x] **통합 스트림(조건분기 실증)**: in-process ASGI로 `ui+impl=route` 에이전트 생성→chat → 토큰 +
      **실 노드 타임라인**. 질문→`[__start__, classify, answer_a, __end__]`(answer_b 미발화), 평서문→
      `[__start__, classify, answer_b, __end__]`(answer_a 미발화). 합성 call_model 아님. 생성 에이전트 DELETE.
- [x] **신뢰 불변식 보존(무회귀)**: `verify_085_runtime_interface.py` 전부 통과(U5 문자열→import 경로
      여전히 None, 드리프트 0). `verify_089_conformance.py` ALL GREEN.
- [x] **검증 사다리 3런**: ① 단위(17단언), ② 통합(조건분기 실 스트림), ③ **적대 타자 codex: no P0/P1**
      (ctx 외 상태 읽음 없음·매니페스트 과대선언 없음·등록이 eval 경로 안 엶·데드/미도달 노드 없음·
      비밀 미노출 확인).

## 5. 알려진 잔존 / 비목표

- **admin UI에서 impl 선택 노출은 비목표**(별도 스펙). 현재 SPA 편집 폼은 `impl`을 안 보냄(085 H5) —
  생성된 flow는 API로 config에 `impl` 넣어 생성/활성화하면 동작하나, admin 드롭다운 배선은 후속.
- **원격 `code`/`external` 플로우 생성 비목표** — 이 스펙은 인프로세스 `impl`만. A2A 카드 등록은 별개
  ([[agent-source-three-way-a2a-external]]).
- **런타임 동적 로딩 비목표** — 등록은 저작 시점 코드 + 재기동(신뢰 불변식 보존이 우선).
- 스킬이 생성하는 그래프의 *논리적 정확성*(플로우가 의도한 태스크를 잘 푸는가)은 스킬 사용자와 검증
  스크립트의 몫 — 이 스펙은 **인터페이스 적합·안전·저작 자동화**를 보장한다.

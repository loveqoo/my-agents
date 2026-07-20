# 420 — 모델 파라미터 캐스케이드 층 정책 단일화(원천 차단)

> 상태: **완료** · 2026-07-20 · 발단: 417(AgentForm)→419(OverridePanel) 같은 부류 2연타.
> codex 적대 4라운드(P1 2→clone/activate→adopt/프롬프트채택→claim-accuracy)로 관문을 라우트 뿌리기→
> **ORM @validates 단일 관문**으로 수렴. verify_420 22/22·verify_410/411·make test 91/0/0.
> 구남님: "말썽 부리는 곳은 원천 차단 안 하면 또 발생." + "미래의 당신이 히스토리 기억하고 예외
> 피할 거라 예상하냐(=아니다)." 설계 기준=[[design-for-amnesiac-future-actor]]: 기억 0 코더가
> 제일 쉬운 걸 집어도 자동으로 옳게, **틀린 길이 존재하지 않게**.

## 근본 진단 — 매트릭스가 한 곳에 없다
modelParams(모델 파라미터)는 캐스케이드 4층으로 적용된다: **model-default → agent → node → session**.
"어느 층이 어느 에이전트 유형에서 유효한가"라는 **매트릭스**가 단일 진실인데, 지금은 각 표면(FE 4곳)과
BE 캐스케이드에 **인라인으로 복붙**돼 있다. 그래서 규칙 바꾸면 N곳을 다 기억해야 하고, 하나 놓치면
재발(417→419가 실증).

| 층 | 노드형(pipeline) | 그 외(직접·조율·산출물) | 현재 위치 |
|---|---|---|---|
| model-default | ✓ | ✓ | ProviderModelView CapsEditor |
| agent | ✗ | ✓ | AgentForm(896) — 417서 `!isPipeline` 인라인 |
| node | ✓ | ✗ | NodeListEditor(197) |
| session | ✗ | ✓ | OverridePanel(518) — 419서 노드형 제거+payload 인라인 |
| **BE 적용** | agent·session **적용(틈)** | 적용 | chat_context_models `_resolve_node_models`(141·146) |

**잠복 틈**: FE는 417/419로 노드형 agent·session을 숨겼지만, BE `_resolve_node_models`는 여전히
노드에 agent 층(141)·session 층(146)을 적용한다 → 레거시 데이터·API 직접호출이면 숨긴 값이 살아
동작. FE 가시성과 BE 동작이 갈리는 드리프트.

## 설계 — 정책을 데이터로, 표면은 파생만(틀린 길 제거)

### 단일 진실: 층 정책
`layerApplies(layer, agentImpl) -> bool` 한 곳(FE `modelParamLayers.ts`, BE `model_param_layers.py`)에
매트릭스를 선언. 규칙은 단순 이진:
- `model-default`: 항상.
- `node`: pipeline만.
- `agent`·`session`: pipeline **아닐 때만**.

### FE — scope-aware 컴포넌트가 **유일한 문**
`<ModelParamsField layer={'agent'|'node'|'session'|'model-default'} agentImpl={...} .../>` 신설:
- 내부에서 `layerApplies(layer, agentImpl)` 판정 → false면 `return null`(표면은 판단 안 함).
- true면 raw `CapabilitySettings` 렌더(이 컴포넌트가 CapabilitySettings의 **유일한 소비자**가 되게).
- **raw `CapabilitySettings`를 표면에서 직접 못 쓰게**: export를 `ModelParamsField` 경유로 좁히거나
  (같은 파일 내부화), lint 규칙/주석 계약으로 "표면은 ModelParamsField만". 목표=6번째 표면을 짜는
  기억 0 코더가 손에 잡는 유일한 도구가 ModelParamsField라, 노드형 숨김이 공짜로 딸려옴.
- 4개 표면(CapsEditor·AgentForm·NodeListEditor·OverridePanel)을 ModelParamsField로 치환. 인라인
  `!isPipeline`·payload `!applied.nodes` 조건은 제거(정책이 흡수).

### BE — 캐스케이드가 정책을 강제(우회 불가)
`_resolve_node_models`가 `layer_applies('agent', impl)`·`layer_applies('session', impl)`를 참조 —
노드형이면 agent·session 층을 **적용 안 함**(누가 검사하러 가는 게 아니라 해석 로직에 박음). 비노드형
경로(직접·조율·산출물의 _resolve_model)는 무변경(agent·session 계속 적용).

### FE/BE 드리프트 봉인
정책이 두 언어에 갈라 사는 건 불가피(TS/Python) → **계약 핀 테스트**: 노드형 에이전트에 agent-level
modelParams를 심고 실행 → 노드 model_cfg에 그 값이 **안 실림**을 단언(BE가 FE 가시성과 일치). +
FE 단위(layerApplies 매트릭스)·BE 단위(layer_applies 매트릭스) 각각.

## 검증
- [ ] FE: ModelParamsField가 유일 소비자(raw CapabilitySettings 직접 렌더 0 — grep). 4표면 치환.
- [ ] FE 브라우저: 417·419 회귀 재확인(노드형 agent·session 숨김·직접형 노출) — SHOT417/419 재실행.
- [ ] BE: `_resolve_node_models`가 노드형에 agent·session 미적용(계약 핀 테스트 신규 verify_420).
- [ ] BE 무회귀: verify_410/411·suite(실모델)·make test 그린(캐스케이드 핵심 경로).
- [ ] tsc 0 · codex 적대(캐스케이드 의미 변경 — 비노드형 무회귀·노드형 층 제거가 정확한지).

## 최종 설계(구현) — codex 4라운드 수렴
- **정책 단일 진실**: FE `modelParamLayerApplies`(CapabilitySettings.tsx)·BE `layer_applies`
  (model_param_layers.py) — model-default=항상·node=pipeline만·agent/session=non-pipeline만.
- **FE 유일한 문**: `ModelParamsField`가 정책 판정 후 null/렌더. raw `CapabilitySettings` 모듈 내부화
  (export 제거). 3표면(AgentForm·OverridePanel·NodeListEditor)이 이것만 사용 → 새 표면도 우회 불가.
- **BE 런타임 관문**: `_resolve_model`·`_resolve_node_models`가 agent/session/node 층을 layer_applies로
  게이팅. **temperature 병렬 통로 봉인**(codex P1②): `ctx.temperature`도 노드형이면 None(4입구
  run_params가 다 None) — modelParams만 막으면 temperature가 별 채널로 노드를 덮던 실우회.
- **저장 관문(원천 차단)**: Agent·AgentVersion.config **ORM @validates**가 노드형 agent층 modelParams
  제거. 정상 라우트(create·update·clone·activate·adopt·resync)는 cfg 마지막 대입이라 이 한 관문 통과 —
  라우트별 strip 뿌리기(codex가 clone·activate·adopt 반복 지적한 안티패턴) 제거.
- **계약 정확화**(codex 재검): @validates는 **ORM 속성 대입** 관문이지 절대 DB 불변식 아님. Core
  update/bulk/raw SQL 우회는 현재 라우트에 없고 런타임 관문이 동작 방어. 절대 불변식은 before_flush/
  DB CHECK가 별도 장치(현존 우회 0이라 미도입 — 잔여 정직 명시).

## OUT
- 단기 기억(historyDepth) 층 — modelParams와 별개 축(모델 독립), 이번 범위 밖.
- temperature 특례 흡수(스펙 411 완료) — 무변경.
- Core/raw SQL 저장 우회 절대 차단(before_flush/DB CHECK) — 현존 우회 0·런타임 방어라 미도입.
- 캐스케이드 층 자체를 늘리는 것(새 층) — 정책이 생겼으니 추후 한 곳에서.

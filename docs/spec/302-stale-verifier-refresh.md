# 302 — stale verifier 정리 + artifact 노드 config 주입 회귀 수정

## 배경

dedup 연작(294~301) 내내 backlog에 쌓인 6개 "stale verifier"를 deep-reasoner 전수 진단. 결과:
**6개 중 1개(190)는 stale가 아니라 진짜 프로덕션 회귀**, 5개는 픽스처/테스트데이터 드리프트.

## 190 — 프로덕션 회귀 (⚠️ 최우선, artifact 에이전트 실사용 중단)

`packages/agent/src/agent/flows/artifact.py:351` `async def produce_node(state, config: RunnableConfig
| None)`. 모듈에 `from __future__ import annotations`(26줄)라 **모든 애노테이션이 문자열**. langgraph
1.2.5의 `_internal/_runnable.py`는 config 파라미터를 **애노테이션 문자열 매칭**(허용집합
`{"RunnableConfig","Optional[RunnableConfig]",...}`)으로 인식하는데 **PEP 604 문자열 `"RunnableConfig
| None"`은 없음** → config 미주입 → 노드를 `produce_node(state)`로 호출 → `TypeError: missing 'config'`.
- 실증(deep-reasoner): `"RunnableConfig"`·`"Optional[RunnableConfig]"` → 주입 O, `"RunnableConfig | None"`
  → 주입 X. 실행 시 `UserWarning: 'config' ... not 'RunnableConfig | None'` 동반(스모킹건).
- **영향**: `ArtifactAgentBase.build_graph`는 ConfigDrivenArtifactAgent·SlotFillDemoAgent·TargetingDemoAgent
  공통 골격 → 전 artifact 계열이 첫 노드에서 크래시. 스위트가 artifact를 안 태워 미검출.
- **수선**: `config: RunnableConfig | None` → `config: RunnableConfig`(langgraph가 항상 실제 config dict
  주입하므로 `| None` 불요). 본문 `(config or {}).get(...)`는 그대로 안전.
- **함정(OUT)**: `= None` 기본값만 추가하는 수선 **금지** — 애노테이션 미인식이면 config 여전히 미주입,
  기본값 None으로 조용히 실행 → `thread_id=""` → 스텝로그 리플레이 캐시(멀티턴 interrupt 결정성) 무력화
  (happy-path 초록·리플레이만 깨짐). **애노테이션을 인식형으로** 바꿔 실제 주입을 복원해야 함.

## 5개 픽스처 드리프트 (순수 테스트 수정)

- **[100] verify_100_broker.py**: `_FakeAgent`에 `active_version` 없음 → `broker/providers/agent.py:91
  _delegable`의 `if not a.active_version` AttributeError(스펙 256 서빙-중 게이트 추가). 수선: `_FakeAgent`에
  `active_version=None` 추가. **값은 반드시 None**(falsy) — ui가 91줄서 배제돼야 P1 기대(`{cap_ext}`) 성립.
- **[084] verify_084_memory_search.py**: 몽키패치가 `api.agents.resolve_agent_mem_cfg`를 패치하나 실제
  lookup은 `api.agents.memory_routes` 모듈 글로벌(스펙 291 분해 이동) → 진짜 함수 실행→fake `A`의 `.source`
  없음. 수선: 패치 대상을 `api.agents.memory_routes.resolve_agent_mem_cfg`로 이동(3곳). fake에 `.source`
  추가는 오답(진짜 resolve가 DB 타 FakeSession서 다르게 깨짐).
- **[103] verify_103_broker_rag.py**: 컬렉션 이름 `CP="col_v103_"`에 **밑줄** → 명명 규칙(영소문자·숫자·
  대시만) 위반 400 → seed 실패 → `next()` StopIteration→RuntimeError. 수선: `CP="col-v103-"`(대시).
- **[130] verify_130_broker_rag_visibility.py**·**[131] verify_131_inspector_detail.py**: `rag:Obsidian`
  참조인데 실 DB에 Obsidian 컬렉션 없음 → invoke error → `invocations[0]` IndexError. 수선: 현존 ready
  컬렉션 참조 또는 **전용 컬렉션 self-seed**(103 패턴, ambient 의존 제거=whole-fix). 131은 line 40 이후
  (V4~V7)가 크래시로 미도달이라 수선 후 **재실행으로 하위 드리프트 확인** 필수.

## 목표 (측정 가능)
1. 6개 verifier 전부 PASS(190은 프로덕션 수정 후, 5개는 픽스처 수정 후).
2. **190 회귀 수정**: artifact 계열 에이전트 첫 노드 크래시 해소 + config 실제 주입 복원(thread_id 보존).
3. 픽스처 수정이 verifier의 **검증 의도 불변**(100 active_version=None로 ui 배제 유지 등).

## 검증 (사다리 3런)
- **단위/게이트**: metrics-fast 0(190 애노테이션 변경 mypy·부팅). 6개 verifier 재실행 PASS.
- **실인프라 통합**: 스위트 51/51. **artifact 에이전트 실행 스모크**(190 — 노드 config 주입 복원 확인).
- **적대(codex)**: 190 수선이 (a) config 실제 주입 복원(애노테이션 인식형)인지 `=None` 눈속임 아닌지,
  (b) 리플레이/thread_id 결정성 보존인지, (c) 픽스처 수정이 검증 의도 훼손 없는지.

## OUT
- 130/131 self-seed vs repoint: 견고성 위해 self-seed 지향(whole-fix), 과하면 stable ambient(docs-kb) 참조+주석.
- 190 `= None` 기본값 수선(눈속임) — 금지.

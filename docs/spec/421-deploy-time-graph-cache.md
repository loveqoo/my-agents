# 421 — 배포후 그래프 캐시(캐시 제외 유형의 요청당 빌드 CPU 상각)

> 상태: **완료(P1+P2+P3 — 6유형 중 artifact 제외 전부 편입)** · 2026-07-20~21 · 발단: 개발자 "실시간
> 그래프를 빌드하는 에이전트 유형을 파악하여, 배포 이후에는 빌드/캐시된 에이전트를 제공." 판정축 교정:
> "응답시간이 아니라 **CPU가 매 요청 빌드하며 튀는 게 문제**"([[cpu-axis-not-latency]]).
> 최종 실측: **전 유형 graph 빌드 0.00ms**(route 0.7·orchestrate 1.6·pipeline-8 5.1 → 전부 버전당 1회).

## 조사 결과

### 실시간(요청마다) 빌드하는 유형 — 6종
`_graph_fingerprint`(chat_graph_build.py)가 None 반환 = 캐시 안 함 = 매 요청 새 빌드:
- **노드형**(pipeline, nodes_resolved) · **산출물형**(artifact_form) · **조율형**(orchestrate·
  orchestrate_ranked) · **커스텀**(route·plan_execute). **직접형(default)만** `_GRAPH_CACHE` 대상.
- 제외 사유(주석): "per-turn 재료(브로커·프록시)가 그래프에 얽혀 — 후속." 스펙 371 D3의 미완 후속.

### 실측 — CPU 축(tests/measure_build_cpu.py, 서버 CPU time 샘플링, mock 모델, 순차 80회)
default(캐시) 대비 **순수 그래프 빌드 CPU/요청**:

| 유형 | 순빌드 CPU/요청 | 참고: 지연(buildMs.graph) |
|---|---|---|
| default(캐시) | **0ms**(상각) | 0 |
| route | 0.9ms | 0.7 |
| orchestrate | 5.8ms | 1.6 |
| plan_execute | 8.8ms | 0.7 |
| pipeline(3노드) | 7.9ms | 2.2 |
| pipeline(8노드) | **26.3ms** | 5.1 |

**핵심 교훈**: 지연 측정(narrow compile 단계)은 실제 빌드 CPU를 **크게 과소평가**했다(8노드 5ms vs 실
CPU 26ms). 단일 이벤트 루프라 이 CPU는 그 시간 동안 **다른 모든 요청(스트리밍 포함)을 블록**한다. 매
요청 반복 → 1000req이면 pipeline-8은 **26초 CPU 낭비**. default가 0ms인 게 캐시 상각 효과를 증명.
→ **작업 가치 있음**(응답시간이 아니라 CPU/상각 관점에서).

### 부수 발견(별건)
- **동시성 취약**: 40 동시 버스트에서 500 다발(route 0/40·pipeline 5~7/40 성공). DB 풀 경합/노드형
  동시성 이슈일 수 있음 — 캐시와 별개, 백로그 후보.
- artifact_form은 단발 채팅 buildMs 미노출(폼 흐름 상이) — CPU 측정엔 잡힘(포함).

## 설계 — 핵심 원리: **함수는 고정·캐시, 가변 데이터는 런타임 파라미터**(개발자 확정)
"per-turn 재료가 그래프에 얽혀 캐시 못 함"은 캐시의 한계가 아니라 **현재 빌드가 유저/세션 상태를 노드
클로저에 박은 설계 냄새**다. 그래프(버전-고정 구조·함수)는 캐시하고, 요청-스코프 가변 데이터는
**RunnableConfig(`config["configurable"]`)로 매 호출 주입**한다 — 이 코드베이스에 **이미 있는 패턴**
(artifact.py:354·pipeline.py:140이 thread_id/store를 이 길로 받음). 그러면 캐시된 그래프가 **유저를
담을 수 없어** 누출이 *구조적으로 불가능*하고(조심이 아니라 불가능, [[design-for-amnesiac-future-actor]]),
인가는 **매 요청 라이브**로 정확하다.

**분류 기준(개발자 정정) — "가변이냐"가 아니라 "같은 버전 안에서 요청마다 다르냐"**:
- **버전이 정하는 값**(같은 버전이면 A·B 모든 요청 동일): 그래프 위상·노드 함수·**프롬프트**·모델·
  MCP/RAG 도구 → **캐시 키(지문+버전)에 넣고 그래프에 박음**. 프롬프트는 버전 고정이라 런타임 주입
  대상이 아니라 **키 입력**이다(플레이그라운드 오버라이드만 예외 — 지문에 프롬프트 해시 넣으면 자동:
  배포 버전 적중·오버라이드 재빌드).
- **같은 버전인데 요청마다 다른 값**: broker(같은 버전을 **유저 A·B가 다른 권한**으로 호출 — principal×
  라이브 RBAC, 얼리면 회수 권한 통하는 구멍 [[gate-on-intent-value-not-mutable-baseline]])·`_MemoryRecall
  Proxy`(세션)·`_HistoryWindowProxy`(턴)·attachment_context → **RunnableConfig로 주입**. broker는 만드는
  게 싸므로(368 broker 단계 ≈ 0) 요청마다 새로.

**캐시 키** = 스펙 367 버전(배포=오픈 확정 불변) + 기존 지문 축 승계(모델 능력 라이브 사실·
attachment_context 등 — 하나라도 빠지면 조용한 우회, retrospect 336).

**정정(2026-07-20 — 초기 조사 오류)**: "P1 route/plan = 요청-스코프 재료 0"은 **틀렸다**. route.consumes=
("memories") → 매 턴 회상 → `prompt_prompt = ctx.prompt + 회상기억`(chat_turn_runtime:226) → route가
이 기억-포함 프롬프트를 노드 클로저에 **굽는다**(route.py:51). 즉 route/plan도 **요청-스코프 재료(회상
기억)를 굽고** 있어 그대로 캐시하면 broker와 **같은 부류의 누출**(유저 A 사적 기억 → 공유 캐시 → 유저 B,
턴 사이 stale). default가 promptless인 이유가 이것 — 아무것도 안 굽고 기억-포함 프롬프트를 **매 턴 seed
선두 메시지로** 태워 캐시 그래프를 기억-무관으로 유지.

**따라서 통일 불변식**: *어떤 impl도 per-turn 재료(회상기억·broker·프록시·창·첨부)를 그래프에 굽지
않는다.* 전부 **매 호출 주입**(promptless seed 또는 RunnableConfig)한다. 그러면 그래프는 버전-고정만
얼려 캐시 안전. 작업은 균일하게 "per-turn 재료를 그래프 밖으로 → 캐시 편입".

**단계(그래프에서 빼낼 per-turn 재료 수 순)**:
- **P1 route·plan_execute**: per-turn 재료 = **회상기억 1개**. default와 동일하게 **promptless화**(기억+
  프롬프트를 seed로) → 캐시 편입. default 메커니즘 재사용. 위험: route는 raw `model.ainvoke([sys, *msgs])`라
  promptless면 [mode_sys, seed_sys, ...] 두 system 메시지 — 프로바이더 수용 여부 **테스트로 확인**.
- **P2 orchestrate·artifact_form**: per-turn 재료 = broker 1개 → config 이관 후 편입.
- **P3 pipeline**: broker + 회상/창 프록시 + broker 유래 agent tools 전부 config 이관 후 편입.
각 단계: per-turn 재료 축출 → 캐시 편입 → measure_build_cpu 재실행(순빌드 CPU ~0) → codex 적대(per-turn
재료가 캐시로 공유 안 됨·기억/권한 누출 "여집합") → 다음.

## P1 완료(route·plan_execute) — 2026-07-21

**설계 정착(이중 모드)**: 순수-promptless는 *모든* invoke 경로가 seed를 넣어야 해서, 새 경로가 잊으면
프롬프트가 조용히 유실(codex가 eval_runner에서 실증). 그래서 노드를 **이중 모드**로:
`base = ctx.prompt if ctx.prompt else split_seed_prompt(state)`. 프롬프트를 넘기는 게 **기본 안전동작**
(직접-빌드 경로=eval·a2a·비캐시가 그걸 굽는다), promptless는 **캐시 관문(_graph_for_turn) 한 곳만**
prompt="" 전달 → 노드가 매 턴 seed에서 읽음. 회상기억을 그래프에 굽는 유일 경로는 비캐시라 누출 0.
([[design-for-amnesiac-future-actor]] — 기억 0인 미래 코더가 프롬프트를 넘겨도 자동으로 옳음.)

**codex 적대 2라운드**:
- R1: ①eval_runner 등 비-seed 입구가 프롬프트 유실(순수-promptless 결함) → **이중 모드**로 봉합.
  ②plan_execute discovery `call_tool`이 config 미전달 → 캐시 그래프가 빌드-시점 closure sink에 turn-간
  오귀속 → `call_tool(config)` 주입+전달로 봉합.
- R2: 두 결함 해소 확인. 선재 결함 발견 — discovery `call_tool`의 `except Exception`이 `GraphInterrupt`
  (HIL)를 삼켜 승인 흐름이 조용히 죽음 → `except GraphBubbleUp: raise`로 봉합(제어흐름 전파 보존).

**검증**: verify_421(단위 U1~U3 + http P1~P3) — 이중 모드 baked/seed·call_tool 이번 턴 sink·HIL 전파·
캐시 적중(buildMs.graph 0)·**P3 격리**(B가 A 캐시 그래프 공유해도 각자 프롬프트만, 누출 0). 회귀 네트
92/0/0. verify_371/099/085/154/203/041 무회귀.

## 완료 기준(CPU 축)
- [x] **P1** route·plan_execute: 2턴째 buildMs.graph=0.0ms(매 요청 재빌드→버전당 1회 상각, verify_421).
- [x] **P1 격리 codex 통과**: 프롬프트/회상이 캐시 그래프에 안 담김(promptless+이중모드) — P3 대칭 격리
      실증. codex 2라운드 봉합(이중모드·call_tool config·HIL 전파).
- [x] **P1 무회귀**: make test 92/0/0 · verify_371/099/085/154/203/041.
- [x] **P2** orchestrate(+ranked): 프롬프트=이중 모드 seed(P1 동형)·broker=config-우선(P3 동형) —
      능력은 도구로 안 굽고 discover가 호출 시점 발견이라 caps 지문 축 불필요. graph 1.6→0.00ms.
      **artifact_form은 제외 유지**(정직한 경계): interrupt 리플레이·thread 스텝 캐시 기계가 얽혀
      복잡 대비 이득 미측정(폼 흐름은 빌드 빈도도 낮음) — 지문 artifact_spec 배제 유지.
- [x] **P3** pipeline: graph 빌드 2.3/5.1→**0.00ms**(nodes/caps 지문 축+프록시·broker config 주입).
      codex 1건(caps rename 축) 봉합, verify_421 U4~6+P4~5·배터리 10종·그물 92/0/0.
- [x] 단계마다 측정→검증 후 다음, 각 단계 codex.

## P3 설계(pipeline) — 2026-07-21 착수

**조사 확정**: MCP·RAG 도구는 이미 config-sink(371 D3 — `_sink_from(config, closure)`)라 캐시 안전.
pipeline이 굽는 per-turn 재료는 셋: ① `ctx.memory_recall`(_MemoryRecallProxy — 유저 스코프·턴 기록)
② `ctx.history_window`(_HistoryWindowProxy — 턴 대화) ③ **agent tools**(`agent__*` — broker를 클로저에
굽고, 집합 자체가 allowlist∩라이브RBAC=유저 의존). 노드 프롬프트·모델·도구참조·형식은 전부
nodes 설정(버전+오버라이드) = 버전-고정. **broker.invoke는 호출 시점마다 `_permitted`(allowlist∩RBAC)
재검사** — broker만 주입하면 인가는 라이브로 정확.

**설계(P1 이중 모드 패턴 승계 — 전부 config-first, ctx-fallback)**:
1. **프록시 주입**: `_step(state, config)`로 노드가 RunnableConfig를 받고, 회상/창 프록시를
   `config["configurable"]` 우선·`ctx` 폴백으로 해석. **캐시 관문 빌드는 프록시를 None으로 스트립** —
   주입을 잊은 미래 경로는 turn-A 데이터 누출이 아니라 "회상 없음"으로 조용히 안전(fail-safe).
2. **agent tools broker 주입**: `_delegate(text, config)` — broker를 config 우선·클로저 폴백. **캐시
   관문에 넣는 빌드는 broker=None 스텁**(클로저 폴백이 turn-A broker가 되는 길 자체를 제거 —
   주입 없이 호출되면 정직한 실패, [[design-for-amnesiac-future-actor]]). 직접 빌드(eval·resume)는
   실 broker 클로저(종전 동작).
3. **지문 확장**: pipeline manifest `cacheable=True` + 새 `seed_prompt=False`(pipeline은 에이전트
   프롬프트 미소비 — seed 선두 system을 넣으면 오히려 오염이라 캐시 경로에서도 seed 생략).
   축 추가: `nodes`=_fp(nodes_resolved 정규 JSON — 노드 프롬프트·모델(라이브 능력 포함)·도구·형식·
   depth 전부 포괄, 오버라이드 자동 분리) + `agent_caps`=위임 가능 집합 정렬 id(allowlist∩라이브RBAC —
   RBAC 다른 유저는 다른 그래프, 같아도 주입 broker가 재검사=이중 방어. caps는 매 턴 이미 조회라 비용 0).
   **코드 노드(impl 키) 포함 파이프라인은 캐시 제외**(build_step이 ctx 전체를 받아 임의 포획 가능 —
   정직한 경계, fp=None).
4. **호출부**: `_turn_config`에 memory_recall/history_window/broker 주입(기존 mcp_calls_sink와 같은
   관문). broker 빌드를 지문 계산 앞으로 호이스트(caps가 지문 축이므로 — build_broker는 368 실측 ≈0).

## P3 완료(pipeline) — 2026-07-21

설계대로 구현. **codex 적대(P3 라운드)**: 핵심 보장 전부 유지 판정(캐시 그래프에 turn-A 클로저 잔존 0·
코드 노드 제외 견고·모든 실행 경로 주입 정합·seed 게이팅·HIL 재개·MCP/RAG sink). **P2 1건** — 위임
대상 rename/후크 변경이 캐시 무효화 안 됨(지문에 cap id만, 도구 설명에 name/hook이 굽힘 — 라이브
사실이라 버전 안 오름) → 축을 **(id, name, hook) 삼중**으로 봉합(caps는 매 턴 이미 조회라 비용 0).

**검증**: verify_421 확장 — U4(프록시: config 주입 사용·미주입=생략 fail-safe·직접 빌드 폴백)·U5(스텁
도구: config broker 위임·미주입=정직 실패)·U6(fp 산출·코드 노드 제외·nodes/caps-id/caps-rename 축 분리)
+ P4(pipeline 2턴째 graph 0.0ms·에이전트 프롬프트 미주입)·P5(캐시 적중 그래프서 위임 매 턴 동작,
brokerCalls t1=t2=1). HIL 수동 프로브: 캐시 적중 턴에도 interrupt·승인 생성 정상. 파이프라인 배터리
(259·260·261·265·268·270·315·317·318·319)·041·371·099·085·154 전부 통과, 그물 92/0/0.

**측정**(measure_perf 재실행): pipeline-3·8 **graph 빌드 2.3/5.1 → 0.00ms**(버전당 1회 상각). 남은
CPU/req 차이는 노드 수만큼의 mock 자기-호출 프레임워크 비용(캐시 무관 — learning 398 아티팩트, 실배포
는 외부 모델 async I/O). orchestrate만 1.6ms 재빌드 잔존(P2). pipeline-8 4워커 버스트 20→22/30 소폭
개선 — 잔존은 자기-호출 증폭(30req×8노드=240 self-call, mock 한계)이지 빌드 아님(정직 기록, 백로그).

## P2 완료(orchestrate·orchestrate_ranked) — 2026-07-21

P1(프롬프트 seed 이중 모드)+P3(broker config-우선) 메커니즘 조합만으로 편입 — **graph 1.6→0.00ms**
(전 유형 0 달성). 능력은 도구로 굽지 않고 `broker.discover`가 호출 시점 발견이라 caps 지문 축 불필요
(라이브 정확). delegate에 broker 미주입 정직 가드 추가. **artifact_form은 제외 확정**(interrupt 리플레이·
thread 스텝 캐시 기계 — 복잡 대비 이득 미측정, 정직한 경계).

**codex 적대(P2 라운드)**: 보장 1·2·4·5 유지 판정. **P1 1건** — 배포 경계 레거시 승인 재개: 구 버전
(굽던 시절) 체크포인트엔 seed가 없는데 새 코드가 지문 기준 promptless로 재빌드 → 프롬프트·회상 유실.
**구조 봉합**(불변식: *재개 그래프의 모양은 지문(코드의 추측)이 아니라 체크포인트의 실제 상태가 결정*):
`_resume_state_has_seed`가 선두 seed 유무를 실물로 판독해 promptless를 결정(레거시=굽기·신규=promptless
— 배포 경계 구분 자체가 소멸, default의 371 시절 레거시 구멍도 함께 닫힘). 판독 불가만 종전 지문 폴백.
synthesize는 seed를 **항상 걷고** `baked or seed` — 어느 조합이든 단일 system 불변식. 수리 중 F821
(thread_id 스코프)로 verify_101 H7 재개 500 → approval.checkpoint로 교정, 전 배터리 재검증.

**검증**: verify_421 U7(재개 seed 판정 4분기)+P6(orchestrate 캐시 적중·seed→synthesize 도달) 추가,
verify_100/101/102/115/116/117(위임·HIL 재개 왕복·협업)·041 전부 통과, 그물 92/0/0 ×2.

## OUT
- 동시성 500 다발(부수 발견) — 별건 조사(백로그).
- MCP 디스커버리 비용 — 이미 버전키 `_TOOL_SPEC_CACHE`로 상각(스펙 368/371), 무변경.
- 원격(code/external) 에이전트 — in-process 빌드 대상 아님.

## 자산
- `tests/measure_build_cpu.py`(신규) — CPU 축 측정 하네스(캐시 前/後 잣대). `tests/measure_build_hotpath.py`
  impl 축 추가(지연 축). 둘 다 재실행 자산.

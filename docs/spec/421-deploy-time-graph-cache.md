# 421 — 배포후 그래프 캐시(캐시 제외 유형의 요청당 빌드 CPU 상각)

> 상태: **초안(조사 완료·승인 대기)** · 2026-07-20 · 발단: 구남님 "실시간 그래프를 빌드하는 에이전트
> 유형을 파악하여, 배포 이후에는 빌드/캐시된 에이전트를 제공." 판정축 교정: "응답시간이 아니라 **CPU가
> 매 요청 빌드하며 튀는 게 문제**"([[cpu-axis-not-latency]]).

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

## 설계 — 핵심 원리: **함수는 고정·캐시, 가변 데이터는 런타임 파라미터**(구남님 확정)
"per-turn 재료가 그래프에 얽혀 캐시 못 함"은 캐시의 한계가 아니라 **현재 빌드가 유저/세션 상태를 노드
클로저에 박은 설계 냄새**다. 그래프(버전-고정 구조·함수)는 캐시하고, 요청-스코프 가변 데이터는
**RunnableConfig(`config["configurable"]`)로 매 호출 주입**한다 — 이 코드베이스에 **이미 있는 패턴**
(artifact.py:354·pipeline.py:140이 thread_id/store를 이 길로 받음). 그러면 캐시된 그래프가 **유저를
담을 수 없어** 누출이 *구조적으로 불가능*하고(조심이 아니라 불가능, [[design-for-amnesiac-future-actor]]),
인가는 **매 요청 라이브**로 정확하다.

**두 갈래로 분류** — 그래프에 든 것을:
- **버전-고정**(모든 유저 공통·불변): 그래프 위상·노드 함수·프롬프트 seed·MCP/RAG 도구(버전키
  `_TOOL_SPEC_CACHE`) → **캐시된 그래프에 박음**.
- **요청-스코프**(유저·세션·턴마다 다름): broker(유저 principal×**라이브 RBAC** — 얼리면 회수된 권한이
  통하는 보안 구멍, [[gate-on-intent-value-not-mutable-baseline]])·`_MemoryRecallProxy`(세션)·
  `_HistoryWindowProxy`(턴)·attachment_context → **RunnableConfig로 주입**. broker는 만드는 게 싸므로
  (368 broker 단계 ≈ 0) 요청마다 새로 만들어 넣는다(캐시 불요·라이브 정확).

**캐시 키** = 스펙 367 버전(배포=오픈 확정 불변) + 기존 지문 축 승계(모델 능력 라이브 사실·
attachment_context 등 — 하나라도 빠지면 조용한 우회, retrospect 336).

**단계(요청-스코프 재료 config 이관 개수 순)**:
- **P1 route·plan_execute**: 요청-스코프 재료 **0**(model+prompt[+version-stable tools]만). 지문만 확장하면
  즉시 캐시 편입 — 371 D3와 거의 동형. 착수 첫 타자(위험 최소).
- **P2 orchestrate·artifact_form**: broker 1개만 config 이관 후 캐시 편입.
- **P3 pipeline**: broker + 회상/창 프록시 + broker 유래 agent tools 전부 config 이관 후 편입.
각 단계: config 이관 → 캐시 편입 → measure_build_cpu 재실행(순빌드 CPU ~0 확인) → codex 적대(요청-
스코프 재료가 캐시로 공유 안 됨: "여집합") → 다음.

## 완료 기준(CPU 축)
- [ ] measure_build_cpu 재실행 — 편입 유형의 순빌드 CPU/요청이 **~0ms**(default 수준)로 상각.
- [ ] **RBAC 누출 codex 적대 통과**(P2/P3 — 유저별 broker·프록시가 캐시로 공유 안 됨: "보장 목록의
      여집합"). attachment_context 강제·stale 회상·prompt-provenance 등 지문 축 누락 0.
- [ ] make test·suite(실모델)·verify_408/410/411 무회귀(캐시 무효화 축 정확).
- [ ] 단계마다 측정→검증 후 다음(P1→P2→P3), 각 단계 codex.

## OUT
- 동시성 500 다발(부수 발견) — 별건 조사(백로그).
- MCP 디스커버리 비용 — 이미 버전키 `_TOOL_SPEC_CACHE`로 상각(스펙 368/371), 무변경.
- 원격(code/external) 에이전트 — in-process 빌드 대상 아님.

## 자산
- `tests/measure_build_cpu.py`(신규) — CPU 축 측정 하네스(캐시 前/後 잣대). `tests/measure_build_hotpath.py`
  impl 축 추가(지연 축). 둘 다 재실행 자산.

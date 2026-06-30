# 086 — 턴 인스펙터 노드별 세부정보 (상태 델타 미리보기 + 실측 시간)

## 배경 — 무엇이 문제인가

스펙 085로 인스펙터의 "LangGraph 경로"가 **실 노드열**(`[__start__, plan, execute, __end__]`)을
싣게 됐다. 하지만 각 노드 행은 **이름 + `+Xms`** 만 보여준다. 그리고 그 `ms`는 *가짜* — 전체
지연을 노드 수로 균등분할한 표시용 추정치다(085 F3로 명시한 빚: `runtime.py:_timeline_from_nodes`
docstring "ms도 total을 노드 수로 균등 분할한 표시용 추정치지 노드별 실측이 아니다").

근본 원인은 `chat.py:634` 한 줄이다:

```python
observed_nodes.extend(k for k in chunk if not k.startswith("__"))
```

`updates` 청크는 `{노드명: {그 노드가 바꾼 상태 델타}}` 딕셔너리인데, **키(노드 이름)만 뽑고
값(상태 델타)·도착 시각을 통째로 버린다.** 그 버려지는 값에 "세부정보"가 다 들어있다:

| 흐르는데 버리는 것 | 보여주면 | 비용 |
|---|---|---|
| 각 update **도착 시각** | `+Xms`가 노드별 **실측**이 됨(F3 빚 청산) | 작음(타임스탬프 1개) |
| 각 노드 **상태 델타** | `plan→execute`가 *이름*이 아니라 *내용*으로 읽힘(plan이 만든 계획 문자열 등) | 중간(redaction·캡 필요) |

`plan` 노드가 발화했다는 사실만 뜨고, *무슨 계획을 세웠는지*는 안 보인다 — 인스펙터의 존재이유
(턴 내부를 들여다본다)를 절반만 채운다.

## 결정 (사용자 합의)

- **범위 = 추천 ①+②.** ① 노드별 실측 시간(F3 빚 청산 + 거의 공짜), ② 노드별 상태 델타 미리보기
  (질문하신 "세부정보" 그 자체). 둘이 같은 한 줄(`updates` 청크 값)을 살리는 것이라 같이 간다.
- **③ 도구↔노드 귀속은 비목표(이번 컷 제외).** 평면 MCP 목록은 그대로 — 노드 귀속은 후속.
- **추가만, 무회귀.** 새 필드는 옵셔널. 원격 재개 등 노드 미관측 경로(`graph_nodes is None`)는
  기존 합성 폴백 그대로(learning 060 — 폐기경로 행동 보존).

## 설계

### 1. 캡처 — 값을 버리지 말고 요약·계측 (`chat.py` astream 루프)

`observed_nodes: list[str]`를 노드 발화 레코드 리스트로 승급:

```python
observed: list[dict] = []   # [{node, ms, summary}] — updates 발화 순서·실측·요약
t_prev = t0
async for stream_mode, chunk in graph.astream(..., stream_mode=["messages", "updates"]):
    ...
    elif stream_mode == "updates" and isinstance(chunk, dict):
        if "__interrupt__" in chunk:
            interrupts.extend(...)
        now = time.perf_counter()
        for node, delta in chunk.items():
            if node.startswith("__"):
                continue
            observed.append({
                "node": node,
                "ms": int((now - t_prev) * 1000),     # ① 실측: 이전 update 이후 경과
                "summary": _summarize_node_update(node, delta),  # ② 안전 요약(아래)
            })
        t_prev = now
```

- **① 실측 ms** = "직전 update 이후 경과". *직렬* 그래프(현 2종)에선 각 노드 update가 그 노드 완료
  시 순차 도착하므로 노드별 실 소요다 → F3의 "균등분할 추정" 빚을 직렬 그래프에 대해 **실측으로
  청산**. *병렬 superstep* 잔여는 §경계에 정직 표기(한 청크에 여러 노드 → 같은 도착시각 공유).
- **재진입 보존**: 같은 노드가 여러 번 발화하면(ReAct 루프) 각 발화가 별도 레코드 — 085의 "중복
  보존=실 재진입" 불변 유지.

### 2. 안전 요약 — `_summarize_node_update(node, delta) -> str | None` (`runtime.py` 신설)

상태 델타를 **사람이 읽을 짧은 문자열**로 요약한다. 보안·크기 불변식:

- **비밀값 redaction(키 기반)**: 델타 키가 민감 패턴(`api_key`·`token`·`password`·`auth`·`secret`·
  `key` 등, 닫힌 집합)에 매치하면 값을 `«redacted»`로 마스킹. CLAUDE.md "비밀값은 절대 trace에
  안 싣는다" 강제. (저장 크레덴셜용 `crypto.is_masked`와 별개 — 여기선 *임의 상태 키* 마스킹.)
- **사이즈 캡은 raw에서**: 직렬화된 **raw 문자열 길이**에서 누적해 자른다(예 노드당 ≤300자, 전체
  trace 노드 요약 합 ≤4KB). learning "raw 소스에서 캡하라 — `.content` 위 카운트는 막은 척".
  잘리면 `…(N자 생략)` 정직 표기(no silent truncation).
- **알려진 형태 우대**: `{"plan": "..."}` → 계획 문자열(캡); `{"messages": [...]}` → 이미 토큰으로
  스트림됐으므로 `메시지 N건`만(중복 본문 안 실음); 그 외 → 변경 키 목록 + 캡된 repr(마스킹 적용).
- **빈/무의미 델타** → `None`(요약 행 안 그림).

### 3. 조립 — `assemble_trace` 계약 진화 (`runtime.py:396`)

- `_timeline_from_nodes(nodes: list[str], total_ms)`는 **폴백 전용으로 보존**(graph_nodes만 있고
  요약/실측 없는 경로 = 현 U4 테스트 계약 무변경).
- 신규 `_timeline_from_observations(observed: list[dict])`: `observed` 레코드를 그대로 `[__start__,
  …실측·요약 노드…, __end__]`로 감싼다. ms는 균등분할 대신 레코드의 실측값.
- `assemble_trace(..., graph_observations: list[dict] | None = None)` 추가. 우선순위:
  `graph_observations`(085+086 풀디테일) → `graph_nodes`(085 순서만) → `build_graph_path`(폴백).
  **무회귀**: 세 경로 모두 보존, 기존 호출부·테스트 불변.

### 4. 프런트 — 노드 행에 요약 렌더 (`agentData.ts` + `Inspector.tsx`)

- `GraphNode`에 `summary?: string` 추가(옵셔널 — 폴백 경로는 `undefined`).
- `GraphPath`(Inspector.tsx:169) 각 노드 행 밑에 `summary`가 있으면 접힌 미리보기 줄/`codeBox`로
  렌더(RAG 호출의 쿼리 박스와 동형 스타일 — 신규 컴포넌트 최소화). 없으면 기존과 동일.
- `ms`는 이미 렌더 중(`+{n.ms}ms`) — 값이 실측으로 바뀔 뿐 렌더 변경 없음.

## RBAC/소유권 체크리스트 — 적용 여부

**트리거 객관 판정**: 이 스펙은 *trace 표시 보강*이다 — `user_id`/테넌트 컬럼을 새로 읽거나
`_own_scope`/`_visible_or_404`/`_assert_*owns` 헬퍼를 건드리지 않는다. 노드 요약은 **사용자가 이미
소유·스트리밍 중인 그 턴**에서 파생(새 자원·새 입구 0). chat 경로의 기존 `own` 세션 게이트는 그대로.
→ **RBAC 체크리스트 미적용** (사유: 새 소유경계 0). 단 §2의 **비밀값 redaction 불변식**은 별도
단언으로 검증한다(설정 자체를 단언 — "installed guard ≠ covering guard": 민감 키 든 델타가 실제로
마스킹돼 스트림 trace에 안 새는지 적대로 확인).

## 검증 사다리 (3런 — 비겹침)

- **① 단위**: `_summarize_node_update`이 (a) 민감 키(`api_key`·`token`…) 값을 `«redacted»`로
  마스킹, (b) raw 문자열에서 노드당·전체 캡 적용(초과분 `…생략` 정직 표기), (c) `{"plan": s}`→계획
  문자열·`{"messages":[…]}`→`메시지 N건`·빈 델타→None; `_timeline_from_observations`이 실측 ms·요약
  보존하고 `__start__/__end__` 감쌈; `assemble_trace` 3경로 우선순위(observations→nodes→폴백)·
  폴백 경로 U4 계약 무변경.
- **② 실인프라 통합(in-process ASGI + 실 그래프)**: plan_execute chat → `trace.graph`의 `plan` 노드
  `summary`에 **실 계획 문자열**이 담김(자리표시 아님)·각 노드 `ms`가 균등분할 아닌 실측(합 ≈
  latencyMs, 단조); 민감 키를 상태에 심은 프로브 그래프 → 스트림 trace에 원문 안 뜨고 마스킹 확인;
  ui(단일 노드) 무회귀; 원격 폴백(graph_nodes 없음)→합성 경로·요약 없음 그대로(learning 060).
- **③ 적대 codex**: 비밀 누출(미마스킹 상태 키·중첩 dict 안의 토큰), 캡 우회(요약 문자열에만 캡
  걸고 raw 델타는 안 걸어 거대 페이로드가 메모리/대역 폭증 — learning "raw에서 캡"), 병렬 superstep
  ms 정직성, 폴백 완전성(learning 060 — 폐기경로 차집합).

## 완료 체크
- [x] 캡처: `observed`를 `{node, ms(실측), summary, parallel?}` 레코드로 승급(`chat.py` astream 루프)
- [x] `_summarize_node_update` — 키기반 redaction + **값-비밀 fail-closed**(plan만 값 노출) + **budgeted 캡** + 알려진 형태 우대 + 비문자 키 fail-closed(`runtime.py`)
- [x] `_timeline_from_observations`(+parallel 보존) + `assemble_trace(graph_observations=)` 3경로 우선순위(폴백 무회귀)
- [x] 프런트: `GraphNode.summary?`·`parallel?` + `GraphPath` 요약 행·병렬 ms 정직 표기(폴백 시 미표시)
- [x] 단위 + 실인프라 통합(plan_execute 실 계획·실측 ms·마스킹·폴백 무회귀) + 적대 codex 그린, 085/041 무회귀
- [x] 브라우저: 플레이그라운드에서 plan 노드 요약·노드별 실측 ms(5ms vs 5928ms) 화면 확인(verify-ui)

## 검증 결과

**검증 사다리 4런 전부 통과**(`tests/verify_086_inspector_per_node_detail.py` 그린, 085/041 무회귀, tsc 0).

- **rung1 단위**: redaction·budgeted 캡·fail-closed·3경로 우선순위 + 아래 codex 공격 4건을 그린 단언으로 고정.
- **rung2 통합(in-process ASGI+실 그래프)**: plan_execute → plan summary 실 계획 문자열, 노드별 실측 ms(plan 1 ≤ execute 58, 균등분할 아님), 마스킹 종단.
- **rung2.5 브라우저**: 인스펙터 화면에 plan 요약 + 실측 ms(5ms vs 5928ms) 렌더 확인(`tests/browser/shot-node-detail.mjs`).
- **rung3 적대 codex**: 5건 발견 → 분류·처리.

### codex 적대 리뷰 분류(5건)

| # | 심각도 | 발견 | 086 도입? | 처리 |
|---|---|---|---|---|
| F1 | P0 | MCP/tool 인자(`calls_sink.args=kwargs`)·result가 원문 그대로 trace에 실리고 Inspector가 `JSON.stringify`로 렌더 — 086 요약 redaction과 *무관한 같은 trace 표면*에서 비밀 노출 | ✗ pre-existing(085 이전, 별 표면) | **follow-up 087로 분리**(공용 recursive redactor를 mcp args/result/interrupt에 적용). 086 스코프 밖이라 같은 커밋에 안 섞음 |
| F2 | P1 | 키기반 redaction은 *값 자체* 비밀(`{"note":"<secret>"}`·한글 키)을 못 막음 | ✓ | **수정**: 값 원문은 최소 allowlist(`plan`)만, 그 외 임의 키 문자열 값은 길이만(fail-closed). U1c 가드 |
| F3 | P1 | 캡이 post-build(거대 값을 join으로 통째 만든 뒤 자름) — raw 캡 아님 | ✓ | **수정**: 필드별 budgeted 캡 선적용 + 필드캡(300)/노드캡(1200) 분리(이중 캡 거짓 표기 제거). U2/U2b 가드 |
| F4 | P1 | 병렬 superstep 노드들이 같은 ms → 순차 누적처럼 과장 | ✓ | **수정**: 한 청크 노드 2+면 `parallel` 플래그, UI는 `병렬 ⏱Xms`로 정직 표기. U4b 가드 |
| F5 | P2 | 비문자 키 → `_SENSITIVE_KEY.search`에서 TypeError로 chat loop 종료 | ✓ | **수정**: `str(key)` 정규화 + 요약기 전체 try/except fail-closed. U4c 가드 |

> **F1은 미해결 의도적 분리**: 비밀 누출 P0이지만 086이 도입하지 않은 *다른 trace 표면*(MCP 호출 카드)이라,
> 086 per-spec 커밋을 오염시키지 않도록 087로 뺀다. 같은 보안경계라 086이 만든 redaction 도구를 087이 재사용한다.

## 비목표
- 도구 호출의 노드 귀속(평면 MCP 목록 유지) — 후속.
- 병렬 superstep **1급** 추적(superstep 그룹핑·노드별 실측 타이밍 전용 스트림 소스) — 086은 직렬
  실측 + 병렬 근사 정직화까지. F3 빚의 *완전* 청산은 별도 스펙.
- langfuse/OpenTelemetry 도입(085 비목표 유지) — 기존 수공 trace dict 강화 선까지.
- 노드별 중간 상태를 클라이언트에 **실시간** 스트림(라이브 패널) — 086은 최종 trace에 요약 첨부까지.

# 119 — 에이전트 평가 하네스 (결정적 수치 점수, 개발·CI)

## 배경 / 왜

사용자의 핵심 지향 = **수치 검증되면 Spec 최대한 뽑고 goal 주고 무한 반복(Ralph)**(memory
numeric-verification-unlocks-autonomy). 그 전제는 "에이전트가 좋아졌나"를 **자동·결정적으로 판정하는
수치**다. 방향 2(Langfuse)가 관측 토대를 놓았고, 방향 3은 그 위에 **평가 하네스**를 얹는다 —
사용자 선택 "개발·CI 하네스"(UI/DB 아님, tests/ 재사용 도구).

## 설계 — 데이터셋 × 실행함수 → 결정적 수치

핵심: **평가 케이스 집합**(입력 + 결정적 assertion)을 **실행함수**로 에이전트에 돌려 **통과율 수치**를
낸다. 자율 루프가 최적화할 "그 숫자".

- `tests/eval_harness.py` — 재사용 모듈:
  - `EvalCase(name, input, asserts)` — 한 케이스(입력 + scorer 리스트).
  - `run_eval(cases, run_fn) -> EvalReport` — 각 케이스를 `run_fn`으로 실행(관측 dict 반환)하고 asserts
    평가. `EvalReport.score` = 전 case 통과율(0.0–1.0), `.passed/.total`, per-case/per-assert 상세.
  - **결정적 scorer**(mock-llm에서 안정): `trace_has(prefix)`·`trace_lacks(prefix)`(trace 노드 =
    스펙 085/100 관측 재사용 — broker_invoke:kind:name 등 **행위** 신호)·`no_error()`·`output_nonempty()`·
    `output_contains(s)`. LLM 생성 텍스트는 비결정이라 **행위(trace)·구조 신호를 하한**으로(learning 110
    "LLM 무관 경로는 mock 결정화"의 연장). LLM-judge scorer는 후속(비결정 → 별도 축).
- `run_fn(case) -> {"output": str, "trace_nodes": list[str], "error": bool}` — 실행 어댑터. 기본 제공 =
  **HTTP 채팅 러너**(생성된 에이전트에 채팅 1턴, trace 노드·출력 수집; verify_110/117 관통 패턴 재사용).
  자율 루프는 이 러너 + 데이터셋만 갈아끼워 재사용.

## 검증 (2런)

- **하네스 자체 단위**: `run_eval`이 통과/실패 case를 정확히 집계(score 산술)·per-assert 상세·빈 데이터셋 경계.
- **관통(HTTP + 실 채팅, mock-llm)**: 능력 1개 조율형 → `trace_has("broker_invoke:")` 통과, 무능력 조율형 →
  `trace_lacks` 통과. **판별력 실측** = 일부러 틀린 assertion을 넣은 case는 score를 내려 숫자가 **움직임**
  (통과만 초록인 하네스는 판별 못 함 — 실패도 정확히 수치에 반영돼야 자율 루프의 신호가 됨).
- **적대(codex rung 3)**: score 산술 오류·항상-통과(판별 실패)·비결정 혼입·run_fn 예외 전파 등 여집합.
- **무회귀**: verify_110/117(채팅·A2A 경로) — 하네스는 기존 EP만 소비.

## 비목표 (OUT)

- **LLM-as-judge 스코어러** — 비결정·모델 의존. 결정적 하한을 먼저; judge는 별도 비결정 축으로 후속.
- **제품화(DB 데이터셋·API·어드민 UI)** — 사용자 선택 "개발·CI 하네스". 쓸만하면 승격(백로그 씨앗).
- **성능/지연 벤치마크** — 품질(행위 정확성) 먼저. Langfuse가 지연은 이미 관측.
- **회귀 골든셋 대량 큐레이션** — 하네스 틀 먼저, 케이스 축적은 사용 중 점증.

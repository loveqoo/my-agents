# 290 — 파이프라인 도구 루프 상한 + 우아한 마무리 (스펙 315)

## 무엇을 했나
`plan-execute-demo`에 "스트리밍 UI 최신 동향을 검색해줘"가 오래 멈추고 답이 이상하던 걸 고쳤다.
실측하니 **실행 노드가 wiki_search/wiki_page를 14회 반복**(수렴 실패)하다 모델 서버가 연결을 끊어
답이 깨졌다. 실행 노드 ReAct 루프에 상한(`_TOOL_ROUNDS_CAP=6`)을 두고, 상한 도달 시 도구를 떼고
(unbound) "지금까지 찾은 것으로 답하라" 유도해 우아하게 마무리한다. 결과: 180초+/연결끊김 → **27초
정상 완료**(도구 6회·끊김 0).

## 배운 것 / 복리 포인트

- **사용자 보고를 "그 컴포넌트"에 액면 매핑하지 말고 실제 재현 경로를 확인하라 — "인스펙터 느림"의
  진짜 증상은 다른 에이전트의 도구 루프였다**. 앞 턴(스펙 314)에서 "인스펙터가 느리다"를 memory.add로
  진단·수정했는데, 사용자가 실제로 겪은 건 `plan-execute-demo`(세션 메모리 → 314 경로 안 탐)의 루프
  러너웨이였다. 사용자는 이 멈춤 때문에 "314가 아직 안 됐다"고 판단했다. **한 증상어("느리다")가 서로
  다른 두 원인(장기메모리 저장 차단 + 파이프라인 루프)을 가리킬 수 있다 — 어느 에이전트·어느 경로에서
  겪는지 재현으로 확정해야 엉뚱한 곳을 고치지 않는다.** → [[measure-real-bottleneck-not-symptom-component]] [[probe-deeper-before-concluding]]

- **인프라부터 ping, 그다음 코드로 좁힌다 — 그리고 trace가 좁히는 렌즈**. 모델 서버(:8045)가 살아있고
  즉답함을 먼저 확인(0.011s)해 "모델 죽음" 가설을 배제한 뒤, trace의 `graph`(노드열)+`mcp calls`로
  실행 노드가 14회 도는 걸 한눈에 봤다. trace가 "어디서 멈추나"를 노드·도구 단위로 드러내 근인을
  루프로 정확히 좁혔다. → [[ping-infra-before-blame]] 계보(239) · [[playground-is-precision-debug-channel]]

- **ReAct 루프엔 상한이 필요하다 — 개방형 질의는 수렴 못 한다. 상한=도구를 떼어 강제 수렴**. "최신
  동향"처럼 위키가 못 답하는 질의는 모델이 만족스런 근거를 못 찾아 무한 재검색한다. LangGraph 기본
  recursion_limit(25)에만 의존하면 러너웨이 → 컨텍스트 폭증 → 모델 서버 연결 끊김. 처방=라운드 상한
  도달 시 **도구를 바인딩 해제**(unbound)하면 tool_calls를 못 내 루프가 끝나고, 넛지로 "찾은 것으로
  정직히 답하라"를 유도. **에러/끊김 대신 정직한 답으로 마무리하는 게 우아함.** 라운드는 상태 스키마
  변경 없이 메시지 꼬리 스캔(`[AI(tool_calls)←ToolMessage]*` 구간, tool_calls 없는 AI가 노드 경계).

- **가정을 코드로 방어하라 — 캡의 안전이 provider 선의에 기대면 안 됨(codex P1)**. "unbound면
  tool_calls를 안 낸다"는 strict provider엔 맞지만 느슨한/커스텀 provider엔 보장 없다. 그런 provider가
  unbound인데도 tool_calls를 내면 `_route`가 다시 루프로 보내 캡을 넘긴다. → `_force_final_if_capped`로
  캡 응답의 tool_calls를 **떼어** 강제 종료(본문 비면 정직 폴백). **불변식("루프는 상한에서 끝난다")을
  provider 동작이 아니라 코드로 성립시켜라.** → [[gate-on-intent-value-not-mutable-baseline]] [[installed-guard-isnt-covering-guard]] [[use-codex-for-adversarial-verification]]

- **사용자 지적은 관찰이 맞아도 원인은 아닐 수 있다 — 존중하되 실측으로 분리**. 사용자가 "wiki로
  찾으라면서 도구를 안 붙였다"고 지적했고, 실제로 **계획 노드**는 프롬프트에 wiki_search를 언급하나
  tools=[]다(맞는 관찰). 하지만 계획 노드는 실행이 아니라 계획만 세우는 노드라 도구가 불필요하고,
  실제 실행 노드엔 도구가 붙어 14회 호출됐다(멈춤의 원인은 도구 미추가가 아니라 루프). 관찰을 확인·
  인정하되, 원인은 trace로 독립 분리. → [[probe-deeper-before-concluding]]

## 검증 (사다리)
- **단위(결정적)**: `tests/verify_315_tool_loop_cap.py` VERIFY315_OK — 항상 tool_call 내는 모델도 도구
  6회 상한(T1)·상한 후 에러 없이 최종 답(T2)·조기 수렴 무회귀(T3)·**rogue unbound(계속 tool_calls)도
  종료(T4, codex P1)**. mock 모델 주입(`_model_from_node` 몽키패치)으로 실 35B 없이 결정적.
- **실 인프라**: plan-execute-demo 같은 질의 → 27초 정상 완료(도구 6회·끊김 0·답 스트림).
- **적대(codex)**: P0 0·P1 1(캡 airtight) 수정·경계 1(병렬 tool_calls 실행총량, 라운드 기준이라 수용).
  ruff/mypy 클린·파이프라인 회귀(259/260/265/268) 무회귀.

## 남은 것 / 주의
- **OUT**: 그래프 recursion_limit 백스톱(노드 캡이 수렴 강제라 불필요)·모델 끊김 자체 재시도(캡으로
  근인 해소)·계획 노드 프롬프트-도구 표기 정합(데모 seed, 무해)·캡 per-node 커스터마이즈(YAGNI).
- 캡=라운드(모델 턴) 기준. 병렬 tool_calls면 도구 실행 총량은 ~6×N(라운드당 도구 수)이나, 비싼
  모델 생성이 캡되므로 멈춤은 해소. 필요 시 실행 총량 캡은 후속.
- 스펙 314와 별개 원인(파이프라인 루프) — 사용자가 314 미완으로 오인한 실체.

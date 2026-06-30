# 069 — 커스텀 에이전트 런타임 인터페이스(in-process SDK) — 스펙 085

## 무엇을 했나

`source` 문자열로만 갈리던 에이전트에 공통 in-process 인터페이스(`CustomAgent` Protocol +
`AgentBuildContext`)를 들였다. 적합 그래프는 무엇이든 플랫폼이 `astream` 루프를 소유해 오버라이드
주입·실 LangGraph 호출 스택 추적을 1급으로 받고, 미구현(원격 code/external)은 `resolve_agent_runtime`
이 None을 돌려 기존 `_a2a_stream` 불투명 fallback으로 "지금처럼" 동작한다. 레퍼런스 2구현
(`DefaultUiAgent`=create_agent 래핑, `examples/plan_execute`=손수 만든 plan→execute 2노드)으로
인터페이스가 create_agent에 과적합되지 않았음을 *측정*했다(learning 039). 추적은 하드코딩 리스트 대신
`updates` 스트림의 실 노드열에서 파생(`_timeline_from_nodes`).

## 무엇이 잘 됐나

- **둘째 구현이 측정 도구로 작동.** plan_execute(다노드 직렬)가 ui(단일 노드)와 같은 루프로 스트림되고
  같은 ctx 주입·실 노드 타임라인을 받는 걸 통합 테스트(H3)와 브라우저(DOM에 `[__start__,plan,execute,
  __end__]`)로 동시에 확인. "추상화가 누수 없다"가 직감이 아니라 측정이 됐다(learning 039 그대로).
- **fallback 게이트를 단일 술어로 수렴하되 원격 경로는 손대지 않음.** learning 060(폐기경로 행동
  차집합)을 지켜 `_a2a_stream`을 보존, 원격 디스패치 None을 통합에서 재확인(H4).
- **검증 사다리 3런 + 회귀 가드가 안 겹침.** 단위(신뢰-로딩 eval 경로 없음)·통합(실 노드 타임라인)·
  브라우저(실 4노드 vs fallback)·codex 적대·verify_041 회귀 — 각자 다른 결함을 잡았다.

## 무엇이 어긋났나 (codex 적대 리뷰 F1–F4)

핵심 패턴 하나로 묶인다: **새 필드(`impl`, `overrides`)를 인터페이스에 더했는데 일부 입구만 그걸
다뤘다 — 나머지 입구는 happy-path 초록인 채로 그 필드를 silent하게 떨어뜨리거나 죽은 계약으로 뒀다.**

- **F1 (impl silent drop).** `update_agent`(PUT)가 `body.config.model_dump()`로 draft를 통째 교체 →
  SPA 편집 폼이 `impl`을 안 보내면 Pydantic 기본 None이 덮어써, 편집→활성화가 커스텀을 DefaultUiAgent로
  silent 되돌렸다. **내가 처음 "편집 폼은 영향 없음"으로 넘긴 게 오판**(probe-deeper 위반: 단정 전 한
  겹 더 안 봄). 코덱스가 짚었다. 수정: `model_fields_set`에 impl 없으면 편집 베이스의 impl 이어받기 +
  verify_085 H5 회귀 가드.
- **F4 (dead overrides 계약).** `AgentBuildContext.overrides`를 설계해놓고 `_load_context`가 ctx에 안
  실어 항상 None — *설계는 했으나 배선 안 한 죽은 계약*. happy-path는 누구도 overrides를 안 읽으니 초록.
  수정: ctx["overrides"] 적재 + 3개 build 사이트 배선.
- **F2 (resume config drift).** approval이 만든 checkpoint topology와 그 사이 바뀐 impl이 어긋나면 stale
  resume이 깨진다. HIL 미지원 런타임 거부 가드 + 잔여경계(impl-A→B 교체) 문서화(후속 스펙).
- **F3 (병렬 추적 순서).** 관측 순서 ≠ 호출 스택 순서. 현 직렬 구현엔 미발생, docstring 정직 표기.

## 배운 것 → learning 088

새 필드를 인터페이스/컨텍스트에 더하면 **읽기·쓰기·빌드 입구를 닫힌 집합으로 세고 각각이 그 필드를
다루는지 단언**해야 한다. full-replace 직렬화(`model_dump`)는 미전송 필드를 silent drop하고, ctx에 안
실린 dataclass 필드는 dead contract다 — 둘 다 그 필드가 *새것*이라 아무도 아직 단언하지 않으니
happy-path가 초록이다. 적대자(codex)에게 "보장 목록의 여집합"을 시켜 둘 다 잡았다(learning 023·086 공명).
회귀는 그 필드가 모든 입구를 통과해 살아남는지 단언하는 테스트로 박는다(H5 = 편집→활성화 후 impl·
타임라인 보존).

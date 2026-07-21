# 382 — dict→typed DTO 대변환: mypy가 소스 완전성 그물이나 tests는 그 밖

## 맥락

캠페인 374 Tier2 ②. `_load_context`의 ctx dict(36키)를 `ChatContext` dataclass로 전면 교체 —
채팅 핫 경로 7파일·~211 접근 사이트. 개발자 선택=전면 DTO(TypedDict 아님, whole-fix). 동작 불변 착지.

## 교훈

- **mypy가 소스 변환의 완전성 그물이다(비-strict라도).** dict→dataclass면 남은 `ctx["x"]`는
  "ChatContext is not indexable", 오타 attr은 "has no attribute"로 **전수 포착**. 변환 후 목표=
  `make typecheck`가 **사전 베이스라인 외 0**. 손으로 "다 바꿨나" 세지 말고 mypy 에러 목록을
  체크리스트로 쓴다(누락=측정). TypedDict 키 접근도 비-strict에서 검사되므로, 이 게이트 유무가
  DTO/TypedDict 선택의 **전제 검증**이었다(게이트 없으면 타입화가 값 0 — verify-premise).
- **그러나 mypy는 tests를 안 본다(PY_SRC=packages만).** tests의 ctx 소비는 소스가 초록이어도
  **런타임에 깨진다**(dict 만들어 이제-타입함수에 넘김·`.get`/subscript). SUITE + 관련 테스트 직접
  실행이 그 층의 유일한 그물. **큰 계약 변경은 소스 그물(mypy)과 테스트 그물(SUITE/직접실행)이
  안 겹친다** — 둘 다 돌려야 한다.
- **blast radius는 한 패턴으로 못 잰다.** 첫 정규식 `ctx\["[a-z_]+"\]`가 **camelCase**(`toolPolicy`)·
  **단일따옴표 f-string**(`ctx['session_id']`)·**다른 변수명**(`ctx_re`·`ctx_ap`·`ctx_resume`)을 놓쳐
  3차례 재측정했다. 계량은 여러 패턴 교차로, 최종 확인은 실행(mypy+SUITE)으로.
- **항상 있는 필드는 Optional-None이 아니라 required로.** `agent_pk: uuid.UUID`는 zero-default가
  없어 `| None = None`으로 두면 타입된 호출부(`_load_session_conversation(agent_pk: UUID)`)에서
  mypy 노이즈. **유일한 required 필드로 선언 첫머리**에 두면(나머지 전부 default) 정직하고 노이즈 0.
- **증분 mutation 대신 단일 생성.** dict를 `ctx[k]=`로 15번 채우던 걸, 값을 지역변수로 계산 후
  `ChatContext(...)` **한 번**에 구성. 부분 ctx를 읽던 헬퍼(`_resolve_nodes_for_ctx`)는 ctx 대신
  **직접 인자**(nodes·model_cfg)로 리팩터 → 증분 상태 의존 소멸. 수령 후 변형(chat_approval의
  session_pk)만 mutable(frozen 금지)로 허용.
- **격리 대조가 회귀 판정과 격리 축소를 동시에 준다.** SUITE 실패 3건을 stash로 원본 대조→전부
  사전 결함(내 회귀 아님) 확증. 그중 verify_049는 격리 사유가 정확히 이번에 곁들여 고친 드리프트
  (`_create_approval user_id`)라 **KNOWN_DRIFT에서 해제**(격리 집합 −1=명시 목표). 사전-broken
  테스트라도 그 안의 옛 `ctx["x"]` 소스검사·subscript는 **landmine 제거차 갱신**(나중에 그 테스트가
  고쳐질 때 내 stale 문자열에 다시 걸리지 않게).

[mypy-is-source-completeness-net, tests-outside-typecheck-need-runtime-net,
blast-radius-needs-multiple-patterns, always-present-field-required-not-optional,
single-construction-over-incremental-mutation, quarantine-diff-judges-regression-and-shrinks-set]

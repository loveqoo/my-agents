# 270 — 에이전트 flow 중복 제거 (스펙 295)

## 무엇을 했나

사용자가 "지금 찾은 것부터 개선"을 지시. agent 패키지의 복붙 중복 2종을 정본화:
- **모델 빌더**: `ChatOpenAI(...)` 구성 블록이 route·orchestrate·plan_execute(**바이트 동일**) +
  main·artifact·pipeline(변형 3) = **6곳** 복제 → `agent/model.py`의 `build_chat_openai`로 단일화.
  차이(cfg 출처·미설정 raise/none·기본 temp 0.7/0.2·에러 문구)만 인자로 파라미터화. `@overload`로
  raise 변형은 `ChatOpenAI`, none 변형은 `ChatOpenAI | None` 반환 타입 정확 분기.
- **`_last_user_text`**: route·orchestrate 동일·artifact는 role 필터 변형 = 3곳 → `toolbox.last_user_text
  (state, roles=None)`로 단일화. `roles=None`이 무필터(route/orchestrate), `("human","user",None)`이
  artifact 필터 — 각 사이트 행위 정확 보존.

수치: model.py 외 `ChatOpenAI(` 0·로컬 def(`_model_from_cfg`/`_make_model`/`_last_user_text`) 0·
`make metrics-fast` 전판·관련 verify(041·076·085·099·102·259·260·261·268·270) + 스위트 51/51·codex 4축 SAFE.

## 잘된 것

- **사용자가 내 "0"을 반증한 게 이번 작업의 씨앗이었다.** 스펙 294 후 "전수조사=0"이라 했는데, 그건
  패턴을 "조립 누출"로 **좁게** 정의한 결과였다. 사용자가 직접 agent 코드서 `_model_from_cfg` 복붙을
  집어내자, 정의를 "복붙/공통화 여지"로 넓혀 재조사→B 8건. **"0"은 렌즈의 함수지 사실이 아니다** —
  전수의 완결성은 패턴 정의의 넓이에 달렸다. [[probe-deeper-before-concluding]]의 코드베이스판.
- **중복의 자백을 증거로 썼다.** 도크스트링이 "plan_execute와 동일 규칙"·"route/plan_execute와 동일"로
  서로를 가리키고 있었다 — 코드 공유 대신 주석 상호참조 = 복붙의 화석. diff로 바이트 동일 확증(268
  교훈: 판별자는 시그니처 아닌 **본문**).
- **테스트 시임이 또 진짜 블래스트였다(294 교훈 재현).** verify_076이 `main.ChatOpenAI`를 몽키패치,
  4개 pipeline 테스트(260·261·268·270)가 `_model_from_node`를 몽키패치. 전자는 정본(`model.ChatOpenAI`)
  으로 패치점 이동(오히려 단일 시임으로 개선), 후자는 **`_model_from_node`를 얇은 어댑터로 존치** —
  구성 블록(중복)은 빼 `build_chat_openai`에 위임하고 노드 cfg 폴백+시임만 남겼다. **중복(본문)은
  없애되 고유 글루/시임은 보존**이 판단.
- **파라미터화가 억지 통합을 막았다.** 6곳을 하나로 합치되 강제 통일이 아니라 차이를 인자로 노출
  (on_missing·default_temperature·error_label·roles). 억지 상속이 아닌 **정직한 공통화** —
  route/pipeline/plan_execute의 그래프 위상은 여전히 각자(공통 베이스 OUT, 268 교훈 유지).

## 배운 것

- **전수조사의 신뢰도는 패턴 정의의 넓이가 좌우한다.** "이 패턴 0건"이 참이어도 "중복 0건"은 거짓일
  수 있다 — 정의를 좁히면 진짜 문제가 정의 밖으로 샌다. 감사(audit)는 **정의를 먼저 넓게** 잡고
  좁혀야지, 좁게 잡고 "없다"면 사용자가 반례를 든다.
- **몽키패치 시임은 리팩터의 숨은 계약이다.** 헬퍼를 지우기 전 "이걸 테스트가 패치하나"를 grep해야
  한다(learning 153의 keyword-only 계약과 동류 — 이름이 외부 계약). 시임이면 얇은 위임 어댑터로 남겨
  본문 중복만 제거.
- **정본화는 패치점도 하나로 만든다.** 흩어진 `ChatOpenAI` 구성을 `model.py`로 모으니 테스트가
  6곳 대신 `model.ChatOpenAI` 한 곳만 스텁하면 된다(부수 이득: 시임 단일화).

## 다음에 적용

- 남은 B(스펙 296 후보): api A2A 프레이밍 3중(mock_remote↔a2a_server)·get-or-404 인라인 36곳·
  `_card_streaming`·`_assert_valid_name`·`_non_blank`. authz `_own_scope`/`_is_admin`은 저자 의도(라우터
  독립)라 설계 판단+적대 검증 별도. eval_* 계열은 미전수(추가 조사 가치).
- 새 flow 추가 시 모델은 `build_chat_openai`, 사용자 텍스트는 `last_user_text` 재사용(복붙 금지).
- 낡은 verify(190 langgraph config 시그니처)는 pristine HEAD 동일 실패 — 스펙 295 무관, 백로그.

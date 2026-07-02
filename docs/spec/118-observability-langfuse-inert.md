# 118 — 관측·측정 계층 (Langfuse, inert-until-configured)

## 배경 / 왜

기술 스택 문서엔 "Metric: Langfuse"가 있으나 **코드엔 0줄**이었다(방향 2 스캔에서 확인). 수치 기반
관측은 사용자가 원하는 **자율(목표 주고 무한 반복, Ralph)**의 전제 — 측정 없이는 "좋아졌나"를 자동
판정할 수 없다. 방향 2(4개 방향 "모두 차례대로") 2번.

## 설계 — inert-until-configured (사용자 선택)

관측은 **부가물이지 하중이 아니다** — 켜져 있든 없든 핵심 채팅 경로가 관측 때문에 깨지면 안 된다.
그래서 **설정될 때만 켜진다**:

- `observability.py` 단일 모듈. `is_configured()` = `LANGFUSE_PUBLIC_KEY`·`LANGFUSE_SECRET_KEY`가 **둘 다**
  env에 있을 때만 True(키는 읽되 **값은 코드/로그/응답에 절대 안 남김** — 외부 비밀).
- `trace_callbacks()` — 미설정이면 **[]**(inert). 설정+핸들러 가용이면 `[LangchainCallbackHandler]`.
  패키지 미설치·핸들러 생성 실패는 **예외 없이 []**(graceful). langfuse v3(`langfuse.langchain`)
  우선·v2(`langfuse.callback`) 폴백.
- `with_trace(config, *, name, session_id, user_id, metadata)` — 실행 config에 콜백·메타를 **병합**(기존
  callbacks/metadata/configurable 덮지 않고 확장, 미설정이면 원본 그대로). session_id/user_id는 Langfuse
  표준 키(`langfuse_session_id`/`langfuse_user_id`)로 실어 trace를 묶는다.
- 배선 3곳(chat.py): 메인 채팅(astream, config에 thread_id 보존)·재개(ainvoke, approval.user_id)·로컬
  A2A 서빙(checkpointer=None이라 thread_id 불요, 콜백만). **키가 스위치** — langfuse는 의존성으로 설치돼
  있고, 키를 넣는 순간 활성(사용자 선택).

기존 관측(스펙 085/086/100 — trace 이벤트·broker_invoke 노드)은 그대로. Langfuse는 그 위 **외부 집계**
계층으로, 평가 하네스(방향 3)가 얹힐 토대.

## 검증 (2런)

- **단위**: inert(키 없음→[])·설정 게이트(양쪽 키 필요)·config 병합(기존 callbacks/metadata/configurable
  보존·확장)·graceful(핸들러 None→[])·실 langfuse 팩토리 핸들러 생성·env 스코프.
- **통합(전달 관통)**: 콜백이 실제 LangGraph astream에 전달돼 이벤트를 수신(Recorder 콜백)·미설정 실행은
  콜백 미수신·정상 실행(무회귀). verify_100/110/117(채팅·A2A 경로) 무회귀(Langfuse inert 상태).
- **적대(codex rung 3)**: P0/P1 없음(inert·비밀 미노출·graceful·thread_id 보존 확인). [P2] `with_trace`가
  기존 callbacks를 list로만 가정(None·CallbackManager면 TypeError) → 타입별로 접어 절대 안 던지게 방어
  + U4b 회귀가드(현 배선 3곳은 callbacks 미주입이라 미재현이나 헬퍼 보장 범위 봉합).

## 비목표 (OUT)

- 실 Langfuse 서버로의 실제 전송 검증 — CI에 외부 서비스/비밀 불포함(사용자가 키 넣어 실환경서 확인).
- 커스텀 span/score 수동 계측 — 이번엔 LangChain 콜백 자동 계측(그래프 노드·LLM 호출)까지. 수동 score는
  평가 하네스(방향 3)에서.
- 메트릭 대시보드/알림 — Langfuse UI가 제공. 여기선 데이터 내보내기까지.
- OpenTelemetry 범용 백엔드 — 사용자가 Langfuse 방식 선택(추후 필요 시 별개).

# 076 — create_react_agent → langchain.agents.create_agent 마이그레이션 (이슈 3)

## 배경

`packages/agent/src/agent/main.py:60`의 `create_react_agent`가 **deprecated**다. 설치 패키지로 실측:
langgraph 1.2.5의 `create_react_agent`는 `@deprecated`이며 메시지가 정확히
*"create_react_agent has been moved to `langchain.agents`. use `from langchain.agents import create_agent`"*.

## 웹 검증 (추측 금지 — 공식 문서 확인)

- `create_agent(model=, tools=, **system_prompt=**, checkpointer=, …)` — persona 파라미터가
  `prompt`→**`system_prompt`**로 개명. model/tools/checkpointer는 동일. (docs.langchain.com/oss/python/langchain/agents)
- **유일한 breaking은 "동적 prompt(콜러블)" 제거** — 콜러블 prompt는 middleware(`@dynamic_prompt`)로 이동.
  우리는 **정적 문자열 persona**를 넘기므로 `system_prompt=persona`로 1:1 대응, 영향 없음.
- 반환물은 동일한 컴파일된 LangGraph 그래프 → `.invoke` / `.astream(stream_mode=...)` /
  `.ainvoke(Command(resume=))` / `__interrupt__` 계약 보존. **가정 말고 회귀로 증명**.
- `langchain` 메타 패키지는 **미설치**(langchain_core만) → `packages/agent`에 `langchain` 의존성 추가 필요.

## 목표 (완료 조건 — 측정 가능)

import·호출이 `langchain.agents.create_agent`로 전환되고 DeprecationWarning 소거. 호출계약 4종 보존:
verify_041 G1-G7 전부 PASS(interrupt/resume/checkpointer 배선) + `.invoke`·`.astream("messages")` 스모크 PASS.

## 조치

1. `packages/agent/pyproject.toml`에 `langchain>=1.0` 의존성 추가 + `uv sync`.
2. `main.py`:
   - `from langgraph.prebuilt import create_react_agent` → `from langchain.agents import create_agent`
   - `create_react_agent(model, tools=tools or [], prompt=persona, checkpointer=checkpointer)`
     → `create_agent(model=model, tools=tools or [], system_prompt=persona, checkpointer=checkpointer)`

## 검증

- `tests/verify_041_hil_approval_gating.py`(API 서버 :8000 전제) — G1-G7 PASS = interrupt/resume/
  checkpointer 배선 무회귀(가장 강한 계약 테스트).
- 스모크(신규 `tests/verify_076_create_agent_contracts.py`): build_agent로 `.invoke({"messages"})` 응답 +
  `.astream(stream_mode="messages")` 토큰 스트림 + DeprecationWarning 부재 단언.

## RBAC 체크리스트 적용 여부

**관련 없음** — 런타임 빌더 교체. 소유권/테넌시 경계 무관(유저 데이터 입구 불변).

## 완료 체크
- [x] langchain>=1.0 의존성 추가 + uv sync(langchain 1.3.11 설치)
- [x] main.py import·호출 전환(`create_agent(system_prompt=persona)`)
- [x] verify_041 G1-G7 PASS(deprecation 0) — interrupt/resume/checkpointer 배선 무회귀
- [x] verify_076 스모크 C1 invoke·C2 astream messages·C3 no-deprecation PASS
- [x] 잔여 정리: chat.py·mock_remote.py 주석 갱신, verify_041 테스트 헬퍼도 create_agent로 전환

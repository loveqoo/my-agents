# 003 — 페르소나 등록 + chat 노출 루프 회고

날짜: 2026-06-19
지배 스펙: [docs/spec/002-persona-registry-and-chat.md](../../docs/spec/002-persona-registry-and-chat.md)

## 루프 개요
- **목표:** 하드코딩 페르소나를 REST로 등록·저장(Postgres)하고, FastAPI chat(SSE)으로 외부 노출. (MCP·메모리는 제외)
- **단계 흐름:**
  - 1 Scaffolding — `packages/api`(FastAPI) 신규, `agent` 파라미터화, docker-compose(Postgres)
  - 2 Context — 결정 질문 라운드(저장=Postgres, 노출=FastAPI chat, 등록=REST)
  - 3 Planning — `docs/spec/002`(AI 초안 → 인간 검토 → 승인)
  - 4 Execution — agents CRUD + `/chat` SSE, SQLAlchemy(async)+asyncpg
  - 5 Verification — codex 비판 리뷰(P1 1, P2 4) → 5건 수정 + thinking 이슈 수정 → 재검증
  - 6 Compounding — 본 회고 + 학습 005/006 + CLAUDE.md 갱신

## 무엇이 잘못됐나 / 배운 것
- **SSE 원문 보간(P1):** 모델 토큰의 개행이 SSE 프레임을 깸. → JSON 인코딩(`data: {"text": ...}`).
- **Qwen thinking 폭증:** 스트리밍에서 content 누락. → `enable_thinking=False`. → [[006]]
- **입력 검증 부재(P2):** role 임의 허용, params 미검증. → `Literal`/`AgentParams`로 422.
- **세션 점유(P2):** 스트리밍 동안 DB 세션 유지. → persona/params만 읽고 세션 조기 해제.
- **DB 노출(P2):** Postgres 전 인터페이스 바인드. → `127.0.0.1:5432`.
- **런타임 가정:** docker는 선점검했으나 Docker Desktop이 아니라 **OrbStack**이었음 → `open -a OrbStack`.

## 잘된 것
- **블로커 선점검**(docker, [[002]]의 교훈 적용)으로 실행 중 멈춤 최소화.
- **타자 비판 검증**(codex)이 SSE 프레이밍 P1을 잡음 — 자가검증으로는 놓쳤을 것.
- **사실 확인 후 결정:** LangGraph A2A/MCP 엔드포인트·MLX OpenAI 호환을 근거로 스펙 확정.
- 페르소나가 응답에 실제 반영됨(해적/하이쿠)로 끝-끝 검증.

## 다음에 다르게 할 것
- 스트리밍/노출 기능은 **긴 출력·추론 모델 케이스로도** 검증(짧은 답만으로 통과시키지 말 것).
- `create_react_agent` deprecation → `langchain.agents.create_agent` 이전 검토(spec 002 §9).

## 관련 기록
- [[005]] docs 스펙은 AI 초안 + 인간 검토
- [[006]] Qwen(MLX) thinking 비활성
- 이전 회고: [002-agent-service-initial-build](./002-agent-service-initial-build.md)

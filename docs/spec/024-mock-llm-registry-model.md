# 024 — Mock LLM을 레지스트리 1급 모델로 등록

상태: **실행 완료 + 타자 검증(codex GATE: PASS)** — main 머지만 대기(사용자 직접 테스트)
날짜: 2026-06-25
브랜치: `feat/agent-service` — **main 머지 금지**(사용자 직접 테스트)
연동: [008 모델 레지스트리](./008-model-registry.md), [009 코드 에이전트 원격 실행](./009-code-agent-remote-exec.md),
[[012-runtime-config-single-source]], [[025-seed-mock-drift-needs-migration-and-shared-constant]]

## 배경 / 문제

라이브 MLX(`localhost:8045`) 없이도 에이전트를 **결정적으로** 돌릴 수단이 없다. 현재 mock은
산발적이다 — `mock_remote.py`의 `/_remote/agent`(코드 에이전트 SSE 더블, 스펙 009)와
`/_remote/models`·`/_remote/embeddings`(연결 테스트 더블)뿐이고, **일반 chat 런타임 경로
(`build_agent` → `ChatOpenAI`)가 칠 OpenAI 호환 chat completions 엔드포인트가 없다.**

`build_agent`(`packages/agent/src/agent/main.py`)는 `ChatOpenAI(base_url, model=model_id)`로
`{base_url}/chat/completions`를 호출하며, 모델은 **항상 레지스트리 `model_cfg`에서만** 온다
(learning 012 — env·특수분기 없음). 따라서 mock도 **레지스트리 ModelConfig**로 들어가야
일관된다.

## 결정 (사용자 확인)

- **mock을 레지스트리 1급 chat 모델로 등록**하고, 런타임은 일반 경로로 그걸 쓴다
  (`build_agent` 수정 없음 = 012의 "런타임은 레지스트리만, 특수분기 없음" 유지).
- **스코프: chat 머스 모델만.** 임베딩/메모리(mem0)는 기존 경로 유지(`multilingual-e5-large`).
- **기본값 아님(`is_default=False`).** 실 MLX(`qwen3.6-35b`)가 기본. mock은 에이전트가
  **명시 선택**해야 발동 — 기본으로 두면 모든 폴백이 mock으로 가 위험(012).

## 변경

1. **`packages/api/src/api/mock_remote.py`** — OpenAI 호환 chat completions 추가:
   - `POST /_remote/v1/chat/completions` — body `{model, messages, stream, temperature, ...}`.
     마지막 user 메시지 기반 **결정적 응답**(echo형, `/_remote/agent`와 동일 톤).
   - **비스트리밍**: `{id, object:"chat.completion", choices:[{index:0,
     message:{role:"assistant", content}, finish_reason:"stop"}], usage:{...}}`.
   - **스트리밍**(`stream:true`): `data: {object:"chat.completion.chunk",
     choices:[{delta:{content:...}}]}` 프레임들 + `finish_reason:"stop"` + `data: [DONE]`
     (langgraph `astream(stream_mode="messages")` → `ChatOpenAI` 스트리밍 계약).
   - **툴 무시**(tool_calls 미반환) → 툴 가진 에이전트도 `create_react_agent`가 1턴에 종료.
     알려진 한계로 명시.
   - `/_remote/models`에 `mock-chat` 노출 유지(연결 테스트 list 계약).
2. **`packages/api/src/api/seed.py`** — `mock-llm` chat ModelConfig 시드:
   - `name="mock-llm"`, `provider="openai-compatible"`,
     `base_url=MOCK_LLM_BASE_URL`(기본 `http://127.0.0.1:8000/_remote/v1` — **이 API 자신의**
     self-주소, env 오버라이드 가능. 코드 에이전트 배포를 가리키는 `REMOTE_AGENT_BASE`와는 의미가
     다른 별개 env, P2-1 참조), `model_id="mock-chat"`, `kind="chat"`,
     `is_default=False`, `params={}`. api_key는 암호화된 `sk-noauth`(mock은 인증 미검증).
3. **신규 Alembic 데이터 마이그레이션** (down_revision = `e3f4a5b6c7d8`) — 이미 시드된 라이브
   DB에도 `mock-llm` 행을 **멱등 삽입**(이름 존재 시 skip). `is_default` 손대지 않음.
   다운그레이드: `mock-llm` 행 삭제(가역). (025: 소스 수정만으론 라이브가 안 고쳐짐 → 마이그레이션 병행.)
4. **Admin UI** — 변경 없음. `listModels('chat')`이 자동으로 `mock-llm`을 반환 →
   AgentsView 모델 드롭다운에 선택지로 노출(스펙 023의 데이터 기반 옵션 경로 그대로).

## 비범위

- mock 임베딩 모델 등록(스코프 chat-only). 메모리는 실 임베딩 경로 유지.
- mock의 툴 호출(function calling) 지원 — 평문 응답만.
- `/_remote/agent`(코드 에이전트 더블) 제거/통합 — 별개 경로라 그대로 둠.

## 검증

1. mock-llm 시드/마이그레이션 후 GET /models → `mock-llm`(chat, 기본 아님) 등장.
2. 에이전트 model을 `mock-llm`로 두고 `POST /agents/{id}/chat` → **MLX 없이** 결정적 mock
   응답 스트리밍, 세션/메시지/트레이스 영속. (실측: MLX 끄거나 무관하게 동작.)
3. 모델 연결 테스트(probe)로 `mock-llm` 통과.
4. 실 MLX 에이전트(`qwen3.6-35b`) 회귀 없음 — mock이 기본 아님 확인.
5. 타자 검증(codex)으로 chat completions 계약(스트리밍/비스트리밍 포맷)·마이그레이션 비판 리뷰.

## 타자 검증 (codex, GATE: PASS)

핵심 계약 전부 통과로 판정:
- 스트리밍/비스트리밍 chat completions 포맷이 `langchain_openai.ChatOpenAI`와 호환.
- 툴 미반환 → `create_react_agent`가 툴 호출 없이 1턴 종료(무한 루프 없음).
- 평문 `sk-noauth`가 `crypto.decrypt` 레거시 평문 관용 + `build_agent` 폴백으로 안전.
- `is_default=False`라 폴백이 mock으로 새지 않음([012] 준수).

**P2 2건 — 정책상 수용 + 문서화로 처리:**
- **P2-1** (env 일관성): codex는 `MOCK_LLM_BASE_URL`을 `REMOTE_AGENT_BASE`에서 파생 제안.
  그러나 둘은 **의미가 다르다** — `REMOTE_AGENT_BASE`는 *코드 에이전트의(운영 시 외부) 배포
  URL*(009), `MOCK_LLM_BASE_URL`은 *이 API 자신의 mock 엔드포인트 self-주소*. 결합하면 운영
  배포(외부 코드 에이전트)에서 mock base가 잘못 파생된다. → **별도 env 유지**, seed.py·마이그
  레이션·본 스펙에 의미 차이를 주석/문서화. (mock은 dev-only 편의라 기본 `127.0.0.1:8000`로 충분.)
- **P2-2** (downgrade 비대칭): upgrade는 존재 시 멱등 skip하나 downgrade는 무조건 삭제 →
  외부 선삽입 행도 삭제됨. **`mock-llm` 이름은 seed/마이그레이션이 소유**하는 데모 데이터라는
  정책이라 수용(스펙 023 수용 스타일과 동일). 마이그레이션 downgrade 주석에 명시.

## 완료 조건

- [x] `/_remote/v1/chat/completions` 추가(스트리밍+비스트리밍, OpenAI 포맷)
- [x] `mock-llm` seed ModelConfig(기본 아님)
- [x] 마이그레이션: 라이브 DB에 `mock-llm` 멱등 삽입(가역 다운그레이드 — downgrade→0/upgrade→1 실측)
- [x] mock-llm 선택 에이전트가 MLX 없이 결정적 실행(실측: Ops 에이전트 임시 전환, `call_model` 노드 통과, latency 22ms, 복원)
- [x] 실 MLX 에이전트 회귀 없음 + probe 통과
- [x] tsc 무오류 + 타자 검증(codex GATE: PASS, P2 2건 수용·문서화)
- [ ] **main 머지 금지**(사용자 직접 테스트)

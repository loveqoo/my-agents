# 002 — 페르소나 등록 + chat 노출 (Persona Registry & Chat)

상태: **승인됨 (실행)**
날짜: 2026-06-19
지배 스펙: [001-system-overview.md](./001-system-overview.md)
이전 증분: [.dev/plan/001-minimal-hardcoded-agent.md](../../.dev/plan/001-minimal-hardcoded-agent.md)

> 코드에 하드코딩돼 있던 페르소나를 **등록·조회**하고, 등록된 에이전트를 **FastAPI chat으로 외부 노출**한다.
> MCP·메모리·모델 레지스트리는 이 증분에서 제외.

---

## 1. 목표 / 비범위

### 목표
- 페르소나를 **REST API로 등록**하고 Postgres에 저장한다.
- 등록된 에이전트를 **`POST /agents/{id}/chat`(SSE 스트리밍)** 으로 대화 노출한다.
- `packages/agent`를 **파라미터화**(persona/params 주입)하여 하드코딩을 제거한다.

### 비범위 (이 증분 제외)
- MCP(소비/노출), Mem0 메모리, 모델 레지스트리(등록·관리), A2A, Admin SPA
- 인증/멀티테넌시 (내부용 전제 유지)
- 서버측 대화 상태(체크포인터) — 대화 히스토리는 **클라이언트가 전달**
- Alembic 마이그레이션 — 스키마는 시작 시 생성

---

## 2. 결정 요약 (초안)

| 항목 | 결정 |
|---|---|
| 저장 | PostgreSQL (docker-compose) |
| 노출 | FastAPI `POST /agents/{id}/chat` (SSE) |
| 등록 | REST API (FastAPI) |
| 모델 | 모든 에이전트가 **env의 MLX 기본 모델** 사용 (레지스트리는 나중) |
| ORM | SQLAlchemy(async) + asyncpg |
| 스키마 | 시작 시 `create_all` (마이그레이션은 나중) |
| 대화 상태 | 무상태 — 클라이언트가 messages 전달 |

---

## 3. 데이터 모델

`agents` 테이블:

| 컬럼 | 타입 | 비고 |
|---|---|---|
| id | uuid (pk) | 서버 생성 |
| name | text | 표시 이름 |
| persona | text | 시스템 프롬프트 |
| params | jsonb | 예: `{"temperature": 0.7}` |
| created_at | timestamptz | 기본 now() |

---

## 4. API 계약 (초안)

| 메서드 | 경로 | 동작 |
|---|---|---|
| POST | `/agents` | 등록. body `{name, persona, params?}` → 생성된 에이전트 |
| GET | `/agents` | 목록 |
| GET | `/agents/{id}` | 단건 (없으면 404) |
| DELETE | `/agents/{id}` | 삭제 (204) |
| POST | `/agents/{id}/chat` | 대화. body `{messages: [{role, content}, ...]}` → **SSE** 토큰 스트림 |

- 수정(`PUT/PATCH`)은 추후.
- chat 응답: `text/event-stream`, 토큰 청크를 `data:` 로 흘리고 종료 이벤트로 마감.

---

## 5. 모듈 구조 (증분)

```
my-agents/
  docker-compose.yml            # 신규: Postgres
  packages/
    agent/                      # 리팩터: build_agent(persona, params) 파라미터화
    api/                        # 신규: FastAPI
      pyproject.toml
      src/api/
        main.py                 # 앱 + 라우터 + 시작 시 스키마 생성
        db.py                   # async engine/session
        models.py               # Agent 테이블
        schemas.py              # Pydantic 입출력
        agents.py               # 등록/조회/삭제 라우터
        chat.py                 # /chat SSE 라우터
```

- `packages/agent`의 `build_agent`는 `(persona, params)`를 받아 ReAct 그래프를 만든다(모델은 env MLX).
- 도메인/DB는 당분간 `packages/api`에 둔다. `packages/core` 추출은 추후.

---

## 6. 핵심 흐름

### 6.1 등록
`POST /agents {name, persona, params}` → `agents`에 insert → 생성된 레코드 반환.

### 6.2 대화 (노출)
1. `POST /agents/{id}/chat {messages}`.
2. id로 에이전트 조회(404 처리) → `build_agent(persona, params)`.
3. LangGraph `astream`(메시지 스트림 모드)로 실행, 토큰을 SSE로 흘림.
4. 모델은 env MLX, 대화 히스토리는 요청의 messages 그대로 사용(무상태).

---

## 7. 환경 / 설정
- `.env`에 `DATABASE_URL=postgresql+asyncpg://...` 추가.
- `docker-compose.yml`: Postgres 1개(로컬). pgvector는 이 증분에서 불필요(메모리 제외).

---

## 8. 검증 (완료 기준)
- [ ] `docker compose up`으로 Postgres 기동, `uv run`으로 API 기동.
- [ ] `POST /agents`로 페르소나 등록 → `GET /agents`/`GET /agents/{id}`로 확인.
- [ ] `POST /agents/{id}/chat`이 등록된 **페르소나가 반영된 응답**을 SSE로 스트리밍 (로컬 MLX 대상).
- [ ] `DELETE /agents/{id}` 후 404 확인.
- [ ] 타자 비판 검증(codex) 통과.

---

## 9. 미해결 / 추후
- 수정(PUT/PATCH) 엔드포인트
- 모델 레지스트리 연동(현재는 env MLX 고정)
- 서버측 대화 상태(LangGraph 체크포인터 → Postgres)
- Alembic 마이그레이션, `packages/core` 추출
- 인증/멀티테넌시
- `create_react_agent` → `langchain.agents.create_agent` 이전 (LangGraph V1.0 deprecation)
- Qwen thinking은 현재 `enable_thinking=False`로 끔. 추론 노출이 필요하면 별도 채널 고려.

## 관련 기록
- 지배 스펙: [001-system-overview.md](./001-system-overview.md)

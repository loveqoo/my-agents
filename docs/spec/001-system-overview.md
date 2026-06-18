# 001 — 시스템 전체 설계 (System Overview)

상태: **초안 (검토 대기)**
날짜: 2026-06-19
원본 의도: [docs/spec/CLAUDE.md](./CLAUDE.md)

> 이 문서는 제품의 **큰 그림**(비전·아키텍처·모듈 경계·도메인 모델·핵심 흐름)을 고정한다.
> 세부 기능 스펙은 002, 003… 으로 분할한다.

---

## 1. 목표 / 비범위

### 목표
- 하드코딩이 아니라 **구조 안에서 에이전트를 생성·관리**하는 서비스.
- 에이전트는 **페르소나 / 파운데이션 모델 / MCP(tools) / 메모리**로 구성된다.
- **MCP를 양방향으로** 다룬다: 외부 MCP를 가져와 에이전트에 장착 + 자체 MCP를 외부에 노출.
- 에이전트를 **A2A 프로토콜로 외부에 노출**한다.
- 메트릭/추적은 **Langfuse**로 일원화한다.

### 비범위 (이번 설계에서 명시적으로 제외)
- **인증·권한·멀티테넌시 없음.** 신뢰된 내부용 전제. (데이터 모델에 owner/tenant 개념도 두지 않는다.)
- **배포는 로컬 개발만** (`uv run` 수준). 클라우드/k8s/CI 배포는 추후 스펙.
- **외부 A2A 에이전트 소비 안 함.** A2A는 *노출만*. (외부 A2A 호출은 추후.)
- **멀티에이전트/슈퍼바이저 오케스트레이션 없음.** 단일 ReAct 에이전트.

> 모델은 *비범위가 아니다* — **사용자가 등록·관리**하는 1급 기능이다(씨앗 스펙의 Admin "파운데이션 모델 관리").
> 다만 **초기엔 쉽게 가기 위해 로컬 MLX 서버 1개를 기본 등록**해 두고 시작한다. (§2·§3 참조)

---

## 2. 결정 요약 (Locked Decisions)

| 항목 | 결정 |
|---|---|
| 인증/테넌시 | 없음 (내부용) |
| 배포 | 로컬 개발만 (`uv run`) |
| 파운데이션 모델 | **등록·관리형 모델 레지스트리** (OpenAI 호환 엔드포인트). 초기 기본 = 로컬 MLX(`mlx_lm.server`) |
| 에이전트 실행 | **단일 ReAct 에이전트** (LangGraph) |
| MCP | **양방향** — 소비(외부 가져오기) + 노출(자체 제공) |
| A2A | **노출만** (외부 소비 제외) |
| chat 응답 | **동기 + 스트리밍(SSE)** |
| 메모리 | Mem0 (에이전트 작업기억 + 유저기억) |
| DB | PostgreSQL + pgvector |
| 메트릭 | Langfuse |

---

## 3. 도메인 모델

```
Agent
 ├─ Persona          역할, 해야 할 업무, 시스템 프롬프트
 ├─ Model(ref)       등록된 Model 참조 + 파라미터(temperature 등)
 ├─ Tools            ← McpServer(소비) N개에서 가져온 툴 집합
 └─ Memory           Mem0: 에이전트 작업기억 + 유저기억

Model (등록·관리)       OpenAI 호환 엔드포인트(base_url) + 모델명 + 기본 파라미터. 초기 기본 = 로컬 MLX
McpServer (소비 대상)   등록된 외부/내부 MCP 서버 — transport(stdio|http), 주소/명령, 활성 툴
ExposedMcp (노출)        자체 툴/에이전트를 MCP로 외부 제공
A2ACard (노출)           에이전트를 A2A로 외부 제공 — agent card, skill 목록
RunTrace                 실행 추적 → Langfuse 연동 식별자
```

핵심 관계: **Agent는 N개의 McpServer를 참조**하여 툴을 구성하고, 단일 ReAct 그래프로 실행된다.

---

## 4. 모듈 경계 (uv 모노레포)

```
my-agents/
  pyproject.toml                 # uv workspace 루트
  packages/
    core/                        # 도메인 모델, 공용 타입, 설정
    agent/                       # LangGraph 단일 ReAct 에이전트 구성/실행
    mcp/                         # MCP 소비(MultiServerMCPClient) + 노출(FastMCP)
    memory/                      # Mem0 래퍼 (작업기억/유저기억)
    api/                         # FastAPI — Agent 프로토콜, A2A 노출, /mcp, chat(SSE)
  admin/                         # React + TypeScript + Antd SPA (별도 빌드)
  docker-compose.yml             # Postgres(pgvector) 등 로컬 의존성
```

- **Backend API** (`packages/api`): MCP·Agent 제공, A2A 노출, chat 스트리밍.
- **Admin SPA** (`admin/`): MCP·Agent·모델 관리 UI.

> 모듈 경계는 초안이며, 002에서 패키지별 책임을 확정한다.

---

## 5. 핵심 흐름

### 5.1 에이전트 생성
1. Admin에서 페르소나 입력 → 모델(OpenAI) 선택 → 사용할 McpServer 선택 → 메모리 정책 선택.
2. API가 Agent 레코드 저장. (실행 시점에 LangGraph 그래프로 조립)

### 5.2 에이전트 실행 (chat)
1. `POST /agents/{id}/chat` (SSE 스트리밍).
2. 등록된 McpServer들 → `MultiServerMCPClient`로 툴 로드.
3. 단일 ReAct 그래프 실행, Mem0에서 관련 기억 주입/저장.
4. 토큰을 SSE로 스트리밍, 전 과정을 Langfuse로 추적.

### 5.3 MCP 등록 (소비)
- Admin에서 McpServer 등록: transport(stdio: 명령/인자, http: URL/헤더), 활성 툴 선택.
- 검증: 연결 → 툴 목록 조회 → 저장.

### 5.4 MCP 노출 (제공)
- 자체 커스텀 툴 → `FastMCP` 서버로 노출.
- 배포된 에이전트 → LangGraph `/mcp` 엔드포인트로 MCP 툴화하여 노출.

### 5.5 A2A 노출
- **LangGraph Agent Server**가 `/a2a/{assistant_id}` 엔드포인트로 에이전트를 A2A 노출.
- 지원 메서드: `message/send`, `message/stream`(SSE), `tasks/get`. 각 assistant가 **A2A Agent Card** 자동 노출.
- 제약: 그래프 state가 **message 기반**이어야 함(`messages` 키 필요) — 단일 ReAct와 자연스럽게 부합.

---

## 6. 데이터 모델 개요 (PostgreSQL + pgvector)

> 컬럼 수준 스키마는 추후 스펙. 여기서는 엔터티 윤곽만.

- `agents` — 페르소나, model 참조 + 파라미터(jsonb), 메모리 정책
- `models` — name, base_url(OpenAI 호환), model명, 기본 파라미터(jsonb) — 초기 1개(로컬 MLX) 시드
- `mcp_servers` — name, transport, config(jsonb), enabled_tools
- `agent_mcp_servers` — agent ↔ mcp_server (N:M)
- `runs` — 실행 메타, langfuse trace id
- 메모리: **Mem0 백엔드로 pgvector 사용** (동일 Postgres 인스턴스)
- 대화 상태: **LangGraph 체크포인터를 Postgres에 저장** (`langgraph-checkpoint-postgres`)

---

## 7. 기술 스택 매핑 (검증된 라이브러리)

| 역할 | 선택 | 비고 |
|---|---|---|
| 에이전트 | LangGraph ReAct | 단일 그래프, message 기반 state |
| 모델 | **로컬 MLX 서버** | `mlx_lm.server`(OpenAI 호환 `/v1`) + `langchain-openai` base_url |
| MCP 소비 | `langchain-mcp-adapters` `MultiServerMCPClient` | stdio + HTTP/SSE |
| MCP 노출(툴) | `FastMCP` (`mcp.server.fastmcp`) | `@mcp.tool()` |
| MCP 노출(에이전트) | LangGraph Agent Server `/mcp` | langgraph-api≥0.4.21 |
| A2A 노출 | LangGraph Agent Server `/a2a/{id}` | message/send·stream·tasks/get, Agent Card 자동 |
| API | FastAPI | 관리 API + chat SSE 스트리밍 |
| 메모리 | Mem0 (pgvector 백엔드) | 작업기억/유저기억 |
| 대화 상태 | `langgraph-checkpoint-postgres` | Postgres 체크포인터 |
| 추적 | Langfuse | 전 실행 추적 |
| DB | PostgreSQL + pgvector | Mem0·체크포인터·도메인 공용 |
| 패키지 | uv workspace | 모노레포 |
| Admin | React + TS + Antd | |

---

## 8. 결정됨 / 추후 결정

### 검토에서 확정 (2026-06-19)
- **A2A 노출** = LangGraph Agent Server `/a2a/{assistant_id}` (langgraph-api≥0.4.21).
- **Mem0 백엔드** = pgvector (동일 Postgres).
- **모델** = 등록·관리형 레지스트리(OpenAI 호환 엔드포인트). **초기 기본값으로 로컬 MLX**(`mlx_lm.server`)를 시드 등록해 쉽게 시작. 이후 사용자가 모델을 등록·관리.
- **대화 상태** = LangGraph 체크포인터를 Postgres에 저장.

### 추후 결정
- **런타임 토폴로지** — A2A/MCP-에이전트 노출이 LangGraph Agent Server(langgraph-api)에 묶이므로,
  자체 FastAPI 관리 API와 LangGraph Agent Server의 관계(분리 vs 임베드)를 002에서 확정.
- **초기 MLX 시드 모델/파라미터** — mlx-community 양자화 모델 중 무엇, tool-call 지원 확인. (이후 사용자 등록이 본 경로)
- **Admin ↔ API 계약(OpenAPI) 생성 방식** — 추후 논의.

---

## 9. 완료 기준 (이 스펙)

- [ ] 위 결정 요약(§2)이 사람 검토로 승인됨.
- [ ] 도메인 모델·모듈 경계·핵심 흐름이 다음 세부 스펙(002+)의 기반으로 합의됨.

## 관련 기록
- 원본 의도: [docs/spec/CLAUDE.md](./CLAUDE.md)
- 검증 출처: langchain-mcp-adapters, FastMCP, LangGraph MCP 엔드포인트 (웹 확인 2026-06-19)

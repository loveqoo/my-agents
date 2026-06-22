# 007 — 실 에이전트 서비스 (백엔드 + 런타임 + UI 배선)

상태: **실행 중 (자율 진행 — 사용자가 6원칙 준수하에 self-drive 위임)**
날짜: 2026-06-22
브랜치: `feat/agent-service` — **main 머지 금지(사용자가 브랜치에서 직접 테스트). 커밋은 브랜치에만.**
연동: [001 시스템 개요](./001-system-overview.md), [006 admin 콘솔](./006-admin-console-port.md)

> 어드민 UI(006, 전부 mock)가 기대하는 도메인을 **실제 백엔드 + 에이전트 런타임**으로 구현한다.
> 스택: FastAPI + SQLAlchemy(async) + PostgreSQL/pgvector, LangChain·LangGraph, Mem0, 로컬 MLX.

---

## 1. 목표 / 비범위
### 목표
- **빌딩 블록**(페르소나·메모리타입·벡터테이블·권한·MCP 서버)을 실제로 등록·관리(CRUD).
- **에이전트**를 블록 조합으로 생성·편집·삭제, **버저닝**(draft/active/archived) + **A2A 공개** 토글.
- **에이전트 실행**: persona + (선택) mem0 장기 메모리 + (선택) MCP 툴을 LangGraph로 합성, SSE 스트리밍. 턴마다 **트레이스**(메모리 히트·툴 호출·그래프 경로) 캡처.
- **세션/메시지** 영속화, **승인 큐**(HIL) 영속화.
- 어드민 UI를 **실 API에 배선**(mockData → fetch).

### 비범위(이번 스펙)
- 인증/인가(로컬 개발, 무인증) — 추후.
- 코드 정의 에이전트의 실제 원격 호출(엔드포인트 프록시) — 등록 메타만, 실행 프록시는 추후.
- Alembic 마이그레이션 — 개발 단계는 `create_all`. (추후 도입)
- Langfuse 관측 — 추후.

---

## 2. 결정 요약 (자율 결정, 기록)
| 항목 | 결정 |
|---|---|
| DB | PostgreSQL + **pgvector**(mem0 벡터 스토어 겸용). docker-compose 이미지를 `pgvector/pgvector:pg16`로 |
| 스키마 | 빌딩 블록은 **개별 테이블**, 에이전트는 컬럼 + `config` jsonb(선택된 블록 이름 배열) + `agent_versions` 테이블. 세션/메시지/승인 테이블 |
| 마이그레이션 | `create_all`(개발). seed 스크립트로 mock 데이터 적재 |
| 모델 | 에이전트별 `model`(기본 로컬 MLX). `langchain-openai` ChatOpenAI(base_url) |
| 메모리 | **Mem0** — agent가 '장기·의미론적' 메모리 보유 시 턴 전 top-k 검색 주입, 턴 후 저장. LLM=MLX, embedder=로컬, store=pgvector. 초기화 실패 시 graceful disable |
| 툴 | agent의 MCP 선택 → 툴 바인딩. v1: `langchain-mcp-adapters` 경로 + 내장 모의 툴 폴백. 권한이 user/admin이면 `interrupt()`(HIL) |
| 트레이스 | 그래프 노드/지연/토큰/메모리/MCP 호출을 수집해 메시지에 jsonb로 저장 → Playground 인스펙터 |
| UI 배선 | `admin/src/api.ts` 확장, 각 뷰의 `useState(MOCK)` → API 로드. 실패 시 mock 폴백 표시 |

---

## 3. 데이터 모델 (목표)
```
personas(id, name, tone, body, created_at, updated_at)
memory_types(id, key, name, scope, body)          # 시드 카탈로그(단기/의미론적/일화적/절차적)
vector_tables(id, name, model, source, dims, rows, status, body)
permissions(id, name, scope, approver, body)
mcp_servers(id, name, source[ui|external], transport, url, endpoint,
            tools jsonb, enabled_tools jsonb, status, published, auth)
agents(id, agent_id, name, source[ui|code], model, persona,
       history_depth, config jsonb, exposed jsonb, status,
       endpoint, token, runtime, repo, commit, created_at)
agent_versions(id, agent_id→agents, version, status[draft|active|archived],
               note, config jsonb, created_at)
sessions(id, agent_id→agents, channel, status, turns, tokens,
         started_at, last_activity)
messages(id, session_id→sessions, role, content, trace jsonb, created_at)
approvals(id, session_id, agent_id, permission, action, args jsonb,
          summary, checkpoint, status[pending|approved|rejected], requested_at)
```
- `config` jsonb = `{model, persona, memories[], vectorTables[], permissions[], mcps[], historyDepth}` (UI AgentConfig와 동일).

## 4. API (목표, REST + SSE)
- `/personas`, `/memory-types`, `/vector-tables`, `/permissions`, `/mcp-servers` — CRUD.
- `/agents` — CRUD + `/{id}/versions`(생성·활성화·되돌리기) + `/{id}/expose`(A2A 토글).
- `/agents/{id}/chat` — SSE(기존 확장: 세션 생성/지속, 트레이스 저장, mem0/툴 반영).
- `/sessions` — 목록/상세, `/sessions/{id}/messages`.
- `/approvals` — 목록, `/{id}/resolve`(approve|reject).
- `/blocks` — 5개 카테고리 묶음 조회(UI 편의).

## 5. 단계 (각 = 실행 + 타자검증)
1. **Phase 1 — 도메인 영속화**: 모델/스키마/CRUD 라우터 + seed(mock→DB). pgvector compose. UI 미배선, API 스모크로 검증.
2. **Phase 2 — 런타임**: build_agent를 persona+mem0+tools로 확장, 세션/메시지/트레이스 저장, HIL interrupt. CLI/HTTP 스모크.
3. **Phase 3 — UI 배선**: api.ts 확장, 각 뷰 실데이터 로드.

## 6. 검증 (결과)
- [x] Phase 1: API 기동·seed 적재, read + create→edit→activate→expose→register→resolve 스모크 통과. codex GATE — P1 2건(fork 단일초안 가드, active 재활성화 차단) 수정.
- [x] Phase 2: 실 채팅 스트리밍 + 세션/메시지/트레이스 영속, **mem0 저장→회상 실동작(score 0.84)**. codex GATE — P1(세션 agent 스코핑) + P2 3건 수정.
- [x] Phase 3: UI build/tsc 통과, Vite(5173)·API(8000) 통합 가동·CORS OK, 5뷰 실 API 배선.
- [x] 타자 검증(codex) 3회 우선 적용.

### 추후 (이번 범위 밖)
- ✅ Playground 실채팅 배선 (완료 — 실 에이전트 + streamChat + 실 트레이스 인스펙터, E2E 검증)
- AgentForm 블록옵션 API 로드, Alembic, sessions/approvals agentId 외부id화, mem0 재시도, 실 MCP 연결, HIL interrupt 실제화.

### E2E (tests/e2e, Playwright)
- API 통합 12 + 브라우저 9 = 20 passed / 1 skip(대기 승인 없음). 회상-주입 system 메시지 버그를 E2E가 포착·수정([[010]]).

## 7. 리스크
- **Mem0 + 로컬 MLX/임베더 정합**: 가장 불확실. 실패 시 메모리 비활성 폴백, 추후 안정화.
- **MCP 실연결**: 외부 서버 가용성. v1은 어댑터 경로 + 모의 툴 폴백.
- 스키마 변경 빈번 → `create_all` 한계. 다수 테이블 안정화 후 Alembic 검토.

## 관련 기록
- mock UI: [006](./006-admin-console-port.md), 디자인 참조 `.dev/design-refs/`
- 런타임 학습: [[006-qwen-mlx-disable-thinking]]

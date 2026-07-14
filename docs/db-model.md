# 데이터베이스 모델 (PostgreSQL + pgvector)

> 이 문서는 **살아 있는 DB에서 덤프한 실제 스키마**를 근거로 작성했다(모델 파일이 아니라 실물 —
> 어긋나면 실물이 이긴다). 2026-07-14 기준, 36개 테이블.
> 스키마의 단일 진실은 **alembic**이다(스펙 330 — `init_db`의 create_all 폴백은 제거됐다).

## 0. 한 장 지도 — 누가 무엇을 소유하나

테이블은 **우리가 소유하는 것**과 **외부 라이브러리가 소유하는 것**으로 갈린다. 후자는 alembic이
건드리지 않는다(라이브러리가 스스로 만들고 마이그레이션한다).

```mermaid
flowchart TB
    subgraph OURS["우리 소유 (alembic 관리)"]
        direction LR
        A["`**에이전트**<br/>agents · agent_versions<br/>personas · node_templates`"]
        B["`**레지스트리**<br/>providers · models<br/>mcp_servers`"]
        C["`**대화**<br/>sessions · messages<br/>message_feedback · approvals`"]
        D["`**RAG**<br/>collections · documents<br/>document_blobs · rag_chunks<br/>collection_reindex_events`"]
        E["`**평가**<br/>eval_datasets · eval_cases<br/>eval_runs · eval_case_results`"]
        F["`**운영**<br/>batch_runs · batch_config<br/>memory_snapshots · memory_types<br/>app_settings · allowed_hosts · roles`"]
    end
    subgraph THEIRS["외부 라이브러리 소유"]
        direction LR
        G["`**LangGraph**<br/>checkpoints · checkpoint_writes<br/>checkpoint_blobs · checkpoint_migrations`"]
        H["`**mem0**<br/>mem0_memories (pgvector)`"]
        I["`**fastapi-users**<br/>user · accesstoken`"]
        J["`**casbin**<br/>casbin_rule`"]
        K["`**alembic**<br/>alembic_version`"]
    end
    C -.->|"thread_id = agent:session:graph"| G
    C -.->|"자동 기억 저장/회상"| H
```

## 1. 에이전트 · 레지스트리

에이전트는 `source`로 3분기한다: `ui`(관리자가 만든 것) · `code`(코드로 정의) · `external`(A2A 원격).
`agents.persona`는 **텍스트 컬럼**이고 `personas` 테이블과 FK로 묶여 있지 않다(§6 참고).

```mermaid
erDiagram
    providers ||--o{ models : "제공(RESTRICT)"
    agents ||--o{ agent_versions : "버전 이력(CASCADE)"

    providers {
        uuid id PK
        varchar name
        varchar protocol "openai-compatible 등"
        varchar base_url
        varchar api_key
        varchar kind
    }
    models {
        uuid id PK
        uuid provider_id FK
        varchar name
        varchar model_id "실제 모델 식별자"
        varchar kind "chat | embedding"
        boolean is_default
        jsonb params
        jsonb meta
    }
    agents {
        uuid id PK
        varchar agent_id "공개 식별자"
        varchar name
        varchar source "ui | code | external"
        varchar model
        text persona "본문 직접 보관"
        integer history_depth
        jsonb config "그래프/노드 구성"
        jsonb exposed "a2a 등 노출 게이트"
        varchar status
        varchar active_version
        varchar endpoint "external 전용"
        varchar token "external 전용"
        varchar owner_id
    }
    agent_versions {
        uuid id PK
        uuid agent_pk FK
        varchar version
        varchar status
        jsonb config "그 시점 스냅샷"
    }
    personas {
        uuid id PK
        varchar name
        varchar tone
        text body
    }
    node_templates {
        uuid id PK
        varchar name
        integer version
        varchar kind
        jsonb config
    }
    mcp_servers {
        uuid id PK
        varchar name
        varchar source "custom | local | external"
        varchar transport
        varchar url
        jsonb tools "탐색된 도구 목록"
        jsonb enabled_tools
        jsonb tools_meta
        boolean published "MCP 서빙 게이트"
        varchar owner_id
    }
```

## 2. 대화 (채팅 한 턴이 쓰는 곳)

`messages.trace`가 **플레이그라운드 인스펙터의 유일한 저장소**다 — 인스펙터 전용 테이블은 없다.

```mermaid
erDiagram
    agents ||--o{ sessions : "대화(CASCADE)"
    sessions ||--o{ messages : "메시지(CASCADE)"
    messages ||--o| message_feedback : "평가(CASCADE)"
    sessions ||--o{ message_feedback : "세션 스코프(CASCADE)"
    agents ||--o{ approvals : "HIL 승인(SET NULL)"
    eval_cases ||--o{ message_feedback : "골든 수확(SET NULL)"

    sessions {
        uuid id PK
        varchar session_id "sess-… 공개 id"
        uuid agent_pk FK
        varchar agent_name
        varchar channel
        varchar status
        integer turns "턴마다 +1"
        integer tokens "누적"
        varchar user_id "소유자(생성 시 1회 스탬프)"
    }
    messages {
        uuid id PK
        uuid session_pk FK
        varchar role "user | assistant"
        text content
        jsonb trace "인스펙터가 읽는 실행 트레이스"
    }
    message_feedback {
        uuid id PK
        uuid message_pk FK
        uuid session_pk FK
        varchar rating "up | down"
        text reason
        uuid harvested_case_pk FK "평가 케이스로 수확되면"
    }
    approvals {
        uuid id PK
        varchar approval_id
        varchar session_id
        uuid agent_pk FK
        varchar permission
        varchar action
        jsonb args
        varchar checkpoint "= LangGraph thread_id (재개 키)"
        varchar status "pending | approved | rejected"
        varchar approver
    }
```

**한 턴의 쓰기(실측, 2026-07-14)** — 평범한 채팅 1회 기준:

| 테이블 | 델타 | 비고 |
|---|---|---|
| `sessions` | +1(신규) 또는 행 갱신 | `turns`·`tokens` 누적 |
| `messages` | +2 | user + assistant(trace 동봉) |
| `checkpoints`/`_writes`/`_blobs` | 각 **+3 ~ +7** | 1 + 슈퍼스텝 수 + 1 (그래프 모양에 비례) |
| `mem0_memories` | +0~N | 기억할 내용이 있을 때만 |
| `approvals` | HIL 인터럽트 시에만 +1 | |
| `message_feedback` | 사용자가 평가할 때만 +1 | |

끄기 스위치: `persistHistory=false` → `messages`만 스킵 · `ephemeral=true`(스펙 235) → 세션·메시지·커밋 전부 스킵(DB 무접촉).

## 3. RAG

원본은 `document_blobs`에 통째로 보관한다 — 재인덱싱·문서 수정(전체 교체 후 재임베딩)의 근거가 된다.
`collections.kind`가 `document`(일반 문서)와 `entity`(JSONL 엔티티)를 가른다.

```mermaid
erDiagram
    models ||--o{ collections : "임베딩 모델(RESTRICT)"
    collections ||--o{ documents : "문서(CASCADE)"
    collections ||--o{ rag_chunks : "청크(CASCADE)"
    collections ||--o{ collection_reindex_events : "재인덱싱 이력(CASCADE)"
    documents ||--o| document_blobs : "원본 보관(CASCADE)"
    documents ||--o{ rag_chunks : "청크(CASCADE)"

    collections {
        uuid id PK
        varchar name
        uuid embedding_model_id FK
        integer dims "벡터 차원(생성 시 고정)"
        integer chunk_size
        integer chunk_overlap
        integer doc_count
        integer chunk_count
        varchar kind "document | entity"
        jsonb entity_schema
        varchar owner_id
    }
    documents {
        uuid id PK
        uuid collection_id FK
        varchar filename
        varchar content_type
        integer byte_size
        integer chunk_count
        varchar status "parsing|embedding|ready|error"
        text error
    }
    document_blobs {
        uuid document_id PK "원본 바이트"
        bytea data
    }
    rag_chunks {
        uuid id PK
        uuid document_id FK
        uuid collection_id FK
        integer ordinal "문서 내 순서(엔티티 편집 좌표)"
        text text
        vector embedding "pgvector(1024)"
        jsonb meta
    }
    collection_reindex_events {
        uuid id PK
        uuid collection_id FK
        varchar from_model_name
        varchar to_model_name
        integer from_chunk_size
        integer to_chunk_size
        integer chunk_count
        varchar status
    }
```

`documents.status`는 배경 인제스트(스펙 334)의 **상태머신**이다: `parsing → embedding → ready`,
실패 시 `error`. 부팅 시 좀비(재시작을 못 넘긴 `parsing`/`embedding`)는 `error`로 박제된다.

## 4. 평가

```mermaid
erDiagram
    eval_datasets ||--o{ eval_cases : "케이스(CASCADE)"
    eval_datasets ||--o{ eval_runs : "실행(CASCADE)"
    eval_runs ||--o{ eval_case_results : "케이스별 결과(CASCADE)"
    agents ||--o{ eval_runs : "대상 에이전트(SET NULL)"
    agents ||--o{ eval_datasets : "출처 에이전트(SET NULL)"
    collections ||--o{ eval_datasets : "RAG 데이터셋(SET NULL)"

    eval_datasets {
        uuid id PK
        varchar name
        varchar kind
        uuid collection_id FK
        uuid source_agent_pk FK
        varchar owner_id
    }
    eval_cases {
        uuid id PK
        uuid dataset_id FK
        varchar name
        text input
        jsonb asserts "trace_has/trace_lacks 등"
        integer order_idx
    }
    eval_runs {
        uuid id PK
        uuid dataset_id FK
        uuid agent_pk FK
        varchar status
        f8 score
        integer passed
        integer total
        jsonb summary
        uuid group_id "격자 비교 묶음"
        jsonb env "모델·버전 등 실행 환경"
    }
    eval_case_results {
        uuid id PK
        uuid run_id FK
        varchar case_name
        boolean case_passed
        jsonb details
        jsonb obs "관측 트레이스(캡)"
    }
```

## 5. 메모리 · 운영 · 인증

```mermaid
erDiagram
    batch_runs ||--o{ memory_snapshots : "통합 전 스냅샷(SET NULL)"
    user ||--o{ accesstoken : "세션 토큰(CASCADE)"

    mem0_memories {
        uuid id PK
        vector vector "pgvector(1024) — mem0 소유"
        jsonb payload "user_id·scope·text 등"
    }
    memory_types {
        uuid id PK
        varchar key
        varchar name
        varchar scope "user | agent | session"
        text body "추출 프롬프트"
    }
    memory_snapshots {
        uuid id PK
        uuid batch_run_id FK
        varchar user_id
        varchar mem_id
        text text "통합 전 원문(되돌림용)"
    }
    batch_runs {
        uuid id PK
        varchar job_name
        varchar status
        boolean dry_run
        jsonb summary
        text error
    }
    batch_config {
        uuid id PK
        integer session_retention_days
        varchar session_cleanup_cron
        integer memory_consolidation_threshold
        varchar memory_consolidation_cron
    }
    app_settings {
        varchar key PK
        jsonb value
    }
    allowed_hosts {
        uuid id PK
        varchar host "SSRF allowlist"
    }
    user {
        uuid id PK
        varchar email
        varchar hashed_password
        boolean is_superuser
        varchar source
    }
    accesstoken {
        varchar token PK
        uuid user_id FK
    }
    casbin_rule {
        integer id PK
        varchar ptype "p | g"
        varchar v0 "sub"
        varchar v1 "obj"
        varchar v2 "act"
    }
    roles {
        uuid id PK
        varchar name
        text description
    }
```

## 6. FK가 **없는** 논리적 관계 (알고 있어야 할 것)

ERD에 선이 없다고 관계가 없는 게 아니다. 아래는 코드가 문자열로 잇는 관계다 — DB가 무결성을
지켜주지 않으므로 삭제·개명 시 조용히 끊긴다.

| 참조 | 대상 | 왜 FK가 아닌가 |
|---|---|---|
| `agents.persona` (text) | `personas.body` | 에이전트가 페르소나 본문을 **복사해 보관**한다(페르소나 수정이 기존 에이전트를 바꾸지 않도록) |
| `sessions.user_id`, `*.owner_id` (varchar) | `user.id` | 소유자를 문자열로 스탬프(외부 주체·머신 토큰도 담기 위해) |
| `approvals.session_id` (varchar) | `sessions.session_id` | 공개 id 문자열로 참조 |
| `approvals.checkpoint` (varchar) | `checkpoints.thread_id` | **테이블 주인이 LangGraph**라 FK를 걸 수 없다 |
| `agents.model`, `eval_runs.model_name` | `models.name` | 이름 문자열 참조 |
| `mem0_memories.payload.user_id` | `user.id` | mem0가 payload JSONB에 담는다(스키마 주인이 mem0) |

## 7. 라이프사이클 주의점

- **체크포인트는 지워지지 않는다.** 턴당 `1 + 슈퍼스텝 수 + 1`행이 `checkpoints`·`checkpoint_writes`·
  `checkpoint_blobs`에 각각 쌓이고(단일 노드 3, 멀티 노드 7 실측), **삭제 경로가 코드에 없다**.
  HIL 재개(`approvals.checkpoint`)의 근거라 턴 중엔 필수지만, 끝난 뒤 정리가 없다. 운영 시 과제
  (백로그 등재 — 세션 종료 시 `adelete_thread` / TTL 배치 / HIL 미사용 에이전트 미부착).
- **대화 이력은 두 곳에 중복 보관**된다: `messages`(우리) + `checkpoints`(LangGraph 채널 상태).
- **벡터 차원은 생성 시 고정**된다(`collections.dims`, `mem0_memories.vector`, `rag_chunks.embedding`
  모두 1024). 차원이 다른 임베딩 모델로 바꾸려면 재인덱싱이 아니라 저장 구조 재설계가 필요하다.
- **RAG 수정은 전체 교체 → 재인덱싱**이다(부분 행 편집 없음 — 원본 `document_blobs`와의 동기화 때문).

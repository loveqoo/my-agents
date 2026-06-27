# 036 — RAG 인제스트 토대 (P2-a, 지식 쓰기 경로)

상태: **초안 — 인간 검토 대기** (AI 작성). 데이터 모델=신규 Collection+Document+Chunk(vectorTables 재생), 분할=인제스트 먼저(037 retrieval 분리).
날짜: 2026-06-27
브랜치: `feat/agent-service` — **main 머지·push 금지**(사용자가 직접 브랜치 테스트)
지배 스펙: [033 로드맵](./033-feature-roadmap.md)(P2 = #9 인제스트 + #10 retrieval), [035 Provider 엔티티](./035-provider-entity.md)(임베딩 provider 상속 토대), [019 mem0 pgvector 공유 백엔드](./019-mem0-pgvector-shared-backend.md)
참고 자산: `.dev/learning/020`(DSN 원본 위임 + **pgvector 차원은 생성 시 고정→모델 결합** + 차원 불일치 시 조용히 죽음), `.dev/retrospect/025`(인라인→관계 정규화 = N개 소비처 eager-load 의무, 셰이프 변경 직후 grep 전수)

## 배경 / 문제

에이전트가 외부 문서(PDF 등)를 근거로 답하려면 **지식을 청크로 쪼개 임베딩해 pgvector에 적재**하는
인제스트 경로가 필요하다. 현재:
- `VectorTable` 엔티티(`models.py:48-59`: name/model/source/dims/rows/status/body) + 풀 CRUD(`blocks.py`)
  + 어드민 UI가 **이미 있으나 런타임 미소비 = 죽은 카탈로그**(seed는 products.title 같은 외부소스 목 데이터).
- `Document`/`File`/`Upload` 엔티티·PDF 처리·청킹 **전무**.
- pgvector는 mem0 전용(`mem0_memories`)뿐 — RAG용 청크 저장소 없음.

→ **`VectorTable`(죽은 카탈로그)을 1급 `Collection`(지식 컬렉션)으로 재생**하고, 그 아래
`Document`(업로드 파일)·`Chunk`(임베딩 청크, 전용 pgvector 테이블)를 신설한다.
이번 스펙(036)은 **쓰기 경로(인제스트)만** — 읽기(retrieval 도구 + 에이전트 와이어링)는 037.

## 현황 (조사로 검증 · file:line)

- `VectorTable`: `packages/api/src/api/models.py:48-59`. CRUD: `blocks.py:130-175`, 집계 `blocks.py:360,397`.
  에이전트 config의 `vectorTables: list[str]`(`schemas.py:153`)가 이름으로 참조(런타임 미소비 → 037에서 배선).
- 임베딩 provider 상속(035): `ModelConfig.kind=="embedding"` + `provider` 관계, 기본 resolver
  `chat.py:209-216`(`_default_embed_model`, `selectinload(provider)`). 연결정보 복호화 `crypto.decrypt`.
- 임베딩 dims 실측: `model_registry._probe`가 `POST {base_url}/embeddings` → `dims=len(vec)`
  (`model_registry.py:40-69`). multilingual-e5-large=1024 실측(019).
- pgvector: 확장 설치됨(0.8.2, 스펙 019), `_sync_dsn`(드라이버 접미사 제거) `memory.py:41-51`.
  단 mem0는 psycopg 직접 사용 — **SQLAlchemy에서 vector 컬럼 쓰려면 `pgvector` 파이썬 패키지 필요**.
- alembic head `a1b2c3d4e5f6`. 라우터 규약: `main.py`에 `include_router(..., dependencies=_auth)`.

## 설계

### 엔티티 (VectorTable → Collection 전환 + 신규 2종)

- **`Collection`**(`collections` 테이블 — `vector_tables` 개명·재편): `id`, `name`(unique, 표시·참조명),
  `description`, `embedding_model_id`(FK→`models.id`, **NOT NULL** — 이 컬렉션이 어떤 임베딩 모델로
  만들어졌는지; 037 질의 시 **같은 모델로 임베딩해야 정합**), `dims`(생성 시 probe 실측으로 고정),
  **`chunk_size`(기본 1000)/`chunk_overlap`(기본 200)** — 청킹도 전략이므로 컬렉션별로 사용자 수정 가능,
  `doc_count`/`chunk_count`(집계, 비정규화 캐시), `status`(empty|ingesting|ready|error), `created_at`.
  - 죽은 컬럼 `model`(문자열)/`source`/`rows`/`body`는 제거, 의미 있는 필드로 교체.
  - 청킹 파라미터는 **인제스트 시점에 그 컬렉션 값을 읽어** splitter에 주입. 수정해도 기존 청크는
    재인제스트 전까지 옛 분할 유지(증분 재인제스트는 범위 밖).
- **`Document`**(`documents` 테이블): `id`, `collection_id`(FK→collections, **ondelete CASCADE** — 컬렉션
  지우면 문서·청크 동반 삭제), `filename`, `content_type`, `byte_size`, `chunk_count`,
  `status`(parsing|embedding|ready|error), `error`(nullable), `created_at`.
- **`Chunk`**(`rag_chunks` 테이블, **전용 pgvector 저장소**): `id`, `document_id`(FK→documents,
  ondelete CASCADE), `collection_id`(FK, 질의 필터용 비정규화), `ordinal`(문서 내 순번),
  `text`(Text), `embedding`(`Vector(N)`), `token_count`(선택), `created_at`.
  - **HNSW 인덱스**(cosine, `vector_cosine_ops`)는 037 retrieval에서 본격 사용하나 036에서 생성해 둔다.

### 인제스트 파이프라인 (쓰기 경로)

```
POST /collections/{id}/documents  (multipart 파일)
  → 1) Document(status=parsing) 생성
  → 2) PDF/텍스트 파싱 (pypdf) → 평문 추출
  → 3) 청킹 (langchain RecursiveCharacterTextSplitter, 기본 1000자/200 오버랩)
  → 4) 각 청크 임베딩 (POST {provider.base_url}/embeddings, 컬렉션의 embedding_model)
  → 5) Chunk 행 N개 insert (embedding=vector)
  → 6) Document.status=ready, chunk_count=N; Collection.chunk_count/doc_count 갱신
  실패 시 status=error + error 메시지 보존 (no silent death — learning 020 함정3 대응)
```

### 차원 고정 트랩 대응 — DB↔모델 차이 3중 가드 (learning 020 함정3 — 핵심)

- **pgvector 컬럼 `vector(N)`은 생성 시 차원 고정**. 차원 다른 벡터 insert는 깨지고 조용히 죽을 수 있다.
  게다가 **DB 컬럼 차원·Collection.dims·임베딩 모델의 실제 출력 차원**이 시간차로 어긋날 수 있다
  (예: 컬렉션 생성 후 누군가 기본 임베딩 모델을 다른 차원 모델로 바꿈 → drift).
- **대응**: `rag_chunks.embedding`은 `Vector(RAG_EMBED_DIMS)`(기본 1024 = `_EMBED_DIMS`와 동일 env)로 고정.
  세 지점에서 차원을 **명시적으로 검사**해 조용한 죽음을 차단한다(no silent death):
  1. **생성 시점**: Collection 생성 시 임베딩 모델 probe → 실제 dims 측정, `RAG_EMBED_DIMS`(=DB 컬럼)와
     불일치하면 **409 거부**. `Collection.dims`에 측정값 박제.
  2. **인제스트 시점**: 각 임베딩 벡터를 insert 전 `len(vec) == Collection.dims`(=DB 컬럼) **검증**.
     불일치 시(모델이 생성 후 바뀌어 차원이 달라짐 등) Document.status=error + error 메시지 보존, insert 안 함.
  3. **점검 시점**: `GET /collections/{id}/health`(또는 점검 유틸) — Collection.dims vs 현재 임베딩 모델
     probe dims vs DB 컬럼 차원을 비교해 drift를 노출(어드민에서 경고 배지). 점검은 읽기 전용·부작용 없음.
- v1은 단일 차원 전제(모든 컬렉션 동일 dims, DB 컬럼=`RAG_EMBED_DIMS`).
- **범위 밖(후속)**: 컬렉션별 가변 차원(컬렉션당 테이블 분리 또는 dim-less + 인덱스 전략), drift 자동 재인제스트.

### 의존성

- `pypdf`(순수 파이썬, 가벼움) — PDF 텍스트 추출.
- `pgvector`(SQLAlchemy `Vector` 타입) — `pyproject.toml`에 추가, `uv sync`.
- 청킹: `langchain-text-splitters`(이미 langchain 계열 의존성 존재 — 확인 후 미존재 시 추가).

### UI (어드민)

- 기존 **VectorTable 탭 → Collection 탭**으로 재편: 컬렉션 CRUD(name/description/embedding 모델 선택) +
  **문서 업로드(드래그/파일)** + 컬렉션별 문서 목록(filename/status/chunk_count) + 문서 삭제.
- 임베딩 모델 드롭다운은 `kind=="embedding"` 모델만(035 provider 상속).
- 비밀 노출 없음(provider api_key는 백엔드 전용).

### 라우터

- 신규 `rag.py`(또는 `collections.py`) 라우터: `/collections` CRUD, `/collections/{id}/documents`
  업로드/목록/삭제. `main.py`에 `include_router(..., dependencies=_auth)`.
- 기존 `blocks.py`의 vector-tables CRUD는 제거/이관(소비처 grep — retrospect 025 교훈).

## 마이그레이션 (alembic 신규 리비전, 부모=a1b2c3d4e5f6)

1. `vector_tables` → `collections` 개명 + 컬럼 재편(죽은 컬럼 drop, 신규 컬럼 add). 기존 목 데이터는
   임베딩 모델 FK가 없으므로 **seed에서 재생성**(목 외부소스 4종은 폐기 — 회귀 아님, 죽은 데이터였음).
2. `documents` 테이블 생성.
3. `rag_chunks` 테이블 생성 + `embedding vector(N)` 컬럼 + HNSW 인덱스(`vector_cosine_ops`).
4. seed 재편(`seed.py`): VECTOR_TABLES 목데이터 제거 → 실제 Collection 1~2개(임베딩 모델 연결) 시드,
   문서는 비움(또는 작은 샘플 1개 인제스트). 에이전트 config `vectorTables` 참조 정합 유지.

## 검증 (측정 가능 · 자가검증 지양)

1. **인제스트 라운드트립(수치)**: 알려진 텍스트/PDF(예: 3페이지) 업로드 → `Document.status=="ready"`,
   `chunk_count == N`(N>0), `rag_chunks`에 N행, **각 embedding이 정확히 `RAG_EMBED_DIMS`차원**,
   `Collection.chunk_count == N`. 인프로세스 ASGI + 자가정리(prefix).
2. **차원 트랩(3중 가드 수치 검증)**: (a) dims 불일치 모델로 Collection 생성 → **409**; (b) 생성 후
   임베딩 벡터 길이 != Collection.dims 상황을 강제 → 인제스트가 **status=error + 메시지 보존**(insert 0);
   (c) `health` 점검이 Collection.dims/모델 probe dims/DB 컬럼 차원 일치를 보고, drift 시 불일치 노출.
3. **CASCADE**: Document 삭제 → 그 청크 동반 삭제, Collection.chunk_count 감소. Collection 삭제 →
   문서·청크 전부 삭제.
4. **무회귀**: 기존 채팅/메모리 경로 영향 없음(RAG는 037 전까지 런타임 미배선). mem0 `mem0_memories`와
   `rag_chunks` 테이블 독립 — 상호 간섭 없음.
5. **UI**(브라우저, Playwright+시스템 Chrome): Collection 탭 CRUD, 문서 업로드 → status=ready 표시,
   chunk_count 노출, 비밀 미노출.
6. **타자 2인**(codex + 서브에이전트) 비판 리뷰: pgvector 차원 고정 트랩, CASCADE 정합, 파일 업로드
   경계(빈 파일/거대 파일/비PDF), 임베딩 실패 시 status=error 보존, vector-tables 소비처 잔존.

## 합의 완료 (인간 승인 2026-06-27 — 5개 권장값 전부 + 보강 2건)

1. **VectorTable → Collection 개명** ✅ — 테이블·엔티티 개명. config 키 `vectorTables` 유지(back-compat).
2. **PDF 파서** ✅ — `pypdf`(순수 파이썬·가벼움).
3. **청킹 전략** ✅ — RecursiveCharacterTextSplitter 1000자/200 오버랩 **기본값**.
   **(보강)** 청킹도 전략이므로 `chunk_size`/`chunk_overlap`을 **Collection 컬럼으로 두고 사용자 수정 가능**.
4. **인제스트 동기/비동기** ✅ — v1 동기(작은 문서 전제). 거대 문서는 P3.
5. **차원 정책** ✅ — 단일 차원 고정 + 불일치 거부.
   **(보강)** DB↔임베딩 모델 차원 차이를 **3중 가드**(생성 409 / 인제스트 status=error / health 점검)로 점검·대비.

## 완료 조건

- [ ] `Collection`(vector_tables 재편, chunk_size/chunk_overlap 포함) + `Document` + `Chunk`(rag_chunks, vector(N)) 엔티티 + alembic
- [ ] 인제스트 파이프라인(파싱→컬렉션 청킹설정→임베딩→적재) + 실패 시 status=error 보존
- [ ] 차원 3중 가드(생성 409 / 인제스트 검증 / `GET /collections/{id}/health`)
- [ ] `/collections` + `/collections/{id}/documents` 라우터, 기존 vector-tables CRUD 이관/제거
- [ ] seed 재편(실제 Collection + 임베딩 모델 연결)
- [ ] Collection 탭(청킹설정·차원 health 노출) + 문서 업로드 UI
- [ ] 검증 1~6 통과 + 타자 2인 SHIP
- [ ] **main 머지 금지** — 사용자 브랜치 테스트 대기

## 범위 밖 (037 또는 후속)

- **retrieval 도구 + 에이전트 와이어링 + 질의 시 임베딩 + 유사도 검색 + trace**(037).
- 컬렉션별 가변 차원, 거대 문서 백그라운드 인제스트(P3 스케줄러), 재인제스트/증분 갱신.
- OCR·이미지 PDF, URL 크롤링, 다른 파일형식(docx/html) — 후속.

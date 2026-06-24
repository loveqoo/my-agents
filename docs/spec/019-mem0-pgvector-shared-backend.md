# 019 — mem0 벡터 스토어를 pgvector(공유 Postgres)로 이전

상태: **승인됨 (인간 검토 완료 — 결정: ① mem0 전용 테이블 같은 agents DB 공존, ② qdrant 완전 제거)**
날짜: 2026-06-24
브랜치: `feat/agent-service` — **main 머지·push 금지**(사용자가 직접 브랜치 테스트)
지배 스펙: [007-real-agent-service](007-real-agent-service.md)(Phase 2 — 메모리), [018-memory-user-scoping](018-memory-user-scoping.md)
연관 코드: `packages/api/src/api/memory.py`, `db.py`, `packages/api/pyproject.toml`

---

## 배경 — 파일 기반 저장소는 N-인스턴스에서 깨진다 (사용자 제기)

현재 mem0는 두 곳에 저장한다(코드로 확인):

| 저장소 | 현재 위치 | N-인스턴스 문제 | 회상(search) 경로? |
|---|---|---|---|
| **벡터 스토어** | qdrant **on-disk** `.dev/mem0_qdrant` (`memory.py:48,67-70`) | 인스턴스마다 별도 파일 → 기억 파편화, `.lock` 동시쓰기 충돌 | ✅ **결정적** |
| **히스토리 DB** | SQLite `~/.mem0/history.db` (mem0 기본) | 인스턴스 로컬 → 감사 이력 파편화 | ❌ **무관**(검증: `Memory.search` 소스에 history 미참조; `_create_memory`의 감사 로그 전용) |

→ **회상 정합성은 벡터 스토어 공유만으로 보장**된다. 히스토리는 회상 경로 밖이라 로컬이어도 정합성 문제 없음(감사 이력만 분산).

## 결정 — pgvector로 이전 (기존 스택 재사용)

mem0 2.0.7은 벡터 스토어 24종을 지원하며 그중 **`pgvector`**가 있다(`VectorStoreFactory.provider_to_class` 확인). 이 프로젝트는 **이미 PostgreSQL+pgvector를 운영**한다(루트 스펙 "PostgreSQL(+pgvector)", `db.py:19` `DATABASE_URL`). 따라서:

- **새 인프라 0** — 기존 Postgres 재사용. qdrant 서버모드(새 서비스)·on-disk(미해결) 대비 우월.
- **스택 일치** — 루트 스펙이 명시한 백엔드.
- **N-인스턴스 공유** — 모든 API 인스턴스가 같은 Postgres를 보면 회상 정합.

대안 기각: qdrant 서버모드(도커 컴포즈 등 새 운영부담), on-disk 유지(문제 미해결).

---

## 변경 계획

### A. 의존성 — `psycopg[pool]` 추가
mem0 `pgvector.py:11-30`은 `psycopg3` + **`psycopg_pool`**(`ConnectionPool`)을 요구한다.
프로젝트엔 `psycopg[binary]>=3.3.4`만 있어 `psycopg_pool`이 빠짐(import 실패 재현됨).
- `packages/api/pyproject.toml`: `psycopg[binary]` → **`psycopg[binary,pool]`** (또는 `psycopg-pool` 추가).
- `uv sync`로 설치 확인.

### B. `memory.py` — `_build_config`의 `vector_store` 블록 교체
qdrant on-disk 블록을 pgvector로 교체. **연결 정보는 `DATABASE_URL`에서** 단일 출처 유지
(별도 MEM0_* 자격 도입 안 함 — [[012-runtime-config-single-source]] 원칙).

> **타자 검증 반영(P1)**: 처음엔 URL을 host/user/password/port로 **분해**했으나, mem0 PGVector가
> 내부에서 `postgresql://{user}:{password}@{host}:{port}/{dbname}`로 **재조립**하는 구조라
> (1) 자격정보 부재 시 문자열 `"None"`으로 인증 실패, (2) raw 특수문자 password 오파싱/`u.port` ValueError,
> (3) 쿼리스트링 `sslmode` 누락 위험이 있었다. → **분해 폐기, 드라이버 접미사만 제거한 raw DSN을
> `connection_string`으로 위임**(mem0 우선순위 `connection_pool > connection_string > 개별` 소스 확인).
> psycopg(libpq)가 인코딩·sslmode·자격정보를 표준대로 처리.

```python
# DATABASE_URL = "postgresql+asyncpg://agent:agent@localhost:5432/agents"
# mem0/psycopg는 동기 드라이버 → "+asyncpg" 제거 후 host/port/user/password/dbname로 분해.
from urllib.parse import urlsplit
u = urlsplit(os.environ.get("DATABASE_URL", "postgresql+asyncpg://agent:agent@localhost:5432/agents"))
"vector_store": {
    "provider": "pgvector",
    "config": {
        "dbname": u.path.lstrip("/") or "agents",
        "user": u.username, "password": u.password,
        "host": u.hostname, "port": u.port or 5432,
        "collection_name": "mem0_memories",   # = 테이블명
        "embedding_model_dims": _EMBED_DIMS,   # 1024 (multilingual-e5-large) 유지
        "hnsw": True,                          # 인덱스
    },
}
```
- **qdrant 완전 제거(승인)**: `MEM0_QDRANT_PATH` 분기·qdrant 블록 삭제, 토글 없음. pgvector 단일 경로.
- 나머지(graceful 무력화, 캐시 `_cfg_key`, search/add)는 **변경 없음** — provider만 바뀜.

### C. pgvector 확장(extension) + 이미지 준비
pgvector 테이블 생성에는 Postgres에 `vector` 확장이 필요. **발견(실측)**: 기존 `docker-compose.yml`이 `postgres:16`(pgvector 미포함)을 써서 확장이 아예 없었음. → **이미지를 `pgvector/pgvector:pg16`로 교체**(postgres:16 기반 → 기존 `pgdata` 볼륨 호환). 신규 볼륨엔 `db/init/01-pgvector.sql`(`CREATE EXTENSION IF NOT EXISTS vector`)가 자동 실행; 기존 볼륨엔 mem0가 superuser로 자체 생성(또는 1회 수동). 검증: pgvector 0.8.2 설치 확인됨.

### C-2. 임베딩 차원 일치 (사용자 지적 — 하드닝)
pgvector 테이블은 **생성 시 차원이 고정**된다. 기본 임베딩 모델의 실제 출력 차원과 다르면 insert가
깨지고 mem0 `add`가 `except`로 삼켜 **메모리가 조용히 죽는다**(018 공백 함정과 동형).
- **실측 검증**: 라이브 임베딩 서버 probe → 실제 1024차원 = `_EMBED_DIMS` 1024 일치. pgvector hnsw 상한(2000) 이내.
- **하드닝**: `_EMBED_DIMS = int(os.environ.get("MEM0_EMBED_DIMS", "1024"))` + 모델 결합 주석 명시.
- **추후(범위 밖)**: 차원을 레지스트리 모델에서 동적 도출(probe 또는 models 테이블에 dims 컬럼) — 하드코딩 제거.

### D. 정리 (선택)
- 기존 `.dev/mem0_qdrant`는 더는 사용 안 함 → 정리 가능(시드 메모리는 새 pgvector 컬렉션으로 안 넘어감 — 아래 비고).

---

## 검증 (완료 조건)

- [x] `uv sync` 후 `from mem0.vector_stores.pgvector import PGVector` import OK (`psycopg-pool==3.3.1` 설치).
- [x] mem0가 pgvector로 초기화되고 `agents` DB에 `mem0_memories` 테이블 생성됨 — `vector(1024)` 컬럼, pgvector 0.8.2.
- [x] **로직**: `add`(`user_id=`)와 `search`(`filters={"user_id":}`)가 **같은 스코프 키스페이스**를 가리킴 — 라운드트립으로 회상 확인(018 1순위 숙제 해소).
- [x] **스코핑**: `user:alice`에 저장 → 같은 스코프 회상 O, `session:sess-xxx`(다른 스코프) 회상 X(격리). (라이브 임베딩 서버로 실측.)
- [x] **N-인스턴스 핵심**: 캐시 비운 '새 인스턴스'가 같은 Postgres에서 이전 인스턴스 저장분 회상 — 공유 정합성 입증.
- [x] **타자 검증**: 서브에이전트 비판 리뷰 → DATABASE_URL 분해 방식의 P1 2건(자격정보 부재 'None' 인증, raw 특수문자 오파싱) 발견 → `connection_string` 위임으로 수정·재검증(엣지케이스 4종 크래시 없음 확인).
- [ ] dry-run: 임베딩 서버 미기동 시에도 graceful 무력화(메모리 없이 채팅 동작) 유지 확인. ← 사용자 브랜치 테스트로 이관 가능

---

## 범위 밖 (이번 스펙 제외)

- **히스토리 DB 공유** — SQLite 로컬 유지(회상 경로 밖, 감사 전용). mem0 2.0.7은 `SQLiteManager`뿐(Postgres 히스토리 백엔드 없음). 추후 `history_db_path` 프로젝트 고정 또는 공유 볼륨은 별도 논의.
- qdrant 코드 완전 삭제(토글로 남길 경우), 임베딩 서버 운영, 메모리 일화적·절차적 타입 배선.
- 멀티유저 인증, A2A 핸들러, LangGraph 체크포인터.

## 비고

- **시드 메모리 단절은 의도**: on-disk qdrant → pgvector로 백엔드가 바뀌므로 기존 qdrant 컬렉션의 기억은 새 테이블로 넘어오지 않는다(018의 키 재스코핑과 동일 성격 — 회귀 아님). 필요 시 마이그레이션 별도.
- main 머지·push 금지. 검증 후 사용자가 직접 브랜치에서 테스트.
- 동기 psycopg 풀은 기존 `asyncio.to_thread(memory.search/add, ...)` 안에서 호출되므로 async 이벤트루프와 충돌 없음.

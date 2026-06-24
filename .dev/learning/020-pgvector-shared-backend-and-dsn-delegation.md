# 020 — mem0 공유 백엔드(pgvector) + DSN은 분해 말고 위임

맥락: mem0 벡터 스토어를 on-disk qdrant → pgvector로 이전(스펙 019). mem0 2.0.7.
대상: `packages/api/src/api/memory.py`, `docker-compose.yml`.

## 함정 1 — 파일 기반 벡터 스토어는 N-인스턴스에서 깨진다

mem0의 qdrant **on-disk 모드**(`path=`, `on_disk=True`)나 chroma/faiss 로컬은 **인스턴스 로컬 파일**이다.
API 서버를 N개로 스케일하면 인스턴스마다 별도 파일 → 기억 파편화(A 저장분을 B가 회상 못 함) + `.lock`
동시쓰기 충돌. **회상 정합성은 벡터 스토어 공유에만 의존**한다(히스토리 DB는 회상 경로 밖 — `Memory.search`
소스 확인). → 프로덕션은 **공유 백엔드** 필수.

**해법**: mem0는 벡터 스토어 24종 지원(`VectorStoreFactory.provider_to_class`). 이미 PostgreSQL을 쓰면
**`pgvector`**가 정답 — 새 인프라 0. `provider:"pgvector"`, 연결정보 + `collection_name`(=테이블명) +
`embedding_model_dims` + `hnsw:True`. 같은 DB에 mem0 전용 테이블(`vector(N)`, `payload jsonb`)이 하나 생긴다.

인프라: 기본 `postgres:N` 이미지엔 pgvector 확장이 **없다**. **`pgvector/pgvector:pgN`** 이미지로 교체
(postgres 기반이라 기존 데이터 볼륨 호환). 확장은 `docker-entrypoint-initdb.d`(신규 볼륨만) 또는
mem0가 superuser로 자체 `CREATE EXTENSION`. 의존성: mem0 pgvector는 `psycopg[pool]`(=psycopg_pool) 요구.

## 함정 2 — 연결정보는 분해하지 말고 원본 위임 (타자 검증 P1)

`DATABASE_URL`을 `urlsplit`으로 host/user/password/port로 **분해**해 mem0에 넘기면 안 된다.
mem0 PGVector는 내부에서 다시 `f"postgresql://{user}:{password}@{host}:{port}/{dbname}"`로 **재조립**한다
(우선순위: `connection_pool > connection_string > 개별 파라미터`, 소스 확인). 이 왕복이 버그를 만든다:
- 자격정보 부재(`postgresql://host/db`) → `None`이 문자열 `"None"`으로 박제 → 인증 실패.
- raw 특수문자 password(`p@ss`, `pa/ss`) → urlsplit 오파싱, `.port` 접근 시 `ValueError`.
- 쿼리스트링 `?sslmode=require` 누락.

**원칙**: 외부 라이브러리에 연결문자열을 넘길 땐 **분해→재조립 대신 원본 DSN을 그대로 위임**해
표준 파서(psycopg/libpq)가 인코딩·sslmode·자격정보를 처리하게 한다. 드라이버 접미사만 제거:
```python
def _sync_dsn(url):  # postgresql+asyncpg://.. → postgresql://..
    if "://" not in url: return url
    scheme, rest = url.split("://", 1)
    return f"{scheme.split('+',1)[0]}://{rest}"
# config: {"connection_string": _sync_dsn(DATABASE_URL), "collection_name":..., "embedding_model_dims":..., "hnsw":True}
```

## 함정 3 — pgvector 차원은 생성 시 고정 → 모델과 결합

테이블이 `vector(1024)`로 생성되면 그 차원만 받는다. 기본 임베딩 모델을 바꿔 차원이 달라지면 insert가
깨지고 mem0 `add`가 `except`로 삼켜 **메모리가 조용히 죽는다**([[019-mem0-memory-scoping]] 공백 함정과 동형).
- 실제 차원은 **라이브 엔드포인트 probe로 확인**(모델명 추측 금지). multilingual-e5-large=1024 실측.
- 최소 하드닝: env 오버라이드 + 모델 결합 주석. 근본책: 레지스트리/probe로 동적 도출.

## 일반화
- **외부 SDK에 연결정보·식별자를 넘기기 전, 그 SDK가 내부에서 무엇으로 변환하는지 소스로 본다**
  (분해 재조립·entity-id 정규화·차원 고정 — 모두 경계에서 조용한 실패를 만든다).
- happy path 통과 ≠ 정합. **타자 검증**으로 엣지케이스를 강제로 들춘다.

관련: 회고 [[010-mem0-pgvector-migration]] · 스펙 docs/spec/019 · [[019-mem0-memory-scoping]] · [[012-runtime-config-single-source]]

# 159 — mem0가 임베더에 차원을 강제해 self-hosted 임베더가 400 (버그)

## 증상 (사용자 배포본, 스펙 158 진단이 표면화)
회상 진단이 이제 진짜 에러를 보여줌:
> 검색 실행 실패: Error code: 400 — Model "snowflake-arctic-embed-l-v2.0" only supports [256]
> matryoshka dimensions, use other output dimensions will lead to poor results.

저장 11건·회상 0건·백엔드 준비됨. 임베딩 모델=snowflake-arctic-embed-l-v2.0(**네이티브 1024**).

## 근인
`mem0_backend._build_config`가 임베더 config에 `embedding_dims: _EMBED_DIMS`(=env 1024)를 넣는다.
mem0 OpenAIEmbedding은 `embedding_dims is not None`이면 API 요청에 **`dimensions=1024`를 붙여 보낸다**
(embeddings/openai.py:18-20,53-54, 주석: "non-matryoshka OpenAI-compatible backends (vLLM, Voyage 등)는
이 파라미터를 거부"). snowflake 서버는 **명시적 출력 차원으로 256만 허용**(matryoshka), 안 보내면
네이티브 1024 반환. 우리가 1024를 강제 → 400 → 검색 임베딩 실패 → 회상 0.

**설계 격차**: `MEM0_EMBED_DIMS`가 두 용도를 겹쳐 쓴다 — (1) pgvector **컬럼 차원**(저장 벡터 길이),
(2) 임베더에 **강제 요청할 차원**(API `dimensions` 파라미터). (2)는 self-hosted 임베더엔 유해하다
(모델 네이티브를 그냥 받으면 됨). RAG는 모델 차원을 probe로 실측(model_registry `_probe` dims=len(vec))
하는데 mem0만 전역 env로 강제.

**11건은 멀쩡하다**: 같은 snowflake(1024) 네이티브 벡터로 저장됐고 컬럼도 1024. `dimensions` 강제만
빼면 검색 임베딩도 네이티브 1024 → 같은 공간 → **재인덱싱/초기화 없이** 회상 복구.

## 설계 (codex 159 High 반영 — 정적 기본값은 양쪽 중 한 케이스를 깬다)
정적 "항상 전송"은 snowflake(파라미터 거부)를, "항상 미전송"은 text-embedding-3류(네이티브≠컬럼,
파라미터 지원)를 깬다. 그래서 **네이티브 차원을 probe해 판단**(RAG 방식):
- (A) `_native_embed_dims(emb)`: mem0가 쓸 OpenAIEmbedding으로 dimensions 미전송 임베딩 1회 →
  `len(vec)`가 네이티브. `(base_url, model_id)`로 **캐시**(요청마다 재probe 방지). 실패 시 None.
- (B) `_embedder_request_dims(emb)`: 요청할 dimensions 결정 — 수동 override(`MEM0_EMBED_REQUEST_DIMS`)
  있으면 그 값; 아니면 **네이티브==컬럼(_EMBED_DIMS)→None(미전송, snowflake 안전)**, **네이티브≠컬럼
  →_EMBED_DIMS(절단 요청, text-embedding-3 안전)**, probe 실패→None(보수적 미전송).
- (C) `_build_config` 임베더: `embedding_dims`를 req_dims!=None일 때만 포함.
- (D) 컬럼 `embedding_model_dims`=`_EMBED_DIMS` **유지**(불변).
- 비파괴: snowflake는 네이티브 1024==컬럼 1024 → 미전송 → 서버가 네이티브 반환 → 기존 11건과 일치,
  재인덱싱 없이 회복. text-embedding-3(1536≠1024)는 dimensions=1024 전송 → 회귀 없음.

## 검증
- verify_159: (V1) 네이티브==컬럼 → embedding_dims 미포함·`_pass_dimensions_to_api`=False(snowflake).
  (V2) 네이티브≠컬럼(1536) → embedding_dims=_EMBED_DIMS(1024)·전송 True(text-embedding-3, codex 회귀
  방지). (V3) opt-in env → 그 값. (V4) probe 실패 → 미전송(보수적). (V5) 로컬 add+search 왕복(실 probe,
  mock 네이티브 1024==컬럼) 동작. (V6) 컬럼 차원 불변.
- 로컬 재현 한계: 400은 dimensions 거부 서버 필요(mock은 무시) → mem0 임베더 `_pass_dimensions_to_api`
  플래그와 실제 요청 dimensions로 직접 측정. codex 여집합. 사용자 배포본 재조회 시 11건 회상 실증.

## 경계 (문서화 — codex 159b High2)
**네이티브≠컬럼 이면서 모델이 dimensions 파라미터를 거부**하는 조합은 코드로 못 고친다: 컬럼은
기존 테이블에 고정(재생성=마이그레이션), 모델은 절단 불가라 컬럼 길이를 못 만든다. 이 경우 회상이
400나며 진단(158)이 표면화한다(경고 로그도 남김). 해결은 컬럼 재생성 또는 모델 교체(운영 결정).

## OUT
- 위 경계의 자동 해소(컬럼 마이그레이션 도구·모델별 컬럼 차원 저장). arctic query-prefix 주입(158 OUT).
- broker.py:810·931의 resolve_backend 이벤트루프 직접 호출(기존부터 Memory.from_config를 루프에서
  실행 — 이번 probe는 타임아웃으로 상한). to_thread 전환은 별개 후속.

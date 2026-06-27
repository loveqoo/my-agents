# 026 — RAG 인제스트(스펙 036) 회고

P2-a. 컬렉션 + 문서 업로드 → 파싱(pypdf/UTF-8) → 청킹(Recursive 1000/200, 컬렉션별 가변)
→ 임베딩(OpenAI 호환 `/embeddings`) → pgvector(`vector(N)`) 적재. retrieval은 037.

## 무엇을 했나
- **죽은 카탈로그 재생**: mock `vector_tables`를 실 저장소 3종(`collections`/`documents`/`rag_chunks`)으로
  교체. embedding_model FK는 RESTRICT(차원 정합 보장), doc/chunk는 CASCADE. HNSW cosine 인덱스(037용).
- **차원 트랩 3중 가드**(스펙 020 함정3 계승): ①생성 probe→409 ②인제스트 벡터 길이 검증→status=error
  ③health 3자 비교(DB컬럼/Collection박제/모델probe). `RAG_EMBED_DIMS`가 컬럼 차원·허용 차원의 단일 출처.
- **결정적 검증 경로**: mock `/embeddings`가 입력 1건당 `RAG_EMBED_DIMS` 벡터를 반환하도록 고쳐
  라이브 MLX 없이 happy-path 인제스트를 인프로세스로 돌림(스펙 024 mock 철학 계승).
- **프론트**: CollectionsView(목록/생성 모달/문서 Drawer/health) + 내비 배선, BlocksView의 깨진
  embedding(vector-tables) 카테고리 제거.

## 잘된 것
- **타자 검증이 결정적이었다.** 내 `verify_036` 스크립트는 ✅ ALL PASS였지만 happy-path·cascade·가드만
  훑었다. 적대적 서브에이전트 + codex(gpt-5.5)를 **독립 병렬**로 돌리니 **5개 결함에 수렴**:
  ①좁은 `except IngestError`(crypto.decrypt·최종 commit 실패 시 doc가 `parsing`에 방치 + 500 —
  "no silent death" 약속 위반) ②가드2가 **컬럼 진실원(RAG_EMBED_DIMS)이 아닌 사본(c.dims)**을 검사
  →drift 시 DB insert 500 ③`embed_texts`가 index 정렬을 맹신 →중복/누락 index면 text↔vector 조용히 오정렬
  ④비원자 `c.chunk_count += N` →동시 인제스트 lost update ⑤무제한 `file.read()` →OOM. 전부 수정 +
  스키마 경계(chunk_size>0) 추가 후 재검증 통과.
- 두 검증자 **수렴**은 거의 확실한 real bug 신호였다(한쪽만 지적했으면 과대평가 의심했을 것).

## 막힌 것 / 교훈
- **MissingGreenlet 재발 방지**: rollback 후 expire된 ORM 접근이 동기 lazy-load를 유발. ingest는
  `doc_id`를 try 전에 박제 후 `session.get`으로 재취득, cleanup·삭제는 `passive_deletes`+DB CASCADE에
  의존(ORM delete-orphan cascade의 동기 load 회피). 이 패턴은 이제 정착.
- **가드를 짜도 사본을 검사하면 함정이 다시 열린다** → learning [[035-guard-the-source-not-the-copy]].

## 남긴 빚(의도적, 037 또는 이후)
- index 정합 수정(#3)은 코드만 들어가고 유닛 테스트 미작성(httpx 목 필요) — 리뷰로 커버.
- delete 시 error-상태 컬렉션의 status 재조정은 best-effort(마지막 문서 제거 시만 empty 전환).
- `token_count = len(t.split())`는 CJK에서 무의미(기능 미사용 — 표시용 메타). 037 retrieval에서 재검토.
- PDF 판별이 content-type/확장자(클라 제공) 신뢰 — 둘 다 IngestError로 수렴하므로 허용.
- antd Drawer `width` deprecation 경고(→`size`는 커스텀 px 미지원) — 비차단, 유지.

## 검증
- 백엔드 수치: `verify_036_rag_ingest.py` ✅ ALL PASS(헬퍼 단위·생성음성·happy 멀티청크·가드2·health·CASCADE·스키마경계).
- UI: Playwright+시스템 Chrome(`shot-collections-036.mjs`) — 목록 4건/생성 모달(임베딩 모델 드롭다운
  기본 선택)/문서 Drawer(업로드+설정)/vector-tables 누출 없음 눈으로 확인.
- 타자: 적대적 서브에이전트 + codex 수렴 → 5건 수정.

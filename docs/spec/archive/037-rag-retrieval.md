# 037 — RAG Retrieval (P2-b): 죽은 `vectorTables` 필드를 검색 도구로 부활

> 상태: AI 초안 (인간 검토 대상). 지배 로드맵: `docs/spec/033-feature-roadmap.md` P2 #10.
> 선행: 036(RAG 인제스트, 쓰기 경로 완료). 본 스펙은 **읽기 경로**(질의 → 유사도 검색 → 에이전트 도구 배선).

## 1. 문제 — `vectorTables`는 죽은 필드다

- `AgentConfig.vectorTables`(컬렉션 이름 리스트)는 저장만 되고 **런타임이 소비하지 않는다**
  (`chat.py`/`runtime.py` grep 0). 에이전트가 컬렉션을 골라도 검색에 쓰이지 않는다.
- 프론트(`AgentsView.tsx`)의 벡터테이블 편집기는 **036에서 제거된 `blocks.embedding`**를 소스로 읽어
  항상 비어 있고, **mem0 장기기억 토글에 잘못 종속**돼 있다(RAG ≠ mem0).
- 036에서 실 저장소(`collections`/`documents`/`rag_chunks` + HNSW cosine 인덱스)와 인제스트가 완성됐고,
  읽기 경로만 비어 있다.

## 2. 목표

에이전트가 고른 컬렉션을 **에이전트 호출형 retrieval 도구**(`search_documents`)로 런타임에 배선한다.
모델이 근거가 필요하다고 판단하면 도구를 호출 → 질의를 **그 컬렉션의 임베딩 모델로** 임베딩 →
pgvector HNSW **cosine** 유사도 검색 → 상위 청크를 모델에 반환. 호출은 Playground 인스펙터 trace에 남는다.

### 설계 결정 (이전 스펙에서 이미 방향 확정)

- **도구형 vs 항시 주입**: **도구형** 채택. 로드맵 033/스펙 036(line151)이 일관되게 "retrieval **도구**"로
  명시. 메모리 회상(항시 주입)과 달리 문서 청크는 크다 — 항시 top-k 주입은 프롬프트를 부풀린다.
  모델이 필요할 때만 당기게 한다. (대안: 항시 주입 — 작은 로컬 모델이 도구 호출을 빠뜨릴 위험이 있으나,
  현재 mem0 `save_agent_knowledge` 도구도 같은 가정 위에 동작하므로 일관성 유지.)
- **질의 임베딩은 컬렉션 자신의 임베딩 모델로**: 인제스트 때 쓴 모델과 **반드시 동일**해야 cosine이
  의미를 가진다. `RAG_EMBED_DIMS`로 컬럼 차원은 공유되지만, 모델이 다르면 벡터 공간이 달라 검색이 무의미.
  여러 컬렉션이 서로 다른 모델을 쓸 수 있으므로 **(base_url, model_id)별로 질의 임베딩을 캐시**해 호출.
  → learning [[035-guard-the-source-not-the-copy]] 정신: 진실원(인제스트 모델)을 직접 따른다.
- **top_k 기본 4**, 최대 10 클램프. **음수 유사도(cosine 거리>1 = 반-상관) floor**만 적용 — 수학적
  경계라 정상(양수) 매치는 절대 탈락 안 함. 양수 구간 임계 튜닝은 모델별 분포 상이로 빚(§7).
- **로컬(web) 에이전트 전용**: code(원격 프록시)·external(A2A)은 비로컬이라 미적용(기존 분기 bypass 보존).

## 3. 백엔드

### 3.1 `runtime.build_rag_tool(collections, calls_sink) -> StructuredTool`
- `collections`: `_load_context`가 해석한 dict 리스트
  `{id, name, embed_base_url, embed_api_key(복호화됨), embed_model_id}`.
- 비동기 도구(`StructuredTool.from_function(coroutine=_search, ...)`). 입력: `query`, `top_k=4`.
- 동작:
  1. 빈 query → 안내 문자열 반환(크래시 금지).
  2. `(base_url, model_id)`별 1회 `rag_ingest.embed_texts(..., [query])` → 질의 벡터(캐시).
  3. `SessionLocal()`로 컬렉션별 `select(Chunk.text, Document.filename,
     Chunk.embedding.cosine_distance(qvec).label("dist")).join(Document)
     .where(Chunk.collection_id == cid).order_by("dist").limit(k)`.
  4. 컬렉션 간 결과를 dist로 통합 정렬 → 상위 k → 번호 매긴 텍스트(파일명·거리 포함) 반환.
  5. 결과 없음 → "관련 문서를 찾지 못했습니다."
  6. 임베딩/DB 실패 → IngestError 등을 잡아 graceful 메시지 + `calls_sink` status="error"(no crash).
  7. `calls_sink.append({server:"rag", tool:"search_documents", status, ms, args:{query,top_k}, result})`.

### 3.2 `chat.py` `_load_context` 배선
- `cfg.get("vectorTables", [])` 추출. 로컬 에이전트 + 비어있지 않을 때만:
  `select(Collection).where(Collection.name.in_(names))
   .options(selectinload(Collection.embedding_model).selectinload(ModelConfig.provider))`
  → provider 없는/불완전 컬렉션은 skip(graceful). `crypto.decrypt`로 키 박제. `ctx["rag_collections"]`.

### 3.3 `chat.py` `chat()` 도구 주입
- `if ctx["rag_collections"]: tools.append(runtime.build_rag_tool(ctx["rag_collections"], calls_sink))`.
- RAG 호출은 `calls_sink`에 쌓여 `assemble_trace`의 `mcp` 배열·`tools` 그래프 노드로 노출(추가 작업 0).
- `trace["ragCollections"] = [names]`로 구성된 컬렉션을 인스펙터에 표시(호출 안 해도 가시).

## 4. 프론트 (`AgentsView.tsx`)

- 벡터테이블 편집기 소스를 **`GET /collections`(실 컬렉션)**로 교체. `blocks.embedding` 의존 제거.
- **mem0 종속 해제**: `form.memories.includes('장기 기억 (mem0)')` 게이트 제거 — RAG는 독립 기능.
  (게이트는 컬렉션 존재 여부로 대체하거나 항상 노출.)
- 라벨/설명을 "지식 소스(RAG 컬렉션)"로 갱신, 각 항목에 임베딩 모델·청크 수 표시.

## 5. 검증 (자가검증 지양 — 036 교훈 계승)

1. **수치(인프로세스, 결정적) — ✅ ALL PASS**: `tests/verify_037_rag_retrieval.py` —
   mock 임베딩 컬렉션 생성 → 036 인제스트로 청크 적재 → `build_rag_tool` 호출:
   (a) exact-match 질의가 유사도 1.000으로 1위 + **변별**(비-exact는 <1, mock 입력의존 벡터로 랭킹 실증),
   (b) 정렬 불변식(유사도 비증가), (c) 빈 query graceful + status=error,
   (d) 무매치 graceful, (e) top_k 클램프 + floor 내 전건 반환(starvation 0), (f) 멀티 컬렉션 통합 정렬,
   (g) 임베딩 실패 graceful, (h) **음수 유사도 floor**(반-상관 청크 제외 → 전부 ≥0).
   - 결정적 트릭: mock `_det_embedding`(sha256 시드)가 입력 1건당 결정적 벡터 → 동일 텍스트=거리 0=유사도 1.000.
     (이전 상수 `[0.1]*dims`는 전부 1.000이라 랭킹을 증명 못 함 — learning 035 "녹색 검증≠견고".)
   - `_sims` 정규식은 **음수 부호 필수**(`유사도 (-?[\d.]+)\)`): 누락 시 음수 라인이 통째로 빠져 반환 수를
     과소집계 → 과거 'HNSW starvation' 오진의 실제 원인이었음(probe-deeper). pgvector 버그 아님.
2. **UI(브라우저, 능동) — ✅**: `tests/browser/shot-agents-037.mjs`(Playwright+시스템 Chrome) —
   에이전트 편집 폼에 '지식 소스 (RAG 컬렉션)' 필드가 **mem0 미선택 상태에서도** 뜨고 실 컬렉션 4개
   (임베딩 모델 · 청크 N개)를 렌더 → 회귀(과거 mem0 게이트+죽은 blocks.embedding 소스) 해소 확인.
   - 한계: trace 인스펙터의 `search_documents` 노출은 **브라우저로 미실증** — mock-llm이 툴 호출을
     안 함(단일턴, tool-call 미지원). `calls_sink`/`_record` 계약은 수치검증 (a)(c)(d)(e)로 직접 단언함.
3. **타자(적대적, 병렬) — ✅ 수렴**: 서브에이전트 + codex 독립 병렬 리뷰. **비밀 누출 0**으로 양측 수렴
   (decrypt 키는 calls_sink/trace/반환문/IngestError 어디에도 미노출 — 상태코드만). 수정한 수렴 결함:
   (1) `top_k` 방어적 강제(비정상 인자도 _record 전 크래시 금지), (2) **음수 유사도 floor**(반-상관 근거 차단),
   (3) 미해석 vectorTables 관측성(요청 vs 해석 차를 `trace["ragUnresolved"]`+log.warning으로 노출).
   멀티모델 통합 정렬은 빚으로 유지(§7).

## 6. 완료 조건

- [x] `vectorTables` 설정 에이전트가 채팅 시 `search_documents`로 컬렉션을 실제 검색(도구 배선 + 수치검증).
- [x] 질의가 **컬렉션 자신의 임베딩 모델**로 임베딩됨(인제스트와 동일 공간) — `(base_url,model_id)`별 캐시.
- [x] trace 인스펙터에 RAG 호출 노출(`trace["ragCollections"]` + `calls_sink` server="rag"; 수치검증으로 단언).
- [x] UI에서 실 컬렉션 선택(mem0 비종속) — 브라우저로 시각 확인.
- [x] verify_037 ALL PASS + 브라우저 확인 + 타자 수렴 결함 수정.

## 7. 빚 (의도적, 이후)

- e5 계열 query/passage 프리픽스 미적용(인제스트도 미적용 → 양측 일관). 검색 품질 개선은 이후.
- **양수 구간 관련도 임계(threshold) 튜닝 미적용** — 음수 유사도(반-상관)는 floor로 컷하지만, 양수
  저관련(예 0.3 미만) 컷은 recall 트레이드오프가 있어 실데이터 기반 튜닝으로 이후. (음수 컷은 임의
  임계가 아니라 수학적 경계라 v1에 적용함.)
- `token_count` CJK 무의미(036 빚) — 표시용, 검색에 미사용.
- **멀티모델 통합 정렬** — 서로 다른 임베딩 모델 컬렉션을 한 에이전트가 동시에 쓰면 dist를 다른 벡터
  공간끼리 단순 비교·정렬하므로 순위가 무의미해진다. 강제 방지(에이전트당 단일 모델) 또는 스코어
  정규화는 후속 스펙. (타자 양측 지적; 비권장 구성이라 v1은 빚으로 기록.)
- 미해석 vectorTables는 `trace["ragUnresolved"]`로 노출만 — 자동 정리(설정에서 죽은 이름 제거)는 이후.

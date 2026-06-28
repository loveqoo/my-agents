# 048 — RAG 임베딩 모델 게이팅 + 조건부 샘플 적재

마스터: `044`(2026-06-28 어드민 테스트 14건) 배치4 — **#9 RAG 빈 컬렉션**.
사용자 결정(2026-06-28, AskUserQuestion 후속): **"임베딩 모델 설정이 있는 경우만 샘플 적재.
또한 임베딩 모델이 있을 때만 해당 메뉴의 모든 동작이 가능해야 한다."**

## 문제 (#9)
어드민 테스트에서 RAG 컬렉션 4개가 전부 비어 있어 **고장처럼** 보였다. 실제로는 인프라가
완비(ingest/embed/search 전부 wired)돼 있고, 컬렉션은 사용자가 문서를 업로드해 채우는 빈
플레이스홀더다. 근본 결함은 **임베딩 모델 의존성이 UI에 드러나지 않아** 빈 상태의 의미가
모호한 것. 시드 컬렉션은 `multilingual-e5-large`(MLX local)에 묶여 있어 MLX 서버가 떠야 적재된다.

## 결정 — 임베딩 모델 가용성을 RAG의 전제조건으로 명시
사용자 원칙을 척추로 삼는다. "가용" = **embedding-kind ModelConfig가 최소 1개 존재**(존재 게이트).

1. **메뉴 게이팅(프론트, 강화·일관화)** — embedding 모델 0개면:
   - 상단에 명확한 배너(Alert): "임베딩 모델이 없어 RAG 동작이 비활성화됩니다 — 프로바이더·모델에서
     임베딩 모델을 먼저 등록하세요." → 빈 컬렉션이 "고장"이 아니라 "전제조건 미충족"으로 읽힌다.
   - `컬렉션 생성` 버튼 **disabled**(현재는 클릭 후 경고만 — 클릭 전에 막아 일관화).
   - 문서 업로드도 모델 없으면 비활성(드로어). 단, 데이터 모델상 컬렉션은 생성 시 FK로 모델이
     이미 고정되므로 "컬렉션이 있는데 모델이 0개"는 RESTRICT로 사실상 불가 — 배너는 **생성 진입점**
     게이팅이 핵심.
2. **백엔드(이미 게이팅 — 확인·보강)** — `create_collection`은 `embedding_model_id` FK 필수+
   `kind=embedding` 검사(rag.py:93-97). ingest는 컬렉션의 모델로만 임베딩. 모델 미존재 시 생성 자체가
   막히므로 백엔드 추가 게이트는 불필요. **회귀 검증으로 고정**만 한다.
3. **빈 컬렉션 정의 명확화(#9)** — 두 가지 빈 상태를 구분해 표기:
   - *모델 있음 + 문서 0* = "비어 있음 — 문서를 업로드하세요"(정상 대기).
   - *모델 0개* = RAG 비활성(위 배너). 컬렉션 자체가 만들어질 수 없음.

## 조건부 샘플 적재 — 대표 컬렉션을 결정적으로 채운다
"임베딩 모델 설정이 있는 경우만" 적재. 결정적·MLX 비의존을 위해 **대표 컬렉션 `docs_kb`를
`mock-embed`에 바인딩**한다(스펙 024가 이 용도로 만든 모델 — `/_remote/v1/embeddings`가
`RAG_EMBED_DIMS`=1024 결정적 벡터 반환, 라이브 MLX 불필요). 나머지 3개(product_titles·
support_tickets·team_notes)는 MLX default 유지 = **실데이터 대기 플레이스홀더**.

- **seed.py**: `docs_kb`만 `mock-embed` 모델로 바인딩(나머지는 기존 default). 같은 트랜잭션에서
  mock-embed 모델을 조회. mock-embed가 없으면(=embedding 모델 전무) 컬렉션 시드도 스킵(게이트 일관).
- **샘플 적재 스크립트** `packages/api/scripts/ingest_rag_samples.py`(신규, 멱등):
  - 번들된 샘플 문서 4~5개(헬프센터 주제 텍스트) → 실행 중 API의 **실 인제스트 엔드포인트**
    `POST /collections/{id}/documents`로 적재(쿠키 인증). extract→chunk→embed(mock)→pgvector 전 경로.
  - 멱등: 대상 컬렉션 `doc_count>0`이면 스킵. 대상은 mock-embed 바인딩 컬렉션(기본 `docs_kb`).
  - 적재 후 검색 1회 호출로 동작 확인(샘플 텍스트 쿼리 → 해당 청크 1위).
  - **본 세션에서 라이브 DB에 직접 실행**해 어드민이 즉시 populated 상태를 본다.

## 실행 순서
A. seed.py `docs_kb`→mock-embed 바인딩 + (이미 mock-embed 시드됨 확인).
B. 샘플 문서 번들 + `ingest_rag_samples.py` 작성 → 라이브 실행으로 docs_kb 적재.
C. CollectionsView 게이트 강화(배너 + 생성 버튼 disabled + 업로드 게이팅).
D. 검증(아래).

## 검증 (자가 + 타자)
1. **샘플 적재 통합**(실 DB + 실 HTTP, self-fixture — learning 045): 자체 mock-embed 컬렉션 생성 →
   샘플 문서 ingest → status=ready, chunk_count>0, 임베딩 dim=1024. 검색 쿼리=샘플 텍스트 → 1위 매칭
   (결정적 mock 벡터라 cosine 변별 행사). 정리.
2. **게이트 회귀**: embedding 모델 0개 시 create_collection이 막히는지(FK/kind), 모델 존재 시 통과.
3. **멱등**: 스크립트 재실행이 중복 적재 안 함(doc_count 불변).
4. **036/037 회귀**: 기존 RAG ingest/retrieval 불변.
5. **타자(적대 서브에이전트)**: 샘플 적재가 비결정·중복 적재? 게이트가 우회 가능(모델 0개인데 생성)?
   docs_kb mock 바인딩이 Research Assistant 에이전트 retrieval을 깨나? 빈 컬렉션 표기가 여전히 모호?
   샘플 문서에 비밀/PII? 스크립트가 인증 우회/SSRF?
6. **브라우저**(Playwright): CollectionsView에서 docs_kb가 populated(문서·청크>0, status ready)로
   보이고, 모델 있는 빈 컬렉션과 구분 표기. (모델 0개 게이트는 모델 삭제가 어려워 단위/통합으로 대체.)

## 검증 결과 — 전부 GREEN (2026-06-28)

| Rung | 수단 | 결과 |
|---|---|---|
| 단위 | `verify_048` A: 게이트 헬퍼 `_collection_seed_specs`(embs=[]→[], 이름매칭, 기본/첫번째 폴백, **chat 제외**) | ✅ A1–A5b |
| 통합 | `verify_048` B: 실 번들 샘플 4개 self-fixtured 적재→ready·chunks>0·dims=1024, 첫 청크 질의→1위 유사도 **1.000**(결정적), B4 **참조모델 삭제 409**, **chat/ghost id 생성 400**(서버 게이트 잠금) | ✅ B1–B4 |
| 통합(라이브) | `ingest_rag_samples.py` 라이브 실행 → docs_kb 4문서/4청크 ready, 검색 hits=3 스니펫매칭 OK | ✅ |
| 멱등·자가치유 | 재실행=전부 스킵(0적재); 문서 1개 삭제(부분상태)→재실행이 **그 1개만** 재적재(파일명 단위) | ✅ |
| 회귀 | `verify_037`(retrieval) ALL PASS, `verify_047`(delete_model) ALL PASS | ✅ |
| 프론트 | `tsc --noEmit` exit 0; Alert `message`→`title`(antd6 deprecation 제거) | ✅ |
| 브라우저 | populated docs_kb=준비됨/4·4 캡처; 게이트 양성 케이스(route 가로채기로 모델 0개)→**배너 표시 + 생성버튼 disabled** | ✅ |
| 타자 | 적대 서브에이전트 리뷰 — CLAIM1 SURVIVES, **CLAIM2 REFUTED**(아래 수정) | ✅ 수정완료 |

### 적대 리뷰가 잡은 결함(수정 완료)
- **#5 MAJOR (CLAIM2 반증)** — 멱등성을 `doc_count>0`에 걸어, 부분 실패 적재(일부 status=error)면
  doc_count>0이라 "이미 적재됨"으로 스킵 → 미완성인데 populated라 주장. **수정**: doc_count 게이트
  제거, *실제 ready 파일명 집합* 기준 멱등(ready 스킵·error 삭제 후 재적재·없으면 적재). 부분상태
  자가치유를 라이브로 실증(1개 삭제→1개만 복구). → learning [[idempotency-on-success-counter-misses-partial]].
- **#1 MINOR** — embedding 모델 삭제 시 Collection FK(RESTRICT)가 IntegrityError 500을 냄. **수정**:
  `delete_model`에 Collection 참조 선검사 추가 → 깔끔한 409(047 패턴과 일관). verify_048 B4로 잠금.
- **#3 MINOR** — `models`=[] 초깃값 탓에 로딩 중 게이트 배너 false-positive 플래시. **수정**: `loaded`
  플래그 추가, `noEmbedModel = loaded && !models.length`.
- **#4 MINOR** — 게이트 헬퍼가 호출자 필터에만 의존(미래 무필터 호출자가 chat 바인딩 위험). **수정**:
  헬퍼 내부에서도 `kind=="embedding"`만 통과(getattr 폴백으로 단위 테스트 호환). A5/A5b로 잠금.
- **#8 NIT** — 검색 자가테스트가 `order_by(ordinal)`만 써 문서 간 ordinal=0 동률에서 비결정. **수정**:
  `order_by(ordinal, id)` tiebreak.
- 부수: docs_kb 설명 self-heal — 적재됐는데 "업로드해 채우세요"라 말하던 옛 시드 문구를 어느 경로든
  `TARGET_DESC`로 교정(populated 정직 표기).

## §7 빚·한계
- docs_kb가 mock-embed로 바인딩 → 그 컬렉션 검색은 결정적 mock 벡터 기반(의미 유사도 아님, 데모용).
  실 의미검색은 MLX 바인딩 컬렉션에 실문서 업로드 시. 트레이드오프 명시(라이브 비의존 데모 우선).
- 샘플 적재는 스크립트 실행 기반(시드-타임 자가 HTTP 호출은 startup 리스닝 전이라 취약 → 회피).
  멱등이라 재실행 안전. 시드에 자동 편입은 비범위.
- 게이트는 "모델 존재"(existence) 기준. "모델 reachable" 게이트는 비범위(probe는 생성·health에서).

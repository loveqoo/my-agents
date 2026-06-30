# 072 — RAG retrieval 시험 수단: 공유 검색 코어 + `/search` 엔드포인트 + 관리 UI 패널

## 배경 (사용자 보고: "rag는 등록만 있지 테스트 방법이 없어")

현 상태 측정(추측 아님):

- **인제스트**(036/048)·**에이전트별 연결**(037: config `vectorTables` + `AgentsView` "지식 소스" 체크박스)은
  이미 동작한다. → **에이전트 설정에 RAG 연결 기능은 신규 불요**(이미 있음).
- **공백**: retrieval을 *직접* 시험할 수단이 없다. 지금 retrieval을 돌리는 길은 두 개뿐 —
  ① 에이전트 채팅 전체를 돌림(무겁고 간접적), ② Python 테스트(`verify_037`)에서 `runtime.build_rag_tool`을
  직접 import(사용자 접근 불가). HTTP retrieval 엔드포인트가 없고(`rag.py`는 ingest/write 전용),
  관리 UI에 "질의 시험" 패널이 없다(`CollectionsView.tsx:3`이 명시적으로 후속 스펙으로 미룸).

즉 "컬렉션 X에 질의 Q를 던지면 어떤 청크가 어떤 유사도로 나오나"를 등록 직후 즉석 확인할 길이 없다.

## 목표 (완료 조건 — 측정 가능)

**P1. 공유 검색 코어 추출 (drift 방지의 핵심).** `build_rag_tool`의 retrieval 본체(질의 임베딩
per-model 캐시 → pgvector cosine → 음수 유사도 필터 → 통합 정렬 → 상위 k)를 **구조화 hit를 반환하는
재사용 함수**로 떼어낸다. `build_rag_tool`은 이 코어를 호출해 **기존과 동일한 문자열**을 포맷한다(거동 보존).

- `runtime.search_collections(collections, query, top_k) -> list[dict]` 신설.
  반환 각 hit: `{"score": float, "filename": str, "text": str}` (score = `1 - cosine_distance`, 내림차순).
  실패(임베딩 서버 다운·DB 오류·빈 질의)는 **예외로 올린다**(`RagSearchError` 등) — 호출자가 포맷/응답을 정함.
- `build_rag_tool`은 `search_collections`를 호출 → 같은 문자열(`[문서 검색 결과 N건] … (파일, 유사도 …)`)
  + `calls_sink` 기록 유지. **회귀 가드: 기존 `verify_037`이 그대로 그린**이어야 한다(거동 불변 증명).

**P2. retrieval 시험 엔드포인트.** `POST /collections/{cid}/search` 신설(`rag.py`).

- 입력 `{query: str, top_k: int=4}`. 단일 컬렉션 대상(`cid`).
- 컬렉션 로드 → embedding 모델/provider **완전성 검사**: 불완전(`base_url`/`model_id` 없음)이면
  **400**(graceful, "이 컬렉션은 임베딩 provider 설정이 불완전해 검색할 수 없습니다"). 차원 drift는 health(가드3)가 담당.
- search dict 구성(provider api_key **복호화는 백엔드 전용**, 응답에 절대 미포함) → `search_collections` 호출.
- 응답 `{"results": [{"score", "filename", "text"}], "query": str, "top_k": int}`. 관련 0건이면 `results: []`.
- `top_k`는 코어가 1..10으로 clamp(도구와 동일 불변식). 빈 질의는 **422/400**(엔드포인트는 도구와 달리
  사용자 직접 입력이므로 명시적 검증; 도구의 graceful 문자열과 달리 HTTP 상태로).

**P3. 관리 UI "검색 시험" 패널.** `CollectionsView.tsx`에 컬렉션별 "검색 시험" 액션.

- 질의 입력 + top_k(기본 4) → `POST /collections/{id}/search` 호출 → 결과를 **순위·유사도·파일명·스니펫**
  테이블로 렌더. 빈 결과/에러는 antd 알림으로 표시.
- 등록(업로드) 직후 같은 화면에서 바로 품질 확인 가능 → 사용자 보고 공백을 닫음.
- `CollectionsView.tsx:3`의 "retrieval UI는 후속 스펙" 주석을 갱신(이 스펙이 그 후속).

## 설계

### 경계 / 재사용 (drift 방지)
- **production 동일 경로 불변**: 시험 엔드포인트가 평행 검색 구현을 새로 짜면 도구와 drift나
  "엔드포인트는 초록인데 에이전트 채팅은 다름"이 된다. 그래서 P1의 공유 코어를 **양쪽이 호출**한다.
  (memory verification-ladder-three-rungs / move-breaks-references 계열: 검증은 *실제 쓰이는 경로*를 타야 함.)
- search dict 구성은 `_load_context`(chat.py:197-205)와 동형이나, 엔드포인트는 단일 컬렉션을 `cid`로
  직접 로드하므로 그 1건만 만든다(`_load_collection`이 이미 embedding_model·provider eager-load).
  4줄 dict 구성이 두 곳(chat.py·rag.py)에 생기면 추출(`_collection_search_dict(c)`)을 고려 — 단 과추출 경계.

### `runtime.py`
- `search_collections(collections, query, top_k)` — 위 본체를 떼어 구조화 리스트 반환. 음수 유사도 필터·
  통합 정렬·상위 k 로직 보존.
- `build_rag_tool._search` — 코어 호출 후 `[문서 검색 결과 …]` 문자열 포맷 + `calls_sink` 기록만 담당.

### `rag.py`
- `POST /collections/{cid}/search` + 응답 스키마 `CollectionSearchIn`/`SearchHit`/`CollectionSearchOut`(schemas.py).
- 완전성 검사 후 `crypto.decrypt`로 키 복호화(응답 미노출), `search_collections` 호출.

### `CollectionsView.tsx`
- "검색 시험" 버튼/드로어 + 결과 테이블. 기존 DocsDrawer 패턴 재사용.

## RBAC 체크리스트 적용 여부
**미적용** — RAG 테이블(Collection/Document/Chunk)에 `user_id`·테넌트 컬럼 없음, `_own_scope`·
`_visible_or_404`·`_assert_*owns` 헬퍼 무관(컬렉션은 전역 행). 트리거 객관 신호 부재(self-judgment 아님 —
docs/spec/CLAUDE.md 트리거 기준). 읽기 전용 retrieval이라 소유권 경계 무관(스펙 071과 동일 판정).

## 검증 사다리 3런 (069 항목 5, 비겹침)

1. **단위 시맨틱** (`tests/verify_072_rag_search.py`): `search_collections` 직접 호출 —
   exact-match→score≈1.000 rank1 / 내림차순 불변 / `top_k=999` clamp≤10 / 빈 질의→예외 / no-match→[] /
   멀티컬렉션 통합. + 엔드포인트 레벨: 불완전 provider→400, 빈 질의→422/400, 정상→구조화 JSON·api_key 미노출.
2. **실 인프라 통합**: mock-embed 샘플(048 경로)로 컬렉션 시드 → 실 DB 상대로 `POST /collections/{id}/search`
   호출 → 저장 청크가 score순으로 반환·필드 정확 확인. + **회귀: `verify_037` 그대로 그린**(P1 거동 보존 증명).
3. **적대 codex** (rung 3): "보장 목록의 여집합". (a) 엔드포인트가 도구와 *정말 같은 코어*를 타나(drift),
   (b) 응답에 api_key/내부 식별자 누출 없나, (c) query injection·top_k 남용·거대 query로 자원 고갈,
   (d) 빈/유니코드/초장 query 경계, (e) 불완전 provider·삭제된 모델에서 graceful한가.

## 적대 검증 결과 (rung 3 — codex 읽기전용 리뷰)

- **P1 치명: 없음.** codex 확인 — `build_rag_tool`이 *실제로* `search_collections`를 호출(drift 부재,
  평행 검색 분기 없음), api_key 누출 없음(복호화 키는 내부 dict에만, `SearchHit`/`CollectionSearchOut`엔
  미포함; `IngestError`도 HTTP body 버리고 상태코드만 메시지화), 빈 질의·무매치·실패 record label·
  stripped query args·음수 유사도 필터·정렬/슬라이스 모두 보존.
- **P2 #1 (봉인): query 길이 상한 부재.** 직접 POST라 LLM 입력 한계에 기댈 수 없음 — 거대 query로 API 메모리·
  임베딩 provider 60초 점유 가능. → `CollectionSearchIn.query`에 `max_length=4000` 추가. 테스트 B6(>4000→422,
  =4000→200)로 봉인.
- **P2 #2 (봉인): 컬렉션 참조 모델이 나중에 chat kind로 바뀌면 502로 뭉개짐.** `update_model`(PUT)이 kind를
  그대로 변경하는데(model_registry.py:195) 엔드포인트 완전성 검사는 base_url/model_id만 봄. → 엔드포인트에
  `if em.kind != "embedding": raise HTTPException(400, …)` 가드 추가. 테스트 B7(모델 kind→chat 변경 후 검색→400)로 봉인.
- **P3 (수용): 응답 `top_k`가 effective clamp 값이 아니라 요청값 echo.** 스키마 `le=10`이라 실사용 버그 없음
  (큰 값은 422), `results` 배열 길이가 실제 반환 건수. 계약상 drift 여지만 있어 과교정 않고 정직히 기록.

## 완료 체크
- [x] P1 `search_collections` 추출 — 구조화 hit 반환, `build_rag_tool` 거동 보존(`verify_037` 그린)
- [x] P2 `POST /collections/{cid}/search` — 완전성 검사·복호화 백엔드 전용·api_key 미노출·top_k clamp·빈질의 4xx·kind 가드·길이 상한
- [x] P3 `CollectionsView` 검색 시험 패널 — 순위·유사도·파일명·스니펫 테이블, 주석 갱신
- [x] 단위 매트릭스 그린(verify_072 32건) + 라이브 통합 그린 + `verify_037` 무회귀
- [x] 적대 codex P1 없음, 발견 triage 기록(P2×2 봉인 + 테스트 커버, P3 수용)

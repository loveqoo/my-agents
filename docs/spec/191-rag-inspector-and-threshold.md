# 191 — RAG 인스펙터 가독성 + **컬렉션별** 유사도 임계값(필터)

> **v2 피벗(2026-07-06)**: 처음엔 에이전트당 임계값 1개(`ragMinScore`)로 구현했으나, 사용자가 추가로
> "문서 검색 유사도는 **Rag(컬렉션)마다** 지정"을 요구 → **컬렉션별 맵**(`ragMinScores: {컬렉션명:0~1}`)으로
> 재설계. 아래 설계 본문은 v1 흔적이 남아 있고, 최종 구현은 "실행 결과 v2"를 참조.

## 배경 (실사용 접수 2건)
1. **문서검색 결과가 보기 불편** — 인스펙터가 `format_rag_hits`의 결과 텍스트를 **한 덩어리**로 뿌린다
   (`Inspector.tsx:164` 직접 RagCall / `:503` 브로커 접이식 pre). 문서 간 구분·강조가 없어 스니펫
   (각 최대 500자)이 벽처럼 이어져 스캔이 어렵다.
2. **"유사도 낮음"의 기준이 안 보임** — "관련도 낮음" 태그는 `topScore < 0.5`(하드코딩)일 때 뜨는데,
   화면이 그 기준도, 척도(0~1, 1=완전 일치)도 안 알려줘 "0.42가 낮은 건가?"를 알 수 없다.

## 사용자 결정 (2026-07-06)
- 임계값은 **실제 필터링**(권장) — 미만 문서는 에이전트가 아예 안 봄(답변 품질↑). 인스펙터에도 기준선 표시.
- **에이전트 생성 시 RAG(문서) 선택 옆에서** per-agent로 설정. 기본값 0 = 무필터(하위호환).

## 설계

### A. 필터 (검색 코어)
- `runtime.search_collections(collections, query, top_k, min_score=0.0)` — 리트리브 후 `score < min_score`
  히트를 **드롭**(top_k 유지 후 후필터). 기본 0.0 = 무변화. score = 1−cosine_distance(내림차순).
- `runtime.build_rag_tool(collections, calls_sink, min_score=0.0)` — 통과 + sink에 구조화 기록(아래 B).
- 브로커(조율형): `RagProvider(session_factory, min_score=0.0)` → `PolicyScopedBroker(..., rag_min_score=)`
  → `build_broker(..., rag_min_score=)`. 두 경로가 **같은 코어**를 타 필터 일관(스펙 103 drift 0 규율).
- 배선: chat.py가 `cfg.get("ragMinScore")`를 direct(build_rag_tool)·orchestrate(build_broker) 둘 다 주입.

### B. 구조화 trace (히트별 → 카드)
- 직접 sink 엔트리에 `hitsDetail: [{score, filename, textPreview}]`(각 preview 캡) + `minScore` 추가
  (기존 `result` 텍스트·`hits` 수는 하위호환 유지 — 인스펙터가 hitsDetail 있으면 카드, 없으면 폴백).
- 브로커 `RagProvider.invoke` raw에 `hitsDetail`+`minScore` 추가 → broker.py 표시 메타 통과부에서
  `inv["hitsDetail"]`/`inv["minScore"]`로 surface(문서 본문은 여전히 표시 프리뷰만·과대 데이터 없음).

### C. 설정 왕복 (3지점, 스펙 190 동형)
- `AgentConfig.ragMinScore: float`(0~1, 검증기: 범위 밖·비수치 거부, 기본 0) + `AgentOut.ragMinScore` +
  `serializers.agent_to_out(ragMinScore=…)`.

### D. 화면 (AgentForm)
- "하는 일" 문서(RAG) 선택 영역 아래 **최소 유사도 슬라이더**(0~1, step 0.05, 기본 0). 라벨: "문서 검색 —
  최소 유사도". 도움말: "이 값 미만으로 유사한 문서는 무시합니다(0=무필터). 유사도는 0~1, 1=완전 일치."
  문서(컬렉션)를 하나라도 골랐을 때만 노출(조율형은 capabilities에 rag:* 있을 때).
- 저장: `config.ragMinScore`.

### E. 화면 (Inspector, 문서 검색 섹션)
- **히트별 카드**: 파일명 태그 + 유사도 배지(점수대 색: ≥0.7 green·0.5~0.7 default·<0.5 orange) +
  본문 프리뷰(길면 접기). hitsDetail로 렌더, 없으면 기존 텍스트 폴백(옛 trace 하위호환).
- **척도 범례**(섹션 상단 1줄): "유사도 0~1 (1=완전 일치)". minScore>0이면 "· 이 에이전트: 최소 {v} 미만 제외".
- "관련도 낮음" 판정 기준을 minScore 있으면 그 값, 없으면 기존 0.5로.

## 검증 (사다리)
- **단위**: `search_collections` min_score 필터(경계값·0=무필터·전부드롭→0건) · build_rag_tool sink에
  hitsDetail/minScore 실림 · format 공유 불변(drift 0).
- **e2e**: 어드민서 RAG 에이전트에 최소 유사도 설정→저장→API 왕복 보존 / 플레이그라운드 실행→인스펙터에
  히트 카드+척도 범례+기준선 노출(스샷). 필터로 저점수 문서 제외 확인.
- **무회귀**: 기존 RAG(072 retrieval 시험)·조율형 RAG(130)·verify_188·admin tsc 0.

## RBAC 경계 (체크리스트 트리거 판정)
- **트리거 아님**: ragMinScore는 유저별/테넌트 데이터(세션·메모리·승인)를 안 만진다. 에이전트 config 필드
  로 기존 에이전트 CRUD(owner 스코프)를 통해서만 쓰기. `user_id`·소유권 헬퍼 미접촉. 검색은 이미
  에이전트에 연결된 컬렉션만(신규 자원 입구 0). → 일반 기능 스펙. 단, 검증기로 형태(0~1)만 강제.

## 경계
- 필터는 top_k **후필터**(리트리브 자체는 top_k 유지) — 임계값 높으면 0건 가능(인스펙터가 "0건" graceful).
- 임계값은 전역 top_k와 독립(둘 다 per-agent 설정 아님 — top_k는 도구 인자 기본 4 유지). 컬렉션별
  개별 임계값 아님(에이전트 1개 값). 색 밴드(0.7/0.5)는 표시 heuristic(임베딩 모델 무관 고정).

## 실행 결과 — 완료·검증 (2026-07-06, v2 컬렉션별)
- **필터(검색 코어)**: `search_collections(..., min_scores: dict)` — 히트에 `collection` 태깅 후
  `_apply_min_scores`가 **컬렉션별** score≥임계값 판정(경계 포함·미설정/0=무필터·비정상값 방어).
  `_norm_min_scores`가 배선 컬렉션 한정+0제거. top_k 후필터(0건 가능, graceful).
- **배선**: direct `build_rag_tool(..., min_scores)` · 브로커 `RagProvider(sf, min_scores)`가 row.name으로
  그 컬렉션 임계값 조회 → `PolicyScopedBroker(rag_min_scores)` → `build_broker(rag_min_scores)`.
  chat.py `ctx["rag_min_scores"]=cfg.get("ragMinScores")`를 3 build_rag_tool + 1 build_broker에 주입.
- **구조화 trace**: 직접 sink `hitsDetail:[{collection,score,filename,textPreview}]`+`minScores(맵)`;
  브로커 raw `hitsDetail`+`minScore(scalar, 그 컬렉션)`+`query`. chat.py `_broker_calls_trace` 화이트리스트에
  hitsDetail/minScore/query 추가. verify_130 불변식 갱신(허용키 확장+hitsDetail 항목 검증).
- **누출 봉합(codex 적대검토)**: 히트 프리뷰·직접 result 모두 `_sanitize_preview`(비밀 마스킹+캡) —
  브로커 resultPreview와 **대칭**. codex가 짚은 "직접 result는 _cap만(마스킹 없음)" 비대칭을 닫음.
  (경계: `args.query`는 기존 `_redact_args` 계약 유지 — 검색 텍스트라 저위험, args 핸들링은 별도 스펙 087.)
- **스키마 왕복 3지점**: `AgentConfig.ragMinScores: dict[str,float]`(+검증기: 각 값 0~1·bool/문자열/빈키 거부)
  + `AgentOut.ragMinScores` + serializer.
- **화면**: AgentForm — 배선된 **컬렉션마다 슬라이더 1개**(0~1, step 0.05, 라벨=컬렉션명). Inspector —
  히트 카드(컬렉션 태그+파일명+점수대 색 배지+본문 접기) + 척도 범례("유사도 0~1…") + 컬렉션별 기준선
  + 검색어. AgentsView 왕복 3곳.
- **검증 사다리**: `verify_191_rag_threshold.py` 단위(F 컬렉션별 필터·N 정규화·D 히트+**D5 마스킹**·W
  직접배선+**W5 result 마스킹**·B 브로커·S 스키마) ALL PASS · `verify-rag-threshold-191.mjs` e2e(U 컬렉션별
  슬라이더 저작→P 맵 왕복→R1 필터 0건+검색어→R2 히트카드+범례+검색어) 15/15 · 무회귀(100·190·188·041·tsc0).
  실 화면 시각 확인(rag-thr-191-form/cards.png). **codex 적대검토**: 필터 로직 정확 확인, 마스킹 비대칭 1건
  지적→봉합.
- **mock 확장**: `mock_remote._TOOL_TRIGGERS`에 search_documents 트리거 추가(스펙 179 장치 확장) — RAG
  경로를 mock-llm으로 결정적 e2e 가능하게(query=user 텍스트).

## 기존 실패 테스트(내 변경 무관 — 격리 확인)
- `verify_072/103/037`(컬렉션 HTTP 생성 400)·`verify_130`(라이브 Obsidian 컬렉션 전제) — **내 백엔드 변경을
  stash해도 동일 실패**(격리 확인). 이 테스트 환경의 기존 인프라 이슈(임베딩/컬렉션 시드). 별도 이슈.
  단, verify_130의 trace 불변식(허용키·hitsDetail)은 v2에 맞게 갱신해 뒀다(환경 복구 시 정합).

## RBAC 경계 (재확인 — 트리거 아님)
- ragMinScores는 유저별/테넌트 데이터 미접촉. 에이전트 config(owner 스코프 CRUD)로만 쓰기. 검색은 이미
  배선된 컬렉션만(신규 입구 0). 검증기가 형태(0~1·컬렉션명 문자열) 강제. → 일반 기능 스펙.

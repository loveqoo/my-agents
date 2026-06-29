# 062 — Admin API 에러 `detail` 가시화 + RAG 차원 불일치 조치 안내

> 상태: 초안(AI) → 인간 검토. 짝 없음(단독). 선행 자산: learning 063(fail-closed 가드 메시지는
> 위반값+조치예시)·035(차원 가드는 진실원)·스펙 036/048(RAG 차원 3중가드).

## 1. 문제 (실제 버그 레포트)

Admin > RAG 컬렉션 생성 시 `POST /collections`가 **"→ 409"만 보이고 원인 파악 불가**.

확정 원인(코드 재현, probe-deeper):
- RAG 저장소 차원은 `RAG_EMBED_DIMS`(1024) 고정(`rag_chunks.embedding=vector(1024)`).
- 선택 임베딩 모델(예: Qwen3-Embedding-8B) 출력 차원 4096.
- 생성 가드1(`rag.py:create_collection`)이 probe 실측 4096 ≠ 1024 → 409 차단(**정상 동작**).
- **그런데** 백엔드는 이미 사유를 `detail`에 담는데(`_dim_mismatch`: "출력 차원(4096)이 저장소
  차원(1024)과 다릅니다…"), 프런트 중앙 헬퍼 `j()`(admin/src/api.ts:44)가
  `throw new Error(... → ${res.status})`로 **본문 `detail`을 버리고 상태코드만** 던진다.
  CollectionsView는 `message.error(e.message)`로 "서버 메시지를 그대로 노출"하려 의도했으나
  (line 483, 주석까지 그렇게 적혀 있음) `j()`가 무력화 → 사용자에겐 "→ 409"만.

즉 **두 결함**: (A) 프런트가 `detail`을 버림(근본·전역). (B) 백엔드 메시지에 *조치(어떻게)*가
빠짐(learning 063의 3요소 中 결핍). (A)가 collections만이 아니라 `j()`를 쓰는 **모든 화면 공통**.

## 2. 목표 / 비목표

- 목표: 백엔드가 `HTTPException(detail=…)`로 내려준 **사람이 읽을 안전한 사유**가 Admin UI에
  그대로 노출. 차원 불일치는 "무엇(4096 vs 1024)·왜·어떻게(조치)"를 모두 담는다.
- 비목표: 409 차단 자체 완화(가드는 정상). 새 엔드포인트. 차원 정책 변경 UI(관리자 요청 흐름은
  메시지 안내까지만, 별도 기능은 후속).

## 3. 보안 원칙 (버그 레포트 명시 — 메시지 노출 규율)

1. 토큰/API Key/Authorization 헤더 **절대 비노출**.
2. 외부 응답 원문 전체(스택트레이스/내부 예외/원본 payload) **그대로 비노출**.
3. 허용 노출: 원인 분류 + 안전 수치(4096 vs 1024) + 조치 방법.
4. 상세 진단은 서버 로그/기본 동작에만, UI는 요약 메시지만.

**불변식**: 프런트는 응답 본문에서 **`detail` 한 필드(문자열)만** 꺼낸다 — 원문 전체/임의 필드
금지(원칙2). 길이 상한·제어문자 strip(적대적/거대 본문 방어). FastAPI 기본 500은
`{"detail":"Internal Server Error"}`(스택 없음)이라 `detail`만 읽으면 원칙2 충족. 백엔드의 모든
`detail`은 큐레이션된 안전 문자열이어야 한다(probe/discover/a2a 에러가 이미 타입만·"비밀 없는
안전 메시지"로 규율 — 이 불변식을 codex가 점검).

## 4. 처방

### D1 — 프런트 중앙 에러에서 `detail` 추출 (근본·전역)
`admin/src/api.ts`:
- `async function httpError(res, method, path): Promise<Error>` 추가: 본문을 안전 파싱해
  `detail`이 문자열이면 그걸 메시지로(상한 ~600자·제어문자 제거), 없으면 `METHOD path → status`
  폴백. 본문 파싱 실패(비-JSON)도 폴백. `detail` 외 필드·원문 전체는 절대 안 씀(원칙2).
- `j()`의 `!res.ok` 분기를 `throw await httpError(...)`로 교체. 401 분기는 기존대로(전역 핸들러).
- 동일 추출을 ad-hoc fetch 핸들러 중 RAG·사용자 노출 경로에 적용: `uploadDocument`(413 크기 등),
  `streamChat`(채팅 시작 실패). `login`은 이미 사용자 친화 메시지라 유지, `getMe`(초기 탐색)는 유지.

### D2 — 백엔드 차원 불일치 메시지에 조치 추가 (learning 063 "어떻게")
`packages/api/src/api/rag.py:_dim_mismatch`: 기존 "무엇·왜"에 조치 한 줄 추가 —
"`{target}`차원 임베딩 모델을 선택하거나, 관리자에게 저장소 차원 정책 변경을 요청하세요." 수치는
probe 실측·`RAG_EMBED_DIMS`만(안전). 이름 중복 409("같은 이름의 컬렉션이 이미 있습니다")는 이미
조치 가능 — D1로 자동 노출.

### D3 — 표시
CollectionsView는 이미 `message.error(e.message)`라 변경 불필요(D1이 메시지를 채움). 무회귀 확인만.

## 5. 검증 (사다리, 자가검증 지양)

- **단위(시맨틱)**: `httpError` 추출 로직 — detail(string)→메시지, detail 없음→status 폴백,
  비-JSON→폴백, 길이상한·제어문자 strip, `detail` 외 필드 무시(원문 비노출). node 기반 fetch mock.
- **라이브 통합**: 부팅 API에 (a) 중복 이름 `POST /collections` → 409 `detail` 존재 확인,
  (b) 차원 불일치(가능 시 4096 mock) → `detail`에 4096·1024·조치 문구 포함 확인.
- **브라우저(E2E·가장 충실)**: Admin에서 **중복 이름 컬렉션 생성** → 토스트가 "→ 409"가 아니라
  "같은 이름의 컬렉션이 이미 있습니다"를 보임(detail 가시화 실증, 4096 모델 불요). 스샷.
- **적대(codex)**: D1이 `detail` 외 원문/스택/토큰을 노출하지 않는지, 길이상한·비-JSON·null·거대
  본문 케이스, 백엔드 모든 `detail`이 안전 문자열 불변식(probe·a2a·crypto 경로)인지.

## 6. 완료 조건

- [x] `j()` 에러가 백엔드 `detail`을 메시지로 노출(없으면 status 폴백), `detail` 외 원문 비노출.
      → `admin/src/httpError.ts` 중앙 추출(detail 한 필드만·제어문자 strip·600자 상한·raw 바이트
      64KB+시간 5s 상한), `j()`·`uploadDocument`·`streamChat`에 적용. 단위 verify_062_http_error.mjs 10/10.
- [x] 차원 불일치 409가 "4096 vs 1024 + 조치"를 담음(D2).
      → `_dim_mismatch`에 조치 한 줄 추가(직접 호출로 3요소+probe미상 통과 확인).
- [x] 브라우저 E2E: 중복 이름 생성 토스트가 서버 사유를 보임(스샷).
      → shot-collections-062-detail.mjs — 토스트 "같은 이름의 컬렉션이 이미 있습니다."(NOT "→ 409"), 스샷 캡처.
- [x] codex 적대 통과(원문/토큰 누출 없음, 불변식 확인).
      → 1차 Medium(huge-body cap-after-parse)·Low(SSE hang) 적발 → raw 바이트+시간 상한 수정 → 2차 Resolved/clean.
- [x] 무회귀: 기존 200/204/401 경로·다른 화면 에러 표시.
      → `j()` 401 분기·login/getMe 무변경, D3 CollectionsView 무변경(e.message로 자동 충전). 라이브 verify_062_live.py PASS.

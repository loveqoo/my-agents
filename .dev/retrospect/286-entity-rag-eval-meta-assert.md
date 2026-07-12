# 286 — 엔티티 RAG 평가 meta 판정 (스펙 310)

## 무엇을 했나
엔티티 RAG(스펙 149)에 **정답 판정 수단이 없던** 갭을 메웠다. 파일 1개에 N엔티티라 파일명
(`rag_source_contains`)은 무가치 → 엔티티 정체인 **metadata id들의 부분집합 매칭**을 새 판정
`rag_meta_contains`로 추가. 두 갈래:
- **러너 노출**(`eval_runner.eval_run_rag`): obs hit dict에 `"meta": h.get("meta")` 추가 —
  전엔 score/filename/text만 남겨 **판정할 근거 자체가 obs에 없었다**(스펙 137 관측 union 계보:
  관측 안 되는 건 채점 못 한다). 문서형 hit는 meta=None으로 실려 fail-closed.
- **판정 팩토리**(`eval_harness.rag_meta_contains`): arg `movie_id=101` 또는 조합
  `director_id=9,genre_id=6`을 파싱 → 어느 한 hit의 meta가 **모든 (k,v)를 부분집합으로 만족**하면
  통과. `_ASSERT_TYPES`에 `(fn, True)` 등록(fail-closed=rag obs 부재 시 False).
- **프론트**: `EvalAssert['type']` union + `ASSERT_TYPES` 풀 1줄(cat='RAG', "엔티티 id") + `assertLabel`
  케이스("엔티티 {arg}"). kind 필터(rag 풀은 `trace_*` 제외)에 자동 편입.

## 배운 것 / 복리 포인트

- **관측을 노출하는 것이 채점의 전제 — obs에 안 실리면 판정은 "조용한 무용"이 된다**. eval_runner가
  hit의 meta를 버려서, meta 판정을 아무리 잘 짜도 obs에 근거가 없어 **항상 fail-closed=무조건 False**가
  됐을 것(happy-path 케이스가 초록이면 "왜 다 실패?"로 뒤늦게 발견). 스펙 137이 직접형 도구 사용을
  놓쳐 "조용한 초록"이 된 것과 대칭 — **판정을 추가할 땐 그 판정이 읽을 관측이 obs에 실리는지 먼저
  확인**한다(러너·하네스는 한 쌍). → [[verification-ladder-three-rungs]]

- **codex 적대 검증이 잡은 두 진짜 결함 — 둘 다 "관대한 문자열 비교"의 여집합**(자가검증이 놓쳤을):
  ① `str(meta.get(k)) == v`가 **`str(None)=="None"`을 누출** — 부재 키·meta=None·빈 meta에 arg `foo=None`이
  거짓 통과. 사용자 실데이터가 `label_cate_id:null`을 갖는 **진짜 함정**(fail-closed 위반: 없는 걸 있다고).
  ② **비스칼라 meta가 Python repr로 매칭** — `flag=True`·`cfg={'a':1}`·`tags=['a']`가 repr 문자열로
  통과(엔티티 id는 스칼라뿐). 봉인 = `k in meta` + 값이 None/bool/컨테이너 아니고 `isinstance(str,int,
  float)`인 스칼라 가드 후 `str(val)==v`. **"문자열로 바꿔 비교"는 편하지만 None·bool·컨테이너의
  여집합을 열어둔다** — 인가/판정 경계는 스칼라를 명시 가드. → [[gate-on-intent-value-not-mutable-baseline]] [[installed-guard-isnt-covering-guard]] [[use-codex-for-adversarial-verification]]

- **부분집합(subset) 매칭이 "가변 id 집합"의 정답 형태 — 엔티티마다 id 종류·개수가 다르다**. 사용자
  실데이터는 엔티티별로 `sql_filter_id`/`column_info_id`/`label_cate_id`(null 포함)가 있고 없고 제각각.
  "지정한 (k,v)만 만족하면 통과, 나머지 키 무시"라는 부분집합 규칙이라야 이 가변성을 담는다(전체 일치는
  불가능). 숫자/문자 관대 비교(`str(101)=="101"`)는 유지하되 스칼라로 한정. → [[playground-is-precision-debug-channel]]

- **판정 하나 추가 = 러너·하네스·api 계약·풀·라벨 5곳이 한 단위 — 하나라도 빠지면 반쪽**. 러너 노출만
  하고 팩토리 없으면 못 채점, 팩토리만 있고 풀 미등록이면 UI서 못 고름, union 미갱신이면 tsc 붉음.
  **관통 축(assert 한 종)이 여러 층을 지난다** — 새 판정은 이 5곳 체크리스트로. 프론트는 순수 가산
  (기존 5개 RAG 판정과 동일 패턴)이라 kind 필터·라벨 스트립("RAG: " 제거)에 자동 편입. → [[context-control-propagates-to-affordances]]

## 검증 (사다리 + 프론트 기능 왕복)
- **단위(합성 obs)** `tests/verify_310_rag_meta_assert.py` Part A: 부분일치·조합 AND·키 부재·숫자 관대·
  malformed→ValueError·**fail-closed**(rag obs 부재=agent 런)·meta=None + codex 회귀 6종(str(None) 누출·
  bool/dict/list repr).
- **실 인프라 통합** Part B: movies-demo 실검색 → `eval_run_rag` obs가 hit meta 실어 내림 확인·정답
  엔티티(movie_id=101) 통과·오답 실패. VERIFY310_OK.
- **적대(codex)** `codex exec ... --sandbox read-only`: 2건(str(None) 누출·비스칼라 repr) 발견 → 봉인 →
  회귀 테스트 등재.
- **정적**: uvx ruff(format 포함)·uvx mypy 클린 / admin tsc --noEmit 0·vite build ✓.
- **프론트 기능 왕복(브라우저)** `tests/browser/verify-310-rag-meta-assert.mjs`: 페이지 세션으로 movies-demo
  바인딩 RAG 문제집 생성 → rag_meta_contains 케이스 **API 수납·유형 왕복**·malformed arg **400 거부** →
  UI서 케이스 Tag가 assertLabel "엔티티 movie_id=101" 렌더 → 판정 유형 드롭다운에 "엔티티 id" 노출·
  RAG 문제집엔 trace_* 숨김(kind 필터)·콘솔 치명 0. (외형 tsc 아닌 동작 겨눔 — [[ui-verification-must-be-functional]])

## 남은 것 / 주의
- **OUT(설계 명시 제외)**: 표준 검색 지표(recall@k·MRR — 랭킹 품질) / 멀티엔티티 OR 매칭(현재 조합은
  AND=한 hit이 모든 (k,v) 만족). 필요 시 후속 스펙.
- 'RAG 평가' 탭이 RAG 문제집 목록(에이전트 문제집은 '문제집' 탭 분리) — 검증 스크립트 교훈.
- movies-demo(스펙 311)가 이 판정의 실 인프라 픽스처 — 스킬로 재적재 가능.
- dev api(8000)·vite(5173) 기동 중.

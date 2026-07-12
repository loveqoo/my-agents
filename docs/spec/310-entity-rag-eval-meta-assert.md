# 310 — 엔티티 RAG 평가: metadata 정답 판정 (rag_meta_contains)

## 배경 (사용자 실사용, 2026-07-12)
스펙 140이 RAG 컬렉션 평가를 만들었으나 **정답 판정이 파일명(`rag_source_contains`)뿐**이다. 엔티티
RAG(스펙 149)는 **파일 1개에 엔티티 N개**라 파일명이 정답으로 무가치하다 — 실제 사용자 데이터의
검색 결과가 전부 같은 `sql_filter_key.jsonl`에서 온다(첨부 화면 실측). 엔티티는 파일명이 아니라
**행별 metadata의 id들**로 특정된다.

사용자 실 metadata 형태(첨부, 참고용 — 비슷한 데이터 다수 등록 예정):
```json
{"label_cate_id": null, "sql_filter_id": 3, "column_info_id": 18, "sql_filter_key_id": 3}
```
id가 여러 개·숫자 또는 null·구성 가변. 즉 정답 판정은 **"필요한 키=값들의 부분 일치"**여야 한다
(스펙 149 v2 씨앗 "엔티티용 평가 assert rag_meta_contains류"의 실현).

## 구멍 (실측 확정)
- `search_collections` hit는 **이미 meta를 싣는다**(`{score,filename,text,meta}`, runtime.py:410).
- 그러나 평가 러너 `eval_run_rag`가 obs 만들 때 **meta를 버린다**(eval_runner.py:231 = score/filename/
  text만). → 판정이 meta에 닿을 수 없음.
- meta로 맞추는 assert 자체가 없음(현 RAG assert는 파일명·건수·유사도뿐).

## 범위
**IN (1·2번만 — 사용자 결정)**:
1. **러너가 meta를 obs에 노출** — `eval_run_rag`의 hit dict에 `meta` 추가(버리던 걸 살림).
2. **`rag_meta_contains` assert 신설** — hit의 meta가 지정한 키=값들을 **부분 일치**로 담는지.

**OUT**: 순위 종합 점수(recall@k·MRR) — 다음 스펙 후보. 여러 정답 엔티티 OR(자세 아래 한계).

## 설계

### 1. 러너 meta 노출 (eval_runner.py `eval_run_rag`)
obs hit dict에 `"meta": h.get("meta")` 한 필드 추가(성공·error 경로 모두 hits 구조 동일). 문서형 hit는
meta=None(엔티티만 dict). 나머지 obs 계약(output/trace_nodes/error/rag.top_score) 무변경.

### 2. `rag_meta_contains` assert (eval_harness.py, `rag_source_contains` 미러)
- **arg 형식**: `키=값` 쉼표 구분 — `sql_filter_key_id=3` 또는 `sql_filter_id=3,column_info_id=18`.
  파싱: `,`로 분해 → 각 항목 첫 `=`로 (키,값) 분리 → 트림. 키·값 빈 항목이면 **ValueError(→400)**.
  (값에 `,`·`=` 포함은 미지원 — 엔티티 id는 숫자/단순값이라 범위 밖, 한계로 명시.)
- **판정**: 반환된 hit 중 **어느 하나라도**, 지정 (키,값) **전부**를 meta에 담으면 통과.
  값 비교는 **문자열 관대 비교** `str((hit.meta or {}).get(k)) == v` — 숫자 `3`과 라벨 `"3"` 일치.
  키 부재 → `str(None)="None" ≠ v` → 불일치(=그 엔티티 아님, 올바름).
- **fail-closed**: `_rag_obs(o).get("hits", [])` — rag 관측 부재(agent 런)면 빈 리스트 → False(스펙 140
  규약, 조용한 초록 방지 = 스펙 119 대죄 회피). meta=None인 문서형 hit는 `{}`로 취급 → 불일치.
- `_ASSERT_TYPES`에 `"rag_meta_contains": (rag_meta_contains, True)` 등록.
- **스키마 계층 확인**: `EvalAssert.type`가 pydantic Literal이면 새 값 동반 추가(build_asserts 외 검증
  이중화 여부 실측 — 없으면 harness 등록만).

### 3. 프론트 (EvalView.tsx `ASSERT_TYPES`)
- 배열에 `{ value: 'rag_meta_contains', label: 'RAG: 엔티티 id', needsArg: true, hint: '예:
  sql_filter_key_id=3 · 여러 개면 a=1,b=2', cat: 'RAG' }` 추가.
- `EvalAssert['type']` 유니온(api.ts)에 `'rag_meta_contains'` 추가.
- `descOf`에 case 추가(예: `엔티티 "${arg}"`). "meta" 같은 내부어는 라벨에 노출 안 함(엔티티 id로 표현).

### 한계 (정직 기록)
- **정답 엔티티 여럿(OR) 미지원**: assert들은 AND(전부 통과)라, "A 또는 B 허용"은 한 assert로 표현
  불가. 단일 정답 엔티티 기준(현 rag_source_contains와 동급). OR은 후속.
- **부분 일치의 성긴 신호**: 지정 키가 유일 식별자가 아니면 다른 엔티티도 통과할 수 있음 — 유일하게
  집는 키(들)를 사용자가 고르는 책임(문서 단위 성긴 신호와 같은 성격, 스펙 140 계보).

## 검증 (사다리 3런)
- **단위(eval_harness)**: 부분 일치 통과·다중 키 AND·키 부재 불일치·숫자/문자 관대(`3`==`"3"`)·malformed
  arg(빈 키/값)→ValueError·**fail-closed**(rag 관측 부재 False, meta=None 문서형 False). 러너 obs에 meta
  실림 단언.
- **실 인프라 통합(rung-2, 일회용/실 DB)**: 현재 dev DB에 **엔티티 컬렉션이 없음**(전부 문서형) — 실측
  전제. 작은 엔티티 `.jsonl`(사용자 형태 metadata: sql_filter_key_id 등) 인제스트 → `eval_run_rag`로
  검색 → `rag_meta_contains`가 정답 엔티티엔 통과·오답엔 실패하는지 실행. 문서형 컬렉션에 이 assert 쓰면
  False(fail-closed) 확인.
- **적대(codex, read-only)**: eval 채점은 "조용한 초록"이 대죄(스펙 119) — 매처의 여집합 실패를 시킴:
  부분 일치가 과통과(엉뚱 키 접두/부분문자 매칭으로 새는지), 값 코어션 엣지(null·타입), 부재 위장 통과.
- **프론트**: `tsc --noEmit` 0·`vite build` ✓·브라우저 — RAG 문제집 케이스 편집에서 이 판정이 RAG
  풀에 뜨고, `키=값` 입력·저장되는지(엔티티 컬렉션 있으면 실제 채점 왕복까지).

## RBAC 체크리스트 — 트리거 불성립
유저별/테넌트 데이터·소유권·`_own_scope`/`_assert_*owns` 무접촉. 평가 assert 종류 추가 + 검색 결과 meta
노출(이미 검색 UI에 표시되던 값)뿐 — 새 소유권 입구 없음. 데이터 큐레이션·판정 로직이라 스킵 아닌
트리거 불성립(스펙 303 선례).

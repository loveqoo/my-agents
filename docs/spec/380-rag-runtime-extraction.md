# 380 — runtime.py에서 RAG 런타임 추출 (캠페인 374 Tier 2)

## 왜

codex 리뷰 A-TOP3: `runtime.py`(1043줄)에 MCP 도구 실행·RAG 검색 코어·트레이스 조립이 한 파일에
섞여 SRP 위반·변경 충돌. RAG 검색 도메인(`search_collections`·`build_rag_tool`·포맷·cutoff)은
독립 관심사.

## 무엇

RAG 검색 도메인을 `rag_runtime.py`로 추출(runtime.py 1043 → 722줄):
`RagSearchError`·`search_collections`·`_norm_score`·`_annotate_cutoffs`·`used_hits`·`format_rag_hits`·
`_hits_detail`·`_norm_min_scores`·`build_rag_tool`.

### 순환 처리 (핵심)

- `_sanitize_preview`는 **runtime에 남김** — MCP 섹션(도구 결과 마스킹)도 쓰므로(공용 trace 유틸).
- rag_runtime이 쓰는 runtime 헬퍼(`_sink_from`·`_redact_args`·`_sanitize_preview`·`_ERR_CAP`·`_RESULT_CAP`)는
  **함수 내 지연 import**.
- 소비자는 `runtime.search_collections`처럼 **모듈 속성 접근**을 쓰므로 runtime이 rag_runtime을
  **모듈 레벨 re-export** → 호출부 **무변경**. 지연 import 덕에 이 re-export가 순환을 만들지 않는다
  (runtime import 시 rag_runtime 로드 → rag_runtime은 module-level에서 runtime 미참조 → OK. 헬퍼는
  호출 시점에 resolve).

## 완료 조건 (동작 불변)

- runtime.search_collections/build_rag_tool 등 속성 접근 = rag_runtime의 동일 객체(재수출) · 앱 import(순환 0).
- build_rag_tool 실빌드(지연 import resolve) · ruff.
- make test SUITE_OK · verify_371(RAG 도구 경유) ALL PASS · e2e 39/39.

## 검증 결과 (2026-07-16 — done)

전부 초록: 재수출 속성 접근·동일 객체·app import(순환 0)·build_rag_tool 실빌드·ruff·SUITE_OK·
verify_371 ALL PASS·e2e 39/39. runtime.py 1043→722줄, RAG 검색 도메인 독립 모듈로.

## OUT / 후속

- 공용 trace/sanitize 유틸(`_content_text`·`_redact_args`·`_cap`·`_sanitize_preview`)의 `trace_util.py`
  독립 모듈화(codex A) — 지금은 runtime 잔류·지연 import로 충분(YAGNI). 필요해지면 후속.

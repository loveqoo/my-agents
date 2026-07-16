# 376 — RAG 임베딩 모델 검증 단일 출처 (캠페인 374 Tier 1-2)

## 왜

codex 리뷰 P1(그룹 D, rag.py:180): 임베딩 모델 **존재·kind·probe 차원** 검증이 `create_collection`과
`_resolve_reindex_model`에 **동일 시퀀스로 복제**됨. 한쪽 규칙이 바뀌면 생성과 재인덱싱의 검증이
드리프트(예: 한쪽만 kind 강제 완화 시 재인덱싱이 chat 모델을 받아 provider 502로 뭉갬).

## 무엇

`_validate_embedding_model(session, model_id) -> ModelConfig` 단일 validator 추출:
- 존재(400) · `kind == "embedding"`(400) · provider 있으면 probe 실측 차원 == `RAG_EMBED_DIMS`(불일치 409).
- provider 부재(레거시)는 probe 생략 — `_dim_mismatch`의 '미상 통과' 규칙 유지.
- `create_collection`·`_resolve_reindex_model` 두 호출부가 이 하나를 호출.

**경계 판단**: `search_collection`의 검색 시점 kind 가드(072 P2 — 메시지·실패모드 다름)는 **합치지
않음**(다른 관심사). 생성 vs 재인덱싱만 단일화. kind-에러 문구를 짧은 쪽으로 통일(문구 단언 테스트 없음 확인 — 상태코드 400 불변).

## 완료 조건 (동작 불변)

- 두 호출부가 validator 하나로 수렴 · `_embedding_model`은 validator 내부서 유지 · ruff 통과.
- make test SUITE_OK · e2e 39/39(라이브 새 코드).

## 검증 결과 (2026-07-16 — done)

전부 초록: ruff·import 스모크·SUITE_OK·e2e 39/39. 생성/재인덱싱 검증 규칙이 한 함수로 수렴.

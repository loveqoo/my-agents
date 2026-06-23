# 016 — 메모리 읽기전용 + kind별 모델 연결 테스트

상태: **완료**
날짜: 2026-06-24
브랜치: `feat/agent-service` — main 머지 금지
연동: [013 모델 연결 테스트], [015 블록 작성/편집 폼], memory.py, model_registry.py

> 사용자 피드백 2건:
> 1. "빌딩 블록의 메모리 영역은 수정을 열어주는 게 맞는가? 시스템 고유의 설정(enum)인 것 같은데?"
> 2. "모델 테스트에서 embedding 모델은 '모델 미발견'이라고 나오는데, embedding은 임베딩 기능을 테스트해야 맞지 않나?"

## A. 메모리 = 시스템 enum → UI 읽기전용

### 진단
- `memory.py:19` `SEMANTIC_MEMORY = "장기·의미론적"` 상수 + `memory_enabled()`가 이 **정확한 이름 문자열**이
  에이전트 `config.memories`에 있는지로 mem0 활성화를 결정.
- 에이전트는 메모리 타입을 **이름 문자열**로 참조 → 이름이 런타임 계약.
- 결론: 이름 변경/삭제 → 런타임 깨짐. 새 타입 생성 → 배선 없는 무력 항목. body/scope만 서술용.
- 즉 memory는 사용자 저작 콘텐츠가 아니라 **시스템 카탈로그**. 015에서 작성/편집 폼을 연 것은 과함.

### 변경 (UI만 — 백엔드 CRUD/시드는 유지)
- `BlocksView.tsx`:
  - `BLOCK_FORMS`에서 `memory` 제거(embedding·permission만 유지).
  - memory 카테고리: "새 항목"(생성)·"편집"·"삭제" 버튼 미노출 → 조회 전용.
  - memory 빈/헤더 영역에 "시스템 정의 — 읽기 전용" 안내.
- E2E: admin.spec "메모리 타입 등록 → 편집"(015) 제거 → "메모리는 읽기전용(작성·편집 버튼 없음)" 검증으로 대체.
  api.spec memory-types 백엔드 CRUD 테스트는 유지(백엔드는 그대로).

## B. kind별 실제 기능 테스트

### 진단
- `model_registry._probe`는 kind 무관하게 `{base_url}/models` 목록만 조회 → `model_id` 존재 확인.
- embedding 모델은 임베딩 기능을 실제로 호출하지 않음 → '모델 미발견'으로 오인 유발.

### 변경
- `schemas.py`:
  - `ModelProbeIn`에 `kind: Literal["chat","embedding"] = "chat"` 추가.
  - `ModelProbeResult`에 `dims: int | None = None` 추가(임베딩 벡터 차원).
- `model_registry._probe(base_url, api_key, model_id, kind)`:
  - `kind=="embedding"`: `POST {base_url}/embeddings` `{model, input:"ping"}` → 200 + `data[0].embedding`(벡터) 확인.
    `ok=도달+인증`, `modelAvailable=벡터 수신`, `dims=len(vector)`. detail="임베딩 OK · N차원" / 실패 사유.
  - `kind=="chat"`: 기존 `/models` 존재 확인 유지.
  - `test_model_config`는 `body.kind`, `test_saved_model`은 `m.kind` 전달.
- `api.ts`: `testModelConfig` body에 `kind`; `ModelProbeResult`에 `dims?` 추가.
- `ModelsView.tsx`: `runTest`가 `kind: f.kind` 전달. embedding 성공 시 detail에 차원 표기(자동).
- `mock_remote.py`: 결정적 E2E용 목업 — `GET /_remote/models`(chat), `POST /_remote/embeddings`(벡터 반환).

## 검증 (완료 조건)
- [x] `tsc --noEmit` 통과.
- [x] memory 탭: 작성/편집/삭제 버튼 없음(읽기전용) E2E (admin.spec 149행).
- [x] embedding 모델 연결 테스트 → 임베딩 호출로 ok + dims 노출 (api.spec 359행, mock_remote).
      실측: 등록된 multilingual-e5-large → "임베딩 OK · 1024차원" (기존 '모델 미발견' 해소).
- [x] chat 모델 연결 테스트 기존 동작 유지(회귀) — 전체 E2E 37 passed / 1 skip.
- [x] codex GATE — P1/P2 0건 (신규 이슈 없음).

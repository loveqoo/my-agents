# 125 — 메모리 검색 진단: "왜 0건인지"를 표면화 (디버깅 우선)

## 배경 / 왜

사용자 보고(3가지, 뿌리 하나): 메모리 UI가 불편하고, **다른 노트북 배포(자체 도커 API+DB+SPA)에서는
유사도 검색이 안 되며**, **왜 결과가 안 나오는지 알 방법이 없다.**

### 근인 (코드 확인)
- `memory.recall_probe`가 **모든 미가용 사유를 `None` 하나로 뭉갠다**: (a) mem_cfg 없음, (b) llm/embedder
  모델 미설정, (c) 백엔드 초기화 예외(`resolve_backend`가 캐시 None으로 흡수). 셋을 구분 못 함.
- 백엔드가 가용해도 **검색 중 예외**(임베더 API 호출 실패·네트워크·타임아웃)는 `recall_probe`가 그대로
  던져 → 엔드포인트 500 → UI는 **사라지는 토스트**(`message.error`)만. `out`은 갱신 안 돼 빈 화면.
- 결과 0건일 때 UI는 "회상된 기억이 없습니다"뿐 — 스코프(user_id)·임베더 모델·백엔드 상태·오류가 전무.

→ 다른 노트북에서 "유사도 검색이 안 됨"은 십중팔구 (b)/(c)/검색예외(그 배포에 임베딩 모델 미구성·미도달)
인데, **진단 정보가 없어 사용자가 원인을 못 본다.** 사용자 선택: **진단/디버깅 먼저**.

## 설계

### 백엔드 (`memory/__init__.py` · `memory_routes.py` · `agents.py` · `schemas.py`)
- **`recall_diag(scope, query, mem_cfg, limit) -> dict`** 신설(예외를 던지지 않고 진단을 반환):
  - `configured` = mem_cfg에 llm·embedder 둘 다 있나.
  - `embedder_model`·`llm_model` = mem_cfg의 model_id(있으면). **api_key·비밀은 절대 미포함.**
  - `backend_ready` = `resolve_backend(mem_cfg)` 비-None.
  - `error`:
    - !configured → `"임베딩/LLM 모델이 설정되지 않았습니다"`.
    - configured & !backend_ready → `"메모리 백엔드 초기화 실패"`(init 예외).
    - backend_ready & 검색 중 예외 → **캐치**해 정제 문자열(str(e) 상한 300자, 비밀 패턴 제거).
    - 그 외 None.
  - `results` = 성공 시 top-k(정상 경로는 `search`와 동일 코어 — drift 0).
  - **정제**: 예외 문자열에서 `api_key`/`sk-`/`Bearer` 류 토큰을 마스킹, mem_cfg raw 미노출.
- `recall_probe`(chat 경로)·`search`는 **무변경**(회상 코어 drift 0). diag는 시험 도구 전용 추가.
- `MemorySearchOut`에 **선택 필드 `diag: MemorySearchDiag | None`** 추가(기존 enabled/results 보존):
  `{configured, backendReady, embedderModel, llmModel, error, scope, count}`.
- `search_user_memory`·`search_agent_memory`가 `recall_diag`로 결과+diag 구성. `enabled=backend_ready`
  (기존 계약 유지). **검색 예외가 이제 500이 아니라 200+diag.error**(사라지는 토스트 제거).

### 프론트 (`RetrievalTestDrawer` · `RecallDrawer` · `api.ts`)
- `api.ts`: `MemorySearchOut`에 `diag?` 타입 추가.
- `RetrievalTestDrawer`: 검색 후 **지속 진단 패널**(접이식, 토스트 아님) — 백엔드 상태(구성/모델/준비)·
  스코프·회상 수·오류를 항상 남긴다. 상태별 메시지 구분:
  - !configured → "임베딩 모델 미설정"(조치 안내).
  - configured & !backendReady → "백엔드 초기화 실패".
  - backendReady & error → "검색 실패: <정제 오류>".
  - backendReady & 0건 → "구성 정상 · 회상 0건(매칭 없음)".
  - 결과 有 → 기존 카드 + 진단 접이식.
  - network/4xx 예외(diag 없이 throw) → 기존 catch로 지속 오류 표시(토스트+패널).
- diag는 **선택**이라 컬렉션 SearchDrawer(같은 셸, enabled 항상 true)는 미전달 → 무영향.

## 검증

- **백엔드 단위(verify_125)**: `recall_diag`가 4모드 구분 —
  (a) mem_cfg=None → configured=False·error 미설정 안내, (b) llm/embedder 누락 → 동, (c) 검색 예외
  주입(FakeBackend raise) → backend_ready=True·error 정제(비밀 마스킹), (d) 정상 → results+error None.
  **비밀 누출 0**: error에 api_key 미포함 단언.
- **무회귀**: `recall_probe`/`search` 불변(기존 verify_084 등) — enabled 계약·chat 경로.
- **브라우저**: 유저 메모리 "조회 시험"에서 (i) 정상 검색 결과+진단 패널, (ii) 미구성/오류 시 지속 진단
  표시(사라지지 않음) 스샷.
- **적대(codex)**: 정제가 비밀을 흘리나·diag 선택 필드가 컬렉션 경로 깨나·enabled 계약 무회귀·예외 캐치가
  진짜 오류를 삼켜 거짓 초록 만드나.

## 비목표 (OUT)

- 다른 노트북 배포의 임베딩 모델 **설정 자체**를 고치기 — 그건 그 환경의 구성. 이 스펙은 **왜 안 되는지
  보이게** 만들어 사용자가 자가진단하게 한다(진단이 "embedder 미설정/초기화 실패"를 명시).
- near-miss(임계 미달) 점수 노출 — mem0가 top-k만 주므로 별도 임계 조정은 후속.
- UI 대개편(검색 상시 노출 등) — 진단 우선. 편의는 후속(사용자 구체 불편 수집 후).

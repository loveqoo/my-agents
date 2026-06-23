# 013 — 모델 연결 테스트

상태: **실행 중 (자율)**
날짜: 2026-06-23
브랜치: `feat/agent-service` — main 머지 금지
연동: [008 모델 레지스트리](./008-model-registry.md), [010 비밀 암호화](./010-secret-at-rest.md)

> 등록한 모델이 실제로 응답하는지 "연결 테스트"로 확인. 에이전트에 쓰기 전 구성 검증.
> (코드 에이전트 등록의 연결 테스트와 대칭.)

## 1. 목표 / 비범위
### 목표
- **등록 전(입력값)**: 새 모델 모달에서 base_url/api_key/model_id로 테스트.
- **등록 후(저장 모델)**: 목록/편집에서 저장된 모델로 테스트(저장 키 복호화).
- 검사 방식: `{base_url}/models` 호출 → **도달성 + 인증(200) + 모델 가용성**(model_id가 목록에 있나). 토큰 비용 없음.
- 결과: `{ok, reachable, modelAvailable, latencyMs, detail}`. **비밀은 detail/로그에 미노출**(상태코드·일반 메시지만).

### 비범위
- 실제 생성(chat/embeddings) 호출로 end-to-end 품질 검증 — 추후(여기선 도달성+가용성).
- 헬스 폴링/배지 상시 표시 — 추후.

## 2. API
- `POST /models/test` (body: base_url, api_key, model_id) → 입력값으로 프로브.
- `POST /models/{id}/test` → 저장 모델(키 복호화)로 프로브.
- 공통 `_probe(base_url, api_key, model_id)`: httpx GET `{base_url}/models` (타임아웃 10s, Bearer). 200이면 응답 `data[].id`에서 model_id 포함 여부. 오류는 상태코드만(본문 미노출).

## 3. UI
- ModelsView 등록 모달: "연결 테스트" 버튼 → `/models/test` → 초록(연결됨·모델 사용가능)/빨강(오류) 표시.
- 목록 행: "테스트" 액션 → `/models/{id}/test` → message로 결과.

## 4. 검증 (결과)
- [x] 저장 모델(qwen) `/models/{id}/test` → ok/modelAvailable true(실 MLX, 29ms).
- [x] 도달 불가 base_url → ok:false("연결 실패"). 비밀(api_key) detail/로그 미노출.
- [x] UI: 등록 모달 연결 테스트 + 행별 테스트. 행 테스트는 reachable이라도 모델 미발견이면 경고.
- [x] 전체 E2E 30 passed. codex GATE — P1/P2 0건.

## 5. 추후 / 알려진 고려
- **SSRF(codex 노트)**: 인증된 소유자가 임의 base_url을 서버가 호출 — 단일 소유자 전제라 수용. 멀티테넌트/저신뢰 인증이 되면 host/사설IP 허용목록 필요.
- 실제 생성 호출 기반 품질 검증, 헬스 폴링/상태 배지 상시 표시.

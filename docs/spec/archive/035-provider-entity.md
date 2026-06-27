# 035 — Provider 엔티티 (P1, 토대)

상태: **완료 — 구현·검증·회고. 1=base_url 그룹핑, 2=RESTRICT 삭제, 3=오버라이드 없음(provider 상속), 4=모델 단위 테스트 유지. 검증: 인프로세스 20단언+브라우저 4뷰+타자 2인(codex·서브에이전트) SHIP 수렴. 회고 `.dev/retrospect/025`. 2026-06-27.** (AI 작성·인간 승인)
날짜: 2026-06-27
브랜치: `feat/agent-service` — **main 머지·push 금지**
지배 스펙: [008 모델 레지스트리](../008-model-registry.md), [010 비밀 at-rest](../010-secret-at-rest.md),
[013 모델 연결 테스트](../013-model-connection-test.md), [033 로드맵](../033-feature-roadmap.md)(P1)
참고: `.dev/retrospect/024`(엔벌로프 셰이프 변경=tsc 전수검사), `.dev/learning/034`(공유DB 불변식+델타 검증)

## 배경 / 문제

현재 `ModelConfig`(`models` 테이블)는 **연결처 정보(provider/base_url/api_key)를 모델마다 인라인 중복**
보유한다. 같은 MLX 서버에 붙는 chat·embedding 두 모델이 각각 base_url·api_key를 따로 들고 있다.
provider는 본질적으로 **엔드포인트 + 자격증명**이며 1:N(provider 1개 → 모델 다수)이다.

→ provider를 1급 엔티티로 승급, 모델은 FK로 참조. **provider 1회 등록 → 하위 모델 나열**.
레지스트리 단일출처를 강화하고, 이후 RAG(임베딩 provider)·메모리(모델 선택)가 이 위에 얹힌다.

## 현황 (조사로 검증 · file:line)

- `ModelConfig`: `packages/api/src/api/models.py:71-85` — `provider: String(40)="openai-compatible"`,
  `base_url: String(400)`, `api_key: String(400)|None`(암호화), `model_id`, `kind`(chat|embedding),
  `is_default`, `params`(JSONB).
- api_key 암호화: `crypto.py` — Fernet(`encrypt`/`decrypt`). **Fernet은 IV 랜덤 → 비결정적**
  (같은 평문도 매번 다른 암호문) → 마이그레이션에서 **암호문 비교로 그룹핑·dedupe 불가**.
- 런타임 로드: `chat.py:76-107` — 모델명/기본값으로 `ModelConfig` 조회 → `decrypt(m.api_key)`로
  `model_cfg={base_url, api_key, model_id, params}` 구성 → `build_agent`.
- 연결 테스트: `model_registry.py` `_probe()` — chat=`GET {base_url}/models`, embedding=`POST /embeddings`.
- 시드: `seed.py` — `qwen3.6-35b`(chat real MLX, default), `multilingual-e5-large`(embedding real MLX,
  default), `mock-llm`(chat, E2E용). 앞 둘은 같은 MLX 엔드포인트로 추정.
- 마이그레이션: head `0301dea55e1a`, 부팅 시 `alembic upgrade head`(`db.py`).
- UI: `admin/src/admin/views/ModelsView.tsx`, `api.ts` `listModels/createModel/updateModel/testModelConfig`.

## 설계

### 엔티티
- **`Provider`**(`providers` 테이블): `id`(UUID), `name`(unique, 표시·참조명), `protocol`(String —
  기존 `provider` 문자열 "openai-compatible" 이관; **모델 `kind`(chat/embedding)와 별개 축 = 와이어 포맷**),
  `base_url`, `api_key`(암호화, nullable), `created_at`. (선택 후속: `enabled`, `description`.)
- **`ModelConfig`**: `provider`/`base_url`/`api_key` 컬럼 **제거**, `provider_id`(FK→providers.id, NOT NULL)
  **추가**. `model_id`/`kind`/`is_default`/`params` 유지(모델 고유).
- **런타임**: `chat.py`가 모델 → provider join → base_url/api_key를 **provider에서** 읽음. 회귀 없음.

### 결정 포인트 (인간 검토 요청 — 아래 ‘합의 필요’)
1. **api_key 위치**: Provider에만(모델은 provider 자격증명 상속). 모델별 키 오버라이드 없음.
2. **마이그레이션 그룹핑**: Fernet 비결정성 때문에 **`base_url` 기준 그룹화**로 Provider 생성
   (같은 base_url = 같은 provider). api_key는 그룹 내 비공백 값 채택. name은 base_url 호스트에서 파생.
3. **연결 테스트 범위**: 1차엔 모델 단위 test 유지(provider join으로 base_url/api_key 취득),
   provider 단위 test는 후속.

### UI
- **Provider 탭 신설**(어드민): provider CRUD(name/protocol/base_url/api_key, 비밀은 010 마스킹 규약) +
  하위 모델 나열.
- **ModelsView**: base_url/api_key 입력 제거 → **provider 드롭다운 선택** + model_id/kind/is_default/params.

## 마이그레이션 (alembic 신규 리비전, 부모=0301dea55e1a)

1. `providers` 테이블 생성.
2. **data migration**: 기존 `models` 행을 `base_url`별로 그룹화 → 각 그룹당 Provider 1개 생성
   (protocol=기존 provider 문자열, api_key=그룹 내 비공백 1개), `models.provider_id` repoint.
3. `models`에서 `provider`/`base_url`/`api_key` 컬럼 drop, `provider_id` NOT NULL.
4. **시드 재편**(`seed.py`): MLX provider(real) + mock provider → 그 아래 모델 3종.

## 검증 (측정 가능 · 자가검증 지양)

1. **마이그레이션 왕복**(불변식): 전후 모델 수 불변; 각 모델이 정확한 `provider_id`; **전 모델에 대해
   마이그레이션 전 `decrypt(model.api_key)` == 후 `decrypt(model.provider.api_key)`**(자격증명 무손실).
2. **런타임 무회귀**: 채팅이 provider join으로 동일 base_url/api_key 사용 — mock-llm E2E green,
   real 모델 model_cfg 동일.
3. **레지스트리 불변식**: provider 1개에 모델 N개 매달림, 같은 base_url 모델은 같은 provider 공유.
4. **UI**(브라우저, Playwright+시스템 Chrome): Provider 탭 CRUD, ModelsView provider 선택→생성,
   비밀 마스킹 노출 안 됨.
5. **타자 2인**(codex + 서브에이전트) 비판 리뷰: FK NULL 경로, 마이그레이션 다운그레이드, 비밀 왕복,
   provider 삭제 시 매달린 모델 처리(restrict/cascade 결정).

## 합의 필요 (검토 포인트)

1. **마이그레이션 그룹핑 키** — base_url 기준(권장, Fernet 비결정성 대응) vs provider 문자열 기준 vs 모델당 1 provider.
2. **provider 삭제 정책** — 매달린 모델 있을 때 RESTRICT(차단, 권장) vs CASCADE vs SET NULL.
3. **api_key 모델 오버라이드** — 없음(권장, provider 상속) vs 모델별 옵션 키.
4. **연결 테스트** — 1차 모델 단위 유지(권장) vs provider 단위로 이동.

## 완료 조건

- [ ] `Provider` 엔티티 + `ModelConfig.provider_id` FK + alembic(테이블·data migration·컬럼 drop)
- [ ] 런타임(`chat.py`) provider join — 무회귀
- [ ] 시드 재편(provider + 하위 모델)
- [ ] Provider 탭 + ModelsView provider 선택 UI
- [ ] 검증 1~5 통과 + 타자 2인 SHIP
- [ ] **main 머지 금지** — 사용자 브랜치 테스트 대기

## 범위 밖 (후속)

- provider 단위 연결 테스트, provider enabled 토글·헬스체크.
- provider별 모델 자동 나열(엔드포인트 `/models` 조회로 카탈로그 동기화).
- RAG 임베딩 provider 선택(P2에서 이 위에 얹음).

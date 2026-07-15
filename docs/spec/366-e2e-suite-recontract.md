# 366 — e2e Playwright 스위트 재정합 + 실행 가능화

## 왜 (스펙 365 전수조사에서 드러남)

e2e 스위트(`tests/e2e/specs/*.ts`)가 `make test` 밖이라 조용히 썩었다. 시드 개편·기능 제거·계약 변경·
이름 규칙 강화가 누적됐는데 아무도 실행 안 해 드리프트가 쌓임. 개명(365) 자체는 정상인데, 이 스위트를
돌리자 11개 실패 + admin/mobile 인증막힘이 나옴 — 전부 **개명 무관 기존 부채**. 방치하면 다음 시드/계약
변경 때 또 썩는다. 사용자 결정: **재정합 + 실행 가능화**(현재 계약에 맞춤 + 제거기능 정리 + 시드 참조
상수화 + `make e2e`로 다시 안 썩게).

## 실측된 현재 계약 (2026-07-15)

- `/blocks` 카테고리: `[prompt, memory, embedding, mcp]` — **permission 제거**(권한 재설계).
- 시드 모델: `mock-llm`(chat)·`mock-embed`(embedding) — qwen3.6-35b·multilingual-e5-large 없음.
- 시드 에이전트: 슬러그 — `research-assistant`(ui)·`doc-translator`(code)·`personal-secretary`(ui).
- `/permissions`·`/vector-tables`: **404 제거**. `/memory-types`·`/mcp-servers`: 200.
- `/sessions`: `{items, total, counts}` 페이지네이션(배열 아님).
- 모델 생성 스키마: `provider`→`provider_id`(FK, 422 없이 통과하려면 provider_id 필요).
- MCP publish: 커스텀 MCP만 외부 서빙(로컬 stdio는 400 "외부 서빙은 커스텀 MCP만").
- mock a2a 스트림 텍스트: `[mock-a2a] "..." 요청에 답합니다…`("원격 에이전트" 아님).
- 시드 MCP: `local-tools`·`calc-tools`·`web-fetch`(tavily 없음). 메모리 타입: `단기(세션)`·`장기 기억 (mem0)`.
- 이름 규칙(naming.py): 영소문자·숫자·대시만(한글·마침표·대문자·공백 금지).
- 인증: admin/mobile 프로젝트의 `page.goto('/')`는 SPA 자동로그인 전제 → vite가 `VITE_API_TOKEN`으로
  떠야 함(dev 토큰 우회). API는 `API_AUTH_TOKEN`으로 Bearer 수용(이미 동작).

## 범위

### api.spec.ts (11 실패 재정합)
- 상단에 **시드/계약 상수 블록** 신설(SEED_CHAT_MODEL·SEED_EMBED_MODEL·SEED_UI_AGENT·SEED_CODE_AGENT·
  A2A_SIGNATURE·BLOCK_CATEGORIES) — 미래 시드 변경 시 한 곳만.
- 공용 `createAgent` 기본값: model `local-mlx`→`mock-llm`, prompt `Calm SRE`→`''`, `permissions` 제거.
- 81 카테고리 5→4(permission 제거). 316·342 모델명→mock-llm/mock-embed. 428 `{items}` 형태.
  480 `research-assistant`. 508 `[mock-a2a]`. 152 유효 슬러그 이름+mock-llm.
- 328 모델 CRUD: `provider_id` 사용(providers 목록서 조회). 359 kind 테스트: mock provider 경로 실측 정합.
- **제거 기능 테스트 정리**: 129(vector-tables/permissions) 삭제. 171 publish는 커스텀 MCP 제약에 맞게
  재작성(로컬→400 제약 단언 또는 커스텀 생성 후 publish) — 실 계약 확인 후 결정.

### admin.spec.ts
- 43·44 `research-assistant`/`doc-translator`. 93·94 `mock-llm`/`mock-embed`. 100 MCP `local-tools`.
- 163-191 벡터테이블 편집 테스트 삭제(/vector-tables 404). 공용 상수 재사용.

### 실행 가능화
- `make e2e` 타깃: 실 API(8000, API_AUTH_TOKEN)+vite(VITE_API_TOKEN) 전제로 playwright 기동.
  vite 토큰 프로비저닝 경로 확정(admin/.env 또는 webServer env 주입). reuseExistingServer 상호작용 정리.

## 완료 조건 (수치)

- **C1** `cd tests/e2e && npx playwright test` — api 프로젝트 green N/N(제거기능 삭제분 제외).
- **C2** admin·mobile 프로젝트 green(vite VITE_API_TOKEN 프로비저닝 후) — 다해상도 오버플로 0 포함.
- **C3** 제거된 기능(/permissions·/vector-tables) 잔여 단언 0. 하드코딩 시드 참조는 상수 블록 1곳으로 수렴.
- **C4** `make e2e` 한 줄로 전 프로젝트 실행 가능(프로비저닝 포함) — 재실행 재현.

## 검증 결과 (2026-07-15 — done)

- **C1/C2** `make e2e` → **39/39 통과**(api 24 + admin 12 + mobile 3). 재정합 내역:
  - api(11 실패→0): 시드 모델/에이전트명·블록 4카테고리·/sessions 페이지네이션·mock a2a 시그니처·
    이름 규칙·모델 provider_id·연결테스트 provider/model 분리·publish 커스텀 제약·mem0 회상 단언 제거
    (mock는 exact-match만·회상은 363/233 소관)·코드 에이전트 노드 a2a_call.
  - admin(4 실패→0): 시드명·출처 탭(코드 에이전트='내부 (Code)')·위저드 4단계 네비·프롬프트/에이전트
    이름 필드 플레이스홀더(슬러그)·인스펙터 클릭 오픈('실행 흐름').
  - mobile: 네비 라벨 '프로바이더·모델'(구 '모델') + **실제 오버플로 봉합**.
- **인증 프로비저닝**: 머신 Bearer는 `/users/me`를 유저로 못 풂(401)→SPA 로그인막힘. `global-setup.ts`가
  UI 오리진 쿠키 로그인→`storageState` 저장, admin/mobile 프로젝트가 이어받아 자동 인증(백엔드 무변경).
- **부수 발견·수정(실 제품 버그)**: 실행가능해진 mobile 가드가 `프로바이더·모델` 뷰 iPhone SE(320px)
  콘텐츠 16px 가로 오버플로를 잡음 — 마스터/디테일 Panel `minWidth: 280/320`이 컨테이너로 못 줄어듦.
  `minWidth: 'min(Npx, 100%)'`로 봉합(데스크톱 나란히 유지·모바일 축소). 개명(365) 무관 기존 버그.
- **C3** 제거기능(/permissions·/vector-tables) 단언 0(테스트 삭제). 시드 참조는 `tests/e2e/seed.ts` 1곳 수렴.
- **C4** `make e2e` 한 명령으로 전 프로젝트 실행(vite 자동기동·쿠키 프로비저닝) — tsc 0.

## OUT

- 헤르메틱 완전 재작성(시드 이름 의존 전부 제거) — 상수화로 대체(과투자 회피).
- CI 파이프라인 배선 — 별개(로컬 실행 가능화까지).

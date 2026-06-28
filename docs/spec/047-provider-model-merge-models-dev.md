# 047 — 프로바이더·모델 메뉴 통합 + models.dev 카탈로그

> 마스터 044 배치 3(가장 큼). UI 테스트 #6(라벨 혼란)·#7(카탈로그)·#8(메뉴 통합).
> 테마: **프로바이더와 모델을 한 화면(마스터-디테일)에서 다루고, 실모델을 자동 나열·토글하며,
> models.dev 메타로 자동 채운다.**
> 참고 자산: learning 028(서버측 URL fetch=보안표면; base_url은 관리자입력이라 신뢰경계 이미 넘음,
> 크기·타임아웃 캡은 기본값), 025(시드↔라이브 양층 갱신), 012(런타임 설정 단일출처), 011(alembic
> async 마이그레이션), 033(autogenerate가 외부테이블 drop—수동 검토), retrospect 025(프로바이더 엔티티).

## 결정 (044 + 2026-06-28 AskUserQuestion)

| 주제 | 결정 |
|---|---|
| #8 통합 UI 형태 | **마스터-디테일** — 좌측 프로바이더 목록, 선택 시 우측에 그 프로바이더의 GET /models 실모델 나열 + 체크박스 토글 |
| #7 카탈로그 깊이 | **등록 시 자동채움** — GET /models로 뜬 실모델 id를 models.dev 스냅샷과 매칭해 메타(context·modalities·cost·capabilities) 자동 채움. 전체 브라우즈 UI는 비범위 |
| #6 라벨 | **프로바이더 종류/설명 필드** — Provider에 `kind`(local/mock/remote)·`description` 추가, 배지+한 줄 설명으로 명확화 |
| 카탈로그 출처 | **번들 JSON 스냅샷**(외부 런타임 의존 없음) — models.dev/api.json을 레포에 박제, 리프레시 스크립트로 갱신 |

## models.dev 구조 (검증됨 2026-06-28, https://models.dev/api.json)

최상위 = 프로바이더 id 키. 각 프로바이더: `{id, name, api, env, doc, models:{...}}`.
모델 엔트리(키=`"openai/gpt-5.2-chat"` 같은 네임스페이스 id):
```
{ id, name, family, modalities:{input:[...], output:[...]},
  limit:{context, output}, cost:{input, output, cache_read},
  reasoning, tool_call, structured_output, attachment, temperature,
  knowledge, release_date, last_updated, open_weights }
```
**매칭**: GET /models가 돌려주는 raw id(예 `gpt-4o`, `mlx-community/Qwen3.6-...`)를 카탈로그와 맞춘다.
스냅샷을 두 키로 색인 — full id(`openai/gpt-4o`)와 bare id(`gpt-4o`). best-effort: 매칭 실패 시
메타는 공란(MLX 로컬 모델은 대개 미수록 — 정상).

## 스키마 변경 (alembic 마이그레이션 1개)

**Provider**(+2 컬럼):
- `kind: str` default `"remote"` — `local`|`mock`|`remote`(향후 `cloud`). 표시·배지용.
- `description: str` default `""` — 한 줄 설명.

**ModelConfig**(+1 컬럼):
- `meta: JSONB` default `{}` — 카탈로그 파생 메타. 런타임 `params`(temperature 등)와 분리.
  형태: `{catalog_id, context, output_limit, modalities:{input,output}, cost:{input,output},
  capabilities:{reasoning,tool_call,structured_output,attachment}}`. 매칭 없으면 `{}`.

> 011: async alembic. 033: autogenerate가 pgvector/외부 테이블을 drop하지 않게 마이그레이션 수동 검토.
> 기존 행: 서버 default로 백필(kind=remote, description="", meta={}). 무중단.

## 백엔드

### 카탈로그 모듈 `api/catalog.py` (신규)
- 번들 스냅샷 `api/data/models_dev.json`(박제) 로드 — `@lru_cache`로 1회.
- `lookup(model_id: str) -> dict | None`: full/bare id 양쪽 색인으로 매칭, 메타 dict 반환.
- `_to_meta(entry) -> dict`: models.dev 엔트리 → ModelConfig.meta 형태로 정규화.
- 리프레시 스크립트 `tests/refresh_models_dev.py`(또는 `.dev/`): api.json 다운로드→스냅샷 갱신
  (크기 캡·타임아웃·http(s)만; learning 028). 런타임 아님, 수동 실행.

### 신규 엔드포인트 (providers.py)
- **GET `/providers/{id}/available-models`** → 그 프로바이더 base_url에 `GET /models` 프록시.
  - SSRF: base_url은 관리자 입력(신뢰경계 이미 넘음, _probe와 동일). 단 응답 **크기 상한·타임아웃·
    http(s) 스킴·data[*].id 타입 검증**은 기본값으로(learning 028, _probe 패턴 재사용).
  - 응답: `list[{ model_id, registered: bool, registered_name: str|null,
    catalog: {...}|null }]`. registered = 이 프로바이더+model_id로 ModelConfig 존재 여부.
  - 도달 실패 시 빈 목록 + reachable=false(전체 응답을 `{reachable, models:[...]}` 봉투로).

### 토글 (기존 재사용 + 보강)
- 토글 ON = `POST /models`(createModel) with `{provider_id, model_id, name, kind, meta}`.
  name 기본값 = model_id의 마지막 세그먼트(`mlx-community/Qwen3.6-35B`→`Qwen3.6-35B`), 전역
  unique 충돌 시 `-2` 등 suffix. meta = catalog.lookup 결과.
- 토글 OFF = `DELETE /models/{id}`. 단 **그 모델을 참조하는 에이전트가 있으면 차단**(이름 참조,
  learning 042 — config.model = name). 409 + 사용처 안내. (현 모델 DELETE는 무가드 → 보강.)
- model_registry.create_model이 `meta` 받도록 확장(없으면 `{}`).

### #6 라벨
- ProviderOut/serializers에 `kind`·`description` 추가. 시드: MLX=`kind=local, description="실제 로컬
  MLX 서버"`, Mock LLM=`kind=mock, description="라이브 없이 결정적 테스트용 내장 목(스펙 024)"`.

## 프론트엔드 (admin)

### 통합 뷰 `views/ProviderModelView.tsx` (신규, ProvidersView+ModelsView 대체)
- **마스터(좌)**: 프로바이더 목록 — name + kind 배지(local/mock/remote) + description + 모델수.
  [+ 프로바이더] 버튼(생성 모달: name·kind·description·protocol·base_url·api_key·Test).
- **디테일(우)**: 선택 프로바이더 — base_url, Test, **[↻ GET /models]** 버튼 →
  `listAvailableModels(id)` 호출 → 실모델 행 목록. 각 행: 체크박스(registered 토글) +
  model_id + catalog 메타(ctx·modalities·cost) 칩. 도달 실패 시 안내 배너.
  - 수동 추가(카탈로그/엔드포인트에 없는 모델)도 유지 — '직접 추가' 폼.
  - 기본 모델 지정(is_default), kind(chat/embedding) 표시·편집.

### AdminShell 메뉴 통합
- `providers`·`models` 두 메뉴 항목 → 하나 `models`(라벨 '프로바이더·모델', 아이콘 유지).
  라우팅·뷰 매핑을 ProviderModelView로. 죽은 ProvidersView/ModelsView는 제거(또는 보존? → 제거).

### api 클라이언트 (api.ts)
- `Provider`에 `kind`·`description`, `Model`에 `meta` 필드 추가.
- `listAvailableModels(id) -> { reachable, models: AvailableModel[] }` 추가.
- AgentsView 모델 셀렉트는 그대로(이름 참조) — meta는 표시 보강만(옵션).

### mockData
- 프로바이더/모델 목 데이터에 kind·description·meta 반영(있으면).

## 실행 순서 (phased)

1. **A. 백엔드**: 마이그레이션(Provider.kind/description, ModelConfig.meta) → catalog.py + 스냅샷 →
   available-models 엔드포인트 → create/delete 보강(meta, 참조가드) → 시드(kind/description) →
   serializers/schemas.
2. **B. 프론트**: api.ts 타입·함수 → ProviderModelView(마스터-디테일) → AdminShell 메뉴 통합 →
   mockData.
3. **C. 라벨/정리**: 시드 description 문구, 죽은 뷰 제거.

각 단계 후 검증. A는 단위+통합으로 먼저 굳히고 B를 얹는다.

## 검증 (자가 + 타자)

1. **카탈로그 단위** `tests/verify_047_*.py`: catalog.lookup이 알려진 id(full·bare) → 메타 정확,
   미수록 id → None. _to_meta 정규화 형태 단언.
2. **available-models 통합**(실 DB + mock 프로바이더): Mock LLM base_url(127.0.0.1 내장목)에 GET
   /models → 실모델 나열, registered 플래그 정확, 카탈로그 매칭 채워짐. 토글 ON→ModelConfig 생성
   (meta 포함)→OFF 차단(에이전트 참조 시)→무참조 시 삭제 라운드트립.
3. **마이그레이션 검증**: upgrade/downgrade, 기존 행 백필 default, pgvector/외부테이블 미drop(033).
4. **#6 라벨**: ProviderOut에 kind/description 내려옴, 시드 문구 일치.
5. **041/045/046 회귀**: 모델 이름 참조·배지·카탈로그 정리 불변.
6. **타자(적대 서브에이전트 리뷰)**: available-models SSRF/크기캡/타임아웃? 토글 OFF가 참조 모델을
   고아로 만드나(이름 참조 가드)? 카탈로그 매칭 오염(잘못된 메타)? 마이그레이션이 데이터 깨나?
   메뉴 통합이 죽은 라우트 남기나? 비밀 누출(api_key 마스킹 유지)?
7. **브라우저**(Playwright+시스템 Chrome): 통합 뷰 마스터-디테일, GET /models 토글, kind 배지·설명,
   메뉴가 하나로 합쳐짐 시각 확인.

## 검증 결과 (2026-06-28 — 전부 GREEN)

| rung | 자산 | 결과 |
|---|---|---|
| 단위(카탈로그+보안표면) | `tests/verify_047_catalog.py` | **PASS** C1–C5(lookup full/bare/miss/None+_to_meta 정규화), S1–S6(빈/스킴거부/200필터/raw바이트캡/비200무파싱/**slow-trickle deadline**) |
| 통합(실 DB+실 HTTP, self-fixture) | `tests/verify_047_integration.py` | **PASS** I1–I7 + **I5b**. kind/desc·meta 영속, available-models 토글, 삭제가드 409(라이브 이름참조 **및 버전 스냅샷 참조**), provider RESTRICT |
| 마이그레이션 | `d4e5f6a7b8c9` down/up 왕복 | **PASS** 3컬럼만 add/drop, server_default 백필, 외부·pgvector 테이블 미drop(033-safe) |
| 회귀 | `verify_041/045/046` | **PASS** 전부 |
| 브라우저 | `tests/browser/shot-providermodel-047.mjs` | **PASS** 9단언(메뉴 단일화·kind 배지 Local/Mock·설명·GET /models→mock-chat 등록 체크) |
| 타자(적대 서브에이전트) | general-purpose 리뷰 | **Ship, BLOCKER 0**. 2건 적발 → **둘 다 수정+테스트 커버** |

**적대 리뷰가 잡은 2건(수정 완료):**
1. **(MAJOR) per-read 타임아웃 ≠ 전체 deadline** — httpx `timeout=10`은 읽기 1회 한도라 1바이트씩
   <10s 간격으로 흘리는 slow-trickle이 코루틴을 무한정 붙잡음. 스펙이 "타임아웃" 방어를 주장하는데
   거짓이 됨 → `asyncio.timeout(_STREAM_DEADLINE=20)`으로 스트림 전체에 벽시계 deadline 추가
   (`providers.py`). 단위 S6로 커버.
2. **(MINOR) 삭제 가드가 버전 스냅샷 미검사** — live `Agent.model`/`config.model`만 보고
   `AgentVersion.config["model"]`을 안 봐, 아카이브 버전이 참조하는 모델을 지운 뒤 그 버전으로
   롤백하면 고아 참조 → 가드에 버전 스냅샷 카운트 추가(별도 409 메시지, `model_registry.py`).
   통합 I5b로 커버.

## §7 빚·한계
- models.dev 스냅샷은 박제 — 최신 모델 누락 가능. 리프레시 스크립트로 수동 갱신(런타임 의존 회피
  트레이드오프). 갱신 주기는 빚으로 기록.
- 카탈로그 매칭 best-effort: MLX 로컬·사설 모델은 메타 공란. 정상 동작이나 UI에 "메타 없음" 명시.
- available-models SSRF: base_url 신뢰경계는 관리자 입력으로 둠(learning 028, _probe와 동일 판단).
  내부망 차단은 dev mock(127.0.0.1)을 깨므로 도입 안 함 — 명시적 기록.
- 전체 카탈로그 브라우즈(프로바이더에 없는 모델 탐색)는 비범위 — 등록 시 자동채움만.

# 077 — 온도 에이전트 필드 승격 + 페르소나 대칭 (이슈 2)

## 배경

사용자 보고: "에이전트 생성 시 온도 설정이 없고, 플레이그라운드 오버라이드엔 온도 설정이 있음.
페르소나도 한 곳만 있음. 통일 또는 재배치 필요."

두 비대칭:
1. **온도** — 플그 오버라이드(세션 한정)엔 있는데 **생성/편집 폼엔 없음**. 저장 에이전트가 온도를
   영속 보유하지 못한다(매번 모델 등록 기본값 또는 세션 오버라이드에만 의존).
2. **페르소나** — 폼엔 페르소나 **블록 Select**가 있는데, 플그 오버라이드엔 raw `systemPrompt`
   TextArea만 있음(블록을 고를 수 없음). "한 곳만 있음."

## 현 배선 (실측 — 추측 금지)

- `AgentConfig`(schemas.py:259-267)에 **temperature 필드가 없다** → 저장 config가 온도를 운반 못함.
- chat.py:79 `"temperature": cfg.get("temperature")` 는 **이미** agent config의 temperature를 읽어
  run_params(:481/:542/:747)로 흘린다 — *입구만 없었던 것*. override allowlist(chat.py:61)에도 temperature 포함.
- create/update(agents.py:111/143)는 `body.config.model_dump()`를 그대로 config JSONB에 저장.
  activate(:224)는 cfg 통째 복사. → **AgentConfig에 필드만 추가하면 round-trip 자동**, 라우터 코드 변경 0.
- 유효 온도 우선순위(불변): caller params > 모델 등록 params > 0.7 기본(main.py). 에이전트 temperature가
  None이면 run_params 비워 모델 등록값이 적용됨(현 동작 보존).
- 페르소나: 폼 Select는 블록 *이름* 참조(저장 시 resolve_persona로 body 해석). 오버라이드 systemPrompt는
  raw 본문으로 persona를 세션 한정 덮어씀(chat.py:65-67, 빈 문자열 가드 있음).

## 목표 (완료 조건 — 측정 가능)

1. 생성/편집 폼에 **온도 슬라이더**(0–2, Switch로 자동/수동) — 자동=null이면 모델 등록값, 수동이면 그 값 저장.
2. 저장한 온도가 config JSONB에 영속되고, GET /agents가 `temperature`로 돌려줘 **폼 재로드 시 복원**.
3. 플그 OverridePanel에 **페르소나 블록 Select** 추가 — 선택 시 그 블록 body를 systemPrompt에 채움
   (양쪽에서 등록 페르소나를 고를 수 있음 = 대칭). TextArea는 자유편집용으로 유지.
4. 무회귀: 온도 미지정(자동) 에이전트는 기존과 동일하게 모델 등록값으로 동작.

## 조치

### 백엔드
- `schemas.py` `AgentConfig`: `temperature: float | None = None` 추가.
- `schemas.py` `AgentOut`: `temperature: float | None = None` 추가.
- `serializers.py` `agent_to_out`: `temperature=cfg.get("temperature")`.

### 프론트 — 생성/편집 폼 (AgentsView.tsx)
- `AgentFormData`에 `temperature: number | null`.
- `blankForm`에 `temperature: null`(기본 자동).
- 온도 Field(Switch 자동/수동 + Slider 0–2, OverridePanel과 동일 UX) — 모델/페르소나 grid 근처.
- `configOf`에 `temperature: a.temperature`, `initial` 매핑에 `temperature: c.temperature ?? a.temperature ?? null`.
- `save()` config에 `temperature: data.temperature`.

### 프론트 — 타입 (mockData.ts)
- `AgentConfig`에 `temperature?: number | null`, `Agent`에 `temperature?: number | null`.

### 프론트 — 오버라이드 대칭 (OverridePanel.tsx)
- systemPrompt Field 위에 페르소나 블록 Select(`blocks.persona?.items`) — 선택 시 `set('systemPrompt', body)`.

## 검증

- **타입**: `tsc --noEmit`(admin) 무에러.
- **백엔드 round-trip**(서브에이전트/스크립트): AgentCreate(config.temperature=0.3) → 저장 →
  GET /agents 응답 temperature=0.3 → chat ctx temperature=0.3 → run_params에 반영. 자동(null)이면 run_params 빔.
- **브라우저**(Playwright + 시스템 Chrome): 생성 모달에 온도 슬라이더 렌더·토글 동작, OverridePanel에
  페르소나 Select 렌더·선택 시 TextArea 채워짐 캡처.

## RBAC 체크리스트 적용 여부

**관련 없음** — 온도/페르소나는 유저별·테넌트 데이터가 아니라 에이전트 런타임 파라미터(전역 config).
소유권/테넌시 경계 무관(유저 데이터 입구 불변, user_id/테넌트 컬럼 미접촉).

## 완료 체크
- [x] 백엔드 AgentConfig/AgentOut temperature 필드 + agent_to_out 노출(라우터 변경 0 — model_dump 자동 round-trip)
- [x] 폼 온도 슬라이더(자동/수동) + 저장/재로드 round-trip(configOf·initial·save)
- [x] mockData 타입 temperature(AgentConfig·Agent)
- [x] OverridePanel 페르소나 블록 Select(선택 시 body→systemPrompt, 대칭)
- [x] tsc 무에러 + 백엔드 pydantic round-trip(0.3 저장·재현, default None) + 브라우저 A(온도 자동→수동·0.7)·B(페르소나 Select 4옵션, Warm Secretary→systemPrompt 99→88자 채움)

## 검증 메모 (antd 6 DOM 클래스)
- 브라우저 셀렉터에서 antd 6는 **Select의 clickable이 `.ant-select-content`**(구 `.ant-select-selector` 개명) —
  `.ant-select-selector`로 잡으면 조용히 타임아웃. Drawer 루트는 `.ant-drawer` 그대로. 옵션은 `.ant-select-item-option`.
  (모달은 `.ant-modal-container`, 스펙 075). 가정 말고 probe로 실제 클래스 확인 → learning 080.

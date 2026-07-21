# 411 — 모델 튜닝 파라미터 N-확장 단일화

> 상태: **완료** · 2026-07-20 · verify_411 24/24 + verify_409 21/21(현행화) + 모델폼 파라미터 UI 브라우저 확인 + FE 빌드 · codex 2패스(P1×2+P2×3 반영)
> 발단: 개발자 "모델 메타값 오버라이드가 아직 부자연스럽다. 두 개 영역만 만들고 N개로 확장 못 함.
> 모델마다 튜닝 메타값(온도·반복 패널티 등)을 관리·오버라이드할 방법이 필요하다."
> **진단**: 지금 **3중 불균일** — ① `temperature`=별도 특례(AgentConfig.temperature 필드+OverridePanel
> TemperatureField, 스펙 077) ② `stream`·`enable_thinking`=409 modelParams(2개) ③ `repetition_penalty`·
> `top_p`·`max_tokens`=**통로 없음**(model.params에 있어도 build_chat_openai가 안 넘김). 409 서술자
> 패턴을 숫자까지 확장해 셋을 **하나**로.

## 설계 — 서술자를 튜닝 파라미터 전반으로 일반화

### 서술자 v2(단일 정본 `capabilities.py` 확장 or `model_params.py`)
각 파라미터 서술자: `key`·`kind`(bool|number)·`label`·`default`·`wire`(API 도달 방식)·(number면
`min`/`max`/`step`)·(bool면 optional `cap`=능력 게이트). `wire` 3종:
- `disable_streaming`: stream — build_chat_openai가 `disable_streaming=not 유효값`
- `extra_body`: enable_thinking(chat_template_kwargs)·repetition_penalty(비표준 OpenAI 파라미터)
- `top`: temperature·top_p·max_tokens(표준 OpenAI 인자 — ChatOpenAI 직접 kwargs)

v1 목록(개발자 승인):
```
stream            bool  cap=streaming  wire=disable_streaming  default=True
enable_thinking   bool  cap=thinking   wire=extra_body         default=False
temperature       number 0~2 step 0.1  wire=top               default=0.7   (스펙 077 흡수)
top_p             number 0~1 step 0.05 wire=top               default=1.0
max_tokens        number(int) 1~32768  wire=top               default=(모델 기본, 미설정=서버 기본)
repetition_penalty number 0.5~2 step 0.05 wire=extra_body     default=1.0
```

### 캐스케이드(409 그대로, 대상만 확장)
모델 params(기본) → 에이전트 modelParams → 노드 modelParams(노드형) → 세션 오버라이드. **모든
파라미터가 이 한 dict(modelParams)**를 탄다. 화이트리스트=서술자 key 집합(하드코딩 없음).

### temperature 흡수(스펙 077 은퇴 — 가장 큰 조각)
- `AgentConfig.temperature` 특례 필드 은퇴 → temperature는 `modelParams.temperature`로.
- `ctx.temperature`·run_params 3곳(chat_turn_runtime·chat_approval·chat_a2a_serve)의 temperature
  주입 은퇴 → temperature는 cfg_params(modelParams 병합본)에서 나머지와 동형으로 해석.
- **마이그레이션**: 기존 저장 에이전트의 `config.temperature`(≠None) → `config.modelParams.temperature`로
  이관(데이터 마이그레이션 또는 로드 시 read-shim). 세션/오버라이드 temperature도 modelParams로.
  (스펙 077의 "None=자동=모델 params" 의미 보존: modelParams에 temperature 없으면 모델 기본.)

## 구현

- **P1 서술자 정본 v2**: kind/wire/range 필드 추가, PARAM_KEYS(화이트리스트) 파생, descriptors 엔드포인트
  확장. clean_setting_params → clean_model_params(bool뿐 아니라 number도 타입·범위 검증).
- **P2 build_chat_openai 관통**: 각 서술자를 wire별로 배선 — top(temperature/top_p/max_tokens는
  ChatOpenAI kwargs), extra_body(enable_thinking·repetition_penalty), disable_streaming(stream).
  number는 범위 클램프. 능력 게이트(bool cap)는 resolve_effective 유지.
- **P3 temperature 흡수+마이그레이션**: AgentConfig.temperature 은퇴·ctx.temperature/run_params 정리·
  데이터 마이그레이션(config.temperature→modelParams.temperature)·그래프 지문·trace 축 현행화.
- **P4 UI 일반화**: CapabilitySettings를 kind별 렌더 — bool=상속/켬/끔 3상(현행), number=상속 토글+
  Slider/InputNumber(범위·기본값 placeholder). 모델 폼 기본값 편집도 kind별. TemperatureField 은퇴
  (OverridePanel도 일반 컴포넌트로 대체). 4화면(모델·에이전트·노드·세션) 한 컴포넌트.
- **P5 검증**: verify_411 — 서술자 파생·number 범위 클램프·캐스케이드(모델→에이전트→노드→세션, 각
  파라미터)·temperature 흡수 무회귀(마이그레이션 왕복·기존 에이전트 temperature 보존)·wire별 실제
  요청 도달(raw 스파이로 repetition_penalty가 extra_body, top_p가 top). e2e+make test+codex.

## OUT
- presence/frequency_penalty(개발자 미선택) — 서술자 한 줄로 후속 추가 가능(N-확장 실증).
- 파라미터별 프리셋(창의적/정밀 등 묶음) — 후속.
- 모델별 지원 파라미터 자동 탐지(모델마다 받는 파라미터 다름) — 지금은 공통 집합 노출.

## codex 2패스
- P1①: 레거시 세션 temperature가 저장 modelParams에 setdefault로 패배 → `_OVERRIDE_ALLOWED`에서
  "temperature" 은퇴(세션도 modelParams로 통일, FE도 그렇게 보냄). verify_411 U7로 못박음.
- P1②: 노드형 플그 세션 modelParams 표면 상실(캐스케이드 4층 UI 회귀) → OverridePanel 노드형 세부에
  세션 CapabilitySettings 추가(전 노드 공통 오버라이드).
- P2: temperature 이중 거처 단일화(serializer가 modelParams로 접고 temperature 필드=None 노출),
  verify_409 현행화(temperature 보존·dict 엔드포인트), NaN/Infinity 유한수 거부(_is_finite_number).

## 완료 기준
- [x] 서술자에 파라미터 한 줄 = 4화면 자동 반영(N-확장 구조 — descriptors {capabilities,params} 단일 정본).
- [x] repetition_penalty·top_p·max_tokens 캐스케이드+wire별 실요청 도달(verify_411 U4·U6, extra_body vs top).
- [x] temperature 흡수: 기존 temperature 보존(_fold_temperature·serializer fold)·세션>저장(U7)·특례 은퇴.
- [x] number 범위 클램프·상속(미설정=모델 기본)·유한수 거부(U2·U3·U8).
- [x] verify_411 24/24 + verify_409 21/21 + 모델폼 파라미터 UI 브라우저 확인 + FE 빌드 + codex 2패스.
      그물 잔여 red(124/130/131/158)는 선재 환경 플레이크(verify_124 커밋상태서도 실패)·411 무관.

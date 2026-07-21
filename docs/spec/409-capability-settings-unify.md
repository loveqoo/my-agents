# 409 — 능력→설정 파생 단일화(408 설정 층 재구조화)

> 상태: **완료** · 2026-07-20 · verify_409 21/21 + verify_408 22/22 + 모델폼 중복제거 브라우저 e2e + make test SUITE_OK(배타 89/0/격리0) + FE 빌드 · codex 2패스(P1 2건 봉합·P2 3건 반영/수용)
> 발단: 개발자 408 검토 — "모델 폼에 스트리밍·thinking이 두 번씩 나온다(헷갈림) / 새 메타
> 설정마다 또 구현할 거냐 / 플레이그라운드 오버라이드가 안 된다 / 노드형은 어떻게 하냐 /
> 그동안 배운 걸 복리로 취하지 않고 바로 작업했다."
> **진단(근거 확인함)**: 408은 `능력 2층` 개념만 세우고 **설정을 다루는 일반 구조 없이** 키
> 두 개(enable_thinking·stream)를 하드코딩했다. 결과 4결함:
> ① 모델 폼 `CapsEditor`가 능력(사실)+사용기본을 **두 줄로 겹쳐** 표시(중복 인상).
> ② `MODEL_PARAM_OVERRIDE_KEYS` 하드코딩 → 설정 하나 추가에 **5곳 수술**.
> ③ `OverridePanel.Overrides`에 modelParams **없음** → API 세션 층이 UI 없는 허구.
> ④ 노드형 미설계(codex 급수정으로 관통만).
> **뿌리**: 이미 있는 범용 캐스케이드(temperature=스펙 077·`OverridePanel`)를 **확장 않고 옆에
> 좁은 통로를 하나 더 팠다** — 회고 261 "사본이면 드리프트"를 설정 축에서 반복.

## 원칙 — 능력이 설정을 파생시킨다

- **능력(capability)** = 모델이 선언하는 사실(불가침). 작은 고정 집합(streaming/thinking/vision…).
- **설정(usage)** = **능력에서 파생**. "능력→설정" 서술자(descriptor)를 **한 곳에 선언**하면,
  그 목록이 백엔드 화이트리스트·모델 폼·에이전트 폼·플레이그라운드·노드 편집을 **전부 구동**한다.
  설정 추가 = 서술자 **한 줄**(5곳 수술 소멸).
- **유효값** = `능력 AND 설정`(능력 false면 설정으로 못 켬 — 부분집합 불가침 유지).

## 서술자(단일 출처) — `model_capabilities.py`

```
CAPABILITY_SETTINGS = [
  {cap:"streaming", setting:"stream",          label:"스트리밍",     default:True,  kind:"bool"},
  {cap:"thinking",  setting:"enable_thinking", label:"Thinking 모드", default:False, kind:"bool"},
  # vision: 능력만(요청별 bool 설정 없음 — 첨부/비전 처리는 별 축, 스펙 408 OUT)
]
```

- 백엔드가 **정본**. `MODEL_PARAM_OVERRIDE_KEYS`·유효값 계산·유효성이 이 목록에서 파생(하드코딩
  중복 제거). admin은 `GET /model-capabilities/descriptors`로 **한 번 받아** 렌더 → FE/BE 드리프트 0.
- 능력만 있는 축(vision)은 `setting=None` — 모델 폼에 능력 토글만, 설정 컨트롤 없음.

## 층(캐스케이드) — 하나의 규칙

`모델 기본(default) → 에이전트 config.modelParams → 노드 modelParams(노드형만) → 세션 오버라이드`

- 각 층은 **바꿀 키만** 명시, 미명시=상속. 세션은 턴-와이드 최상위(사용자 라이브 의도가 이김).
- temperature는 **여기 없음** — `AgentConfig.temperature`(077)가 이미 에이전트 층 정본(단일 거처).
- 노드형: 노드가 자기 설정도 오버라이드(개발자 "노드별 오버라이드까지"). 노드 미명시=에이전트 상속.

## 구현

- **P1 서술자 정본**: `model_capabilities.py` 신설(위 목록). `MODEL_PARAM_OVERRIDE_KEYS`·
  `_apply_agent_model_params`·`build_chat_openai` 유효값 계산을 **목록 구동**으로 교체(하드코딩
  두 곳 소멸). `GET /model-capabilities/descriptors` 노출. 능력 층(JSONB)은 408 그대로 유지.
- **P2 모델 폼 중복 제거**: `CapsEditor`를 서술자 구동 **per-capability 블록**으로 — `[능력 토글]`
  + 능력 ON일 때만 들여쓴 `[기본값 켬/끔]` 하나. 두 겹친 목록 → 능력당 한 블록(vision=토글만).
- **P3 단일 설정 컴포넌트**: `<CapabilitySettings mode=... />` 신설(상속/켬/끔 tri-state, 능력
  false면 해당 컨트롤 비활성+사유). **에이전트 폼·플레이그라운드 `OverridePanel`·노드 편집기가
  공유**(사본 금지 — 회고 261). AgentForm의 손수 짠 Thinking/스트리밍 Select 2개 제거·대체.
- **P4 플레이그라운드 세션 오버라이드**: `Overrides`에 `modelParams` 추가 + `overridePayload`가
  전송 + `OverridePanel`이 P3 컴포넌트 렌더 → **408에서 UI 없던 3층을 실제 통로로**.
- **P5 노드별 오버라이드**: 노드 dict에 `modelParams`(부분) + 노드 편집기에 P3 컴포넌트.
  캐스케이드에 노드 층 삽입(`_resolve_node_models`가 노드 modelParams를 에이전트 위에 병합).
  `normalize_nodes`·라운드트립(저장/로드) 보존.

## 이관 주의(behavior change)

- **thinking도 능력 게이트가 된다**(408은 미게이트 — enable_thinking을 능력과 무관하게 보냈음).
  이제 `capabilities.thinking=true`를 선언한 모델에서만 thinking이 켜진다. 기존 모델은 능력 기본이
  false라 **thinking이 꺼진 상태**로 시작 — MLX처럼 thinking 있는 모델은 관리자가 "thinking 모드
  보유"를 켜야 작동한다(능력=선언 사실 원칙에 정합, streaming과 대칭). 이 축은 사용자 승인 원칙
  ("유효값=능력 AND 설정")의 직접 귀결.

## OUT

- max_tokens·top_p 등 비-능력 파라미터(서술자에 `cap=None` 순수 설정으로 확장은 후속 — v1은
  능력 파생만). 컨텍스트 예산 계약(스펙 404 OUT)과 함께.
- 능력 자동 탐지(probe)·비전 요청별 게이트(C안).

## codex 적대 리뷰(2패스)

- **1패스 P1 2건 봉합**: ①노드형에서 노드 설정이 세션 오버라이드를 되덮던 순서 버그(세션 modelParams를
  노드 층 뒤에 재적용) ②문자열 `"false"`가 `bool()`로 능력/설정을 켜던 게이트 우회(`resolve_effective`
  `_as_bool` + 인제스션 `clean_capabilities`/`clean_setting_params`). **2패스에서 두 P1 봉합 확인.**
- **P2 반영**: FE fetch 실패 현재-마운트 재시도(백오프), FE/BE 비-bool 기본값 해석 일치(`inheritedOn`·
  `capable` 판정을 진짜 bool만). **P2③ 수용**: ModelIn validator 우회 직접 ORM/SQL은 미검증이나
  **실행 관문(`resolve_effective` `_as_bool`)이 모든 저장값을 안전 처리**(covering guard가 실행부에
  있음) — codex도 실제 프로덕션 오염 경로 없음 확인(seed·models.dev 카탈로그 모두 capabilities 미직접
  저장). ORM validate 이벤트는 gold-plating으로 미도입.

## 완료 기준

- [x] 모델 폼: 능력당 한 블록(중복 두 줄 소멸) — 스트리밍·thinking 각각 **한 번만** 노출(브라우저 e2e 확인).
- [x] 설정 추가 = 서술자 한 줄 → 4화면 자동 반영(verify_409 U1 화이트리스트=SETTING_KEYS·H1 엔드포인트 파리티).
- [x] 플레이그라운드 세션 오버라이드가 실행에 반영(verify_408 H6 세션 층 왕복).
- [x] 노드형 노드별 오버라이드 저장/로드/실행(verify_409 H2 왕복·U3 캐스케이드·U4 세션>노드).
- [x] 유효값 불가침: 능력 false는 어느 층도 못 켬(verify_409 U2·U5 문자열 게이트 포함).
- [x] verify_409 21/21 + verify_408 22/22 + 모델폼 e2e + make test SUITE_OK(배타 89/0/격리0) + FE 빌드.
- [x] codex 적대 리뷰 2패스(P1 봉합 확인).

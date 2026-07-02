# 109 — cross-surface UI 일관성은 재사용 컴포넌트로 / 어댑터로 이질적 상태를 하나로 흡수

## 맥락

능력 UI를 여러 번 다듬던 중 사용자가 "늘어나는 항목 효율 렌더 + **같은 개선을 플레이그라운드
오버라이드에도**"를 요구. 두 화면(등록 폼·오버라이드)에 같은 UX를 일관되게 넣는 문제.

## 배운 것

### 1. "여기도 저기도 같게"는 복붙이 아니라 재사용 컴포넌트로

사용자가 같은 UX를 두 곳에 원할 때 각 화면에 코드를 복붙하면 **즉시 drift**가 생긴다(한쪽만 고치고
잊음, learning 106 "비대칭 배선"의 UI판). 대신 **컴포넌트를 추출**하면:
- 렌더·검색·카운트·기본펼침 로직이 한 곳 → 두 소비처가 항상 동일(drift 0).
- 세 번째 화면도 컴포넌트 한 줄로 공짜.

스펙 109에서 `PickerGroups`(접이식+카운트+검색)를 뽑아 등록 폼·오버라이드가 공유 → "오버라이드에도
반영"이 `<PickerGroups .../>` 한 줄로 끝났다. 사용자가 "일관되게"를 말하면 그건 **컴포넌트 추출
신호**다.

### 2. 어댑터(prefix + toggle 라우팅)로 이질적 저장 구조를 한 컴포넌트에 흡수

같은 UI지만 뒤의 저장 구조가 다른 게 흔하다:
- 등록 폼 직접 자원 = **4개** 배열(memories/vectorTables/permissions/mcps)
- 오버라이드 = **2개** 배열(mcps/memories)
- 조율형 능력 = **1개** 배열(capabilities)

컴포넌트를 이 셋에 다 맞추려 storage를 통일할 필요 없다. 대신 **id를 카테고리 prefix로 네임스페이스**
(`mem:`·`col:`·`perm:`·`tool:`)하고, 컴포넌트엔 `selected: string[]`(prefix 붙인 합집합)과
`onToggle(id)`만 준다. 소비처의 `onToggle`이 prefix를 떼어 **올바른 배열로 라우팅**한다:

```
const directSelected = [...memories.map(x=>`mem:${x}`), ...mcps.map(x=>`tool:${x}`), ...]
const toggleDirect = (id) => { const f = FIELD[id.split(':')[0]]; toggle(f, id.slice(...)) }
```

→ 컴포넌트는 **storage-agnostic**(단일 selected/onToggle 계약), 소비처가 얇은 어댑터로 자기 저장
구조에 연결. 저장 스키마·왕복은 무변경(표현 계층만 바뀌어 회귀가 뷰에 갇힘, learning 107).

### 3. 폼 위계 = 필수/공통 → 종류별 → 선택(접힘)

"뭘 꼭 정하고 뭘 나중에 손봐도 되나"가 안 보이면 평평한 폼이다. 세 켜:
- **기본(필수·공통)**: 매번 정하는 소수(이름·모델·종류) — 항상 보임.
- **종류별(하는 일)**: 모드가 가르는 핵심 설정(108) — 접이식 효율 렌더.
- **세부(선택·기본값 있음)**: 튜닝(temperature·history) — **기본 접힘**으로 평소 감춤.

## 함정

- antd v6 Collapse 헤더 텍스트 = `.ant-collapse-header`(‑text 클래스 아님). 체크박스 토글은
  `label.ant-checkbox-wrapper … locator('input').check()`.
- 플레이그라운드 오버라이드 폼은 **ui 에이전트에서만**(code/external=read-only) — 검증 시 ui 에이전트 선택 선행.

## 적용

같은 UX가 2곳 이상이면 컴포넌트 추출(복붙 금지). 저장 구조가 달라도 prefix+어댑터로 흡수하고
storage는 그대로. 폼은 필수→종류별→선택(접힘) 3켜로. 관련:
[[106-config-roundtrip-completeness-and-namespace-as-authoring-layer]],
[[107-growing-catalog-in-form-conditional-plus-accordion]], [[108-dont-expose-internal-architecture-as-ui]].

# 123 — 오버라이드 드로어: `<label>`이 그룹을 감싸 헤더 클릭이 첫 체크박스를 오토글 (버그)

## 배경 / 왜

사용자 보고: 플레이그라운드 오버라이드 드로어에서 **"기억" 탭(그룹 헤더)을 누르면 "도구" 탭 안의
아이템(첫 체크박스)이 영향받는다**(체크됨).

### 근인 (브라우저 이벤트 트레이스로 확정)
`OverridePanel`의 `Field` 컴포넌트가 자식을 **`<label>`로 감싼다**. 그 안에 여러 컨트롤을 담는
`PickerGroups`(Collapse + 체크박스 다수)를 넣었더니, HTML `<label>` 규칙상 **label 내부 아무 곳이나
클릭하면 브라우저가 그 label의 첫 번째 labelable 하위 컨트롤로 클릭을 전달**한다. 그래서 Collapse
그룹 헤더를 클릭하면 → label이 → 문서상 첫 체크박스(local-tools)로 click을 dispatch → 그 항목이
토글됐다.

이벤트 캡처 증거(헤더 1클릭이 클릭 2개 생성):
```
click → SPAN.ant-collapse-title «사용자 기억»   (헤더)
click → INPUT.ant-checkbox-input               (엉뚱한 첫 체크박스)
change → INPUT.ant-checkbox-input              (onChange 발화 → capToggle)
```
`forceRender`로 DOM 순서를 바꾸자 토글 대상이 "DOM 첫 체크박스"로 따라 움직여(local-tools→Doc
Translator) **"label→첫 하위 컨트롤 전달"**임이 확정됐다. (id 부여는 무효 — htmlFor 아닌 label 래핑.)

## 설계

- `Field`에 `group?: boolean` 추가. **group=false(기본)**: 단일 컨트롤용 `<label>`(라벨 클릭→포커스 이동,
  좋은 UX 유지). **group=true**: `<div role="group" aria-label>`로 감싼다 — `<label>`은 컨트롤 하나에만
  붙어야 하므로 그룹엔 label을 쓰지 않는다.
- 여러/그룹 컨트롤을 담는 Field에 `group` 지정:
  - "이 대화에서 맡길 것/쓸 것"(PickerGroups) — 버그 당사자.
  - "Temperature"(Switch + Slider 2개) — 같은 부류의 잠복 버그(라벨 클릭→Switch 토글). 방어적 수정.
- 단일 컨트롤 Field(모델·페르소나·시스템 프롬프트·채팅 히스토리)는 그대로 `<label>`(정상·UX 이점).
- **편집 폼(AgentsView)은 무영향** — PickerGroups를 `SectionHeader` 뒤 독립 렌더(Field/label 밖)라
  애초에 안 감쌌음(확인).

## 검증

- **브라우저 회귀(결정적)**: 조율형 오버라이드에서 (a) 그룹 헤더 클릭 → **다른 그룹 체크박스 상태 불변**
  (before==after), (b) 실제 체크박스 클릭 → 그 항목만 토글(정상 동작 보존), (c) Temperature 라벨 클릭 →
  Switch 안 바뀜. 직접형/조율형 둘 다.
- **무회귀**: shot-orchestrator-override-122·shot-override-by-kind-122 재실행(표면·체크 상태 정상).
- **적대(codex)**: 다른 Field가 여전히 다중 컨트롤을 label로 감싸나(누락)·group 라벨 접근성(aria-label)·
  edit 폼 동류 여부 등 여집합.

## 비목표 (OUT)

- PickerGroups 자체 수정 — 컴포넌트는 정상(체크박스 onChange는 옳다). 문제는 **호출측의 label 래핑**.
- 단일 컨트롤 Field를 div로 바꾸기 — label 유지가 포커스 UX상 이점(그대로 둠).

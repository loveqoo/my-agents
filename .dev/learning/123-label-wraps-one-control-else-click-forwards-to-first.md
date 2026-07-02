# 123 — `<label>`은 컨트롤 하나만 감싼다 (그룹을 감싸면 클릭이 첫 컨트롤로 전달)

## 트리거
공용 필드 래퍼(`Field`, `FormItem` 등)가 자식을 `<label>`로 감싸는데, 그 자식에 **컨트롤이 둘 이상**
(체크박스 목록·Switch+Slider·Collapse 안의 입력들)일 때.

## 사례 (버그, 스펙 123)
사용자: "오버라이드 드로어에서 **기억 탭을 누르면 도구 탭 아이템이 영향받는다**(체크됨)."
- 근인: `OverridePanel`의 `Field`가 `<label>`로 자식을 감쌌고, 그 안에 `PickerGroups`(Collapse +
  체크박스 다수)를 넣었다. **HTML `<label>`은 컨트롤 하나에만 붙어야 한다** — 여러 컨트롤을 감싸면
  label 내부 아무 곳을 클릭해도 브라우저가 **그 label의 첫 번째 labelable 하위 컨트롤로 click을 전달**
  한다. 그래서 Collapse 그룹 헤더 클릭 → label → 문서 첫 체크박스 토글.
- 처방: `Field`에 `group` prop. group이면 `<label>` 대신 `<div role="group" aria-label>`로 감싼다.
  다중/그룹 컨트롤 Field(PickerGroups·Switch+Slider)에 지정. 단일 컨트롤 Field는 `<label>` 유지
  (라벨 클릭→포커스 이동 UX 이점).

## 배운 것 ① (본질)
**`<label>`은 정확히 하나의 폼 컨트롤에만 붙인다.** 여러 컨트롤(또는 컨트롤을 품은 위젯)을 label로
감싸면, label의 아무 영역 클릭이 첫 컨트롤로 forwarding돼 "엉뚱한 항목이 토글"된다. 공용 필드 래퍼가
`<label>`이면 그 슬롯에 그룹 위젯을 넣는 순간 이 버그가 심어진다 — 래퍼는 "단일 컨트롤용 label"과
"그룹용 div(role=group)"를 구분해야 한다. (id/htmlFor 무관 — label **래핑** 자체가 forwarding.)

## 배운 것 ② (디버깅 방법)
근인을 **가설→경험적 반증**으로 좁혔다:
1. "빈/중복 `id=''` → htmlFor 전달" 가설 → 각 체크박스에 고유 id 부여 → **여전히 오토글**(반증).
2. "접힌 패널이 클릭 시 mount되며 stray click" 가설 → `forceRender`로 전부 미리 mount →
   **여전히 오토글, 단 토글 대상이 'DOM 첫 체크박스'로 따라 이동**(local-tools→Doc Translator).
   이 이동이 **"label→첫 하위 컨트롤 전달"**을 결정적으로 증명.
3. 이벤트 캡처 트레이스(헤더 1클릭 → `click:헤더` + `click:INPUT` + `change:INPUT`)로 확정.
- 교훈: **실패한 수정이 근인을 가리킨다.** id 수정이 안 먹혔을 때 "id 아님"으로 방향을 틀었고,
  forceRender의 DOM 순서 변화가 "첫 요소" 규칙을 드러냈다. UI 이벤트 버그는 **capture 리스너 트레이스 +
  DOM 순서 흔들기**가 근인을 못 숨기게 한다([[probe-deeper-before-concluding]]·
  [[verify-ui-in-browser-proactively]]).

## 다음에 할 일
- 공용 필드 래퍼가 `<label>`이면, 그 슬롯에 **컨트롤이 2개 이상 들어가는 순간 group(div role=group)**로.
  단일 컨트롤만 label. (편집 폼 AgentsView는 PickerGroups를 label 밖 독립 렌더라 무사 — 확인.)
- UI "클릭이 엉뚱한 걸 건드린다"류는 곧장 **document capture 리스너로 click/change 트레이스** + 필요시
  DOM 순서를 바꿔 대상이 따라오는지 본다(위치 기반 vs id 기반 vs 첫-요소 기반 구분).

# 104 — 회고: 오버라이드 드로어 그룹 헤더 오토글 (스펙 123)

## 무엇을 / 왜
사용자: "오버라이드에서 기억 탭 클릭이 도구 탭 아이템에 영향." 근인은 `Field`가 `<label>`로 자식을
감싸는데 그 안에 여러 컨트롤(PickerGroups)이 들어가, label 클릭이 첫 하위 컨트롤로 전달된 것.
`Field`에 `group` prop을 추가해 그룹은 `<div role="group">`로 감쌌다.

## 잘된 것
- **가설을 코드가 아니라 실험으로 반증**했다. id 부여(실패)·forceRender(DOM 순서 이동으로 대상이 따라옴)
  두 실험이 "label→첫 하위 컨트롤 전달"을 결정적으로 가리켰다. 추측으로 "PickerGroups 버그"라 단정하지
  않고 이벤트 캡처 트레이스까지 확보(헤더 클릭이 INPUT click/change를 만드는 걸 눈으로).
- **버그 부류를 함께 봉합**: 신고된 PickerGroups Field 외에 Temperature Field(Switch+Slider 2컨트롤)도
  같은 부류라 group 지정(방어). 편집 폼(AgentsView)은 PickerGroups를 label 밖 렌더라 무사임을 확인.
- **수정 지점이 정확**: PickerGroups(컴포넌트)는 정상 — 문제는 호출측 label 래핑. 컴포넌트를 안 건드리고
  래퍼만 고침(최소 변경, 무회귀).
- 회귀 테스트가 세 가지를 결정적으로 고정: 헤더 클릭 불변(H)·실제 토글 정상(T)·Temperature 라벨 불변(S).

## 아쉬운 것 / 리스크
- 초기 두 수정(id·forceRender)이 헛다리 — 다만 **빠르게 반증**해 근인으로 수렴(비용 낮음). 되돌림 확인
  (PickerGroups diff 0)까지 함.
- 이 버그는 스펙 122에서 조율형 오버라이드에 PickerGroups를 **Field로 감싸며** 처음 노출됐을 수도
  (직접형도 같은 Field 사용). 122 브라우저 검증(H2~H4)은 "표시/체크 상태"만 봐서 **헤더 클릭 상호작용은
  안 짚었다** — 상호작용까지 검증했어야. 다음엔 UI 검증에 "인접 요소 클릭이 서로 안 건드리나"도.

## 다음 작업 Context에서 상기할 것
- 공용 `<label>` 필드 래퍼 슬롯에 **컨트롤 2개+가 들어가면 group(div role=group)**. 단일만 label.
- UI "엉뚱한 걸 토글" 버그 → document capture 트레이스 + DOM 순서 흔들기로 근인 규명(learning 123).
- UI 검증은 표시뿐 아니라 **인접 상호작용(클릭 크로스토크)**까지.
- 참고: learning 123, [[verify-ui-in-browser-proactively]], [[probe-deeper-before-concluding]].

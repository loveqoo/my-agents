# 078 — "체크박스 + 설명"은 설명을 Checkbox 형제로 두지 말고 라벨 *안에* 세로 스택하라

## 상황
에이전트 생성 폼의 메모리 타입 "단기(세션)" 라벨이 **글자단위 세로 줄바꿈**("단/기/(세/션)")으로
깨졌다. 구조는 외부 `<label style={display:flex}>` 안에 antd `Checkbox`(이름 라벨 포함)와 설명
`<span>`을 **형제**로 둔 것:
```jsx
<label style={{display:'flex', gap:8}}>
  <Checkbox ...><span>{name}</span></Checkbox>   {/* flex-shrink:1 기본 → 눌림 */}
  <span>{description}</span>                       {/* 긴 설명이 폭을 다 가져감 */}
</label>
```
긴 설명 span이 행 폭을 차지하자 Checkbox 래퍼가 `flex-shrink`되어 이름이 최소폭까지 눌렸고,
한글 이름이 글자단위로 세로 래핑됐다. 짧은 이름(RAG `docs_kb`)은 안 깨졌을 뿐 **같은 잠재버그**.

## 배운 것 (일반화)
- **"체크박스 + 제목 + 설명" 패턴은 제목·설명을 Checkbox의 `children` 안에 세로 스택**으로 넣어라.
  설명을 Checkbox의 *형제 flex 아이템*으로 두면 둘이 폭을 다투고 라벨이 shrink돼 깨진다.
  ```jsx
  <Checkbox style={{alignItems:'flex-start'}} ...>
    <span style={{display:'flex', flexDirection:'column', gap:2}}>
      <span style={{fontWeight:500}}>{name}</span>
      <span style={{fontSize:12, color:tertiary}}>{description}</span>
    </span>
  </Checkbox>
  ```
  flex 경쟁이 사라지고(설명이 라벨 내부에서 자연 줄바꿈), 멀티라인이면 래퍼 `alignItems:flex-start`로
  박스를 상단 정렬. 덤으로 **중첩 `<label>` 제거** — 외부 `<label>` + antd Checkbox 자체 라벨은
  중첩 label(invalid HTML, 클릭 이중토글 위험)이었다. children 안으로 합치면 행당 label 1개.
- **antd 6 모달 본문 클래스는 `.ant-modal-container`** (구버전 `.ant-modal-content` 아님). 셀렉터로
  모달 내부를 스코프할 때 안 맞으면 빈 결과를 내 *거짓 초록*이 된다. DOM 클래스를 probe로 실측해 맞춰라.

## 어떻게 적용하나
"체크박스 옆에 설명문" UI를 만들 때: 설명을 형제로 두지 말고 라벨 children에 세로 스택. 측정으로
검증할 땐 **이름 노드만** 집어 `boundingRect.height`로 한 줄(≈20px) 확인 — 이름+설명 묶음을 재면
2줄이라 거짓 양성. antd 셀렉터는 버전별 클래스명을 probe로 확인 후 사용.

## 근거
- 스펙 075. `AgentsView.tsx` 메모리(170)·RAG(191)·권한(244) 3행 재구조화. 측정: 단기(세션) h 62→22,
  장기 기억 h 81→22(이름 노드만), VERTICAL_WRAP_BROKEN [] (1280·390 둘 다), 토글 무회귀. tsc 통과.
- 관련: [[verify-ui-in-browser-proactively]](직접 캡처로 확인),
  [[measure-table-overflow-to-find-the-culprit-column]](잘린 요소가 아니라 측정으로 진짜 폭을 재라 — 여기선 이름 노드만 정확히),
  [[probe-deeper-before-concluding]](셀렉터 빈 결과를 "통과"로 오인 말고 DOM probe로 실측).

# 334 — 드래그&드롭 첨부(스펙 406, 소형): 입구가 분리돼 있으면 확장은 라우팅이다

- 404/405가 첨부의 두 의도를 **프롭스(onAttachFiles/onAttachKnowledge)로 분리**해 둔 덕에,
  드롭이라는 새 입구는 "판별(Files 타입)+선택 모달+위임"만으로 끝(백엔드 0줄·캡 규칙 무복제 —
  규칙은 기존 흐름이 소유, 새 입구는 위임만).
- 드롭 존 구현 관용구: dragenter/leave는 자식 요소에서 반복 발화하므로 **깊이 카운터**로
  오버레이 깜빡임을 막고, `dataTransfer.types`의 Files 판별로 텍스트 드래그 오발동을 차단.
- e2e에서 드롭은 합성 DataTransfer(evaluateHandle로 페이지 컨텍스트에 File 생성 →
  dispatchEvent('dragenter'/'drop'))로 결정적으로 재현 가능 — 실 마우스 시뮬레이션 불요.

# 스펙 221 — 유사도 검색(RetrievalTestPanel) 입력 레이아웃 정돈

## 배경 (사용자 실사용 지적 2026-07-07, 스샷)

유사도 검색 입력부가 "들쭉날쭉". 원인: 질의 TextArea(높이 큼)와 오른쪽 세로 스택(limit 라벨+숫자+조회
버튼)이 `alignItems: flex-start`(top-align)라 **바닥이 안 맞고**, 라벨이 오른쪽에만 있어 상단도 어긋남.

## 변경 (admin/src/admin/views/RetrievalTestPanel.tsx — 공용, 메모리 회상+컬렉션 검색 드로어 공유)

- 좌우 배치(TextArea | 세로 스택)를 **세로 스택**으로: 질의 TextArea 전체 폭 위 → 그 아래 **한 줄
  컨트롤 행**(limit 라벨 + InputNumber(72px) + 조회 버튼, `justifyContent: flex-end`·`alignItems: center`).
- 바닥·상단 어긋남 제거. 좁은 컬렉션 검색 드로어에서도 더 깔끔(세로 스택이 폭 제약에 유리).

## 검증
- 브라우저: 질의 전체 폭 + 아래 우측 정렬 컨트롤 한 줄(라벨·숫자·버튼 수직 중앙 정렬). tsc 0.

## 비고
순수 레이아웃 정돈(로직·라벨·동작 불변) — 별도 회고 생략.

# 338 — 검색 히트 편집 진입 제거(문서 목록으로 일원화)

## 배경 / 결정 (사용자, 2026-07-14)

"검색 기능에 수정 기능을 넣지 말고, 일반 임베딩처럼 리스트에서 수정" — 확인 결과 **기존 문서
목록 편집으로 일원화**(새 UI 없음). 스펙 333(히트→편집)·337(ordinal 좌표)의 UI를 제거하고,
편집 진입은 스펙 331/332의 문서 목록 버튼 하나로.

## 범위 (333·337의 롤백 — 죽은 영역 원칙대로 소비자 없는 배관까지)

- **프론트**: SearchDrawer의 hitAction 편집 버튼·editHit 상태·에디터 모달 인스턴스 제거,
  RetrievalTestPanel의 hitAction 주입점 제거(소비자 0 = 죽은 표면), DocumentEditorModal의
  locate/locateLine 기제 제거(검색 진입 전용이었음).
- **백엔드**: SearchHit·검색 코어 히트의 document_id/ordinal 제거(유일 소비자가 사라짐 —
  additive였으므로 인챗 도구·trace 무영향).
- **테스트**: verify_333·verify-hit-edit-333.mjs 삭제(대상 기능 소멸 — H4 additive/H5 비노출
  핀은 대상 필드 자체가 사라져 무의미). 331/332 편집·검색 무회귀 확인.
- **스펙 기록**: 333·337 문서에 "338로 롤백" 주석(이력 보존 — git이 복원점).

## 검증
- verify_331/332 무회귀 · 엔티티 편집 e2e(332) 통과 · 검색 시험 드로어 정상(편집 버튼 부재) ·
  lint/mypy/tsc/build 클린 · grep: hitAction/locateLine/SearchHit document_id 소스 0.

## OUT
- 행 단위 편집 UI(방안 A — 필요가 실증되면 재론).

## 결과 (2026-07-14 실행)

- 범위대로 제거 — UI(hitAction·editHit·모달 인스턴스·주입점·locate 기제)+백엔드 배관
  (SearchHit document_id/ordinal)+테스트(verify_333·e2e). 333·337 스펙에 롤백 주석.
- 검증: verify_331/332 무회귀 · 332 e2e(문서 목록 편집 — 유일한 편집 진입) 통과 ·
  검색 드로어 실측(정상 검색 + 히트 카드 편집 버튼 0) · 제거 심볼 grep 0 · lint/mypy/tsc/build 클린.

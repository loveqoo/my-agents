# 스펙 255 — 엔티티 meta=JsonTree·인스펙터 RAG 히트 구조화 (사용자 제안)

## 배경 (254 후속, 2026-07-09)
① 히트 카드의 "실제 데이터"(meta)는 JSON — 칩 나열 대신 **JSON 뷰어**로(사용자 제안).
② 플레이그라운드 인스펙터의 RAG 검색 이력 히트도 같은 처리 필요.

## 변경
- **meta → JsonTree**(승인된 커스텀 접이식 JSON 뷰어, 타입별 색): null 포함 원본 그대로 —
  뷰어가 타입을 구분. 254의 key=value 칩은 하루살이로 대체됨.
- **EntityFields 공용화**: parseEntityText+2열 표+빈 필드 한 줄을 admin/EntityFields.tsx로 추출 —
  검색 시험(RetrievalTestPanel)과 인스펙터 HitCard가 공유(두 벌=드리프트).
- **백엔드 프리뷰 개행 보존**(runtime._hits_detail): "\n"→" " 치환 제거 — 라인 경계가 있어야
  구조화 렌더 가능. 평문 청크는 pre-wrap이라 무해. 캡·비밀 마스킹 규율은 그대로.

## 검증
- 검색 시험 e2e 8/8(JsonTree 계약: 키·null 표시) + 인스펙터 2/2(구조화·빈 라벨 나열 부재,
  엔티티 vectorTables 에이전트로 실검색) + 칩 스위트 무회귀. 시드 정리. tsc 0.

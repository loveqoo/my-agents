# 304 — 죽은 영역 감사 잔여 3건 제거 (스펙 329)

## 무엇을 했나

스펙 324가 사용자 판단 대기로 남긴 3건(generate-dataset 백엔드·Chunk.token_count·하네스 088)을
사용자 결정(전부 제거)대로 소거 — 감사 축 완전 마감. 실행 중 여집합 2겹(마커 화석 3곳·하네스
소비자)을 추가 발견해 동봉 제거.

## 핵심 배운 것

### 1) init_db의 create_all 폴백이 마이그레이션 실패를 조용히 우회한다 — 최대 발견
틀린 테이블명(`chunks`≠`rag_chunks`)의 DROP이 실패했는데 **서버는 정상 부팅하고 alembic_version은
head가 됐다**. init_db가 upgrade 예외를 warning으로 삼키고 create_all 폴백+head 스탬프하기 때문
(db.py:98-128). 기존 테이블엔 create_all이 무동작이라 **스키마 드리프트가 버전 기록과 어긋난 채
침묵**한다. 회고 177("비가역/인프라 변경은 앱검증 그물 밖")의 메커니즘 실증 — 백로그 등재(fail-fast
또는 virgin-DB 한정 폴백, k8s 마이그레이션 Job 분리와 합류).

### 2) 존재하지 않는 것을 조회하면 "부재 단언"은 자명통과다
V4a가 오타 테이블(`chunks`)의 컬럼을 조회 → 빈 결과 → "token_count 없음" 초록(false green).
라이브 확인 스크립트도 같은 오타로 같은 초록. **부재 단언에는 산 것의 존재를 짝으로 단언**해야
한다(`embedding in cols AND token_count not in cols`). ORM은 `__tablename__`을 알지만 손 마이그레이션
·raw SQL은 문자열이라 이 함정에 무방비 — 제거 스펙일수록 적대 리뷰가 P1을 잡는다(codex가 잡음).

### 3) 죽은 기능의 "계약 소비자"는 기능 밖에 산다 — 323 원형의 재연
generate-dataset 코드는 지웠지만 그 **description 마커("생성 중…")를 읽는 코드 3곳**(_is_generating·
좀비 스윕·실행 409 게이트)이 남아 있었다. 특히 실행 게이트는 사용자가 설명에 그 문구를 넣기만 해도
실행을 막는 오탐 표면. 제거 감사는 "심볼 참조 0"으로 끝나지 않는다 — **문자열 계약(마커·문구·
포맷)의 소비자를 별도 grep**해야 닫힌다(스킬 dead-area-audit에 반영할 가치).

### 4) 오래된 e2e는 귀속부터 — stash 재현이 30초에 결론
193 브라우저 e2e가 P1부터 실패 → 내 회귀 의심 대신 stash 재현 → HEAD도 동일 4건 실패 = 기존
드리프트(UI 개편으로 셀렉터 노후). 백로그에 등재하고 내 변경(P3 마커 교체)은 단위(V7)로 커버.

## 검증
- VERIFY329_OK 27/27 — 일회용 virgin DB(전 마이그레이션 체인 실적용, **폴백 경고 0 확인**).
- 라이브 DB: rag_chunks 컬럼 부재+head 정합(수동 ALTER — 미공개 리비전 제자리 수정과 짝).
- lint/format/mypy·tsc·build 클린 · codex 적대(P1 1·P2 2 → 전부 수정).

관련: [[hand-authored-migration-ids-collide-silently]](그물 밖 메커니즘 실증) ·
[[adversarial-review-before-destructive-ship]](제거도 파괴 경로) · 스펙 323(마커 화석 원형)·324·325

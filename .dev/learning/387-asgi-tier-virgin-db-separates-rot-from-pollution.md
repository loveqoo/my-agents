# 387 — 격리 하네스 Phase 1: virgin DB가 "오염"과 "노후"를 갈랐다

## 맥락

스펙 384가 남긴 근본 문제(격리 16/17=공유 라이브 DB) 착수. 설계 전 http 층(99개)을 측정하니
**ASGI 인프로세스 33개는 서버를 안 친다** — DATABASE_URL만 격리하면 끝. 기존 자산
`_throwaway_db.py`(스펙 307)를 그대로 재사용해 run_suite에 `asgi` 층 신설(ASGITransport 있고
:8000 무참조 → 스크립트마다 virgin DB 생성→alembic+seed→실행→drop). 새 하네스 코드 0줄.
결과: asgi 층 33개 SUITE_OK·라이브 DB 무접촉(행 수 전후 동일)·233 격리 해제.

## 교훈

- **대형 하네스 설계 전에 대상을 측정하라 — 1/3은 하네스가 필요 없었다.** "http 99개 격리"는
  대형 작업처럼 보였지만, ASGITransport(인프로세스) vs 라이브 :8000을 galla 보니 33개는 기존
  virgin-DB 러너로 즉시 격리됐다(비용=분류 정규식 몇 줄). 남은 Phase 2(라이브 66개)만이 진짜
  하네스(전용 uvicorn+BASE env 치환)를 요구한다. 문제를 쪼개면 절반은 이미 있는 자산으로 풀린다.
- **virgin DB는 격리 사유의 심판이다 — "공유 DB 오염" 13건 중 12건이 노후로 반증됐다.** 384에서
  "공유 DB 상태" 사유로 격리한 것들을 virgin DB에서 돌리니 **1건(233)만 통과**. 나머지는 깨끗한
  DB에서도 실패 = 오염이 아니라 **기대치 노후**(034 배지 스코핑·048 컬렉션 플로우·084 hit shape·
  098 검색 조합…). 오염 가설은 virgin 실행으로만 판정된다 — 사유를 정직하게 갱신(quarantine-is-honesty).
- **virgin-DB 층은 병렬 금지 — CREATE DATABASE TEMPLATE template0은 동시 실행이 충돌한다**
  ("source database is being accessed by other users"). asgi 층은 각자 DB라 논리적으론 병렬
  안전하지만 생성 단계가 직렬화 지점. workers=1로 고정(33개 × ~5-8s ≈ 3-5분, 수용).
- **B023(루프 변수 lambda 캡처)는 `list()`가 즉시 소진하면 실버그 아님** — 하지만 기본인자
  바인딩(`lambda f, _iso=isolate:`)으로 고치는 게 정석(나중에 lazy 소비로 바뀌면 진짜 버그).
- **무접촉은 주장 말고 행 수로 증명** — asgi 층 전체 실행 전후 라이브 DB 6개 테이블 카운트
  동일을 스펙 완료 조건(C4)으로 박았다. "virgin DB니까 안 건드린다"는 가정이 아니라 측정.

[measure-before-harness-design, virgin-db-adjudicates-quarantine-reasons,
template0-create-serializes, loop-lambda-default-arg-bind, no-touch-proven-by-row-counts]

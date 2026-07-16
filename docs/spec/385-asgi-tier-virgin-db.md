# 385 — verify 격리 하네스 Phase 1: asgi 층 분리 + virgin-DB 실행

> 상태: 초안(AI 작성 → 인간 검토). 성격: 회귀망 인프라(스펙 384의 근본 후속, 백로그 "verify 스위트 격리" Phase 1).
> 참고: [[regression-net-quarantine-not-fix-all]] · 스펙 307(_throwaway_db) · 스펙 353(회귀망) · 회고 386

## 배경 — 격리 16/17의 청구서, 그리고 측정이 알려준 지름길

스펙 384가 http 17건을 triage하니 전부 "공유 라이브 DB 얽힘"이었다(앱 결함 0, 16건 격리).
근본 해결 설계 전에 http 층(99개)을 **측정**하니 세 종류였다:

| 부류 | 수 | 격리 | 서버 필요? |
|---|---|---|---|
| **ASGI 인프로세스**(ASGITransport, :8000 무참조) | 33 | 13 | **불필요** — DATABASE_URL만 격리하면 끝 |
| 라이브 :8000 | 46 | 9 | 필요(서버가 보는 DB까지 격리해야) |
| 혼합(둘 다) | 12 | 5 | 필요 |
| 기타(urlopen 등) | 8 | 0 | 필요 |

**ASGI 33개는 서버를 안 친다** — 앱을 직접 import하므로 기존 `_throwaway_db.py`(스펙 307:
virgin DB 생성→alembic+seed→대상 실행→drop)로 즉시 격리된다. 새 하네스 0줄.

## 목표 (Phase 1)

1. run_suite의 categorize에 **`asgi` 층 신설**: `ASGITransport` 있고 라이브 주소(:8000) 없으면 asgi.
2. asgi 층은 **스크립트마다 `_throwaway_db.py`로 감싸 virgin DB에서 실행**(라이브 dev DB 무접촉).
   - 직렬 실행(CREATE DATABASE TEMPLATE template0은 동시 실행 시 "source database is being
     accessed" 충돌 — 병렬 금지).
   - 타임아웃 180s(부트스트랩 alembic+seed 비용 포함).
3. 격리 13건(034·048·054auth·055·084·098·114·143 등)을 virgin DB에서 재실행 —
   **통과분은 KNOWN_DRIFT에서 해제**(그물 복귀). virgin DB에서도 실패하는 건 사유 갱신 격리 유지.

## 완료 조건(측정 가능)

- C1: `run_suite.py asgi`가 33개를 virgin DB로 실행, 그물(비격리) 전부 통과.
- C2: KNOWN_DRIFT 감소를 수치로: asgi 격리 13건 중 통과분 해제(전/후 카운트 기록).
- C3: 씨앗 그물 `make test` **SUITE_OK 불변**(unit+db 분류 무변경).
- C4: 라이브 dev DB **무접촉 증명**: asgi 층 전체 실행 전후 라이브 DB 주요 테이블 행 수 동일.
- C5: `make test-all`이 asgi 층 포함 SUITE_OK.

## 아웃(Phase 2 — 별도 스펙)

- **라이브 층(46+12+8) 격리**: 전용 uvicorn(임시 포트+임시 DB) 기동 하네스 + 하드코딩
  `127.0.0.1:8000` 58파일을 env(`VERIFY_BASE`) 주입으로 일괄 치환(fast-worker 기계 작업).
- asgi 층을 씨앗 그물(기본 `make test`)에 편입할지 — virgin DB라 상태 안전하나 33×~5s 비용.
  Phase 1에선 `all`/명시 시만 실행, 편입은 속도 실측 후 결정.

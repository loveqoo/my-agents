# 414 — 그물 fresh-DB-per-run 격리 하네스

> 상태: **완료** · 2026-07-20
> 발단: 이번 세션 내내 `make test`가 **매 실행 다른 db층 테스트를 red**로 냄(137/140/141 → 124/130/
> 131/158 …). 근인(회고 338·340·백로그): db층 테스트가 **공유 dev DB**로 직접 실행돼 ①이번 세션 프로브·
> e2e 잔재(세션/메시지) ②dev 서버 배치 스케줄러의 동시 DB 쓰기 ③테스트 간 상태 오염에 노출. 개별
> 격리(throwaway) 실행은 통과 → 공유 DB가 근본. [[net-runs-are-exclusive]]를 "규율"에서 "구조"로.

## 현재 구조(파악)
- `run_suite.py` db 그룹: 대부분 `run_one(f)`가 **직접 실행**(`python <file>`) — 앱이 붙는 **공유 dev DB**
  (DATABASE_URL 기본)에 그대로. `_throwaway_db.py`를 파일이 명시한 것만 격리.
- `_throwaway_db.py`: **테스트마다** temp DB(CREATE TEMPLATE template0)+alembic head+`seed_if_empty`
  부트스트랩 → 대상 실행 → drop. 격리 확실하나 **부트스트랩 비용이 커 45개 낱개는 느림**.

## 설계 — run당 virgin DB 1개(부트스트랩 1회 상각)
- **db 그룹 전체를 한 temp DB로**: run_suite가 db 그룹 시작 전 temp DB 1개 생성+부트스트랩(alembic+seed)
  1회 → 모든 db 테스트를 `DATABASE_URL=<temp>` env로 순차 실행 → 그룹 끝나면 drop. dev DB 무접촉
  (잔재·동시활동 격리). `_throwaway_db.py`의 create/bootstrap/drop 로직 재사용(사본 금지 — 헬퍼 추출).
- **직접형 격리 마커 유지**: `_throwaway_db.py`를 명시한 테스트(downgrade 등 파괴적)는 여전히 낱개
  virgin DB(그룹 DB도 오염하면 안 되므로) — 기존 경로 보존.
- **verify_124 분리 판정**: 실모델 discovery 랭킹 비결정(fresh DB·커밋상태서도 2/7 실패 — DB 무관).
  하네스 적용 후에도 flaky면 **KNOWN_DRIFT 격리 + 사유 명시**(실모델 discovery 비결정, 별도 조사
  후보) 또는 근인 조사. 하네스가 고치는 건 ①②③(공유 DB), ④(모델)는 별개.

## 구현
- **P1 헬퍼 추출**: `_throwaway_db.py`의 `_create`·`_bootstrap`·`_drop`·`_sa_url`을 재사용 가능 모듈
  (`_dbharness.py`)로 추출(throwaway_db는 이를 import — 사본 0).
- **P2 run_suite 그룹 격리**: db 그룹 실행을 `with fresh_run_db() as db_url:` 컨텍스트로 감싸 —
  진입 시 temp DB 생성+부트스트랩, db 테스트 subprocess env에 DATABASE_URL 주입, 종료 시 drop.
  낱개 `_throwaway_db.py` 마커 테스트는 예외(자기 virgin DB 유지).
- **P3 검증 반복**: 하네스로 `make test`를 **여러 번** 돌려 결정성 확인(매번 같은 결과). dev 서버
  가동 중에도 통과해야(동시활동 격리 실증) — 이게 핵심 완료 조건.
- **P4 verify_124 처리**: 하네스 후에도 flaky면 KNOWN_DRIFT 등재(사유)·백로그에 조사 항목.

## OUT
- 테스트 간 상태 오염(같은 run-DB 공유)이 결정적으로 드러나면(같은 순서 재현) 개별 정리 or 순서
  고정 — 관찰 후(이번은 공유 DB→run-DB 격리가 우선, 상호오염은 나오면 대응).
- http/asgi 층 격리는 이미 있음(스펙 385·390) — 무변경.
- verify_124 discovery 근인 수리 — 별도 스펙(모델 비결정 or 로직 버그 판정 후).

## 완료 기준
- [x] db 그룹이 dev DB 무접촉(run당 virgin DB) — 로그 "run당 virgin DB 격리", temp DB `agents_run_*` 생성/drop.
- [x] `make test` **여러 번** 결정적 — run 3·4·5 연속 91/0/0, **api 서버 가동 중**(동시활동 격리 실증).
- [x] verify_124 포함 db 테스트 전부 그린 — 하네스가 공유 DB 플레이크 제거. verify_124도 3회 연속 그린.
- [x] verify_124 그린 — KNOWN_DRIFT 격리 불필요(공유 DB가 근본이었고 격리로 사라짐 — 실모델 비결정 아님).
- [x] 부트스트랩 1회 상각 — db 45개가 virgin DB 1개 공유(부트스트랩 45→1회). `make test` 실측 real 182s.

## 결과 — 하네스가 노출한 "한 번도 격리된 적 없던 테스트" 4건

세션 내내 매번 다른 db 테스트가 red였던 **플레이크**(124/130/131/137/140/141/158)는 하네스 적용 즉시
사라졌다(공유 dev DB가 근본 — 확정). 그런데 하네스는 **결정적으로 red인** 4건을 새로 드러냈다 —
공유 dev DB의 ambient 상태에 **암묵 의존**해 그동안 우연히 통과하던 테스트들이다:

| 테스트 | 의존한 ambient 상태 | 수리 |
|---|---|---|
| verify_330 | `_throwaway_db`의 옛 헬퍼 이름 | 헬퍼를 `_dbharness`로 추출하며 옛 이름 **재수출**(사본 0) |
| verify_148 | 부팅 시 생기는 `casbin_rule`(+연쇄로 verify_050 잔재) | 부트스트랩에 **`init_authz()` 추가**(앱 startup과 동일 순서) |
| verify_050 | 부트스트랩 어드민(`admin@/alice@example.com`) | B1이 keep-list 유저를 **스스로 멱등 생성**(자기완결) |
| verify_352 | mem0 lazy 테이블 + 부트스트랩 어드민 | setup서 `mem0_memories` 확보(앱 `_EMBED_DIMS`)+live 유저 자가 확보 |

- **부트스트랩은 앱 startup을 미러**(init_db → init_authz → seed). mem0 테이블은 앱이 **런타임에 lazy
  생성**(startup 아님)이라 부트스트랩에 안 넣고, 그 테이블을 쓰는 테스트가 **자기 setup서 확보**한다.
- **seed는 유저 0행**(faithful한 "fresh 설치, ADMIN_EMAIL 미설정" 상태). 유저 필요한 테스트는 자가 생성.
- 안전 테스트(삭제정리·메모리고아)를 **격리(coverage 감소) 대신 자기완결 수리**로 살렸다(구남님 선택).

# 038 — 배치 토대 + 세션 보존정리 (P3-a)

> 상태: AI 초안 (인간 검토 대상). 지배 로드맵: `docs/spec/033-feature-roadmap.md` P3 #3.
> 합의 완료: **시스템과 격리된 별도 배치 서비스(자체 프로세스 + 내부 스케줄러)** — 호스트 crontab
> 아님(시스템 결합 회피), 인프로세스(API 앱 내장) 아님. DAG 서비스(Airflow)는 격리의 무거운 끝판이나
> 현재 오버엔지니어링 → 경량 자체 스케줄러로 시작, 그 길만 열어둠.
> **토대+#3 먼저(본 스펙) · #6 유저메모리 요약·재적재는 다음 스펙(039)**.

## 1. 문제 — 반복 운영 작업을 돌릴 토대가 없다

- `main.py:35` lifespan은 **startup-only**(init_db/init_authz/seed_admin). 백그라운드 태스크·
  스케줄러·배치 진입점이 **전혀 없다**(grep 0).
- 로드맵 #3: 오래된 세션이 무한 누적된다. Session에 `last_activity`(onupdate)·`started_at`가
  있어 **나이 판정은 가능**하지만, 이를 소비해 정리하는 경로가 없다.
- 운영 설정(보존창 등)을 둘 **DB 설정 테이블이 없다**(env+하드코딩 산재). learning
  `012-runtime-config-single-source`: 운영 토글·주기·보존창은 env가 아니라 **DB 설정**이 진실원.

## 2. 목표 — 격리된 배치 서비스(자체 스케줄러) + 첫 작업(세션정리)

시스템·API 앱과 **격리된 별도 배치 서비스**(`api.batch`)를 **독립 프로세스**로 만든다. 작업은
**idempotent 서비스 함수**이고, **runner**가 매 실행을 `BatchRun` 감사 행으로 박제한다(시작→ok/error
+ 건수). 두 실행 모드 + 한 수동 경로:

1. **`batch serve`(주 경로)**: 장기 실행 서비스. 내부 **경량 스케줄러(APScheduler)**가 DB 설정 주기로
   작업을 발화. 자체 프로세스(독립 컨테이너/유닛)라 호스트 crontab·API lifecycle와 무관, 단일
   프로세스라 멀티워커 중복 없음.
2. **`batch run <job> [--dry-run]`(원샷)**: 한 작업 1회 실행 후 종료 — 테스트·ad-hoc·수동 운영.
3. **보호 엔드포인트(브라우저/브랜치 테스트)**: `POST /admin/batch/{job}/run`
   (`authz.require("batch","run")`, superuser 우회). API 앱에 두되 **같은 작업 함수**를 호출.

첫 작업으로 **세션 보존정리**(#3)를 구현한다.

### 설계 결정

- **격리된 배치 서비스 vs 호스트 크론 vs 인프로세스**: **격리 서비스** 채택(합의). 호스트 crontab은
  시스템에 결합되고, API 인프로세스는 lifecycle·멀티워커 중복에 묶인다. 자체 프로세스로 띄워 둘 다
  회피. 스케줄러를 **서비스 내부**에 둬 "언제"도 격리한다. 배치가 다양해져 의존·DAG가 필요해지면
  DAG 서비스(Airflow)로 승격 가능하나 현재 오버엔지니어링 → 빚(§7).
- **스케줄러 기제(APScheduler)**: 자체 프로세스라 멀티워커 중복 우려가 없어 인프로세스 단점이 소거됨.
  cron 표현식·인터벌을 깔끔히 지원. 의존성 1개(작은 비용). 앱은 **언제 호출되든 1회 idempotent 실행**만 보장.
- **OS 비의존 / k8s 매핑**(배포 의도 반영): 두 모드가 k8s 두 패턴에 그대로 대응하며 **호스트 OS에 무의존**.
  ① `batch serve`(내부 스케줄러 상주) → **Deployment** 1 파드(플랫폼 무관, 베어메탈/compose/k8s 동일).
  ② `batch run <job>` 원샷 → **k8s CronJob**이 파드로 호출(스케줄을 k8s가 선언적 관리, 호스트 crontab 아님).
  동일 이미지·엔트리포인트, 스케줄 위치만 배포 시 선택. 호스트 OS crontab/systemd timer에 의존 안 함.
- **dry-run 필수**: 삭제는 되돌릴 수 없는 사이드이펙트 → 모든 작업은 `--dry-run`/`?dry_run=true`로
  **삭제 없이 대상·건수만 보고**(CLAUDE.md 검증 단계 dry-run 원칙 + learning 036 "원시 진실 먼저").
- **세션정리는 `last_activity < cutoff` 나이 기준**: status 라벨과 무관하게 `last_activity`가
  비활성의 진실(90일 무활동 세션은 'running' 라벨이어도 죽은 것). status별 정교화는 빚(§7).
- **보존창 기본 비활성(NULL)**: `BatchConfig.session_retention_days = NULL` → 작업이 **no-op**.
  운영자가 명시적으로 일수를 넣어야 삭제 시작 → 실수로 인한 데이터 손실 차단(보수적 기본값).
- **세션정리는 mem0 메모리를 건드리지 않는다**: Session/Message 행만 삭제(cascade). 유저의
  장기기억(mem0, user_id/run_id 키)은 별 저장소·별 수명 → #6(039)의 영역. 대화 전사 ≠ 장기기억.
- **idempotency는 자연적**: 나이 기준 삭제는 이미 지워진 행을 다시 못 찾음 → 중단 후 재실행 안전.
  별도 cleanup 마커 불필요.

## 3. 백엔드

### 3.1 모델 (`models.py`) — Base.metadata 등록 필수(learning 033 autogenerate 안전)

- **`BatchRun`**(감사 로그): `id`, `job_name: str(80)`, `status: str(20)`(running|ok|error),
  `dry_run: bool`, `started_at`, `finished_at: datetime|None`, `summary: JSONB|None`(건수 등),
  `error: Text|None`. 인덱스: `(job_name, started_at)`.
- **`BatchConfig`**(싱글톤 설정): `id`(고정 1행), `session_retention_days: int|None`(NULL=비활성;
  API에서 `ge=1` 강제 — `0`이면 cutoff=now()라 전체 삭제되는 푸트건, 1일 미만은 422 거부),
  `session_cleanup_cron: str|None`(스케줄러가 읽는 cron식, 예 `"0 3 * * *"`; NULL=스케줄 미등록),
  `updated_at`. 부팅 시 1행 시드(멱등, 값 NULL → 기본적으로 아무 것도 자동 발화·삭제 안 함).

### 3.2 배치 서비스 (`api/batch/`)

- **`jobs.py`** — idempotent 작업 함수 + 레지스트리.
  - `async def cleanup_sessions(retention_days: int|None, dry_run: bool) -> dict`:
    `retention_days` None **또는 <1** → `{"status":"disabled"}` 반환(no-op; API ge=1 위에 삭제
    지점 방어층 — 설정값이 잘못돼도 delete-all로 번지지 않게). 아니면
    `cutoff = now() - timedelta(days=retention_days)`; `select Session where last_activity < cutoff`로
    대상 집계. dry_run이면 `{"would_delete": n, "session_ids": [...앞 N]}` 반환(삭제 안 함).
    실삭제면 `delete()` (Message는 FK cascade로 자동) → `{"deleted": n}`. 모든 분기 건수 로깅.
  - `JOBS = {"session-cleanup": cleanup_sessions_entry}` (config에서 인자 해석해 호출하는 래퍼).
- **`runner.py`** — `async def run_job(name: str, dry_run: bool) -> dict`:
  미지 job → 에러. `BatchRun`(status=running) insert → 작업 실행 → 성공 시 status=ok+summary,
  예외 시 status=error+error 메시지(graceful, 크래시 전파 안 함) → finished_at 박제 → summary 반환.
  **감사행 데이터 최소화**: 미리보기 전용 키(`sample` = dry-run 대상 세션 식별자 목록)는 라이브
  응답에만 남기고 `BatchRun.summary`에는 미영속(`_AUDIT_OMIT_KEYS`) — 삭제된 식별자를 장기 감사
  테이블에 무기한 쌓지 않는다(codex 적대 리뷰 반영; 건수 would_delete는 감사행에도 보존).
- **`service.py`** — `serve()`: APScheduler `AsyncIOScheduler` 기동. `BatchConfig`의 cron식을
  읽어 작업을 등록(예 `session_cleanup_cron` → `run_job("session-cleanup", dry_run=False)`).
  NULL이면 미등록(아무 것도 자동 발화 안 함). graceful 종료(SIGTERM) 처리. 독립 프로세스로 상주.
- **`__main__.py`** — CLI(argparse): `python -m api.batch serve` | `python -m api.batch run <job> [--dry-run]`.
  `run`은 `asyncio.run(run_job(...))` 후 결과 JSON stdout + 에러 시 비0 종료코드(원샷·테스트).
  pyproject `[project.scripts]`에 `batch = "api.batch.__main__:main"` 등록 + 의존성 `apscheduler` 추가
  → `uv run batch run session-cleanup --dry-run`, `uv run batch serve`.
- **`routes.py`** — `APIRouter(prefix="/admin/batch")`:
  - `POST /{job}/run?dry_run=bool` → `run_job` 호출, summary 반환. `Depends(authz.require("batch","run"))`.
  - `GET /runs?limit=` → 최근 `BatchRun` 목록(상태·건수·시각). 같은 보호.
  - `GET /config` / `PATCH /config` → `session_retention_days` 조회·수정. 같은 보호.
  main.py에 `app.include_router(batch_routes.router)` 마운트(user_admin과 같은 자체보호 라우터).

> admin 정책(`("admin","*","*")`)이 `("batch","run")`을 이미 커버 → authz 정책 추가 불필요.

## 4. 프론트 (`admin/`) — 경량 배치 패널

- 새 뷰 `BatchView`(메뉴 "배치"/"시스템"): ① 보존창 설정(`session_retention_days` 입력·저장,
  NULL=비활성 표시), ② **dry-run 실행 버튼**(대상 건수 미리보기) + **실행 버튼**(확인 후 삭제),
  ③ 최근 실행 이력 테이블(`GET /admin/batch/runs`: job·status·dry_run·건수·시각).
- 풍부한 UI(스케줄 캘린더·작업별 상세)는 빚(§7) — 본 스펙은 **수동 트리거+이력 가시성**까지.

## 5. 검증 (자가검증 지양 — 036 교훈 계승)

1. **수치(인프로세스, 결정적)**: `tests/verify_038_batch_cleanup.py` —
   (a) 오래된 세션(메시지 포함) + 최근 세션 시드 → `session_retention_days` 설정,
   (b) **dry-run**: `would_delete`가 오래된 것만 집계 + **DB 실제 행 수 불변**(no-op 증명),
   (c) **실행**: 오래된 세션·그 메시지(cascade) 삭제 + 최근 세션·메시지 **보존**,
   (d) **idempotent**: 재실행 시 `deleted=0`(이미 지워짐),
   (e) `retention_days=None`(비활성) → `status=disabled` + 행 불변,
   (f) `BatchRun` 행이 running→ok로 박제되고 summary에 건수 기록, 작업 예외 시 status=error graceful,
   (g) **mem0 미접촉**: 세션 삭제가 mem0 저장소를 호출하지 않음(서비스 함수 의존성에 memory 모듈 부재 단언).
2. **UI(브라우저, 능동)**: `tests/browser/shot-batch-038.mjs`(Playwright+시스템 Chrome) —
   배치 뷰에서 dry-run 버튼 → 대상 건수 표시 → 이력 테이블에 실행 행 렌더 확인.
3. **타자(적대적, 병렬)**: 서브에이전트 + codex 독립 병렬. 중점:
   **데이터 손실 안전**(최근/활성 세션 절대 미삭제, dry-run 진짜 no-op, cutoff 경계 off-by-one),
   **권한**(보호 엔드포인트가 비-admin 403), **비밀/사이드이펙트 누출 0**.

## 6. 완료 조건

- [x] `api.batch` 격리 서비스: `batch serve`(내부 스케줄러 상주) + `batch run <job> [--dry-run]`(원샷) 동작.
- [x] `POST /admin/batch/session-cleanup/run`(admin 보호)으로 수동 트리거 + summary 반환.
- [x] 세션정리가 `last_activity < cutoff`만 삭제, 메시지 cascade 정리, 최근/비활성-config 보존.
- [x] 모든 실행이 `BatchRun`으로 박제(상태·건수), 작업 실패 graceful.
- [x] UI에서 보존창 설정·dry-run·이력 확인(브라우저 시각 검증 — shot-batch-038 3컷).
- [x] verify_038 ALL PASS(가드·감사 최소화 단언 포함) + 브라우저 확인 + 타자 수렴 결함 수정
      (서브에이전트 SHIP + codex: `days<1` 푸트건 가드 추가, dry-run sample 감사 미영속).

## 7. 빚 (의도적, 이후)

- **#6 유저메모리 요약·재적재**: 다음 스펙(039). 본 토대(runner/BatchRun/CLI/엔드포인트) 재사용.
- status별 정교화(예: 'running'은 더 긴 보존, 'error'는 짧게) 미적용 — v1은 `last_activity` 단일 기준.
- 배포 매니페스트(k8s Deployment/CronJob YAML, Dockerfile)는 **이 레포 밖**(배포 단계). 본 스펙은
  OS 비의존 진입점(`batch serve`/`batch run`)까지만 보장 — k8s 어느 패턴에도 그대로 얹힘.
- 풍부한 스케줄 UI(주기 편집·작업별 상세·알림)는 이후. v1은 수동 트리거+이력 가시성.
- 배치 동시 실행 잠금(같은 job 중복 기동 방지)은 미적용 — 외부 크론 단일 스케줄 가정. 동시성
  우려 시 advisory lock은 후속.

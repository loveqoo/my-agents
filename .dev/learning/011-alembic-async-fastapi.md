# 011 — Alembic를 async FastAPI 시작 시 안전하게 돌리기

날짜: 2026-06-23
맥락: [docs/spec/007](../../docs/spec/007-real-agent-service.md), `packages/api/src/api/db.py`, `packages/api/alembic/env.py`

## 함정
FastAPI lifespan(`init_db`)은 **이미 도는 이벤트 루프** 안이다. Alembic의 기본 **async 템플릿 env.py는 `asyncio.run()`을 호출** → "asyncio.run() cannot be called from a running event loop"로 깨진다.

## 해법 (검증됨)
- **마이그레이션은 동기 드라이버로**: `env.py`가 `DATABASE_URL`의 `+asyncpg`를 `+psycopg`로 바꿔 **psycopg(sync)** 엔진 사용. (`uv add alembic "psycopg[binary]"`)
- 시작 시: `await asyncio.to_thread(command.upgrade, cfg, "head")` — sync alembic을 스레드에서.
- `cfg`는 코드 위치에서 절대경로로: `Config(packages/api/alembic.ini)` + `cfg.set_main_option("script_location", ".../alembic")`.
- **부팅은 항상 성공**해야 하니 try/except로 감싸 실패 시 `create_all` 폴백. 단 폴백 후 **`command.stamp(cfg, "head")`** 로 `alembic_version`을 남겨야 다음 부팅에서 초기 마이그레이션이 재시도→재폴백으로 무한 우회되지 않는다.
- 로깅 충돌: alembic `fileConfig`가 루트 로거를 리셋해 uvicorn 로그를 삼킴 → 임베디드 실행 땐 `ALEMBIC_EMBEDDED` 가드로 `fileConfig` 스킵.

## 초기 마이그레이션
- autogenerate는 **모델 vs 현재 DB**를 비교한다. DB에 이미 테이블이 있으면(예: 기존 create_all) **빈 마이그레이션**이 나온다. → 먼저 스키마를 비우고(`DROP SCHEMA public CASCADE`) autogenerate 해야 전체 create_table이 생성된다.
- 생성된 `alembic/versions/*.py`는 **스키마의 진실 소스 — 반드시 커밋**(gitignore 금지).

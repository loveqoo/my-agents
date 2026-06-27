"""격리 배치 서비스 (스펙 038).

시스템·API 앱과 분리된 별도 프로세스로 도는 배치 토대. HTTP 서버·FastAPI 앱 라이프사이클을 띄우지
않고 독립 실행한다 — `python -m api.batch serve|run`. (모델을 `..models`와 공유하므로 import 그래프엔
fastapi-users가 딸려오지만, 프로세스는 웹 서버 없이 돈다.) API 측 수동 트리거는 `api.batch_routes`.

- jobs:    idempotent 작업 함수 + 레지스트리(JOBS)
- runner:  작업 1회 실행을 BatchRun으로 박제
- service: 내부 APScheduler로 상주(serve)
"""

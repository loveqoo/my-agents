"""배치 CLI 진입점 — `batch serve` | `batch run <job> [--dry-run]`. 스펙 038.

- serve: 내부 스케줄러로 상주(k8s Deployment 모드). apscheduler 필요.
- run:   작업 1회 실행 후 종료(원샷/테스트/k8s CronJob 모드). apscheduler 불필요.

pyproject `[project.scripts]`의 `batch`가 이 main을 가리킨다 → `uv run batch run session-cleanup --dry-run`.
"""

import argparse
import asyncio
import json
import logging
import sys

from .jobs import JOBS
from .runner import run_job


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    parser = argparse.ArgumentParser(prog="batch", description="격리 배치 서비스 (스펙 038)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("serve", help="내부 스케줄러로 상주(Deployment 모드)")

    p_run = sub.add_parser("run", help="작업 1회 실행 후 종료(원샷/CronJob 모드)")
    p_run.add_argument("job", choices=sorted(JOBS), help="실행할 작업")
    p_run.add_argument("--dry-run", action="store_true", help="삭제 없이 대상·건수만 보고")

    args = parser.parse_args()

    if args.cmd == "serve":
        from .service import serve  # 지연 임포트 — run 모드는 apscheduler 불필요

        asyncio.run(serve())
        return

    result = asyncio.run(run_job(args.job, dry_run=args.dry_run))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("status") == "error":
        sys.exit(1)


if __name__ == "__main__":
    main()

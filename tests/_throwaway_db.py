"""일회용 DB 격리 러너(스펙 307·414) — 검증 스크립트를 **테스트당 virgin DB**에서 돌린다.

동기: verify_*.py 다수가 공유 dev DB에 붙어, ambient 상태(정리 대상 세션 등)가 전역 집계·sample
truncation에 새어들어 결정성을 깬다. 이 러너는 매 실행마다 임시 DB를 만들어 alembic 스키마 +
`seed_if_empty`(트림된 정예)만 심고, 대상 스크립트를 그 DB로 격리 실행한 뒤 **drop**한다. 라이브
`agents` DB는 절대 건드리지 않는다(smoke_303 계보).

스펙 414: 생성/부트스트랩/drop 로직은 `_dbharness.fresh_db`로 추출(run_suite가 run당 db 그룹에 같은
헬퍼 재사용 — 사본 0). 이 파일은 그 헬퍼로 **테스트당** 격리 실행을 얇게 감싼다.

사용:  uv run python tests/_throwaway_db.py tests/verify_056_session_cleanup_counter.py
전제:  postgres 도달 가능(기본 dev 인스턴스), 롤 CREATE DATABASE 권한.
"""

import subprocess
import sys

# 스펙 330(fail-fast)이 옛 이름으로 임포트하던 저수준 헬퍼를 재수출(사본 0 — 진짜 정의는 _dbharness).
from _dbharness import DEFAULT_URL as _DEFAULT
from _dbharness import _create, _drop, fresh_db
from _dbharness import pg_dsn as _pg_dsn
from _dbharness import sa_url as _sa_url

__all__ = ["_DEFAULT", "_create", "_drop", "_pg_dsn", "_sa_url", "fresh_db"]


def main() -> None:
    if len(sys.argv) < 2:
        print("사용: python tests/_throwaway_db.py <target_verifier.py> [args...]")
        sys.exit(2)
    target = sys.argv[1]
    rc = 1
    with fresh_db(label="iso") as (_child_url, env):
        print(f"== 일회용 DB 부트스트랩(alembic+seed) → 대상 격리 실행: {target} ==")
        rc = subprocess.run([sys.executable, target, *sys.argv[2:]], env=env).returncode
    print("== 일회용 DB drop 완료 ==")
    sys.exit(rc)


if __name__ == "__main__":
    main()

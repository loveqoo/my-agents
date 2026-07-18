"""일회용 서버 격리 러너(스펙 390 — 격리 하네스 Phase 2) — virgin DB + **전용 uvicorn**.

`_throwaway_db.py`(스펙 307)의 확장: http 층 verify는 라이브 서버(:8000)를 치므로 DB 격리만으론
부족하다 — 임시 DB를 보는 **전용 서버를 임시 포트에 기동**해 대상 스크립트를 돌린다.
라이브 dev DB·서버는 절대 건드리지 않는다.

동작:
  1. 임시 DB 생성(+pgvector) — _throwaway_db의 _create/_drop 재사용.
  2. 빈 포트 확보 → uvicorn 기동. env로 자기참조 시드를 임시 포트에 정렬:
     DATABASE_URL(임시 DB) · SELF_BASE_URL · MOCK_LLM_BASE_URL · REMOTE_AGENT_BASE.
     부팅 lifespan이 alembic head + seed_if_empty 수행(별도 부트스트랩 불요).
  3. health(/docs 200) 대기 후 대상 실행 — env `VERIFY_BASE=http://127.0.0.1:<port>`
     (+DATABASE_URL: DB를 직접 검사하는 verify용).
  4. 서버 종료 + DB drop(finally — 부분 실패도 정리).

사용:  uv run python tests/_throwaway_server.py tests/verify_072_rag_search.py
전제:  postgres 도달 가능·롤 CREATE DATABASE 권한. 대상 스크립트는 VERIFY_BASE를 읽어야
       한다(스펙 390 치환 규약 — 하드코딩 8000은 라이브 서버를 친다).
"""

import asyncio
import os
import socket
import subprocess
import sys
import time
import urllib.request
import uuid
from pathlib import Path

from _throwaway_db import _create, _drop, _sa_url  # 스펙 307 재사용(발명 없는 배선)

_DEFAULT = "postgresql+asyncpg://agent:agent@127.0.0.1:5432/agents"
REPO = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    """빈 포트 확보 — bind(0)로 OS 할당받아 닫고 그 번호를 쓴다(짧은 창의 레이스는 로컬 dev 허용)."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_health(port: int, timeout_s: int = 120) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/docs", timeout=3) as r:
                if r.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(1)
    return False


def main() -> None:
    if len(sys.argv) < 2:
        print("사용: python tests/_throwaway_server.py <target_verifier.py> [args...]")
        sys.exit(2)
    target = sys.argv[1]
    url = os.environ.get("DATABASE_URL", _DEFAULT)
    tmp = f"agents_srv_{uuid.uuid4().hex[:12]}"
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    child_url = _sa_url(url, tmp)
    env = {
        **os.environ,
        "DATABASE_URL": child_url,
        "_THROWAWAY_DB": "1",
        # 자기참조 시드 정렬(스펙 390) — mock LLM/MCP/A2A가 자기(임시 포트) 서버를 가리키게.
        "SELF_BASE_URL": base,
        "MOCK_LLM_BASE_URL": f"{base}/_remote/v1",
        "REMOTE_AGENT_BASE": f"{base}/_remote/a2a",
    }
    proc = None
    rc = 1
    try:
        asyncio.run(_create(url, tmp))
        print(f"== 일회용 서버 [{tmp} @ :{port}] 기동(부팅=alembic+seed) ==")
        with open(f"/tmp/throwaway-server-{port}.log", "w") as log:  # noqa: SIM115 — 자식이 상속
            proc = subprocess.Popen(
                [
                    "uv",
                    "run",
                    "--project",
                    "packages/api",
                    "uvicorn",
                    "api.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                ],
                cwd=REPO,
                env=env,
                stdout=log,
                stderr=log,
                start_new_session=True,
            )
        if not _wait_health(port):
            print(f"서버 기동 실패 — /tmp/throwaway-server-{port}.log 확인")
            sys.exit(1)
        print(f"== 대상 격리 실행: {target} (VERIFY_BASE={base}) ==")
        rc = subprocess.run(
            [sys.executable, target, *sys.argv[2:]],
            env={**env, "VERIFY_BASE": base},
        ).returncode
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
        asyncio.run(_drop(url, tmp))
        print(f"== 일회용 서버 [{tmp}] 정리 완료 ==")
    sys.exit(rc)


if __name__ == "__main__":
    main()

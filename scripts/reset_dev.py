"""dev 환경 초기화 장치(회고 389·391 승격) — 정지→DB 초기화→재기동→실모델 복원→검증 일괄.

**왜 스크립트인가**: 수동 초기화가 두 번 같은 함정을 밟았다(2026-07-17):
- 포트 kill(`lsof -ti :8000`)이 vite 프록시 PID를 딸려 죽임 → **pkill 패턴만** 사용(함정 내장 회피).
- seed는 mock 모델만 만들어 실모델(MLX)이 사라짐 → 회상·suite가 조용히 죽음(회고 389 3층 근인).
  **재등록+기본값 지정까지가 초기화다.**
- 마이그레이션 데이터 시드가 죽은 행을 부활시킬 수 있다(회고 391) → 최종 상태 검증 포함.

안전: 인자 없이 실행하면 **계획만 출력**(무해). 실제 초기화는 `--yes` 필수(파괴적 노브 바닥,
learning 037). 세션·메시지·기억·직접 만든 에이전트가 전부 사라진다 — 시드 데모 5개만 재생성.

사용:  uv run python scripts/reset_dev.py          # 계획 출력(안 지움)
       uv run python scripts/reset_dev.py --yes    # 실제 초기화
       (make reset-dev / make reset-dev-yes)
"""

import asyncio
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

PLAN = """dev 초기화 계획(순서 고정 — 함정 회피 내장):
  1. api 정지: pkill -f 'uvicorn api.main:app'  (포트 kill 금지 — vite 프록시 PID 딸림 함정)
  2. DB 초기화: agents drop → create(+pgvector)
  3. api 재기동: 부팅이 alembic head + seed_if_empty 수행(시드 데모 5개 재생성)
  4. 실모델 복원: .env MLX_* 로 provider+chat/embedding 모델 재등록 + 기본값 지정
     (seed는 mock만 만듦 — 이 단계를 빼먹으면 기억 회상·suite가 조용히 죽는다, 회고 389)
  5. 검증: /docs 200 · 시드 5 에이전트 · 실모델 기본값 · memory_types에 죽은 행 없음(회고 391)
     · vite(5173) 생존 확인(죽었으면 재기동 레시피 안내)
사라지는 것: 세션·메시지·기억·직접 만든 에이전트 전부. 실행: --yes
"""


def sh(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


async def _reset_db() -> None:
    import asyncpg

    conn = await asyncpg.connect("postgresql://agent:agent@localhost:5432/postgres")
    await conn.execute(
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        "WHERE datname='agents' AND pid <> pg_backend_pid()"
    )
    await conn.execute('DROP DATABASE IF EXISTS "agents"')
    await conn.execute('CREATE DATABASE "agents" TEMPLATE template0')
    await conn.close()
    conn = await asyncpg.connect("postgresql://agent:agent@localhost:5432/agents")
    await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    await conn.close()
    print("  ✓ DB drop→create(+pgvector)")


def _wait_health(timeout_s: int = 90) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with urllib.request.urlopen("http://127.0.0.1:8000/docs", timeout=3) as r:
                if r.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(2)
    return False


_RESTORE_SNIPPET = r"""
import asyncio, os, sys, uuid
sys.path.insert(0, "src")
from dotenv import load_dotenv
load_dotenv("../../.env")
import httpx
from api.auth import _token
from api.main import app
from api.users import current_active_user

class _Super:
    id = uuid.uuid4()
    is_superuser = True; is_active = True; is_verified = True
    email = "reset-dev@local"
app.dependency_overrides[current_active_user] = lambda: _Super()

async def main():
    base = os.environ["MLX_BASE_URL"]; key = os.environ["MLX_API_KEY"]
    auth = {"Authorization": f"Bearer {_token()}"}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t", headers=auth, timeout=60) as c:
        r = await c.post("/providers", json={
            "name": "MLX", "protocol": "openai-compatible", "base_url": base,
            "api_key": key, "kind": "local",
            "description": "로컬 MLX 서버(rapid-mlx, .env MLX_*) — suite/기억 실모델(reset_dev 복원)",
        })
        pid = r.json()["id"]
        for name, mid, kind in [
            ("qwen3.6-35b", os.environ.get("MLX_MODEL", "mlx-community/Qwen3.6-35B-A3B-mxfp8"), "chat"),
            ("e5-large-mlx", "mlx-community/multilingual-e5-large-mlx", "embedding"),
        ]:
            r = await c.post("/models", json={"name": name, "provider_id": pid, "model_id": mid, "kind": kind})
            await c.put(f"/models/{r.json()['id']}/default")
        ms = (await c.get("/models")).json()
        real = [(m["name"], m["kind"]) for m in ms if m.get("provider_kind") != "mock" and m["is_default"]]
        ags = (await c.get("/agents")).json()
        mts = (await c.get("/memory-types")).json()
        print(f"  ✓ 실모델 기본값: {real}")
        print(f"  ✓ 시드 에이전트: {len(ags)}개")
        dead = [x["name"] for x in mts if x["name"] != "장기 기억 (mem0)"]
        print(f"  {'✓' if not dead else '✗'} memory_types 정상(죽은 행 {dead or '없음'})")

asyncio.run(main())
"""


def main() -> int:
    if "--yes" not in sys.argv:
        print(PLAN)
        return 0

    print("① api 정지(pkill 패턴 — 포트 kill 금지)")
    sh(["pkill", "-f", "uvicorn api.main:app"])
    time.sleep(3)

    print("② DB 초기화")
    asyncio.run(_reset_db())

    print("③ api 재기동(부팅=alembic+seed)")
    log = open("/tmp/api-server.log", "w")
    subprocess.Popen(
        [
            "uv", "run", "--project", "packages/api", "uvicorn", "api.main:app",
            "--host", "127.0.0.1", "--port", "8000", "--reload",
            "--reload-dir", "packages/api/src", "--reload-dir", "packages/agent/src",
            "--timeout-graceful-shutdown", "5",
        ],
        cwd=REPO, stdout=log, stderr=log, start_new_session=True,
    )
    if not _wait_health():
        print("  ✗ api 기동 실패 — /tmp/api-server.log 확인")
        return 1
    print("  ✓ docs 200")

    print("④ 실모델(MLX) 복원 + 검증")
    r = sh(["uv", "run", "python", "-c", _RESTORE_SNIPPET], cwd=REPO / "packages" / "api")
    print("\n".join(ln for ln in r.stdout.splitlines() if ln.strip().startswith(("✓", "✗", "  "))) or r.stdout[-500:])
    if r.returncode != 0:
        print("  ✗ 실모델 복원 실패:", r.stderr[-300:])
        return 1

    print("⑤ vite(5173) 확인")
    alive = sh(["lsof", "-nP", "-iTCP:5173", "-sTCP:LISTEN"]).returncode == 0
    if alive:
        print("  ✓ vite 생존")
    else:
        print(
            "  ✗ vite 죽음 — 재기동: cd admin && VITE_ALLOWED_HOSTS=true npm run dev -- --host 127.0.0.1"
        )
    print("\n초기화 완료. (원격 브라우저는 하드 리프레시 + 재로그인 필요)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

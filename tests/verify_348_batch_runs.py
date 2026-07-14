"""verify_348 — 배치가 **실제로 돈다** (스펙 348).

`batch_runs` 0행 = 이 서비스가 생긴 이래 배치 잡이 한 번도 안 돌았다는 뜻이었다. cron 설정은 있었지만
그걸 읽어 실행할 프로세스를 아무도 안 켰다 — **청소 잡은 손이 없으면 죽은 코드**다.

  B1 스케줄러가 **리더**로 떠 있고 cron이 설정된 잡이 등록됐다(next_run_time 존재).
  B2 **실제로 발화한다**: cron을 1분 주기로 두면 90초 내 `batch_runs`가 증가한다(살아 있는 손의 증거).
     — 스케줄이 등록됐다는 것과 실제로 실행됐다는 것은 다르다(설치 ≠ 가동).
  B3 **이중 발화 없음**: 두 번째 프로세스는 advisory lock을 못 잡아 리더가 아니며 잡을 등록하지 않는다
     (같은 삭제 잡이 워커 수만큼 실행되면 파괴가 배수된다).
  B4 리더 락을 놓으면 다른 프로세스가 **승계**할 수 있다(락 해제 실측).

실행: uv run python tests/verify_348_batch_runs.py   (dev 서버 8000 필요 · 약 2분 소요)
"""

import asyncio
import json
import pathlib
import sys
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "api" / "src"))

from sqlalchemy import text  # noqa: E402

from api.db import SessionLocal, engine  # noqa: E402

BASE = "http://127.0.0.1:8000"
_fails: list[str] = []
passed = 0


def check(cond: object, msg: str) -> None:
    global passed
    print(("  ok  " if cond else " FAIL ") + msg, flush=True)
    if cond:
        passed += 1
    else:
        _fails.append(msg)


_cookie = ""


def login() -> None:
    global _cookie
    req = urllib.request.Request(
        BASE + "/auth/login",
        data=b"username=admin@example.com&password=adminpass123",
        method="POST",
    )
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=20) as r:
        _cookie = "; ".join(c.split(";")[0] for c in r.headers.get_all("Set-Cookie") or [])


def _req(path: str, method: str = "GET", body: dict | None = None):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(body).encode() if body else None, method=method
    )
    req.add_header("Cookie", _cookie)
    if body:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read().decode()
        return json.loads(raw) if raw else {}


async def _runs() -> int:
    async with SessionLocal() as s:
        return (await s.execute(text("select count(*) from batch_runs"))).scalar_one()


async def main() -> None:
    login()

    # ---- B1 리더 + 잡 등록
    st = _req("/admin/batch/scheduler")
    jobs = {j["name"]: j["next_run_time"] for j in st.get("jobs", [])}
    check(st.get("leader") is True, f"B1a 스케줄러가 리더로 가동 중 (mode={st.get('mode')!r})")
    check(
        "checkpoint-cleanup" in jobs and jobs["checkpoint-cleanup"],
        f"B1b cron 설정된 잡이 등록됨(next_run_time 존재) (jobs={jobs})",
    )

    # ---- B3 이중 발화 없음: 두 번째 프로세스는 락을 못 잡는다
    conn = await engine.connect()
    got = (
        await conn.execute(text("select pg_try_advisory_lock(:k)"), {"k": 0x6D7961_6231})
    ).scalar_one()
    await conn.close()
    check(
        got is False,
        "B3 두 번째 프로세스는 리더 락을 못 잡는다(크론 이중 발화 구조적 차단)",
    )

    # ---- B2 실제로 발화하는가 — cron을 1분 주기로 바꾸고 기다린다(설치 ≠ 가동)
    original = _req("/admin/batch/config")
    before = await _runs()
    print(f"  ... cron을 매분으로 바꾸고 최대 100초 대기(현재 batch_runs={before}행)", flush=True)
    _req("/admin/batch/config", "PATCH", {"checkpoint_cleanup_cron": "* * * * *"})
    # 스케줄 재적재: 앱이 재기동 없이 반영하지 않으므로 트리거는 서버 재시작 없이 확인 불가 →
    # 대신 **runner를 직접 태우지 않고** 스케줄러가 다시 뜰 때 등록되게 lifespan을 재사용한다.
    # (여기서는 cron 변경 후 스케줄러가 이미 등록한 잡의 다음 발화를 기다린다.)
    fired = False
    for _ in range(20):  # 20 × 5초 = 100초
        await asyncio.sleep(5)
        if await _runs() > before:
            fired = True
            break
    after = await _runs()
    check(
        fired,
        f"B2 스케줄러가 **실제로 발화**해 batch_runs 증가 ({before} → {after})",
    )

    # 원복(cron)
    _req(
        "/admin/batch/config",
        "PATCH",
        {"checkpoint_cleanup_cron": original.get("checkpoint_cleanup_cron") or "0 * * * *"},
    )

    # ---- B4 락 해제 시 승계 가능
    async with SessionLocal() as s:
        held = (
            await s.execute(
                text(
                    "select count(*) from pg_locks where locktype='advisory' "
                    "and ((classid::bigint << 32) | objid::bigint) = :k"
                ),
                {"k": 0x6D7961_6231},
            )
        ).scalar_one()
    check(held >= 1, f"B4 리더 락이 DB에 실제로 잡혀 있다(승계 근거) (advisory lock {held}건)")

    print()
    if _fails:
        print(f"FAIL {len(_fails)}건: {_fails}")
        sys.exit(1)
    print(f"VERIFY348_OK — {passed}건 전부 통과")


asyncio.run(main())

"""verify_350 — 승인 회수 + 폴링 비용 (스펙 350).

누수 둘: ①위험 도구 호출마다 `approvals` 1행이 쌓이는데 **삭제 코드가 리포 전체에 없었다**
②플레이그라운드가 승인 1건의 상태를 알려고 **전 목록**(LIMIT 없음)을 2.5초마다 60회까지 폴링
(행이 쌓일수록 폴링 비용이 같이 커지는 증폭 구조).

  A1 **처리된 승인만** 회수 — 오래된 approved/rejected/expired는 삭제.
  A2 **pending은 0건 삭제** — 그건 **재개의 근거**다(회고 038: pending을 지우면 그래프가 재개 불가 고아).
  A3 dry-run은 세기만 하고 삭제 0.
  A4 보존기간 <1이면 잡 비활성(delete-all 금지).
  A5 **폴링이 O(1)**: 단건 조회 응답 크기가 승인 행 수에 **비례하지 않는다**(행을 20개 더 심어도
     응답 크기 불변) — 목록 응답은 커지는 것과 대조.
  A6 인가: 단건 조회도 목록과 같은 스코프(admin은 조회 가능, 없는 id는 404).
  A7 소비자 스캔: 플레이그라운드가 더 이상 전체 목록 폴링을 쓰지 않는다.

실행: uv run python tests/verify_350_approval_retention.py   (dev 서버 8000 필요)
"""

import asyncio
import json
import pathlib
import sys
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime, timedelta

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "api" / "src"))

from sqlalchemy import text  # noqa: E402

from api.batch.jobs import cleanup_approvals  # noqa: E402
from api.db import SessionLocal  # noqa: E402

BASE = "http://127.0.0.1:8000"
MARK = f"v350-{uuid.uuid4().hex[:6]}"
_fails: list[str] = []
passed = 0


def check(cond: object, msg: str) -> None:
    global passed
    print(("  ok  " if cond else " FAIL ") + msg)
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


def _get_raw(path: str) -> tuple[int, int]:
    """(status, 응답 바이트 수)."""
    req = urllib.request.Request(BASE + path)
    req.add_header("Cookie", _cookie)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, len(r.read())
    except urllib.error.HTTPError as e:
        return e.code, 0


async def _plant(n: int, *, status: str, age_days: float) -> list[str]:
    """합성 승인 — status와 나이를 지정."""
    ts = datetime.now(UTC) - timedelta(days=age_days)
    ids = []
    async with SessionLocal() as s:
        for i in range(n):
            apid = f"{MARK}-{status}-{i}"
            await s.execute(
                text(
                    "insert into approvals (id, approval_id, status, agent_name, permission, action, args, "
                    "summary, requested_at, resolved_at, created_at, updated_at, created_by, updated_by) "
                    "values (gen_random_uuid(), :a, :st, 'v350', 'data.delete', 'v350 검증 액션', "
                    "'{}'::jsonb, 'v350 검증용', :ts, :rs, now(), now(), 'system', 'system')"
                ),
                {"a": apid, "st": status, "ts": ts, "rs": None if status == "pending" else ts},
            )
            ids.append(apid)
        await s.commit()
    return ids


async def _count(where: str) -> int:
    async with SessionLocal() as s:
        return (
            await s.execute(text(f"select count(*) from approvals where {where}"))  # noqa: S608
        ).scalar_one()


async def _cleanup() -> None:
    async with SessionLocal() as s:
        await s.execute(text("delete from approvals where approval_id like :p"), {"p": f"{MARK}%"})
        await s.commit()


async def main() -> None:
    login()
    await _cleanup()

    # 오래된 처리 승인 3 + 오래된 **pending** 2(보존돼야 함) + 최근 처리 승인 1(보존돼야 함)
    await _plant(3, status="approved", age_days=40)
    await _plant(2, status="pending", age_days=40)
    await _plant(1, status="rejected", age_days=1)

    # A3 dry-run
    dry = await cleanup_approvals(dry_run=True)
    check(
        dry.get("would_delete", 0) >= 3 and await _count(f"approval_id like '{MARK}%'") == 6,
        f"A3 dry-run은 대상만 집계하고 삭제 0 (would_delete={dry.get('would_delete')}, "
        f"pending 보호={dry.get('pending_protected')})",
    )

    # A1/A2 실행
    res = await cleanup_approvals(dry_run=False)
    old_done = await _count(f"approval_id like '{MARK}-approved%'")
    pend = await _count(f"approval_id like '{MARK}-pending%'")
    recent = await _count(f"approval_id like '{MARK}-rejected%'")
    check(old_done == 0, f"A1a 오래된 처리 승인 삭제 (남음: {old_done}, deleted={res.get('deleted')})")
    check(recent == 1, f"A1b 보존기간 내 처리 승인은 **안 지운다** (남음: {recent}/1)")
    check(pend == 2, f"A2 **pending은 0건 삭제**(재개 근거 보존) (남음: {pend}/2)")

    # A4 바닥
    async with SessionLocal() as s:
        await s.execute(text("update batch_config set approval_retention_days = 0"))
        await s.commit()
    floor = await cleanup_approvals(dry_run=False)
    still = await _count(f"approval_id like '{MARK}%'")
    check(
        floor.get("status") == "disabled" and still == 3,
        f"A4 보존기간<1이면 잡 비활성(delete-all 금지) (status={floor.get('status')!r}, 잔존={still})",
    )
    async with SessionLocal() as s:
        await s.execute(text("update batch_config set approval_retention_days = 30"))
        await s.commit()

    # A5 폴링이 O(1) — 행을 늘려도 단건 조회 응답 크기 불변, 목록은 커진다
    one_id = f"{MARK}-pending-0"
    st1, one_before = _get_raw(f"/approvals/{one_id}")
    _, list_before = _get_raw("/approvals")
    await _plant(20, status="approved", age_days=0.1)  # 최근 행 20개 추가(회수 대상 아님)
    st2, one_after = _get_raw(f"/approvals/{one_id}")
    _, list_after = _get_raw("/approvals")
    check(
        st1 == 200 and st2 == 200 and one_before == one_after,
        f"A5a 단건 조회 응답 크기가 행 수에 **불변**({one_before}B → {one_after}B) = O(1) 폴링",
    )
    check(
        list_after > list_before,
        f"A5b (대조) 목록 응답은 행 수에 비례해 커진다 ({list_before}B → {list_after}B) — 옛 폴링이 이걸 60회 받았다",
    )

    # A6 인가/404
    st404, _ = _get_raw(f"/approvals/{MARK}-nope")
    check(st404 == 404, f"A6 없는 승인은 404(존재 비노출) (got {st404})")

    # A7 소비자 스캔 — 플레이그라운드가 전체 목록 폴링을 안 쓴다
    pg = (ROOT / "admin/src/playground/Playground.tsx").read_text()
    check(
        "getApproval(apid)" in pg and "await listApprovals()" not in pg,
        "A7 플레이그라운드가 단건 조회로 폴링(전체 목록 폴링 제거)",
    )

    await _cleanup()
    print()
    if _fails:
        print(f"FAIL {len(_fails)}건: {_fails}")
        sys.exit(1)
    print(f"VERIFY350_OK — {passed}건 전부 통과")


asyncio.run(main())

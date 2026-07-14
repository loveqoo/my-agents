"""verify_349 — 만료 토큰 회수 (스펙 349).

로그인마다 `accesstoken` 1행이 쌓이는데 지우는 코드가 **로그아웃뿐**이었다. 만료(7일)된 뒤에도
행은 영원히 남는다 — 인증에 못 쓰는 자격증명 조각이 무한 누적(위생·보안 부채).

  T1 **만료 토큰만 삭제**: 8일 된 합성 토큰은 지워지고, **방금 만든 토큰은 남는다**.
  T2 dry-run은 세기만 하고 **삭제 0**.
  T3 **살아 있는 세션은 안 끊긴다**: 청소 후에도 내 쿠키로 API 호출이 성공한다(진짜 위험은 이것 —
     로그아웃시켜 버리면 청소가 아니라 사고다).
  T4 **파괴적 노브 바닥**: 수명이 0/음수면 잡 비활성(전량 삭제=전 사용자 로그아웃 금지).

실행: uv run python tests/verify_349_token_reclaim.py   (dev 서버 8000 필요)
"""

import asyncio
import pathlib
import sys
import urllib.request
import uuid
from datetime import UTC, datetime, timedelta

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "api" / "src"))

from sqlalchemy import text  # noqa: E402

from api.batch.jobs import cleanup_tokens  # noqa: E402
from api.db import SessionLocal  # noqa: E402

BASE = "http://127.0.0.1:8000"
_fails: list[str] = []
passed = 0
MARK = f"v349{uuid.uuid4().hex[:6]}"


def check(cond: object, msg: str) -> None:
    global passed
    print(("  ok  " if cond else " FAIL ") + msg)
    if cond:
        passed += 1
    else:
        _fails.append(msg)


def login() -> str:
    req = urllib.request.Request(
        BASE + "/auth/login",
        data=b"username=admin@example.com&password=adminpass123",
        method="POST",
    )
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=20) as r:
        return "; ".join(c.split(";")[0] for c in r.headers.get_all("Set-Cookie") or [])


def call_ok(cookie: str) -> bool:
    """이 쿠키가 아직 유효한가 = 살아 있는 세션이 안 끊겼나."""
    req = urllib.request.Request(BASE + "/agents")
    req.add_header("Cookie", cookie)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status == 200
    except Exception:
        return False


async def _plant_expired(n: int) -> None:
    """8일 전에 만들어진 토큰 행 — 만료(7일) + 유예(1일)를 넘긴 회수 대상."""
    old = datetime.now(UTC) - timedelta(days=8, hours=1)
    async with SessionLocal() as s:
        uid = (await s.execute(text('select id from "user" limit 1'))).scalar_one()
        for i in range(n):
            await s.execute(
                text(
                    "insert into accesstoken (token, user_id, created_at) "
                    "values (:t, :u, :c)"
                ),
                {"t": f"{MARK}{i}{uuid.uuid4().hex[:24]}", "u": uid, "c": old},  # token 컬럼은 varchar(43)
            )
        await s.commit()


async def _count(where: str = "") -> int:
    async with SessionLocal() as s:
        return (
            await s.execute(text(f"select count(*) from accesstoken {where}"))  # noqa: S608 — 상수
        ).scalar_one()


async def main() -> None:
    cookie = login()  # 살아 있는 토큰 1개(내 세션)
    await _plant_expired(3)

    planted = await _count(f"where token like '{MARK}%'")
    fresh_before = await _count("where created_at > now() - interval '1 hour'")
    check(planted == 3, f"준비: 만료 토큰 3개 심음 (got {planted})")

    # T2 dry-run — 세기만 한다
    dry = await cleanup_tokens(dry_run=True)
    still = await _count(f"where token like '{MARK}%'")
    check(
        dry.get("would_delete", 0) >= 3 and still == 3,
        f"T2 dry-run은 대상만 집계하고 삭제 0 (would_delete={dry.get('would_delete')}, 잔존={still})",
    )

    # T1 실행 — 만료만 삭제
    res = await cleanup_tokens(dry_run=False)
    left_expired = await _count(f"where token like '{MARK}%'")
    fresh_after = await _count("where created_at > now() - interval '1 hour'")
    check(left_expired == 0, f"T1a 만료 토큰 삭제됨 (남은 만료 토큰: {left_expired}, deleted={res.get('deleted')})")
    check(
        fresh_after == fresh_before,
        f"T1b 방금 만든 토큰은 **안 지운다** ({fresh_before} → {fresh_after})",
    )

    # T3 살아 있는 세션 — 청소 후에도 내 쿠키가 유효한가(진짜 위험: 청소가 로그아웃 사고가 되는 것)
    check(call_ok(cookie), "T3 청소 후에도 로그인 세션 유지(살아 있는 토큰 보존)")

    # T4 파괴적 노브 바닥 — 수명 0이면 잡 비활성
    import api.users as users_mod

    orig = users_mod.SESSION_LIFETIME_SECONDS
    users_mod.SESSION_LIFETIME_SECONDS = 0
    try:
        floor = await cleanup_tokens(dry_run=False)
    finally:
        users_mod.SESSION_LIFETIME_SECONDS = orig
    alive = await _count("where created_at > now() - interval '1 hour'")
    check(
        floor.get("status") == "disabled" and alive == fresh_after,
        f"T4 수명<=0이면 잡 비활성(전 사용자 로그아웃=delete-all 금지) (status={floor.get('status')!r})",
    )

    print()
    if _fails:
        print(f"FAIL {len(_fails)}건: {_fails}")
        sys.exit(1)
    print(f"VERIFY349_OK — {passed}건 전부 통과")


asyncio.run(main())

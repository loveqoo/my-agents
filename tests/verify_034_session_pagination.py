"""스펙 034 검증 — 세션 페이징(offset/limit + total + counts).

인프로세스 httpx(ASGI) + 실 DB(읽기 위주)로 수치 단언한다. 검증용 세션을
고유 prefix(sess_v034_)로 삽입 → 단언 → **삭제**(자가정리, 실데이터 불간섭).

단언:
  1. 셰이프 {items, total, counts}, items ≤ limit.
  2. offset/limit 페이지네이션이 정렬(started_at desc, id desc) 위에서 결정적·비중복.
  3. total = 필터 적용 총 건수. 페이지 가로질러 합 = total.
  4. counts(전체 집계)의 live 버킷이 status active/running/draining 합과 일치.
  5. limit 클램프(>100 → 422), offset 음수 → 422.
  6. 알 수 없는 status → all 폴백(필터 안 함).

실행: .venv/bin/python tests/verify_034_session_pagination.py
"""
import asyncio
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))

import httpx  # noqa: E402
from sqlalchemy import delete, select  # noqa: E402

from api.auth import _token  # noqa: E402
from api.db import SessionLocal as async_session  # noqa: E402
from api.main import app  # noqa: E402
from api.models import Agent, Session  # noqa: E402

# 머신 Bearer 토큰(앱과 동일 출처: env API_AUTH_TOKEN → .dev/.api_token).
_AUTH = {"Authorization": f"Bearer {_token()}"}

_fails: list[str] = []
PREFIX = "sess_v034_"
N = 45  # > 2 페이지(limit 20)
# 검증용 status 분포: active 25, running 8, draining 4, completed 8 → live 버킷 = 37
_DIST = ["active"] * 25 + ["running"] * 8 + ["draining"] * 4 + ["completed"] * 8


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


async def _seed(sess) -> None:
    agent = (await sess.execute(select(Agent).limit(1))).scalar_one_or_none()
    if agent is None:
        raise RuntimeError("검증 불가: agents 테이블이 비어 있음(시드 필요)")
    # started_at을 i초씩 어긋나게 둬 정렬을 결정적으로(최근=i 큰 것).
    from datetime import datetime, timedelta, timezone

    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i, st in enumerate(_DIST):
        sess.add(
            Session(
                session_id=f"{PREFIX}{i:03d}",
                agent_pk=agent.id,
                agent_name="verify034",
                status=st,
                started_at=base + timedelta(seconds=i),
            )
        )
    await sess.commit()


async def _cleanup(sess) -> None:
    await sess.execute(delete(Session).where(Session.session_id.like(f"{PREFIX}%")))
    await sess.commit()


async def _baseline(c) -> tuple[int, int]:
    """주입 전 counts 기준선(all, live) — 델타 단언용."""
    r = (await c.get("/sessions", params={"status": "all", "limit": 1})).json()
    return r["counts"]["all"], r["counts"]["live"]


async def main() -> None:
    async with async_session() as sess:
        await _cleanup(sess)  # 이전 실패 잔재 제거

    # 주입 전 baseline 측정(인증 클라로).
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t", headers=_AUTH
    ) as c0:
        base_all, base_live = await _baseline(c0)

    async with async_session() as sess:
        await _seed(sess)

    transport = httpx.ASGITransport(app=app)
    # 불변식 기반 검증(실 DB에 기존 데이터가 있어도 견고). 주입한 47건 외 기존 행은 baseline으로 흡수.
    INJ_LIVE = 37  # active 25 + running 8 + draining 4
    INJ_ALL = len(_DIST)  # 45 (live 37 + completed 8)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://t", headers=_AUTH) as c:
            # --- 셰이프 ---
            print("[shape] 엔벌로프")
            r1 = (await c.get("/sessions", params={"status": "live", "limit": 20, "offset": 0})).json()
            check(set(r1) == {"items", "total", "counts"}, "셰이프 {items,total,counts}")
            check(len(r1["items"]) == 20, f"1페이지 items == limit(20) (got {len(r1['items'])})")
            check(set(r1["counts"]) == {"all", "live", "awaiting", "error"}, "counts 버킷 4종")

            # --- 핵심 불변식: total(status=X) == counts[X] ---
            print("[invariant] total(status=X) == counts[X]")
            for bucket in ("all", "live", "awaiting", "error"):
                rb = (await c.get("/sessions", params={"status": bucket, "limit": 1})).json()
                check(rb["total"] == rb["counts"][bucket],
                      f"{bucket}: total({rb['total']}) == counts.{bucket}({rb['counts'][bucket]})")

            r_all = (await c.get("/sessions", params={"status": "all", "limit": 1})).json()
            check(r_all["counts"] == r1["counts"], "counts는 필터 무관(동일)")
            check(r_all["total"] >= r1["total"], "all total >= live total")

            # --- 주입 델타: 우리 47건이 카운트에 정확히 반영 ---
            print("[delta] 주입 분포가 counts에 반영")
            check(r1["counts"]["all"] - base_all == INJ_ALL,
                  f"counts.all 델타 == {INJ_ALL} (got {r1['counts']['all'] - base_all})")
            check(r1["counts"]["live"] - base_live == INJ_LIVE,
                  f"counts.live 델타 == {INJ_LIVE} (got {r1['counts']['live'] - base_live})")

            # --- 페이지네이션 완전성·정렬: live 전체를 페이지로 순회 ---
            print("[paging] 전 페이지 순회 — 완전·비중복·정렬(desc)")
            total_live = r1["total"]
            seen: list[str] = []
            prev_started = None
            monotonic = True
            for off in range(0, total_live, 20):
                pg = (await c.get("/sessions", params={"status": "live", "limit": 20, "offset": off})).json()
                for s in pg["items"]:
                    seen.append(s["id"])
                    if prev_started is not None and s["started"] is not None and s["started"] > prev_started:
                        monotonic = False
                    if s["started"] is not None:
                        prev_started = s["started"]
            check(len(seen) == total_live, f"순회 수집 == total({total_live}) (got {len(seen)})")
            check(len(set(seen)) == len(seen), "전 페이지 비중복(distinct)")
            check(monotonic, "started_at 내림차순 단조(정렬 안정)")
            injected_live = {f"{PREFIX}{i:03d}" for i, st in enumerate(_DIST) if st != "completed"}
            check(injected_live <= set(seen), "주입한 live 37건 모두 순회에 포함")

            # offset이 total 초과 → 빈 페이지(total 유지)
            over = (await c.get("/sessions", params={"status": "live", "limit": 20, "offset": total_live + 100})).json()
            check(over["items"] == [] and over["total"] == total_live, "offset>total → items=[]·total 유지")

            # --- 클램프/검증 ---
            print("[validation] 클램프·폴백")
            check((await c.get("/sessions", params={"limit": 101})).status_code == 422, "limit>100 → 422")
            check((await c.get("/sessions", params={"limit": 0})).status_code == 422, "limit<1 → 422")
            check((await c.get("/sessions", params={"offset": -1})).status_code == 422, "offset<0 → 422")
            r_unknown = (await c.get("/sessions", params={"status": "bogus", "limit": 1})).json()
            check(r_unknown["total"] == r_all["total"], "알 수 없는 status → all 폴백(필터 안 함)")
    finally:
        async with async_session() as sess:
            await _cleanup(sess)


if __name__ == "__main__":
    asyncio.run(main())
    print()
    if _fails:
        print(f"❌ {len(_fails)} FAILED")
        for f in _fails:
            print("   - " + f)
        sys.exit(1)
    print("✅ ALL PASS")

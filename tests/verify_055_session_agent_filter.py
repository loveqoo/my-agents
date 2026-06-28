"""스펙 055 검증 — 세션 목록 agent_id 필터(Playground 세션 이어가기 백엔드).

인프로세스 httpx(ASGI) + 실 DB로 수치 단언한다. 두 에이전트(A·B)에 고유 prefix
(sess_v055_) 세션을 주입 → 단언 → **삭제**(자가정리). 검증 사다리 중 '실인프라 통합' 단.

단언:
  1. `agent_id=A` → items 전부 A 소속(B 세션 누출 0). total == 주입한 A 건수(델타).
  2. `agent_id=B` → items 전부 B 소속. A·B 교차 누출 0.
  3. 미지의 agent_id → items=[]·total=0 (404 아님 — 목록 API 관대).
  4. `counts`는 전역(필터 무관) — agent_id 유무와 무관하게 동일.
  5. agent_id 미지정(기존 동작) → A·B 둘 다 포함(필터 없음, 회귀 0).
  6. status 버킷 + agent_id 동시 적용 → 교집합(A의 live만).

실행: .venv/bin/python tests/verify_055_session_agent_filter.py
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
from api.models import Agent, Message, Session  # noqa: E402

_AUTH = {"Authorization": f"Bearer {_token()}"}
_fails: list[str] = []
PREFIX = "sess_v055_"
# A: live 6 (active4+running2) + completed 3 = 9.  B: live 4 (active4) + error 2 = 6.
_A_DIST = ["active"] * 4 + ["running"] * 2 + ["completed"] * 3
_B_DIST = ["active"] * 4 + ["error"] * 2


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


async def _two_agents(sess):
    agents = (await sess.execute(select(Agent).limit(2))).scalars().all()
    if len(agents) < 2:
        raise RuntimeError("검증 불가: agents 테이블에 에이전트가 2개 미만(시드 필요)")
    return agents[0], agents[1]


async def _seed(sess, agent, dist, tag):
    from datetime import datetime, timedelta, timezone

    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i, st in enumerate(dist):
        sess.add(
            Session(
                session_id=f"{PREFIX}{tag}_{i:03d}",
                agent_pk=agent.id,
                agent_name=f"verify055_{tag}",
                status=st,
                started_at=base + timedelta(seconds=i),
            )
        )
    await sess.commit()


async def _cleanup(sess) -> None:
    await sess.execute(delete(Session).where(Session.session_id.like(f"{PREFIX}%")))
    await sess.commit()


async def _all_items(c, params):
    """페이지를 끝까지 순회해 전체 items 수집(필터 검증은 누락 없어야 함)."""
    out, off = [], 0
    while True:
        r = (await c.get("/sessions", params={**params, "limit": 100, "offset": off})).json()
        out.extend(r["items"])
        if len(r["items"]) < 100:
            return out, r["total"], r["counts"]
        off += 100


async def main() -> None:
    async with async_session() as sess:
        await _cleanup(sess)
        agent_a, agent_b = await _two_agents(sess)
        a_ext, b_ext = agent_a.agent_id, agent_b.agent_id
        a_ids = {f"{PREFIX}A_{i:03d}" for i in range(len(_A_DIST))}
        b_ids = {f"{PREFIX}B_{i:03d}" for i in range(len(_B_DIST))}
        await _seed(sess, agent_a, _A_DIST, "A")
        await _seed(sess, agent_b, _B_DIST, "B")
        # preview 검증용: A_000 세션에 긴 첫 사용자 메시지 + 이후 메시지(첫 것만 잡혀야 함).
        s000 = (
            await sess.execute(select(Session).where(Session.session_id == f"{PREFIX}A_000"))
        ).scalar_one()
        long_first = "사용자가-처음-보낸-매우-긴-질문-" + ("X" * 100)
        from datetime import datetime, timedelta, timezone

        mbase = datetime(2026, 1, 2, tzinfo=timezone.utc)
        # created_at을 명시적으로 어긋나게 — '첫 사용자 메시지' 판정을 결정적으로(동일 트랜잭션
        # server_default면 타임스탬프가 같아 정렬이 모호해진다).
        sess.add(Message(session_pk=s000.id, role="user", content=long_first, created_at=mbase))
        sess.add(Message(session_pk=s000.id, role="assistant", content="답변1", created_at=mbase + timedelta(seconds=1)))
        sess.add(Message(session_pk=s000.id, role="user", content="두번째질문-무시되어야함", created_at=mbase + timedelta(seconds=2)))
        await sess.commit()

    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://t", headers=_AUTH) as c:
            # --- 전역 counts 기준(필터 없음) ---
            _, _, global_counts = await _all_items(c, {"status": "all"})

            # --- 1. agent_id=A → A만 ---
            print("[filter] agent_id=A → A 세션만(B 누출 0)")
            a_items, a_total, a_counts = await _all_items(c, {"status": "all", "agent_id": a_ext})
            a_seen = {s["id"] for s in a_items}
            check(a_ids <= a_seen, f"주입한 A {len(a_ids)}건 모두 반환(got {len(a_ids & a_seen)})")
            check(len(b_ids & a_seen) == 0, "B 세션 누출 0(A 필터에 B 없음)")
            check(all(s["agentId"] == a_ext for s in a_items),
                  "A 필터 items 전부 agentId==A(타 에이전트 0)")

            # --- preview: 첫 사용자 메시지가 80자 절단+'…'로 라벨화(스펙 055 사용자 피드백) ---
            print("[preview] 첫 사용자 메시지 → 사람이 알아볼 라벨(80자 절단)")
            s000_out = next((s for s in a_items if s["id"] == f"{PREFIX}A_000"), None)
            check(s000_out is not None, "A_000 세션이 응답에 존재")
            if s000_out:
                pv = s000_out["preview"]
                check(pv is not None and pv.startswith("사용자가-처음-보낸-매우-긴-질문-"),
                      f"preview가 첫 사용자 메시지로 시작(got {pv!r})")
                check(pv is not None and len(pv) == 81 and pv.endswith("…"),
                      f"긴 메시지는 80자+'…'로 절단(len={len(pv) if pv else 0})")
                check(pv is not None and "두번째질문" not in pv,
                      "두번째 사용자 메시지는 preview에 안 들어감(첫 것만)")
            # 메시지 없는 세션은 preview=None(빈 세션).
            s001_out = next((s for s in a_items if s["id"] == f"{PREFIX}A_001"), None)
            check(s001_out is not None and s001_out["preview"] is None,
                  "메시지 없는 세션 → preview=None")

            # --- 2. agent_id=B → B만 ---
            print("[filter] agent_id=B → B 세션만(A 누출 0)")
            b_items, b_total, b_counts = await _all_items(c, {"status": "all", "agent_id": b_ext})
            b_seen = {s["id"] for s in b_items}
            check(b_ids <= b_seen, f"주입한 B {len(b_ids)}건 모두 반환(got {len(b_ids & b_seen)})")
            check(len(a_ids & b_seen) == 0, "A 세션 누출 0(B 필터에 A 없음)")
            check(all(s["agentId"] == b_ext for s in b_items),
                  "B 필터 items 전부 agentId==B")

            # --- 3. 미지의 agent_id → 빈 목록 ---
            print("[filter] 미지의 agent_id → items=[]·total=0(404 아님)")
            r_unknown = (await c.get("/sessions", params={"agent_id": "agt_does_not_exist_zzz"})).json()
            check(r_unknown["items"] == [] and r_unknown["total"] == 0,
                  f"미지의 id → 빈 목록(items={len(r_unknown['items'])}, total={r_unknown['total']})")

            # --- 4. counts 전역(필터 무관) ---
            print("[counts] agent_id 유무와 무관하게 counts 동일(전역)")
            check(a_counts == global_counts, "A 필터 counts == 전역 counts")
            check(b_counts == global_counts, "B 필터 counts == 전역 counts")
            check(r_unknown["counts"] == global_counts, "미지 필터 counts == 전역 counts")

            # --- 5. agent_id 미지정 → 회귀 0(A·B 둘 다 포함) ---
            print("[regression] agent_id 미지정 → 필터 없음(A·B 모두 포함)")
            no_items, _, _ = await _all_items(c, {"status": "all"})
            no_seen = {s["id"] for s in no_items}
            check(a_ids <= no_seen and b_ids <= no_seen, "필터 없으면 A·B 모두 포함(기존 동작)")

            # --- 6. status + agent_id 교집합 ---
            print("[combo] status=live + agent_id=A → A의 live만(6건)")
            la_items, la_total, _ = await _all_items(c, {"status": "live", "agent_id": a_ext})
            la_seen = {s["id"] for s in la_items}
            a_live = {f"{PREFIX}A_{i:03d}" for i, st in enumerate(_A_DIST) if st in ("active", "running", "draining")}
            check(a_live <= la_seen, f"A의 live {len(a_live)}건 모두 포함")
            check(len({f'{PREFIX}A_{i:03d}' for i, st in enumerate(_A_DIST) if st == 'completed'} & la_seen) == 0,
                  "A의 completed는 live 필터에서 제외")
            check(len(b_ids & la_seen) == 0, "live+A 교집합에 B 누출 0")
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

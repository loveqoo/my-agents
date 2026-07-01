"""스펙 098 검증 — 세션 목록 서버측 메타데이터 검색(q).

인프로세스 httpx(ASGI) + 실 DB로 수치 단언한다. 고유 prefix(sess_v098_) 세션을 주입 →
단언 → **삭제**(자가정리). 검증 사다리: rung① 단위 시맨틱 + rung② 실인프라 RBAC 통합.

rung① 검색 시맨틱(admin=머신토큰, 전체 스코프):
  1. q가 session_id·user_id·agent_name 각각을 부분일치로 매칭(3컬럼 OR).
  2. 대소문자 무시(ilike).
  3. 빈/공백 q → 필터 미적용(회귀 0 — 전부 반환).
  4. q + status 버킷 = AND(교집합).
  5. total·counts가 검색 반영(페이징 이전 전체 스코프 매칭).
  6. 와일드카드 이스케이프: q의 `_`·`%`는 리터럴(오라클/과매칭 차단).

rung② RBAC own-scope 통합(비-admin principal 오버라이드):
  7. 비-admin이 *타인* 세션과 매칭되는 검색어(agent_name 공유)를 넣어도 타인 세션 0(own-scope 홀드).
  8. 비-admin이 *본인* 세션을 검색어로 정상 조회(자가-잠금 핀 — 조임이 정당 접근 차단 안 함).

실행: .venv/bin/python tests/verify_098_session_search.py  (DB 필요)
"""
import asyncio
import os
import sys
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))

import httpx  # noqa: E402
from sqlalchemy import delete, select  # noqa: E402

from api import authz  # noqa: E402
from api.auth import _token, current_principal  # noqa: E402
from api.db import SessionLocal as async_session  # noqa: E402
from api.main import app  # noqa: E402
from api.models import Agent, Session  # noqa: E402

_AUTH = {"Authorization": f"Bearer {_token()}"}
_fails: list[str] = []
PREFIX = "sess_v098_"


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


class P:
    """비-admin principal 모사(id·is_superuser). own_scope=str(id)로 스코핑."""

    def __init__(self, is_superuser=False):
        self.id = uuid.uuid4()
        self.is_superuser = is_superuser


class FakeEnforcer:
    def __init__(self, allow):
        self.allow = allow

    def enforce(self, sub, obj, act):
        return (sub, obj, act) in self.allow


MEMBER = P(is_superuser=False)
OWN_UID = str(MEMBER.id)

# rung① 시드: 각 검색어가 정확히 한 컬럼만 때리도록 마커를 분산.
#   S1=session_id 마커, S2=user_id 마커, S3=agent_name 마커. plainagent 공통어로 OR 다중매칭.
# 이스케이프 시드: E_UND(리터럴 `_`) vs E_UNX(임의문자) — q="ESC-a_b"는 `_` 이스케이프 시 E_UND만.
#                  E_PCT(리터럴 `%`) vs E_PXX(임의런)  — q="ESC-p%q"는 `%` 이스케이프 시 E_PCT만.
_SEED = [
    dict(session_id=f"{PREFIX}MARKERID_1", user_id="v098_plainuser_a", agent_name="v098_plainagent_a", status="active"),
    dict(session_id=f"{PREFIX}s2", user_id="v098_MARKERUSER_b", agent_name="v098_plainagent_b", status="error"),
    dict(session_id=f"{PREFIX}s3", user_id="v098_plainuser_c", agent_name="v098_MARKERAGENT_c", status="active"),
    dict(session_id=f"{PREFIX}eund", user_id="v098_e_a", agent_name="ESC-a_b", status="active"),
    dict(session_id=f"{PREFIX}eunx", user_id="v098_e_b", agent_name="ESC-axb", status="active"),
    dict(session_id=f"{PREFIX}epct", user_id="v098_e_c", agent_name="ESC-p%q", status="active"),
    dict(session_id=f"{PREFIX}epxx", user_id="v098_e_d", agent_name="ESC-pXXq", status="active"),
]
# rung② 시드: 같은 agent_name(v098_SECRETAGENT)을 own/foreign이 공유 → 검색이 스코프를 못 넘음 증명.
_SEED_RBAC = [
    dict(session_id=f"{PREFIX}own", user_id=OWN_UID, agent_name="v098_SECRETAGENT", status="active"),
    dict(session_id=f"{PREFIX}foreign", user_id="v098_other_user", agent_name="v098_SECRETAGENT", status="active"),
]


async def _seed(sess, rows, agent_pk) -> None:
    from datetime import datetime, timedelta, timezone

    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i, r in enumerate(rows):
        sess.add(Session(**r, agent_pk=agent_pk, started_at=base + timedelta(seconds=i)))
    await sess.commit()


async def _cleanup(sess) -> None:
    await sess.execute(delete(Session).where(Session.session_id.like(f"{PREFIX}%")))
    await sess.commit()


async def _ids(c, params):
    """페이지 끝까지 순회해 (id 집합, total, counts) 반환."""
    seen, off = set(), 0
    total = counts = None
    while True:
        r = (await c.get("/sessions", params={**params, "limit": 100, "offset": off})).json()
        total, counts = r["total"], r["counts"]
        seen |= {s["id"] for s in r["items"]}
        if len(r["items"]) < 100:
            return seen, total, counts
        off += 100


def _mine(seen):
    """이 테스트가 주입한 세션만(공유 DB의 타 세션 노이즈 제거)."""
    return {x for x in seen if x.startswith(PREFIX)}


async def main() -> None:
    async with async_session() as sess:
        await _cleanup(sess)
        agent = (await sess.execute(select(Agent).limit(1))).scalar_one_or_none()
        if agent is None:
            raise RuntimeError("검증 불가: agents 테이블 비어있음(시드 필요)")
        await _seed(sess, _SEED, agent.id)
        await _seed(sess, _SEED_RBAC, agent.id)

    transport = httpx.ASGITransport(app=app)
    try:
        # ===== rung① 검색 시맨틱(admin) =====
        async with httpx.AsyncClient(transport=transport, base_url="http://t", headers=_AUTH) as c:
            print("[1] q가 3컬럼 각각을 부분일치 매칭(session_id·user_id·agent_name)")
            sid, _, _ = await _ids(c, {"q": "MARKERID"})
            check(_mine(sid) == {f"{PREFIX}MARKERID_1"}, f"session_id 매칭(got {_mine(sid)})")
            uid, _, _ = await _ids(c, {"q": "MARKERUSER"})
            check(_mine(uid) == {f"{PREFIX}s2"}, f"user_id 매칭(got {_mine(uid)})")
            aid, _, _ = await _ids(c, {"q": "MARKERAGENT"})
            check(_mine(aid) == {f"{PREFIX}s3"}, f"agent_name 매칭(got {_mine(aid)})")

            print("[1b] OR 다중매칭(공통 agent_name 부분어)")
            multi, _, _ = await _ids(c, {"q": "v098_plainagent"})
            check(_mine(multi) == {f"{PREFIX}MARKERID_1", f"{PREFIX}s2"},
                  f"plainagent → S1·S2(got {_mine(multi)})")

            print("[2] 대소문자 무시(ilike)")
            lower, _, _ = await _ids(c, {"q": "markerid"})
            check(_mine(lower) == {f"{PREFIX}MARKERID_1"}, "소문자 질의도 매칭")

            print("[3] 빈/공백 q → 필터 미적용(회귀 0)")
            empty, _, _ = await _ids(c, {"q": ""})
            ws, _, _ = await _ids(c, {"q": "   "})
            all_mine = {r["session_id"] for r in _SEED + _SEED_RBAC}
            check(all_mine <= _mine(empty), "빈 q → 전부 반환")
            check(all_mine <= _mine(ws), "공백 q → 전부 반환(strip 후 미적용)")

            print("[4] q + status = AND(교집합)")
            combo, _, _ = await _ids(c, {"q": "v098_plainagent", "status": "error"})
            check(_mine(combo) == {f"{PREFIX}s2"}, f"plainagent+error → S2만(got {_mine(combo)})")

            print("[5] total·counts가 검색 반영(전체 스코프)")
            _, t_marker, _ = await _ids(c, {"q": "MARKERID"})
            check(t_marker == 1, f"q=MARKERID total==1(got {t_marker})")

            print("[6] 와일드카드 이스케이프(`_`·`%` 리터럴)")
            und, _, _ = await _ids(c, {"q": "ESC-a_b"})
            check(_mine(und) == {f"{PREFIX}eund"},
                  f"`_`는 리터럴 → ESC-a_b만(ESC-axb 제외, got {_mine(und)})")
            pct, _, _ = await _ids(c, {"q": "ESC-p%q"})
            check(_mine(pct) == {f"{PREFIX}epct"},
                  f"`%`는 리터럴 → ESC-p%q만(ESC-pXXq 제외, got {_mine(pct)})")

        # ===== rung② RBAC own-scope 통합(비-admin) =====
        authz.get_enforcer = lambda: FakeEnforcer(set())  # 정책 전무 → MEMBER=비-admin
        app.dependency_overrides[current_principal] = lambda: MEMBER
        try:
            async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
                print("[7] 비-admin 검색이 own-scope를 못 넘음(타인 세션 0)")
                secret, _, _ = await _ids(c, {"q": "SECRETAGENT"})
                mine = _mine(secret)
                check(f"{PREFIX}foreign" not in mine,
                      f"타인 세션(foreign) 검색 누출 0(got {mine})")
                check(mine <= {f"{PREFIX}own"},
                      f"비-admin 검색 결과는 본인 세션에 한정(got {mine})")

                print("[8] 비-admin이 본인 세션 검색 정상(자가-잠금 핀)")
                own, _, _ = await _ids(c, {"q": "SECRETAGENT"})
                check(f"{PREFIX}own" in _mine(own), "본인 세션은 검색으로 조회됨(정당 접근 차단 안 함)")
                ownid, _, _ = await _ids(c, {"q": "v098_own"})
                check(_mine(ownid) == {f"{PREFIX}own"}, "본인 session_id 검색도 정상")
        finally:
            app.dependency_overrides.pop(current_principal, None)
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
    print("✅ ALL PASS — 스펙 098 세션 검색(시맨틱·이스케이프·RBAC own-scope) 통과")

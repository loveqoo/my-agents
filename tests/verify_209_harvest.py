"""스펙 209 Phase 2 검증(라이브 통합) — 피드백 → 평가 케이스 수확을 실 HTTP 위에서.

verify_209_feedback 패턴 재사용. 수확 입구의 소유권·정확성을 실측한다:
- 에이전트 소유자/admin만 수확·수확수 조회(비소유=404 은폐).
- 미수확 피드백 → 초안 케이스(질문=직전 user 메시지, assert=llm_judge). 도우미 mock이라 폴백 템플릿.
- 케이스별 harvested_case_pk 스탬프 → 재수확 스킵(중복 0).
- **크로스에이전트 격리**: agent1 수확이 agent2 세션 피드백을 먹지 않음.
- idempotent: 재수확은 같은 문제집(source_agent_pk) 재사용, 2번째 문제집 미생성.

전제: API(127.0.0.1:8000)+실 DB 생존. 실행: .venv/bin/python tests/verify_209_harvest.py
"""

import asyncio
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))

import httpx  # noqa: E402
from dotenv import load_dotenv  # noqa: E402
from sqlalchemy import delete, func, select  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

from api.db import SessionLocal  # noqa: E402
from api.models import (  # noqa: E402
    Agent,
    EvalCase,
    EvalDataset,
    Message,
    MessageFeedback,
    Session,
    User,
)

BASE = os.environ.get("VERIFY_BASE", "http://127.0.0.1:8000")  # 스펙 390: 격리 서버 주입
PY = os.path.join(ROOT, ".venv", "bin", "python")
PROV = os.path.join(ROOT, "tests", "_provision_super.py")

OWNER_EMAIL = "probe209ho@example.com"
OTHER_EMAIL = "probe209hn@example.com"  # 비소유 멤버
SUPER_EMAIL = "probe209hs@example.com"
PW = "Probe209h-pw!"
A1 = "agt-209h1"
A2 = "agt-209h2"
SPREFIX = "sess-209h-"

_fails: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def _provision(create: bool) -> None:
    cmd = "create" if create else "delete"
    for email, extra in [(OWNER_EMAIL, ["member"]), (OTHER_EMAIL, ["member"]), (SUPER_EMAIL, [])]:
        args = [PY, PROV, cmd, email] + ([PW] + extra if create else [])
        subprocess.run(args, check=False, capture_output=True, text=True)


async def _uid(session, email: str) -> str:
    return str((await session.execute(select(User.id).where(User.email == email))).scalar_one())


async def _seed(owner_id: str) -> dict:
    """member 소유 agent1·agent2. agent1 세션 2개(👍·👎+이유), agent2 세션 1개(👍, 격리 검증용).
    피드백은 owner가 남긴 것으로 직접 삽입(미수확)."""
    ids: dict = {}
    async with SessionLocal() as s:
        a1 = Agent(agent_id=A1, name="probe209h1", source="ui", owner_id=owner_id)
        a2 = Agent(agent_id=A2, name="probe209h2", source="ui", owner_id=owner_id)
        s.add(a1)
        s.add(a2)
        await s.flush()
        ids["a1"] = str(a1.id)
        ids["a2"] = str(a2.id)

        async def _sess(agent, key, q, rating, reason):
            sid = f"{SPREFIX}{key}"
            sess = Session(
                session_id=sid,
                agent_pk=agent.id,
                agent_name=agent.name,
                user_id=owner_id,
                status="active",
            )
            s.add(sess)
            await s.flush()
            um = Message(session_pk=sess.id, role="user", content=q)
            am = Message(session_pk=sess.id, role="assistant", content=f"답변-{key}")
            s.add(um)
            s.add(am)
            await s.flush()
            fb = MessageFeedback(
                message_pk=am.id,
                session_pk=sess.id,
                rating=rating,
                reason=reason,
                owner_id=owner_id,
            )
            s.add(fb)
            return {"sid": sid, "asst_mid": str(am.id), "q": q, "fb_rating": rating}

        ids["A"] = await _sess(a1, "A", "질문A는 무엇인가?", "up", "")
        ids["B"] = await _sess(a1, "B", "질문B는 무엇인가?", "down", "환각이 있었다")
        ids["C"] = await _sess(a2, "C", "질문C는 무엇인가?", "up", "")  # agent2 — 격리 대상
        await s.commit()
    return ids


async def _cleanup() -> None:
    async with SessionLocal() as s:
        # 수확 문제집(source_agent_pk가 이 에이전트) 삭제 → 케이스 CASCADE
        agent_pks = (
            (await s.execute(select(Agent.id).where(Agent.agent_id.in_([A1, A2])))).scalars().all()
        )
        if agent_pks:
            await s.execute(delete(EvalDataset).where(EvalDataset.source_agent_pk.in_(agent_pks)))
        await s.execute(delete(Session).where(Session.session_id.like(f"{SPREFIX}%")))
        await s.execute(delete(Agent).where(Agent.agent_id.in_([A1, A2])))
        await s.commit()


async def _login(client: httpx.AsyncClient, email: str) -> bool:
    r = await client.post(
        "/auth/login",
        data={"username": email, "password": PW},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    return r.status_code in (200, 204)


async def _poll_done(client: httpx.AsyncClient, dataset_id: str, tries: int = 40) -> dict:
    """수확 배경 작업 완료까지 폴링(generating=False). 반환=최종 DatasetOut."""
    for _ in range(tries):
        r = await client.get(f"/eval/datasets/{dataset_id}")
        d = r.json()
        if not d.get("generating"):
            return d
        await asyncio.sleep(0.25)
    return d


async def _dataset_count_for(agent_pk: str) -> int:
    async with SessionLocal() as s:
        return (
            await s.execute(
                select(func.count())
                .select_from(EvalDataset)
                .where(EvalDataset.source_agent_pk == agent_pk)
            )
        ).scalar_one()


async def _stamped_count(agent_pk: str) -> int:
    """이 에이전트 세션에서 harvested_case_pk가 채워진(수확된) 피드백 수."""
    async with SessionLocal() as s:
        return (
            await s.execute(
                select(func.count())
                .select_from(MessageFeedback)
                .join(Session, Session.id == MessageFeedback.session_pk)
                .where(Session.agent_pk == agent_pk, MessageFeedback.harvested_case_pk.isnot(None))
            )
        ).scalar_one()


async def main() -> None:
    _provision(create=True)
    try:
        async with SessionLocal() as s:
            owner_id = await _uid(s, OWNER_EMAIL)
        ids = await _seed(owner_id)
        a1, a2 = ids["a1"], ids["a2"]

        owner = httpx.AsyncClient(base_url=BASE, timeout=15)
        other = httpx.AsyncClient(base_url=BASE, timeout=15)
        superc = httpx.AsyncClient(base_url=BASE, timeout=15)
        try:
            check(await _login(owner, OWNER_EMAIL), "SETUP: owner 로그인")
            check(await _login(other, OTHER_EMAIL), "SETUP: other(비소유) 로그인")
            check(await _login(superc, SUPER_EMAIL), "SETUP: super 로그인")

            # ---- HC1 소유자 수확수 = 미수확 피드백 2건(agent1), 아직 문제집 없음 ----
            r = await owner.get("/eval/harvest-count", params={"agent_id": a1})
            j = r.json()
            check(
                r.status_code == 200 and j["available"] == 2 and j["dataset_id"] is None,
                f"HC1: 소유자 수확수=2·문제집없음 — got {r.status_code}/{j}",
            )

            # ---- O1 비소유 멤버 수확수 조회 → 404(은폐) ----
            r = await other.get("/eval/harvest-count", params={"agent_id": a1})
            check(r.status_code == 404, f"O1: 비소유 수확수 → 404(은폐) — got {r.status_code}")

            # ---- O2 비소유 멤버 수확 → 404 + 실제 문제집 미생성 ----
            r = await other.post("/eval/datasets/harvest", json={"agent_id": a1})
            check(r.status_code == 404, f"O2: 비소유 수확 → 404 — got {r.status_code}")
            check(await _dataset_count_for(a1) == 0, "O2: 비소유 수확 문제집 실제 미생성")

            # ---- F4(codex) 미존재 에이전트 → 404(admin도 500 아님) ----
            RAND = "11111111-1111-1111-1111-111111111111"
            r = await superc.get("/eval/harvest-count", params={"agent_id": RAND})
            check(
                r.status_code == 404,
                f"F4: admin 미존재 에이전트 수확수 → 404 — got {r.status_code}",
            )
            r = await superc.post("/eval/datasets/harvest", json={"agent_id": RAND})
            check(
                r.status_code == 404,
                f"F4b: admin 미존재 에이전트 수확 → 404(500 아님) — got {r.status_code}",
            )

            # ---- H1 소유자 수확 → 202 + 수확 문제집(source_agent_pk) ----
            r = await owner.post("/eval/datasets/harvest", json={"agent_id": a1})
            check(
                r.status_code == 202 and r.json()["kind"] == "agent",
                f"H1: 소유자 수확 → 202 agent 문제집 — got {r.status_code}/{r.text[:80]}",
            )
            ds_id = r.json()["id"]
            done = await _poll_done(owner, ds_id)

            # ---- H2 케이스 2건 생성(agent1의 👍·👎), agent2(C)는 격리 ----
            check(
                done.get("case_count") == 2,
                f"H2: 수확 케이스=2건(agent1만) — got {done.get('case_count')}",
            )

            async with SessionLocal() as s:
                cases = (
                    (
                        await s.execute(
                            select(EvalCase)
                            .where(EvalCase.dataset_id == ds_id)
                            .order_by(EvalCase.order_idx)
                        )
                    )
                    .scalars()
                    .all()
                )
            inputs = {c.input for c in cases}
            check(
                inputs == {"질문A는 무엇인가?", "질문B는 무엇인가?"},
                f"H2b: 케이스 질문=직전 user 메시지(A·B), C(agent2) 격리 — got {inputs}",
            )
            check(
                all(c.asserts and c.asserts[0]["type"] == "llm_judge" for c in cases),
                "H2c: 각 케이스 assert=llm_judge(폴백 기준)",
            )
            check(
                any("싫어요" in c.name for c in cases) and any("좋아요" in c.name for c in cases),
                f"H2d: name에 평점 반영(좋아요/싫어요) — got {[c.name for c in cases]}",
            )

            # ---- F1(codex) 수확 문제집=세션 파생 콘텐츠 → 소유자/admin만 읽음(비소유 404) ----
            r = await other.get(f"/eval/datasets/{ds_id}")
            check(
                r.status_code == 404,
                f"F1: 비소유 수확 문제집 GET → 404(스코프 상속) — got {r.status_code}",
            )
            r = await other.get(f"/eval/datasets/{ds_id}/cases")
            check(r.status_code == 404, f"F1b: 비소유 수확 케이스 GET → 404 — got {r.status_code}")
            lst = (
                await other.get("/eval/datasets", params={"q": "피드백 수확", "limit": 50})
            ).json()
            check(
                all(x["id"] != ds_id for x in lst["items"]), "F1c: 비소유 목록에 수확 문제집 미노출"
            )
            r = await owner.get(f"/eval/datasets/{ds_id}/cases")
            check(
                r.status_code == 200,
                f"F1d: 소유자 수확 케이스 GET → 200(자가-잠금 아님) — got {r.status_code}",
            )

            # ---- H3 harvested_case_pk 스탬프(agent1 피드백 2건 수확됨) ----
            check(
                await _stamped_count(a1) == 2,
                f"H3: agent1 피드백 2건 harvested 스탬프 — got {await _stamped_count(a1)}",
            )
            check(await _stamped_count(a2) == 0, "H3b: agent2 피드백 미수확(격리 유지)")

            # ---- H4 재수확 → 미수확 0 → 0건 추가(중복 방지), 같은 문제집 재사용 ----
            r = await owner.get("/eval/harvest-count", params={"agent_id": a1})
            j = r.json()
            check(
                j["available"] == 0 and j["dataset_id"] == ds_id,
                f"H4: 재수확수=0·기존 문제집 링크 — got {j}",
            )
            r = await owner.post("/eval/datasets/harvest", json={"agent_id": a1})
            check(
                r.status_code == 202 and r.json()["id"] == ds_id,
                "H4b: 재수확=같은 문제집(idempotent)",
            )
            done2 = await _poll_done(owner, ds_id)
            check(
                done2.get("case_count") == 2,
                f"H4c: 재수확 후에도 2건(중복 미추가) — got {done2.get('case_count')}",
            )
            check(await _dataset_count_for(a1) == 1, "H4d: 수확 문제집 1개만(2번째 미생성)")

            # ---- O3 super(admin)는 임의 에이전트 수확수 조회 가능 ----
            r = await superc.get("/eval/harvest-count", params={"agent_id": a2})
            check(
                r.status_code == 200 and r.json()["available"] == 1,
                f"O3: admin agent2 수확수=1 — got {r.status_code}/{r.json()}",
            )
        finally:
            await owner.aclose()
            await other.aclose()
            await superc.aclose()
    finally:
        await _cleanup()
        _provision(create=False)

    print()
    if _fails:
        print(f"❌ {len(_fails)} FAIL")
        for f in _fails:
            print("   -", f)
        sys.exit(1)
    print(
        "✅ 스펙 209 Phase 2 수확 — 소유권 404·수확→케이스·harvested 스탬프·크로스에이전트 격리·idempotent 전부 통과"
    )


asyncio.run(main())

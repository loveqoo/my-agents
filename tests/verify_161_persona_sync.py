"""verify_161 — 프롬프트 수정 반영: 스냅샷 유지 + 명시적 동기화(스펙 161, 370 재계약).

스펙 370에서 promptStale 키·POST /agents/{id}/prompt/refresh는 은퇴(채택 adopt로 일반화·pins가
버전을 못박음). 생존 표면: 스냅샷 격리(systemPrompt) + GET /prompts/{id}/agents(stale·canManage)
+ POST /prompts/{id}/apply(applied/skipped — can_manage 게이트).

  H1 생성 직후 systemPrompt=원본·usage stale=false.
  H2 프롬프트 수정 → 스냅샷은 옛 본문(자동 전파 안 함=격리)·usage stale=true.
  H3 apply(소유자) → applied·스냅샷 갱신·stale=false.
  H4 타 member apply → skipped(무단 변경 금지)·스냅샷 불변. bob은 usage서 타인 private 못 봄.
  H5 admin usage 전부 봄·canManage=true.
  H6 소유자 apply로 최신 반영.
  H7 literal 프롬프트 에이전트는 usage 미포함.
실행: uv run --project packages/api python tests/_throwaway_server.py tests/verify_161_persona_sync.py
"""

import asyncio
import uuid

import httpx

from api.auth import current_principal
from api.main import app

_fails: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


class Stub:
    def __init__(self, is_superuser=False):
        self.id = uuid.uuid4()
        self.is_superuser = is_superuser
        self.is_active = True
        self.is_verified = True
        self.email = f"u-{self.id.hex[:6]}@x"


def _as(principal):
    app.dependency_overrides[current_principal] = lambda: principal


async def main() -> None:
    from api import authz

    await authz.init_authz()

    alice, bob, admin = Stub(), Stub(), Stub(is_superuser=True)
    t = httpx.ASGITransport(app=app)
    pname = f"prompt-{uuid.uuid4().hex[:8]}"
    pid = None
    made_agents: list[str] = []
    try:
        async with httpx.AsyncClient(transport=t, base_url="http://t", timeout=60) as c:
            # admin이 프롬프트 생성(body="old").
            _as(admin)
            r = await c.post("/prompts", json={"name": pname, "body": "old body"})
            check(r.status_code == 201, f"setup 프롬프트 생성 201 (got {r.status_code})")
            pid = r.json()["id"]

            # alice가 그 프롬프트로 에이전트 생성.
            _as(alice)
            r = await c.post(
                "/agents",
                json={
                    "name": f"ag-{uuid.uuid4().hex[:6]}",
                    "config": {"model": "mock-llm", "prompt": pname, "historyDepth": 6},
                },
            )
            check(r.status_code == 201, f"setup 에이전트 생성 201 (got {r.status_code})")
            aid = r.json()["id"]
            made_agents.append(aid)

            # H1 생성 직후: 스냅샷=원본, usage stale=false. (promptStale 키·refresh는 스펙 370서 은퇴)
            r = await c.get(f"/agents/{aid}")
            j = r.json()
            check("promptStale" not in j, "H1 promptStale 키 은퇴(스펙 370 — adopt/pins로 대체)")
            check(j["systemPrompt"] == "old body", f"H1 스냅샷=원본 (got {j['systemPrompt']!r})")
            u = next(
                (x for x in (await c.get(f"/prompts/{pid}/agents")).json() if x["id"] == aid), None
            )
            check(u is not None and u["stale"] is False, "H1 usage stale=false")

            # H2 프롬프트 수정(body="new") → 자동 전파 안 함(스냅샷 격리), usage가 오래됨을 가시화.
            _as(admin)
            r = await c.put(f"/prompts/{pid}", json={"name": pname, "body": "new body"})
            check(r.status_code == 200, f"H2 프롬프트 수정 200 (got {r.status_code})")
            _as(alice)
            j = (await c.get(f"/agents/{aid}")).json()
            check(
                j["systemPrompt"] == "old body", "H2 스냅샷은 여전히 옛 본문(자동 전파 안 함=격리)"
            )
            u = next(
                (x for x in (await c.get(f"/prompts/{pid}/agents")).json() if x["id"] == aid), None
            )
            check(u is not None and u["stale"] is True, "H2 usage stale=true(가시화)")

            # H3 apply(소유자) → 채택 스크래치 생성(스펙 370: 서빙 불변 — 오픈해야 반영).
            r = await c.post(f"/prompts/{pid}/apply", json={"agentIds": [aid]})
            check(
                r.status_code == 200 and r.json()["applied"] == [aid],
                f"H3 소유자 apply → applied (got {r.json()})",
            )
            j = (await c.get(f"/agents/{aid}")).json()
            check(
                j["systemPrompt"] == "old body",
                "H3a apply 직후 서빙 불변(채택=스크래치, 오픈 전 반영 안 됨 — 스펙 370)",
            )
            scr = next(
                (v["version"] for v in j.get("versions", []) if not v.get("everOpened")), None
            )
            check(scr is not None, f"H3b 채택 스크래치 존재 (got {scr})")
            r = await c.post(f"/agents/{aid}/activate", json={"version": scr})
            check(r.status_code == 200, f"H3c 스크래치 오픈 200 (got {r.status_code})")
            j = (await c.get(f"/agents/{aid}")).json()
            check(j["systemPrompt"] == "new body", "H3d 오픈 후 스냅샷 갱신=new body")

            # H4 준비: 다시 stale로.
            _as(admin)
            await c.put(f"/prompts/{pid}", json={"name": pname, "body": "newer body"})

            # H5 usage: alice가 조회 → 사용 에이전트+stale+canManage.
            _as(alice)
            r = await c.get(f"/prompts/{pid}/agents")
            usage = r.json()
            mine = next((u for u in usage if u["id"] == aid), None)
            check(mine is not None, "H5 usage에 내 에이전트 포함")
            check(mine and mine["stale"] is True, "H5 stale=true(newer body 반영 전)")
            check(mine and mine["canManage"] is True, "H5 alice canManage=true")
            # 가시성(codex 161 High): bob은 alice private 에이전트를 usage에서 못 본다(식별자·stale 누출 금지).
            _as(bob)
            ub = next(
                (u for u in (await c.get(f"/prompts/{pid}/agents")).json() if u["id"] == aid), None
            )
            check(ub is None, "H5 bob은 타인 private 에이전트를 usage에서 못 봄(누출 차단)")
            # 특권은 전부 봄.
            _as(admin)
            ua = next(
                (u for u in (await c.get(f"/prompts/{pid}/agents")).json() if u["id"] == aid), None
            )
            check(ua is not None and ua["canManage"] is True, "H5 admin은 전부 봄·canManage=true")

            # H6 apply: bob(타인) → skipped, alice(소유자) → applied.
            _as(bob)
            rb = await c.post(f"/prompts/{pid}/apply", json={"agentIds": [aid]})
            check(
                rb.status_code == 200
                and rb.json()["applied"] == []
                and aid in rb.json()["skipped"],
                f"H6 bob apply → skipped(무단 변경 금지) (got {rb.json()})",
            )
            _as(alice)  # 검증 GET은 소유자로(alice private 에이전트라 bob GET은 404)
            j = (await c.get(f"/agents/{aid}")).json()
            check(j["systemPrompt"] == "new body", "H6 bob apply 후 스냅샷 불변(여전히 new body)")
            ra = await c.post(f"/prompts/{pid}/apply", json={"agentIds": [aid]})
            check(
                ra.status_code == 200 and ra.json()["applied"] == [aid],
                f"H6 alice apply → applied (got {ra.json()})",
            )
            j = (await c.get(f"/agents/{aid}")).json()
            scr2 = next(
                (v["version"] for v in j.get("versions", []) if not v.get("everOpened")), None
            )
            r = await c.post(f"/agents/{aid}/activate", json={"version": scr2})
            j = (await c.get(f"/agents/{aid}")).json()
            check(
                j["systemPrompt"] == "newer body",
                f"H6 alice apply+오픈 후 스냅샷=newer body (got {j['systemPrompt']!r})",
            )
            u = next(
                (x for x in (await c.get(f"/prompts/{pid}/agents")).json() if x["id"] == aid), None
            )
            check(u is not None and u["stale"] is False, "H6b 반영 후 usage stale=false")

            # H7 미참조 에이전트 stale=false(다른 프롬프트 literal).
            r = await c.post(
                "/agents",
                json={
                    "name": f"ag2-{uuid.uuid4().hex[:6]}",
                    "config": {
                        "model": "mock-llm",
                        "prompt": "literal-없는이름",
                        "historyDepth": 6,
                    },
                },
            )
            aid2 = r.json()["id"]
            made_agents.append(aid2)
            usage2 = (await c.get(f"/prompts/{pid}/agents")).json()
            check(
                all(x["id"] != aid2 for x in usage2),
                "H7 literal 프롬프트 에이전트는 usage 미포함(참조 아님)",
            )
    finally:
        app.dependency_overrides.clear()
        # cleanup
        from api.db import SessionLocal
        from api.models import Agent, Prompt
        from sqlalchemy import select

        async with SessionLocal() as db:
            for aid in made_agents:
                a = await db.get(Agent, uuid.UUID(aid))
                if a:
                    await db.delete(a)
            if pid:
                p = await db.get(Prompt, uuid.UUID(pid))
                if p:
                    await db.delete(p)
            await db.commit()

    print(f"\n{'PASS' if not _fails else 'FAIL'} — {len(_fails)} failed")
    if _fails:
        raise SystemExit(1)


asyncio.run(main())

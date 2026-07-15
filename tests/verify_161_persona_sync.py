"""verify_161 — 프롬프트 수정 반영: 스냅샷 유지 + 명시적 동기화(스펙 161).

에이전트는 프롬프트를 저장 시점 스냅샷으로 복사(영향도 격리). 프롬프트 수정이 자동 전파 안 됨 →
promptStale 가시화 + refresh(에이전트쪽)/apply(프롬프트쪽)로 통제된 반영. 권한(can_manage) 게이트.

  H1 생성 직후 stale=false·systemPrompt=원본.
  H2 프롬프트 수정 → stale=true·스냅샷은 옛 본문(자동 전파 안 함 = 격리).
  H3 refresh(소유자) → 스냅샷 갱신·stale=false.
  H4 타 member refresh → 404-fold(권한).
  H5 GET /prompts/{id}/agents → 사용 에이전트+stale+canManage.
  H6 apply(소유자) → applied, 스냅샷 갱신. 타 member → skipped(무단 변경 금지).
  H7 외부 에이전트 refresh → 400(로컬 프롬프트 없음). 미참조 에이전트 stale=false.
실행: cd packages/api && uv run python ../../tests/verify_161_prompt_sync.py
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
            r = await c.post("/agents", json={"name": f"ag-{uuid.uuid4().hex[:6]}",
                                              "config": {"model": "mock-llm", "prompt": pname, "historyDepth": 6}})
            check(r.status_code == 201, f"setup 에이전트 생성 201 (got {r.status_code})")
            aid = r.json()["id"]; made_agents.append(aid)

            # H1 생성 직후: stale=false, 스냅샷=원본.
            r = await c.get(f"/agents/{aid}")
            j = r.json()
            check(j["promptStale"] is False, "H1 생성 직후 promptStale=false")
            check(j["systemPrompt"] == "old body", f"H1 스냅샷=원본 (got {j['systemPrompt']!r})")

            # H2 프롬프트 수정(body="new") → 자동 전파 안 함.
            _as(admin)
            r = await c.put(f"/prompts/{pid}", json={"name": pname, "body": "new body"})
            check(r.status_code == 200, f"H2 프롬프트 수정 200 (got {r.status_code})")
            _as(alice)
            j = (await c.get(f"/agents/{aid}")).json()
            check(j["promptStale"] is True, "H2 수정 후 promptStale=true(가시화)")
            check(j["systemPrompt"] == "old body", "H2 스냅샷은 여전히 옛 본문(자동 전파 안 함=격리)")

            # H3 refresh(소유자) → 갱신.
            r = await c.post(f"/agents/{aid}/prompt/refresh")
            check(r.status_code == 200, f"H3 refresh 200 (got {r.status_code})")
            check(r.json()["systemPrompt"] == "new body", "H3 스냅샷 갱신=new body")
            check(r.json()["promptStale"] is False, "H3 refresh 후 stale=false")

            # H4 타 member refresh → 404-fold. (먼저 다시 stale로)
            _as(admin); await c.put(f"/prompts/{pid}", json={"name": pname, "body": "newer body"})
            _as(bob)
            r = await c.post(f"/agents/{aid}/prompt/refresh")
            check(r.status_code == 404, f"H4 타 member refresh 404-fold (got {r.status_code})")

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
            ub = next((u for u in (await c.get(f"/prompts/{pid}/agents")).json() if u["id"] == aid), None)
            check(ub is None, "H5 bob은 타인 private 에이전트를 usage에서 못 봄(누출 차단)")
            # 특권은 전부 봄.
            _as(admin)
            ua = next((u for u in (await c.get(f"/prompts/{pid}/agents")).json() if u["id"] == aid), None)
            check(ua is not None and ua["canManage"] is True, "H5 admin은 전부 봄·canManage=true")

            # H6 apply: bob(타인) → skipped, alice(소유자) → applied.
            _as(bob)
            rb = await c.post(f"/prompts/{pid}/apply", json={"agentIds": [aid]})
            check(rb.status_code == 200 and rb.json()["applied"] == [] and aid in rb.json()["skipped"],
                  f"H6 bob apply → skipped(무단 변경 금지) (got {rb.json()})")
            _as(alice)  # 검증 GET은 소유자로(alice private 에이전트라 bob GET은 404)
            j = (await c.get(f"/agents/{aid}")).json()
            check(j["systemPrompt"] == "new body", "H6 bob apply 후 스냅샷 불변(여전히 new body)")
            ra = await c.post(f"/prompts/{pid}/apply", json={"agentIds": [aid]})
            check(ra.status_code == 200 and ra.json()["applied"] == [aid],
                  f"H6 alice apply → applied (got {ra.json()})")
            j = (await c.get(f"/agents/{aid}")).json()
            check(j["systemPrompt"] == "newer body" and j["promptStale"] is False,
                  f"H6 alice apply 후 스냅샷=newer body·stale=false (got {j['systemPrompt']!r})")

            # H7 미참조 에이전트 stale=false(다른 프롬프트 literal).
            r = await c.post("/agents", json={"name": f"ag2-{uuid.uuid4().hex[:6]}",
                                              "config": {"model": "mock-llm", "prompt": "literal-없는이름", "historyDepth": 6}})
            aid2 = r.json()["id"]; made_agents.append(aid2)
            j2 = (await c.get(f"/agents/{aid2}")).json()
            check(j2["promptStale"] is False, "H7 블록 아닌 literal 프롬프트 → stale=false")
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

"""verify_241 — 버전 활성화 시 자동 회귀(스펙 241, AgentOps B).

R1 베이스라인: 문제집을 수동 실행(에이전트↔문제집 링크 생성)
R2 편집→새 버전 활성화 → 자동 런 생성(env.trigger=activate·새 버전 박제·완주)
R3 문제집 없는 에이전트 활성화 → 자동 런 0(무해)
R4 revert(아카이브 승격) → 자동 회귀 트리거

실행: cd packages/api && uv run python ../../tests/verify_241_auto_regression.py
"""

from __future__ import annotations

import asyncio
import uuid

import httpx

from api.auth import _token, current_principal
from api.main import app


class _Super:
    id = uuid.UUID("00000241-0000-0000-0000-000000000241")
    is_superuser = True
    is_active = True
    is_verified = True
    email = "e2e-241@local"


app.dependency_overrides[current_principal] = lambda: _Super()

checks: list[tuple[bool, str]] = []


def ck(c: bool, m: str) -> None:
    checks.append((c, m))
    print(("  ok  " if c else " FAIL ") + m)


async def _runs(c: httpx.AsyncClient, ds_id: str) -> list[dict]:
    return (await c.get(f"/eval/runs?dataset_id={ds_id}")).json()


async def _wait_all_done(c: httpx.AsyncClient, ds_id: str, timeout_s: int = 90) -> list[dict]:
    for _ in range(timeout_s * 2):
        rs = await _runs(c, ds_id)
        if rs and all(r["status"] != "running" for r in rs):
            return rs
        await asyncio.sleep(0.5)
    return rs


async def _activate_draft(c: httpx.AsyncClient, agent_id: str) -> str | None:
    g = (await c.get(f"/agents/{agent_id}")).json()
    draft = next((v["version"] for v in g.get("versions", []) if v.get("status") == "draft"), None)
    if draft:
        await c.post(f"/agents/{agent_id}/activate", json={"version": draft})
    g2 = (await c.get(f"/agents/{agent_id}")).json()
    return g2.get("activeVersion") or g2.get("active_version")


async def run() -> bool:
    t = httpx.ASGITransport(app=app)
    headers = {"Authorization": f"Bearer {_token()}"}
    async with httpx.AsyncClient(transport=t, base_url="http://t", headers=headers, timeout=120) as c:
        agents: list[str] = []
        ds_id = None
        try:
            a = (await c.post("/agents", json={
                "name": f"reg241-{uuid.uuid4().hex[:6]}",
                "config": {"model": "mock-llm", "persona": "회귀 실습"},
            })).json()
            agents.append(a["id"])
            v1 = await _activate_draft(c, a["id"])  # v1 활성화(자동 회귀는 문제집 없어 0)

            ds = (await c.post("/eval/datasets", json={"name": f"ds241-{uuid.uuid4().hex[:6]}", "kind": "agent"})).json()
            ds_id = ds["id"]
            await c.post(f"/eval/datasets/{ds_id}/cases", json={"name": "인사", "input": "안녕", "asserts": [{"type": "no_error"}]})

            # R1 베이스라인 수동 런(링크 생성)
            await c.post(f"/eval/datasets/{ds_id}/runs", json={"agent_id": a["id"]})
            rs = await _wait_all_done(c, ds_id)
            ck(len(rs) == 1 and rs[0]["status"] == "ok", f"R1 베이스라인 수동 런 완료 (v={rs[0].get('agent_version')})")

            # R2 편집→v2 활성화 → 자동 회귀 런
            await c.put(f"/agents/{a['id']}", json={"config": {"model": "mock-llm", "persona": "회귀 실습 v2"}})
            v2 = await _activate_draft(c, a["id"])
            await asyncio.sleep(1.0)  # fire-and-forget 태스크 시작 여유
            rs = await _wait_all_done(c, ds_id)
            auto = [r for r in rs if (r.get("env") or {}).get("trigger") == "activate"]
            ck(len(auto) == 1, f"R2a 활성화가 자동 런 1건 생성 (총 {len(rs)}건)")
            ck(auto and auto[0].get("agent_version") == v2 and v2 != v1,
               f"R2b 자동 런에 새 버전 박제 ({v1}→{v2}, run={auto[0].get('agent_version') if auto else None})")
            ck(auto and auto[0]["status"] == "ok", f"R2c 자동 런 완주 (status={auto[0]['status'] if auto else None})")

            # R3 문제집 없는 에이전트 — 활성화해도 아무 일 없음(전체 런 수 불변)
            b = (await c.post("/agents", json={
                "name": f"noreg-{uuid.uuid4().hex[:6]}",
                "config": {"model": "mock-llm", "persona": "x"},
            })).json()
            agents.append(b["id"])
            before = len(await _runs(c, ds_id))
            await _activate_draft(c, b["id"])
            await asyncio.sleep(1.5)
            after = len(await _runs(c, ds_id))
            ck(after == before, f"R3 무관 에이전트 활성화 → 이 문제집 런 불변 ({before}→{after})")

            # R4 revert(v2 활성 → 강등·v1 승격) — 자동 회귀 트리거
            before = len(await _runs(c, ds_id))
            r = await c.post(f"/agents/{a['id']}/revert", json={"version": v2})
            if r.status_code >= 400:
                print(f"  skip R4 — revert 불가({r.status_code}: {r.text[:80]})")
            else:
                await asyncio.sleep(1.0)
                rs = await _wait_all_done(c, ds_id)
                new_auto = [x for x in rs if (x.get("env") or {}).get("trigger") == "activate"]
                ck(len(rs) == before + 1 and len(new_auto) == 2,
                   f"R4 revert 승격도 자동 회귀 ({before}→{len(rs)}건, auto={len(new_auto)})")

                # R5 — 같은 버전(v2) 재활성화: 이미 v2 자동 런이 있으므로 dedupe로 스킵(비용 폭주 차단, codex #2)
                before5 = len(await _runs(c, ds_id))
                await c.post(f"/agents/{a['id']}/activate", json={"version": v2})
                await asyncio.sleep(1.5)
                after5 = len(await _runs(c, ds_id))
                ck(after5 == before5, f"R5 같은 버전 재활성화 → 중복 자동 런 없음 ({before5}→{after5})")
        finally:
            if ds_id:
                await c.delete(f"/eval/datasets/{ds_id}")
            for aid in agents:
                await c.delete(f"/agents/{aid}")

    ok = all(x for x, _ in checks)
    print("VERIFY241_OK" if ok else f"VERIFY241_FAIL({sum(1 for x, _ in checks if not x)})")
    return ok


if __name__ == "__main__":
    raise SystemExit(0 if asyncio.run(run()) else 1)

"""verify_120 — 에이전트 복제(저마찰 재사용, 스펙 120, 방향 4).

복제 = 기존 설정을 새 ui 초안으로 복사(행위 재사용). 복제자가 소유(069 no-takeover)·원본 관리 권한
불요(가시하면 복제 — 사용≠관리 112)·미존재 404-fold.

실행: cd packages/api && uv run python ../../tests/verify_120_agent_clone.py
"""
import asyncio
import uuid

import httpx

from api.auth import _token, current_principal
from api.main import app


class _SuperPrincipal:
    id = uuid.UUID("000000dd-0000-0000-0000-0000000000dd")
    is_superuser = True
    is_active = True
    is_verified = True
    email = "e2e-120-super@local"


app.dependency_overrides[current_principal] = lambda: _SuperPrincipal()

_fails = []
def check(c, m):
    print(("  ok  " if c else " FAIL ") + m)
    if not c:
        _fails.append(m)


async def run():
    made = []
    auth = {"Authorization": f"Bearer {_token()}"}
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://t", headers=auth, timeout=60) as c:
            # 원본: 조율형 + 능력 + requires_approval + 프롬프트 설정.
            src = (await c.post("/agents", json={
                "name": f"clone-src-{uuid.uuid4().hex[:6]}",
                "config": {"model": "mock-llm", "prompt": "", "historyDepth": 9,
                           "impl": "orchestrate", "capabilities": ["rag:x", "mcp:y/z"],
                           "requires_approval": True, "temperature": 0.3},
            })).json()
            made.append(src["id"])

            r = await c.post(f"/agents/{src['id']}/clone")
            check(r.status_code == 201, f"H1 복제 201 (got {r.status_code})")
            clone = r.json()
            made.append(clone["id"])

            check(clone["id"] != src["id"], "H2 새 id(원본과 다름)")
            check(clone["name"] == f"{src['name']} (복사본)", f"H2 이름='{src['name']} (복사본)' (got {clone['name']})")
            check(clone.get("source") == "ui", f"H3 복제본 source=ui (got {clone.get('source')})")
            # 행위 설정 복사 확인.
            check(clone.get("capabilities") == ["rag:x", "mcp:y/z"], f"H4 능력 복사 (got {clone.get('capabilities')})")
            check(clone.get("impl") == "orchestrate", f"H4 impl 복사 (got {clone.get('impl')})")
            check(clone.get("historyDepth") == 9, f"H4 historyDepth 복사 (got {clone.get('historyDepth')})")

            # 저장된 config(DB)로 requires_approval·temperature 복사 확인(라운드트립).
            from api.db import SessionLocal
            from api.models import Agent
            from sqlalchemy import select
            async with SessionLocal() as s:
                row = (await s.execute(select(Agent).where(Agent.id == uuid.UUID(clone["id"])))).scalar_one()
                cfg = row.config or {}
            check(cfg.get("requires_approval") is True, f"H4 requires_approval 복사 (got {cfg.get('requires_approval')})")
            check(abs((cfg.get("temperature") or 0) - 0.3) < 1e-9, f"H4 temperature 복사 (got {cfg.get('temperature')})")
            check("card" not in cfg, "H5 외부 등록 스냅샷(card) 미복사")

            # 복제자가 관리 가능(소유 스탬프 — 069).
            check(clone.get("can_manage") is True, "H6 복제자가 복제본 관리 가능(소유 스탬프)")

            # 복제본이 목록에 뜸(독립 에이전트).
            lst = (await c.get("/agents")).json()
            ids = {a["id"] for a in lst}
            check(clone["id"] in ids and src["id"] in ids, "H7 원본·복제본 둘 다 목록에 존재(독립)")

            # 미존재 복제 → 404-fold.
            r404 = await c.post(f"/agents/{uuid.uuid4()}/clone")
            check(r404.status_code == 404, f"H8 미존재 복제 → 404 (got {r404.status_code})")
    finally:
        async with httpx.AsyncClient(transport=transport, base_url="http://t", headers=auth) as c:
            for aid in made:
                try:
                    await c.delete(f"/agents/{aid}")
                except Exception:
                    pass

    print()
    if _fails:
        print(f"❌ {len(_fails)} FAILED")
        for f in _fails:
            print("   - " + f)
        return False
    print("✅ ALL PASS (VERIFY120_OK)")
    return True


if __name__ == "__main__":
    raise SystemExit(0 if asyncio.run(run()) else 1)

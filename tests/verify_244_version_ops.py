"""verify_244 — 버전 운영 집계(스펙 244, AgentOps D).

O1 v1 채팅 턴에 👍 → ops.versions.v1.up=1 (trace.agentVersion 귀속 인과)
O2 v1 평가 실행 → ops.versions.v1.evalRuns/lastScore 집계
O3 v2 활성화(자동 회귀) → ops.versions.v2.autoRuns≥1 — v1 지표는 v1에 그대로(버전 분리)
O4 다른 에이전트 지표 혼입 없음(격리)
O5 비가시(멤버, 타인 소유) → 404

실행: cd packages/api && uv run python ../../tests/verify_244_version_ops.py
"""

from __future__ import annotations

import asyncio
import json
import uuid

import httpx

from api.auth import _token, current_principal
from api.main import app


class _Super:
    id = uuid.UUID("00000244-0000-0000-0000-000000000244")
    is_superuser = True
    is_active = True
    is_verified = True
    email = "e2e-244@local"


app.dependency_overrides[current_principal] = lambda: _Super()

checks: list[tuple[bool, str]] = []


def ck(c: bool, m: str) -> None:
    checks.append((c, m))
    print(("  ok  " if c else " FAIL ") + m)


def _frames(sse: str) -> list[dict]:
    out = []
    for line in sse.splitlines():
        if line.startswith("data: ") and line != "data: [DONE]":
            try:
                out.append(json.loads(line[6:]))
            except Exception:
                pass
    return out


async def _activate_draft(c, aid):
    g = (await c.get(f"/agents/{aid}")).json()
    d = next((v["version"] for v in g.get("versions", []) if v.get("status") == "draft"), None)
    if d:
        await c.post(f"/agents/{aid}/activate", json={"version": d})
    g2 = (await c.get(f"/agents/{aid}")).json()
    return g2.get("activeVersion") or g2.get("active_version")


async def run() -> bool:
    from api.authz import init_authz
    await init_authz()
    from api import checkpointer as _ckpt
    await _ckpt.init_checkpointer()

    t = httpx.ASGITransport(app=app)
    headers = {"Authorization": f"Bearer {_token()}"}
    async with httpx.AsyncClient(transport=t, base_url="http://t", headers=headers, timeout=120) as c:
        agents, ds_id = [], None
        try:
            a = (await c.post("/agents", json={
                "name": f"ops244-{uuid.uuid4().hex[:6]}",
                "config": {"model": "mock-llm", "prompt": "운영 집계"},
            })).json()
            agents.append(a["id"])
            v1 = await _activate_draft(c, a["id"])

            # O1 — v1 턴 + 피드백 👍
            r = await c.post(f"/agents/{a['id']}/chat", json={"messages": [{"role": "user", "content": "안녕"}]})
            frames = _frames(r.text)
            sid = next((f["session"] for f in frames if "session" in f), None)
            mid = None
            for line in r.text.splitlines():
                if line.startswith("event: message_id"):
                    continue
            # message_id 프레임(event: message_id 다음 data)
            lines = r.text.splitlines()
            for i, line in enumerate(lines):
                if line == "event: message_id" and i + 1 < len(lines) and lines[i + 1].startswith("data: "):
                    mid = json.loads(lines[i + 1][6:]).get("id") or json.loads(lines[i + 1][6:]).get("messageId")
            if mid is None:
                # 폴백: 세션 메시지 조회로 assistant id 획득
                msgs = (await c.get(f"/sessions/{sid}/messages")).json()
                items = msgs if isinstance(msgs, list) else msgs.get("items", [])
                mid = next((m["id"] for m in reversed(items) if m.get("role") == "assistant"), None)
            fbr = await c.put(f"/sessions/{sid}/messages/{mid}/feedback", json={"rating": "up", "reason": ""})
            ck(fbr.status_code < 300, f"O1a 피드백 등록 (status={fbr.status_code})")
            ops = (await c.get(f"/agents/{a['id']}/ops")).json()
            v1ops = (ops.get("versions") or {}).get(v1) or {}
            ck(v1ops.get("up") == 1, f"O1b v1 피드백 귀속 (up={v1ops.get('up')})")

            # O2 — v1 평가
            ds = (await c.post("/eval/datasets", json={"name": f"ds244-{uuid.uuid4().hex[:6]}", "kind": "agent"})).json()
            ds_id = ds["id"]
            await c.post(f"/eval/datasets/{ds_id}/cases", json={"name": "q", "input": "안녕", "asserts": [{"type": "no_error"}]})
            run_ = (await c.post(f"/eval/datasets/{ds_id}/runs", json={"agent_id": a["id"]})).json()
            for _ in range(60):
                rr = (await c.get(f"/eval/runs/{run_['id']}")).json()
                if rr.get("status") != "running":
                    break
                await asyncio.sleep(0.5)
            ops = (await c.get(f"/agents/{a['id']}/ops")).json()
            v1ops = (ops.get("versions") or {}).get(v1) or {}
            ck(v1ops.get("evalRuns") == 1 and v1ops.get("lastScore") == 1.0,
               f"O2 v1 평가 집계 (runs={v1ops.get('evalRuns')} score={v1ops.get('lastScore')})")

            # O3 — v2 활성화 → 자동 회귀가 v2에 집계, v1 지표 불변
            await c.put(f"/agents/{a['id']}", json={"config": {"model": "mock-llm", "prompt": "운영 집계 v2"}})
            v2 = await _activate_draft(c, a["id"])
            await asyncio.sleep(1.0)
            for _ in range(60):
                runs = (await c.get(f"/eval/runs?dataset_id={ds_id}")).json()
                if runs and all(x["status"] != "running" for x in runs):
                    break
                await asyncio.sleep(0.5)
            ops = (await c.get(f"/agents/{a['id']}/ops")).json()
            v2ops = (ops.get("versions") or {}).get(v2) or {}
            v1ops = (ops.get("versions") or {}).get(v1) or {}
            ck(v2ops.get("autoRuns", 0) >= 1 and v2ops.get("evalRuns", 0) >= 1,
               f"O3a v2 자동 회귀 집계 (auto={v2ops.get('autoRuns')} runs={v2ops.get('evalRuns')})")
            ck(v1ops.get("evalRuns") == 1 and v1ops.get("up") == 1,
               f"O3b v1 지표 불변(버전 분리) (runs={v1ops.get('evalRuns')} up={v1ops.get('up')})")

            # O4 — 다른 에이전트 격리
            b = (await c.post("/agents", json={
                "name": f"iso244-{uuid.uuid4().hex[:6]}",
                "config": {"model": "mock-llm", "prompt": "x"},
            })).json()
            agents.append(b["id"])
            ops_b = (await c.get(f"/agents/{b['id']}/ops")).json()
            ck(not ops_b.get("versions") and ops_b.get("unversionedUp") == 0,
               f"O4 타 에이전트 혼입 없음 ({ops_b})")

            # O5 — 비가시 404 (멤버가 타인 소유 에이전트 ops)
            class _Member:
                id = uuid.UUID("00000244-1111-0000-0000-000000000244")
                is_superuser = False
                is_active = True
                is_verified = True
                email = "member-244@local"

            app.dependency_overrides[current_principal] = lambda: _Member()
            try:
                r = await c.get(f"/agents/{a['id']}/ops")
                ck(r.status_code == 404, f"O5 비가시 404-fold (got {r.status_code})")
            finally:
                app.dependency_overrides[current_principal] = lambda: _Super()

            # O6 — 공유(무소유) 에이전트: 멤버가 사용은 가능해도 운영 지표는 403(관리자 전용, codex #2)
            from api.models import Agent as _A
            from api.db import SessionLocal as _SL
            from sqlalchemy import select as _sel
            async with _SL() as db:
                ag = (await db.execute(_sel(_A).where(_A.id == uuid.UUID(a["id"])))).scalar_one()
                ag.owner_id = None
                await db.commit()
            app.dependency_overrides[current_principal] = lambda: _Member()
            try:
                r = await c.get(f"/agents/{a['id']}/ops")
                ck(r.status_code == 403, f"O6 공유 에이전트 멤버 ops 403(관리자 전용) (got {r.status_code})")
            finally:
                app.dependency_overrides[current_principal] = lambda: _Super()
        finally:
            if ds_id:
                await c.delete(f"/eval/datasets/{ds_id}")
            for aid in agents:
                await c.delete(f"/agents/{aid}")

    ok = all(x for x, _ in checks)
    print("VERIFY244_OK" if ok else f"VERIFY244_FAIL({sum(1 for x, _ in checks if not x)})")
    return ok


if __name__ == "__main__":
    raise SystemExit(0 if asyncio.run(run()) else 1)

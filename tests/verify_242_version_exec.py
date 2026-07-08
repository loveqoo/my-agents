"""verify_242 — 버전 지정 실행(내부 서빙)+버전별 평가(스펙 242).

V1 초안(v2, 다른 페르소나) 지정 채팅 → 그 버전 config로 실행(sentMessages system=초안 페르소나)
   + trace.agentVersion=v2·versionPinned
V2 무지정 채팅 → trace.agentVersion=활성(v1)
V3 미존재 버전 → 404
V4 버전 지정 평가(초안 v2에만 도구 배선) → EvalRun.agent_version=v2·env.mcps=초안 기준(인과 증명)
V5 버전 미리보기 + 승인형 도구 → 명시 에러 + Approval 행 0

실행: cd packages/api && uv run python ../../tests/verify_242_version_exec.py
"""

from __future__ import annotations

import asyncio
import json
import uuid

import httpx
from sqlalchemy import func, select, text

from api.auth import _token, current_principal
from api.db import SessionLocal
from api.main import app


class _Super:
    id = uuid.UUID("00000242-0000-0000-0000-000000000242")
    is_superuser = True
    is_active = True
    is_verified = True
    email = "e2e-242@local"


app.dependency_overrides[current_principal] = lambda: _Super()

checks: list[tuple[bool, str]] = []


def ck(c: bool, m: str) -> None:
    checks.append((c, m))
    print(("  ok  " if c else " FAIL ") + m)


def _last_trace(sse: str) -> dict:
    tr = {}
    for line in sse.splitlines():
        if line.startswith("data: ") and '"latencyMs"' in line:
            try:
                tr = json.loads(line[6:])
            except Exception:
                pass
    return tr


async def _activate_draft(c, agent_id):
    g = (await c.get(f"/agents/{agent_id}")).json()
    d = next((v["version"] for v in g.get("versions", []) if v.get("status") == "draft"), None)
    if d:
        await c.post(f"/agents/{agent_id}/activate", json={"version": d})
    g2 = (await c.get(f"/agents/{agent_id}")).json()
    return g2.get("activeVersion") or g2.get("active_version")


async def run() -> bool:
    # 인프로세스라 lifespan 미실행 — 멤버 principal 경로(V6)가 casbin을 타므로 authz 초기화 필요.
    from api.authz import init_authz
    await init_authz()

    t = httpx.ASGITransport(app=app)
    headers = {"Authorization": f"Bearer {_token()}"}
    async with httpx.AsyncClient(transport=t, base_url="http://t", headers=headers, timeout=120) as c:
        aid = None
        ds_id = None
        try:
            a = (await c.post("/agents", json={
                "name": f"vx242-{uuid.uuid4().hex[:6]}",
                "config": {"model": "mock-llm", "persona": "V1-PERSONA-MARK"},
            })).json()
            aid = a["id"]
            v1 = await _activate_draft(c, aid)  # v1 활성

            # 초안 v2: 페르소나 변경 + 도구 배선(활성엔 없음 — V4 인과 증명 축)
            await c.put(f"/agents/{aid}", json={
                "config": {"model": "mock-llm", "persona": "V2-PERSONA-MARK", "mcps": ["local-tools"]},
            })
            g = (await c.get(f"/agents/{aid}")).json()
            v2 = next((v["version"] for v in g.get("versions", []) if v.get("status") == "draft"), None)

            # V1 — 초안 지정 채팅
            r = await c.post(f"/agents/{aid}/chat", json={
                "messages": [{"role": "user", "content": "안녕"}], "version": v2,
            })
            tr = _last_trace(r.text)
            sysmsg = next((m["content"] for m in tr.get("sentMessages") or [] if m.get("role") == "system"), "")
            ck("V2-PERSONA-MARK" in sysmsg, f"V1a 초안 config로 실행(system=초안 페르소나)")
            ck(tr.get("agentVersion") == v2 and tr.get("versionPinned") is True,
               f"V1b trace 버전 기록 (agentVersion={tr.get('agentVersion')} pinned={tr.get('versionPinned')})")

            # V2 — 무지정: 활성 버전 실행·기록
            r = await c.post(f"/agents/{aid}/chat", json={"messages": [{"role": "user", "content": "안녕"}]})
            tr = _last_trace(r.text)
            sysmsg = next((m["content"] for m in tr.get("sentMessages") or [] if m.get("role") == "system"), "")
            ck("V1-PERSONA-MARK" in sysmsg and tr.get("agentVersion") == v1 and not tr.get("versionPinned"),
               f"V2 무지정=활성 실행 (agentVersion={tr.get('agentVersion')})")

            # V3 — 미존재 버전
            r = await c.post(f"/agents/{aid}/chat", json={"messages": [{"role": "user", "content": "x"}], "version": "v99"})
            ck(r.status_code == 404, f"V3 미존재 버전 404 (got {r.status_code})")

            # V4 — 버전 지정 평가: 초안 v2(도구 배선)로 → 버전·env 인과
            ds = (await c.post("/eval/datasets", json={"name": f"ds242-{uuid.uuid4().hex[:6]}", "kind": "agent"})).json()
            ds_id = ds["id"]
            await c.post(f"/eval/datasets/{ds_id}/cases", json={"name": "q", "input": "안녕", "asserts": [{"type": "no_error"}]})
            run_ = (await c.post(f"/eval/datasets/{ds_id}/runs", json={"agent_id": aid, "agent_version": v2})).json()
            for _ in range(60):
                rr = (await c.get(f"/eval/runs/{run_['id']}")).json()
                if rr.get("status") != "running":
                    break
                await asyncio.sleep(0.5)
            env = rr.get("env") or {}
            ck(rr.get("status") == "ok" and rr.get("agent_version") == v2,
               f"V4a 버전 지정 평가 완주+버전 박제 (v={rr.get('agent_version')})")
            ck("local-tools" in (env.get("mcps") or {}),
               f"V4b env=초안 config 기준(활성엔 없는 도구 기록 — 인과) ({list((env.get('mcps') or {}).keys())})")

            # V5 — 미리보기 + 승인형 도구: 명시 에러 + Approval 0
            async with SessionLocal() as db:
                before = int((await db.execute(text("SELECT count(*) FROM approvals"))).scalar_one())
            r = await c.post(f"/agents/{aid}/chat", json={
                "messages": [{"role": "user", "content": "레코드 rec-001 삭제해줘"}], "version": v2,
            })
            async with SessionLocal() as db:
                after = int((await db.execute(text("SELECT count(*) FROM approvals"))).scalar_one())
            ck("승인이 필요한 도구를 사용할 수 없습니다" in r.text and after == before,
               f"V5 미리보기 승인형 도구 → 명시 에러+Approval Δ0 ({before}→{after})")

            # V6 — 비관리자(멤버)의 버전 지정 실행은 403(초안=미공개 작업본, codex #2)
            class _Member:
                id = uuid.UUID("00000242-1111-0000-0000-000000000242")
                is_superuser = False
                is_active = True
                is_verified = True
                email = "member-242@local"

            # 소유 에이전트는 멤버에게 404-fold(사용 게이트가 먼저) — 버전 게이트 자체를 재려면
            # "사용은 되지만 관리는 안 되는" 공유(무소유) 상태로 만들어야 한다(DB 직접 — 시드 시뮬레이션).
            from api.models import Agent as _A
            async with SessionLocal() as db:
                ag = (await db.execute(select(_A).where(_A.id == uuid.UUID(aid)))).scalar_one()
                ag.owner_id = None
                await db.commit()
            app.dependency_overrides[current_principal] = lambda: _Member()
            try:
                r = await c.post(f"/agents/{aid}/chat", json={"messages": [{"role": "user", "content": "안녕"}]})
                ck(r.status_code == 200, f"V6a 공유 에이전트: 멤버 일반 채팅 가능 (got {r.status_code})")
                r = await c.post(f"/agents/{aid}/chat", json={
                    "messages": [{"role": "user", "content": "안녕"}], "version": v2,
                })
                ck(r.status_code == 403, f"V6b 멤버 버전 지정 채팅 403(초안 누출 차단) (got {r.status_code})")
            finally:
                app.dependency_overrides[current_principal] = lambda: _Super()
        finally:
            if ds_id:
                await c.delete(f"/eval/datasets/{ds_id}")
            if aid:
                await c.delete(f"/agents/{aid}")

    ok = all(x for x, _ in checks)
    print("VERIFY242_OK" if ok else f"VERIFY242_FAIL({sum(1 for x, _ in checks if not x)})")
    return ok


if __name__ == "__main__":
    raise SystemExit(0 if asyncio.run(run()) else 1)

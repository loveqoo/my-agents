"""verify_240 — 평가의 버전 귀속+경량 환경 기록(스펙 240, AgentOps A).

V1 평가 실행 → EvalRun.agent_version=실행 시점 활성 버전, env에 모델·컬렉션·도구 기록
V2 새 버전 활성화 후 재실행 → 새 버전이 박제(귀속이 활성 버전을 따라감)
V3 RunOut(API)에 agent_version·env 노출

실행: cd packages/api && uv run python ../../tests/verify_240_eval_version.py
"""

from __future__ import annotations

import asyncio
import uuid

import httpx

from api.auth import _token, current_principal
from api.main import app


class _Super:
    id = uuid.UUID("00000240-0000-0000-0000-000000000240")
    is_superuser = True
    is_active = True
    is_verified = True
    email = "e2e-240@local"


app.dependency_overrides[current_principal] = lambda: _Super()

checks: list[tuple[bool, str]] = []


def ck(c: bool, m: str) -> None:
    checks.append((c, m))
    print(("  ok  " if c else " FAIL ") + m)


async def _wait_run(c: httpx.AsyncClient, run_id: str, timeout_s: int = 60) -> dict:
    for _ in range(timeout_s * 2):
        r = (await c.get(f"/eval/runs/{run_id}")).json()
        if r.get("status") != "running":
            return r
        await asyncio.sleep(0.5)
    return r


async def run() -> bool:
    t = httpx.ASGITransport(app=app)
    headers = {"Authorization": f"Bearer {_token()}"}
    async with httpx.AsyncClient(
        transport=t, base_url="http://t", headers=headers, timeout=120
    ) as c:
        made_agents: list[str] = []
        ds_id = None
        try:
            a = (
                await c.post(
                    "/agents",
                    json={
                        "name": f"v240-{uuid.uuid4().hex[:6]}",
                        "config": {
                            "model": "mock-llm",
                            "prompt": "평가 귀속",
                            "mcps": ["local-tools"],
                        },
                    },
                )
            ).json()
            made_agents.append(a["id"])
            v0 = a.get("activeVersion") or a.get("active_version")

            ds = (
                await c.post(
                    "/eval/datasets",
                    json={"name": f"ds240-{uuid.uuid4().hex[:6]}", "kind": "agent"},
                )
            ).json()
            ds_id = ds["id"]
            await c.post(
                f"/eval/datasets/{ds_id}/cases",
                json={
                    "name": "인사",
                    "input": "안녕",
                    "asserts": [{"type": "no_error"}],
                },
            )

            r = (await c.post(f"/eval/datasets/{ds_id}/runs", json={"agent_id": a["id"]})).json()
            done = await _wait_run(c, r["id"])
            ck(done.get("status") == "ok", f"V0 평가 실행 완료 (status={done.get('status')})")
            # 새 에이전트는 초안만 있고 활성 버전이 없다(None) — 런의 None은 그 사실의 정직한 기록.
            # 활성 버전 추적 증명은 V2(활성화 후 v1 박제)가 담당.
            ck(
                done.get("agent_version") == v0,
                f"V1a 버전 박제=활성 버전과 일치 (run={done.get('agent_version')} agent={v0})",
            )
            env = done.get("env") or {}
            ck(
                (env.get("model") or {}).get("name") == "mock-llm",
                f"V1b env.model 기록 ({env.get('model')})",
            )
            ck(
                "local-tools" in (env.get("mcps") or {}),
                f"V1c env.mcps 도구 목록 기록 ({list((env.get('mcps') or {}).keys())})",
            )

            # V2 — 편집(초안 v2 생성)→활성화→재실행: 새 버전이 박제되나
            await c.put(
                f"/agents/{a['id']}",
                json={
                    "config": {
                        "model": "mock-llm",
                        "prompt": "평가 귀속 v2",
                        "mcps": ["local-tools"],
                    },
                },
            )
            g = (await c.get(f"/agents/{a['id']}")).json()
            draft = next(
                (v["version"] for v in g.get("versions", []) if v.get("status") == "draft"), None
            )
            if draft:
                await c.post(f"/agents/{a['id']}/activate", json={"version": draft})
            g2 = (await c.get(f"/agents/{a['id']}")).json()
            v1 = g2.get("activeVersion") or g2.get("active_version")
            r2 = (await c.post(f"/eval/datasets/{ds_id}/runs", json={"agent_id": a["id"]})).json()
            done2 = await _wait_run(c, r2["id"])
            ck(
                bool(v1) and v1 != v0 and done2.get("agent_version") == v1,
                f"V2 버전 전환 추적 ({v0} → {v1}, run={done2.get('agent_version')})",
            )

            # V3 — 목록 API에도 노출
            runs = (await c.get(f"/eval/runs?dataset_id={ds_id}")).json()
            ck(any(x.get("agent_version") for x in runs), "V3 목록 RunOut에 agent_version 노출")
        finally:
            if ds_id:
                await c.delete(f"/eval/datasets/{ds_id}")
            for aid in made_agents:
                await c.delete(f"/agents/{aid}")

    ok = all(x for x, _ in checks)
    print("VERIFY240_OK" if ok else f"VERIFY240_FAIL({sum(1 for x, _ in checks if not x)})")
    return ok


if __name__ == "__main__":
    raise SystemExit(0 if asyncio.run(run()) else 1)

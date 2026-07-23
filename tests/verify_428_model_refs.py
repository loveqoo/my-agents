"""스펙 428 검증 — 미등록 모델 폴백 재설계(불변식 우선).

P2③(in-process): _resolve_model이 선언-broken(cfg.model 미등록)이면 400, 미설정은 기본 폴백.
P1①(live): PUT /models 이름변경 — 참조 에이전트 있으면 409, 없으면 200, 동명 저장은 무영향.
P1②(live): POST /agents — 미등록 모델명 400, 등록 모델 201, 미설정 201(기본 폴백).

라이브 서버(8000)+실모델 등록 전제(reset 후 상태). 던짐유저·테스트 에이전트는 끝에 정리(debris 0).
실행: uv run python tests/verify_428_model_refs.py
"""
from __future__ import annotations
import asyncio, secrets, subprocess, sys
from pathlib import Path
import httpx

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "packages" / "api" / "src"))
BASE = "http://127.0.0.1:8000"
PROV = REPO / "tests" / "_provision_super.py"
fails: list[str] = []
def ok(c, m): print(("  ok  " if c else " FAIL ")+m); (fails.append(m) if not c else None)

async def p2_resolve_inprocess():
    from api.db import SessionLocal
    from api.chat_context_models import _resolve_model
    from fastapi import HTTPException
    async with SessionLocal() as db:
        # 선언-broken → 400
        try:
            await _resolve_model(db, {"model": f"nope-{secrets.token_hex(3)}"}, None)
            ok(False, "P2③ 선언-broken이 거절 안 됨(조용한 폴백)")
        except HTTPException as e:
            ok(e.status_code == 400, f"P2③ 선언-broken → 400 (got {e.status_code})")
        # 미설정 → 기본 폴백(예외 없이 cfg 반환)
        try:
            cfg = await _resolve_model(db, {"model": ""}, None)
            ok(isinstance(cfg, dict) and cfg.get("model_id"), "P2③ 미설정 → 기본 폴백(무회귀)")
        except HTTPException as e:
            ok(False, f"P2③ 미설정이 거절됨(회귀!) {e.status_code}:{e.detail}")

async def live():
    email = f"verify428_{secrets.token_hex(3)}@example.com"; pw = "Verify428!pw"
    subprocess.run(["uv","run","python",str(PROV),"create",email,pw], check=True, capture_output=True)
    created_agents = []
    async with httpx.AsyncClient(timeout=40) as c:
        r = await c.post(f"{BASE}/auth/login", data={"username":email,"password":pw},
                         headers={"Content-Type":"application/x-www-form-urlencoded"})
        assert r.status_code in (200,204), f"login {r.status_code}"
        c.cookies.set("agentauth", r.cookies.get("agentauth"))
        models = {m["name"]: m for m in (await c.get(f"{BASE}/models")).json()}
        def body(m, **over):
            b = {"name":m["name"],"provider_id":m.get("providerId") or m.get("provider_id"),
                 "model_id":m.get("modelId") or m.get("model_id"),"kind":m["kind"],
                 "is_default":m.get("isDefault",m.get("is_default",False)),
                 "params":m.get("params") or {},"capabilities":m.get("capabilities") or {},"meta":m.get("meta") or {}}
            b.update(over); return b
        # P1① rename 참조 모델(mock-llm=시드 에이전트 4개 참조) → 409
        ref = models["mock-llm"]
        r = await c.put(f"{BASE}/models/{ref['id']}", json=body(ref, name="mock-llm-RENAMED"))
        ok(r.status_code == 409, f"P1① 참조 모델 rename → 409 (got {r.status_code}: {r.text[:80]})")
        # 동명 저장(이름 안 바꿈) → 무영향 200
        r = await c.put(f"{BASE}/models/{ref['id']}", json=body(ref))
        ok(r.status_code == 200, f"P1① 동명 저장(rename 아님) → 200 (got {r.status_code})")
        # P1① rename 미참조 모델(qwen36=시드 미참조) → 200, 되돌리기
        unref = models["qwen36"]
        r = await c.put(f"{BASE}/models/{unref['id']}", json=body(unref, name="qwen36-tmp"))
        ok(r.status_code == 200, f"P1① 미참조 모델 rename → 200 (got {r.status_code}: {r.text[:80]})")
        if r.status_code == 200:  # 되돌리기
            await c.put(f"{BASE}/models/{unref['id']}", json=body(unref, name="qwen36"))
        # P1② POST /agents 미등록 모델명 → 400
        r = await c.post(f"{BASE}/agents", json={"name":f"v428-bad-{secrets.token_hex(2)}",
            "config":{"model":f"nope-{secrets.token_hex(3)}","prompt":"x"}})
        ok(r.status_code == 400, f"P1② 미등록 모델명 저장 → 400 (got {r.status_code})")
        # P1② 등록 모델 → 201
        r = await c.post(f"{BASE}/agents", json={"name":f"v428-ok-{secrets.token_hex(2)}",
            "config":{"model":"qwen36","prompt":"x"}})
        ok(r.status_code == 201, f"P1② 등록 모델 저장 → 201 (got {r.status_code}: {r.text[:80]})")
        if r.status_code == 201: created_agents.append(r.json()["id"])
        # P1② 미설정(model 빈값) → 201(기본 폴백)
        r = await c.post(f"{BASE}/agents", json={"name":f"v428-unset-{secrets.token_hex(2)}",
            "config":{"model":"","prompt":"x"}})
        ok(r.status_code == 201, f"P1② 미설정 모델 저장 → 201(기본 폴백) (got {r.status_code}: {r.text[:80]})")
        if r.status_code == 201: created_agents.append(r.json()["id"])
        # codex 428: 공백 패딩(" mock-llm ") → 정규화 통과 201 + 저장값 canonical("mock-llm")
        r = await c.post(f"{BASE}/agents", json={"name":f"v428-pad-{secrets.token_hex(2)}",
            "config":{"model":" mock-llm ","prompt":"x"}})
        ok(r.status_code == 201, f"P1② 공백패딩 모델 → 201(정규화) (got {r.status_code}: {r.text[:80]})")
        if r.status_code == 201:
            aid = r.json()["id"]; created_agents.append(aid)
            got = (await c.get(f"{BASE}/agents/{aid}")).json()
            stored = (got.get("config") or {}).get("model") or got.get("model")
            ok(stored == "mock-llm", f"P1② 저장값 canonical strip (got {stored!r})")
        # codex 428: 공백만("   ") → unset 취급 201(기본 폴백, 런타임 400 안 남)
        r = await c.post(f"{BASE}/agents", json={"name":f"v428-ws-{secrets.token_hex(2)}",
            "config":{"model":"   ","prompt":"x"}})
        ok(r.status_code == 201, f"P1② 공백만 모델 → 201(unset 취급) (got {r.status_code}: {r.text[:80]})")
        if r.status_code == 201: created_agents.append(r.json()["id"])
        # codex 428: clone도 검증 경유 — 정상 원본 clone → 201(검증 추가로 무회귀 확인)
        if created_agents:
            r = await c.post(f"{BASE}/agents/{created_agents[0]}/clone")
            ok(r.status_code == 201, f"P1② clone(정상 원본) → 201(검증 무회귀) (got {r.status_code})")
            if r.status_code == 201: created_agents.append(r.json()["id"])
        # 정리
        for aid in created_agents: await c.delete(f"{BASE}/agents/{aid}")
    subprocess.run(["uv","run","python",str(PROV),"delete",email], capture_output=True)
    print(f"  · 정리: 테스트 에이전트 {len(created_agents)}개 + 던짐유저 삭제")

async def main():
    await p2_resolve_inprocess()
    await live()
    print("\n" + ("VERIFY428_OK" if not fails else f"FAIL {len(fails)}"))
    sys.exit(1 if fails else 0)

if __name__ == "__main__":
    asyncio.run(main())

"""RAG 인제스트 메모리 실측(자원감사 ② — 스펙 347의 '1.6GB 추정' 검증).
mock-embed(1024차원, 인프로세스)로 ~50k 청크 인제스트하며 API 워커 RSS를 1초 샘플링."""
import asyncio, secrets, subprocess, sys, time
from pathlib import Path
import httpx

REPO = Path.cwd(); BASE = "http://127.0.0.1:8000"
PROV = REPO / "tests" / "_provision_super.py"
WORKER_PID = int(sys.argv[1])

def rss_mb(pid: int) -> float:
    try:
        out = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)], capture_output=True, text=True)
        return int(out.stdout.strip() or 0) / 1024
    except Exception:
        return -1

async def main():
    email = f"probe_rss_{secrets.token_hex(3)}@example.com"; pw = "Rss427!pw"
    subprocess.run(["uv","run","python",str(PROV),"create",email,pw],check=True,capture_output=True)
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post(f"{BASE}/auth/login", data={"username":email,"password":pw},
                         headers={"Content-Type":"application/x-www-form-urlencoded"})
        c.cookies.set("agentauth", r.cookies.get("agentauth"))
        models = (await c.get(f"{BASE}/models")).json()
        emb = next(m for m in models if m["name"] == "mock-embed")
        # 컬렉션(청크 500/100 → 20MB 텍스트 ≈ 50k 청크)
        r = await c.post(f"{BASE}/collections", json={
            "name": f"rss-probe-{secrets.token_hex(3)}", "embedding_model_id": emb["id"],
            "chunk_size": 500, "chunk_overlap": 100})
        assert r.status_code in (200,201), r.text[:200]
        col = r.json(); cid = col["id"]
        print(f"컬렉션 생성: {col['name']} (chunk 500/100)")
        # 20MB 텍스트 생성(문장 단위 — splitter가 자연 분할)
        line = "자원 감사 실측용 문장입니다. 메모리 소비를 재기 위한 반복 텍스트. "
        text = (line * (20_000_000 // len(line.encode()) // 1 + 1))
        data = text.encode()[:20_000_000].decode(errors="ignore")
        print(f"텍스트 {len(data.encode())/1e6:.1f}MB 생성")
        base_rss = rss_mb(WORKER_PID)
        print(f"기저 RSS: {base_rss:.0f}MB")
        # 업로드(multipart) → 백그라운드 인제스트 spawn
        r = await c.post(f"{BASE}/collections/{cid}/documents",
                         files={"file": ("rss-probe.txt", data.encode(), "text/plain")})
        assert r.status_code in (200,201), f"{r.status_code}: {r.text[:200]}"
        doc = r.json(); did = doc["id"]
        print(f"업로드 완료(doc {did}) — 인제스트 시작. RSS 샘플링:")
        peak = base_rss; t0 = time.monotonic(); status = "?"
        while True:
            cur = rss_mb(WORKER_PID)
            peak = max(peak, cur)
            docs = (await c.get(f"{BASE}/collections/{cid}/documents")).json()
            row = next((d for d in (docs if isinstance(docs, list) else docs.get("items", [])) if d["id"] == did), None)
            status = (row or {}).get("status", "?")
            el = time.monotonic() - t0
            print(f"  t={el:5.1f}s rss={cur:7.1f}MB (Δ{cur-base_rss:+7.1f}) status={status}", flush=True)
            if status in ("ready", "error") or el > 600:
                break
            await asyncio.sleep(1)
        await asyncio.sleep(3)
        final = rss_mb(WORKER_PID)
        col2 = (await c.get(f"{BASE}/collections/{cid}")).json()
        print(f"\n=== 결과 ===")
        print(f"status={status} · chunk_count={col2.get('chunkCount') or col2.get('chunk_count')}")
        print(f"기저 {base_rss:.0f}MB · 피크 {peak:.0f}MB (Δ{peak-base_rss:+.0f}MB) · 종료후 {final:.0f}MB (잔류 Δ{final-base_rss:+.0f}MB)")
        # 정리
        r = await c.delete(f"{BASE}/collections/{cid}")
        print(f"정리: 컬렉션 삭제 {r.status_code}")
    subprocess.run(["uv","run","python",str(PROV),"delete",email],capture_output=True)
asyncio.run(main())

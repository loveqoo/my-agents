"""재인덱싱·문서편집 메모리 실측(스펙 433 — 432 측정 패턴 미러).

20MB 문서를 인제스트한 컬렉션에서 ①재청킹 재인덱싱 ②문서 전체 편집을 각각 실행하며 API 워커 RSS를
1초 샘플링해 피크·잔류를 보고한다. mock-embed(1024차원 — 실전과 같은 벡터 형상)로 결정적.
실행: uv run python tests/measure_reindex_rss.py <워커PID>
"""
import asyncio
import secrets
import subprocess
import sys
import time
from pathlib import Path

import httpx

REPO = Path.cwd(); BASE = "http://127.0.0.1:8000"
PROV = REPO / "tests" / "_provision_super.py"
WPID = int(sys.argv[1])

def rss_mb(pid: int) -> float:
    out = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)], capture_output=True, text=True)
    return int(out.stdout.strip() or 0) / 1024

async def watch(c, label, done_check, base):
    peak = base
    t0 = time.monotonic()
    while True:
        cur = rss_mb(WPID)
        peak = max(peak, cur)
        el = time.monotonic() - t0
        finished = await done_check()
        print(f"  [{label}] t={el:5.1f}s rss={cur:7.1f}MB (Δ{cur-base:+7.1f}) {finished or ''}", flush=True)
        if finished or el > 600:
            break
        await asyncio.sleep(1)
    return peak

async def main():
    email = f"probe_rx_{secrets.token_hex(3)}@example.com"
    pw = "Rx433!pw"
    subprocess.run(["uv","run","python",str(PROV),"create",email,pw],check=True,capture_output=True)
    async with httpx.AsyncClient(timeout=300) as c:
        r = await c.post(f"{BASE}/auth/login", data={"username":email,"password":pw},
                         headers={"Content-Type":"application/x-www-form-urlencoded"})
        c.cookies.set("agentauth", r.cookies.get("agentauth"))
        emb = next(m for m in (await c.get(f"{BASE}/models")).json() if m["name"] == "mock-embed")
        r = await c.post(f"{BASE}/collections", json={
            "name": f"rx-probe-{secrets.token_hex(3)}", "embedding_model_id": emb["id"],
            "chunk_size": 500, "chunk_overlap": 100})
        cid = r.json()["id"]
        line = "재인덱싱 메모리 실측용 문장입니다. 반복 텍스트로 청크를 만든다. "
        text = (line * (20_000_000 // len(line.encode()) + 1))
        data = text.encode()[:20_000_000].decode(errors="ignore")
        print(f"컬렉션 준비 · 텍스트 {len(data.encode())/1e6:.1f}MB")
        r = await c.post(f"{BASE}/collections/{cid}/documents",
                         files={"file": ("rx.txt", data.encode(), "text/plain")})
        did = r.json()["id"]
        async def doc_ready():
            docs = (await c.get(f"{BASE}/collections/{cid}/documents")).json()
            rows = docs if isinstance(docs, list) else docs.get("items", [])
            st = next((d["status"] for d in rows if d["id"] == did), "?")
            return f"status={st}" if st in ("ready","error") else None
        while not await doc_ready():
            await asyncio.sleep(1)
        col = (await c.get(f"{BASE}/collections/{cid}")).json()
        print(f"인제스트 완료 · chunks={col.get('chunkCount') or col.get('chunk_count')}")

        # ① 재청킹 재인덱싱(chunk_size 변경 → 전 문서 재청킹 경로)
        await asyncio.sleep(3)
        base1 = rss_mb(WPID)
        print(f"\n[재인덱싱] 기저 {base1:.0f}MB — chunk_size 500→400")
        task = asyncio.create_task(c.post(f"{BASE}/collections/{cid}/reindex", json={"chunk_size": 400}))
        async def rx_done():
            return "완료" if task.done() else None
        peak1 = await watch(c, "재인덱싱", rx_done, base1)
        rr = await task
        await asyncio.sleep(3)
        after1 = rss_mb(WPID)
        col = (await c.get(f"{BASE}/collections/{cid}")).json()
        print(f"[재인덱싱] HTTP {rr.status_code} · chunks={col.get('chunkCount') or col.get('chunk_count')}")
        print(f"[재인덱싱] 기저 {base1:.0f} · 피크 {peak1:.0f}MB (Δ{peak1-base1:+.0f}) · 종료후 {after1:.0f}MB (잔류 Δ{after1-base1:+.0f})")

        # ② 문서 전체 편집(내용 절반 교체 → 재사용+재임베딩 혼합)
        await asyncio.sleep(2)
        base2 = rss_mb(WPID)
        edited = data[: len(data)//2] + "수정된 내용 " * 20000
        print(f"\n[편집] 기저 {base2:.0f}MB — 본문 {len(edited.encode())/1e6:.1f}MB로 교체")
        task2 = asyncio.create_task(
            c.put(f"{BASE}/collections/{cid}/documents/{did}/content", json={"text": edited}))
        async def ed_done():
            return "완료" if task2.done() else None
        peak2 = await watch(c, "편집", ed_done, base2)
        r2 = await task2
        await asyncio.sleep(3)
        after2 = rss_mb(WPID)
        print(f"[편집] HTTP {r2.status_code} · {str(r2.json())[:120] if r2.status_code < 300 else r2.text[:150]}")
        print(f"[편집] 기저 {base2:.0f} · 피크 {peak2:.0f}MB (Δ{peak2-base2:+.0f}) · 종료후 {after2:.0f}MB (잔류 Δ{after2-base2:+.0f})")

        await c.delete(f"{BASE}/collections/{cid}")
        print("\n정리 완료")
    subprocess.run(["uv","run","python",str(PROV),"delete",email],capture_output=True)
asyncio.run(main())

"""스펙 368 — 채팅 핫패스 빌드 비용 베이스라인 측정 하네스 (재실행 자산).

매턴 그래프 재구성 비용(trace.buildMs — memory/mcp/rag/broker/graph/total)을
축별로 실측해 표로 낸다. 캐시(스펙 367-D) 前/後 비교의 '이전' 잣대.

축: MCP 바인딩 {0, 1, 3} × 동시성 {순차 1, 동시 8}. 모델=mock-llm(모델 지연 배제).
전제: 실서버(8000, 계측 포함 코드) + 시드 served MCP(calc-tools·local-tools·web-fetch).
실행: .venv/bin/python tests/measure_build_hotpath.py  (또는 make perf-build)
"""

import asyncio
import json
import os
import statistics
import sys
import uuid

import httpx

BASE = os.environ.get("API_BASE", "http://127.0.0.1:8000")
EMAIL = os.environ.get("ADMIN_EMAIL", "admin@example.com")
PASSWORD = os.environ.get("ADMIN_PASSWORD", "adminpass123")
SEQ_TURNS = int(os.environ.get("SEQ_TURNS", "10"))
CONC = int(os.environ.get("CONC", "8"))
CONC_WAVES = int(os.environ.get("CONC_WAVES", "3"))  # 동시 8 × 3파 = 24표본

MCP_AXES = {0: [], 1: ["calc-tools"], 3: ["calc-tools", "local-tools", "web-fetch"]}
STAGES = ["memory", "mcp", "rag", "broker", "graph", "total"]


def _trace_from_sse(text: str) -> dict | None:
    for frame in text.split("\n\n"):
        if "event: trace" not in frame:
            continue
        for line in frame.split("\n"):
            if line.startswith("data: "):
                return json.loads(line[6:])
    return None


async def _chat_build_ms(cli: httpx.AsyncClient, aid: str, msg: str) -> dict | None:
    r = await cli.post(f"/agents/{aid}/chat", json={"messages": [{"role": "user", "content": msg}]})
    r.raise_for_status()
    tr = _trace_from_sse(r.text)
    return (tr or {}).get("buildMs")


def _pct(xs: list[float], p: float) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    k = max(0, min(len(s) - 1, round(p / 100 * (len(s) - 1))))
    return s[k]


async def measure_cell(
    cli: httpx.AsyncClient, aid: str, concurrency: int
) -> dict[str, list[float]]:
    """한 셀(에이전트×동시성) 측정 — 단계별 표본 리스트 반환. 워밍업 1턴은 버린다."""
    await _chat_build_ms(cli, aid, "368 워밍업")
    samples: dict[str, list[float]] = {s: [] for s in STAGES}

    def collect(bm: dict | None) -> None:
        if not bm:
            return
        for s in STAGES:
            samples[s].append(float(bm.get(s, 0)))

    if concurrency == 1:
        for i in range(SEQ_TURNS):
            collect(await _chat_build_ms(cli, aid, f"368 순차 {i}"))
    else:
        for w in range(CONC_WAVES):
            results = await asyncio.gather(
                *[_chat_build_ms(cli, aid, f"368 동시 {w}-{i}") for i in range(concurrency)]
            )
            for bm in results:
                collect(bm)
    return samples


async def main() -> None:
    tag = uuid.uuid4().hex[:6]
    async with httpx.AsyncClient(base_url=BASE, timeout=180.0) as cli:
        r = await cli.post("/auth/login", data={"username": EMAIL, "password": PASSWORD})
        if r.status_code >= 400 or "agentauth" not in cli.cookies:
            raise SystemExit(f"로그인 실패({r.status_code}) — 서버 8000 확인")

        agents: dict[int, str] = {}
        try:
            for n, mcps in MCP_AXES.items():
                cr = await cli.post(
                    "/agents",
                    json={
                        "name": f"perf368-mcp{n}-{tag}",
                        "config": {
                            "model": "mock-llm",
                            "prompt": "",
                            "memories": [],
                            "vectorTables": [],
                            "mcps": mcps,
                            "historyDepth": 10,
                        },
                    },
                )
                cr.raise_for_status()
                j = cr.json()
                ver = next(
                    (v for v in j.get("versions", []) if v.get("status") == "draft"),
                    (j.get("versions") or [{}])[0],
                )
                (
                    await cli.post(
                        f"/agents/{j['id']}/activate", json={"version": ver.get("version")}
                    )
                ).raise_for_status()
                agents[n] = j["id"]

            rows: list[tuple[str, dict[str, list[float]]]] = []
            for n in MCP_AXES:
                for conc in (1, CONC):
                    label = f"mcp={n} × {'순차' if conc == 1 else f'동시{conc}'}"
                    print(f"  측정 중: {label} …", flush=True)
                    rows.append((label, await measure_cell(cli, agents[n], conc)))

            hdr = f"{'셀':<16}" + "".join(f"{s:>14}" for s in STAGES)
            print("\n=== 빌드 비용 베이스라인 (p50/p95 ms) ===")
            print(hdr)
            for label, samples in rows:
                cells = "".join(
                    f"{_pct(samples[s], 50):>7.1f}/{_pct(samples[s], 95):<6.1f}" for s in STAGES
                )
                print(f"{label:<16}{cells}")
            n_ok = sum(len(s["total"]) for _, s in rows)
            print(
                f"\n표본 합계 {n_ok}턴 · 평균 total p50 = "
                f"{statistics.median([_pct(s['total'], 50) for _, s in rows]):.1f}ms"
            )
            if any(len(s["total"]) == 0 for _, s in rows):
                print("경고: 표본 0인 셀 존재 — buildMs 미노출(서버 구코드?) 확인 필요")
                sys.exit(1)
        finally:
            for aid in agents.values():
                await cli.delete(f"/agents/{aid}")


if __name__ == "__main__":
    asyncio.run(main())

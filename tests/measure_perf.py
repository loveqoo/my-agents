"""배포 에이전트 종합 성능 프로파일(스펙 421 후속) — CPU·메모리·응답속도 + 유형 비교.

판정 축(개발자): 1순위 = **매 요청 반복 CPU**(단일 이벤트 루프를 블록, [[cpu-axis-not-latency]]).
응답속도·메모리도 함께 보되 CPU를 캐시 가치의 주축으로 본다. **mock-llm**이라 지연은 모델 추론이
아니라 **플랫폼 오버헤드**(그래프 빌드+프레임워크+스트리밍)다 — 캐시가 건드리는 바로 그 비용을 격리.

측정(유형별):
- latency p50/p95(ms, wall) — 요청 왕복(플랫폼 오버헤드).
- buildMs.graph p50 — 트레이스가 노출하는 **정밀 그래프 컴파일 시간**(캐시 적중=0). 캐시의 직접 신호.
- CPU/요청(ms) — 서버 프로세스 cpu_times 델타 / 요청수(빌드+프레임워크 전부, psutil 타 PID 조회).
- RSS Δ(MB) — 실행 전후 상주 메모리 증가(캐시 엔트리 + 누수 탐지).
- 동시성 버스트: ok/total·wall·처리량(req/s)·p95(경합·500 다발 관측).

비교: **캐시됨(default·route·plan_execute)** vs **미캐시(orchestrate·pipeline-3/8, 스펙 421 P2/P3 잔여)**.

실행: SERVER_PID=<uvicorn pid> uv run --with psutil --project packages/api python tests/measure_perf.py
전제: 서버 8000 + 로그인(ADMIN_EMAIL/PASSWORD). [[net-runs-are-exclusive]] — 실행 중 서버 다른 활동 금지.
"""

import asyncio
import json
import os
import statistics
import subprocess
import time

import httpx
import psutil

BASE = os.environ.get("API_BASE", "http://127.0.0.1:8000")
EMAIL = os.environ.get("ADMIN_EMAIL", "admin@example.com")
PASSWORD = os.environ.get("ADMIN_PASSWORD", "adminpass123")
K = int(os.environ.get("PERF_TURNS", "60"))  # 유형별 순차 요청 수
BURST = int(os.environ.get("BURST", "30"))  # 동시 버스트 총 요청 수
WARMUP = 3

CACHED = {"default", "route", "plan_execute", "orchestrate", "pipeline-3", "pipeline-8"}  # 421 완주(artifact 제외)


def _find_pid() -> int:
    env = os.environ.get("SERVER_PID")
    if env:
        return int(env)
    out = subprocess.run(
        ["lsof", "-nP", "-iTCP:8000", "-sTCP:LISTEN"], capture_output=True, text=True
    ).stdout
    for line in out.splitlines()[1:]:
        return int(line.split()[1])
    raise SystemExit("서버 PID 못 찾음 — SERVER_PID 지정")


def _cpu_s(p: psutil.Process) -> float:
    t = p.cpu_times()
    return t.user + t.system


def _rss_mb(p: psutil.Process) -> float:
    return p.memory_info().rss / 1024 / 1024


def _trace(body: str) -> dict | None:
    for f in body.split("\n\n"):
        if "event: trace" in f:
            for line in f.split("\n"):
                if line.startswith("data: "):
                    return json.loads(line[6:])
    return None


def _pct(xs: list[float], q: float) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    i = min(len(s) - 1, int(q * len(s)))
    return s[i]


def _configs(delegate: str) -> dict[str, dict]:
    m = "mock-llm"

    def node(i: int) -> dict:
        return {"name": f"n{i}", "model": m, "prompt": "짧게.", "tools": []}

    return {
        "default": {"model": m, "prompt": "", "mcps": []},
        "route": {"model": m, "impl": "route"},
        "plan_execute": {"model": m, "impl": "plan_execute"},
        "orchestrate": {"model": m, "impl": "orchestrate", "capabilities": [delegate]},
        "pipeline-3": {"model": m, "impl": "pipeline", "nodes": [node(i) for i in range(3)]},
        "pipeline-8": {"model": m, "impl": "pipeline", "nodes": [node(i) for i in range(8)]},
    }


async def _mk(cli: httpx.AsyncClient, name: str, cfg: dict) -> str:
    j = (await cli.post("/agents", json={"name": name, "config": cfg})).json()
    ver = (j.get("versions") or [{}])[0].get("version")
    await cli.post(f"/agents/{j['id']}/activate", json={"version": ver})
    return j["id"]


async def _chat(cli: httpx.AsyncClient, aid: str) -> tuple[bool, float, dict | None]:
    """반환 (ok, latency_ms, trace)."""
    t0 = time.perf_counter()
    try:
        r = await cli.post(
            f"/agents/{aid}/chat", json={"messages": [{"role": "user", "content": "perf"}]}
        )
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code >= 400:
            return False, dt, None
        return True, dt, _trace(r.text)
    except httpx.HTTPError:
        return False, (time.perf_counter() - t0) * 1000, None


async def main() -> None:
    pid = _find_pid()
    proc = psutil.Process(pid)
    print(f"서버 PID={pid} · 순차 K={K} · 버스트={BURST} · mock-llm(지연=플랫폼 오버헤드)\n")
    async with httpx.AsyncClient(base_url=BASE, timeout=180.0) as cli:
        r = await cli.post("/auth/login", data={"username": EMAIL, "password": PASSWORD})
        if r.status_code >= 400 or "agentauth" not in cli.cookies:
            raise SystemExit(f"로그인 실패({r.status_code})")
        import uuid

        tag = uuid.uuid4().hex[:6]
        delegate = await _mk(cli, f"perf-del-{tag}", {"model": "mock-llm", "prompt": "", "mcps": []})
        made: dict[str, str] = {}
        seq_rows = []
        burst_rows = []
        try:
            for key, cfg in _configs(delegate).items():
                made[key] = await _mk(cli, f"perf-{key.replace('_', '-')}-{tag}", cfg)

            rss_start_all = _rss_mb(proc)
            for i, (key, aid) in enumerate(made.items(), 1):
                print(f"[{i}/{len(made)}] {key} 측정 중…", flush=True)
                for _ in range(WARMUP):
                    await _chat(cli, aid)
                rss0, cpu0 = _rss_mb(proc), _cpu_s(proc)
                lats, graphs, totals, ok = [], [], [], 0
                for _ in range(K):
                    o, lat, tr = await _chat(cli, aid)
                    ok += o
                    if o:
                        lats.append(lat)
                        b = (tr or {}).get("buildMs") or {}
                        graphs.append(b.get("graph", 0.0))
                        totals.append(b.get("total", 0.0))
                cpu_seq = _cpu_s(proc) - cpu0
                rss_d = _rss_mb(proc) - rss0
                seq_rows.append(
                    (
                        key,
                        key in CACHED,
                        _pct(lats, 0.5),
                        _pct(lats, 0.95),
                        _pct(graphs, 0.5),
                        _pct(totals, 0.5),
                        (cpu_seq / ok * 1000) if ok else 0.0,
                        rss_d,
                        ok,
                    )
                )
                # 동시성 버스트
                w0 = time.perf_counter()
                res = await asyncio.gather(*[_chat(cli, aid) for _ in range(BURST)])
                wall = time.perf_counter() - w0
                okb = sum(1 for o, _, _ in res if o)
                blats = [lat for o, lat, _ in res if o]
                burst_rows.append(
                    (key, okb, BURST, wall, (okb / wall) if wall else 0.0, _pct(blats, 0.95))
                )
            rss_end_all = _rss_mb(proc)
        finally:
            await cli.delete(f"/agents/{delegate}")
            for aid in made.values():
                await cli.delete(f"/agents/{aid}")

    base_cpu = next((r[6] for r in seq_rows if r[0] == "default"), 0.0)
    print("\n== 순차(요청당) — 캐시됨 vs 미캐시 ==")
    print(f"{'유형':<14}{'캐시':>5}{'지연p50':>9}{'지연p95':>9}{'graph빌드':>10}{'total빌드':>10}{'CPU/req':>9}{'순빌드CPU':>10}{'RSSΔMB':>9}")
    for key, cached, lp50, lp95, gp50, tp50, cpu, rss_d, ok in seq_rows:
        net = cpu - base_cpu
        print(
            f"{key:<14}{'Y' if cached else 'N':>5}{lp50:>8.1f}{lp95:>8.1f}{gp50:>9.2f}{tp50:>9.2f}"
            f"{cpu:>8.2f}{net:>9.2f}{rss_d:>8.1f}  (ok {ok}/{K})"
        )
    print("\n== 동시 버스트 ==")
    print(f"{'유형':<14}{'ok/total':>10}{'wall(s)':>9}{'처리량req/s':>12}{'지연p95':>9}")
    for key, okb, tot, wall, thr, p95 in burst_rows:
        print(f"{key:<14}{f'{okb}/{tot}':>10}{wall:>8.2f}{thr:>11.1f}{p95:>8.0f}")
    print(f"\n서버 RSS: 시작 {rss_start_all:.0f}MB → 종료 {rss_end_all:.0f}MB (Δ {rss_end_all-rss_start_all:+.0f}MB, 캐시 엔트리+워크로드)")
    print(
        "\n해석: graph빌드=정밀 그래프 컴파일(캐시 적중=0). '순빌드CPU'=default(캐시) 뺀 순수 빌드 CPU. "
        "지연=mock 모델이라 플랫폼 오버헤드(모델 추론 제외). RSSΔ 지속 증가=누수 신호."
    )


if __name__ == "__main__":
    asyncio.run(main())

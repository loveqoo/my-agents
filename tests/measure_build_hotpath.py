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


_chat_errors: dict[str, int] = {}


async def _chat_build_ms(cli: httpx.AsyncClient, aid: str, msg: str) -> dict | None:
    """한 턴 채팅 → buildMs. 개별 실패(500 등)는 통계 측정을 멈추지 않게 None으로 삼키되 카운트
    (동시성서 깨지는 유형 자체가 발견 대상 — 스펙 420 후속)."""
    try:
        r = await cli.post(f"/agents/{aid}/chat", json={"messages": [{"role": "user", "content": msg}]})
        if r.status_code >= 400:
            _chat_errors[str(r.status_code)] = _chat_errors.get(str(r.status_code), 0) + 1
            return None
        tr = _trace_from_sse(r.text)
        return (tr or {}).get("buildMs")
    except (httpx.HTTPError, json.JSONDecodeError) as e:
        _chat_errors[type(e).__name__] = _chat_errors.get(type(e).__name__, 0) + 1
        return None


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


async def _make_agent(cli: httpx.AsyncClient, name: str, config: dict) -> str:
    """에이전트 생성+활성화 → id. (perf 측정용 공용 — MCP 축·impl 축 공유)."""
    cr = await cli.post("/agents", json={"name": name, "config": config})
    cr.raise_for_status()
    j = cr.json()
    ver = next(
        (v for v in j.get("versions", []) if v.get("status") == "draft"),
        (j.get("versions") or [{}])[0],
    )
    (await cli.post(f"/agents/{j['id']}/activate", json={"version": ver.get("version")})).raise_for_status()
    return j["id"]


def _impl_configs(delegate_agent_id: str) -> dict[str, dict]:
    """impl 축(스펙 420 후속 조사) — 캐시 제외 유형의 graph 빌드 비용을 default와 대조. mcps=[]로
    MCP 축을 격리(그 비용은 별도 버전키 캐시라 여기선 순수 compile+래핑 CPU만 본다). default=베이스라인."""
    m = "mock-llm"

    def node(i: int) -> dict:
        return {"name": f"n{i}", "model": m, "prompt": "짧게 한 문장으로 답하세요.", "tools": []}

    return {
        "default": {"model": m, "prompt": "", "mcps": []},
        "pipeline-3": {"model": m, "impl": "pipeline", "nodes": [node(i) for i in range(3)]},
        "pipeline-8": {"model": m, "impl": "pipeline", "nodes": [node(i) for i in range(8)]},
        "orchestrate": {"model": m, "impl": "orchestrate", "capabilities": [delegate_agent_id]},
        "route": {"model": m, "impl": "route"},
        "plan_execute": {"model": m, "impl": "plan_execute"},
        "artifact_form": {"model": m, "impl": "artifact_form",
                          "artifactSpec": {"fields": [{"key": "a", "label": "A"}, {"key": "b", "label": "B"}]}},
    }


async def _measure_impl_axis(cli: httpx.AsyncClient, tag: str) -> None:
    """impl 유형별 graph 빌드 비용 표(스펙 420 후속) — 전제 '실시간 빌드=비싸다' 검증."""
    delegate = await _make_agent(cli, f"perf420-delegate-{tag}", {"model": "mock-llm", "prompt": "", "mcps": []})
    made: dict[str, str] = {}
    try:
        for key, cfg in _impl_configs(delegate).items():
            # 이름 규칙(스펙 148) — 밑줄 금지라 키의 `_`를 `-`로(config 키는 유지).
            made[key] = await _make_agent(cli, f"perf420-{key.replace('_', '-')}-{tag}", cfg)
        rows: list[tuple[str, dict[str, list[float]]]] = []
        for key in made:
            for conc in (1, CONC):
                label = f"{key} × {'순차' if conc == 1 else f'동시{conc}'}"
                print(f"  측정 중(impl): {label} …", flush=True)
                rows.append((label, await measure_cell(cli, made[key], conc)))
        print("\n=== impl 유형별 빌드 비용 (스펙 420 후속 — graph/total p50/p95 ms · n=표본) ===")
        print(f"{'셀':<24}{'graph':>16}{'total':>16}{'n':>5}")
        for label, samples in rows:
            g = f"{_pct(samples['graph'], 50):>7.1f}/{_pct(samples['graph'], 95):<6.1f}"
            t = f"{_pct(samples['total'], 50):>7.1f}/{_pct(samples['total'], 95):<6.1f}"
            print(f"{label:<24}{g:>16}{t:>16}{len(samples['total']):>5}")
        if _chat_errors:
            print(f"\n채팅 실패(동시성 취약 신호): {_chat_errors}")
    finally:
        await cli.delete(f"/agents/{delegate}")
        for aid in made.values():
            await cli.delete(f"/agents/{aid}")


async def main() -> None:
    tag = uuid.uuid4().hex[:6]
    impl_only = os.environ.get("IMPL_ONLY") == "1"
    async with httpx.AsyncClient(base_url=BASE, timeout=180.0) as cli:
        r = await cli.post("/auth/login", data={"username": EMAIL, "password": PASSWORD})
        if r.status_code >= 400 or "agentauth" not in cli.cookies:
            raise SystemExit(f"로그인 실패({r.status_code}) — 서버 8000 확인")

        if impl_only:  # 스펙 420 후속 — impl 축만(빠른 재실행)
            await _measure_impl_axis(cli, tag)
            return

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

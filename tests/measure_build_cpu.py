"""스펙 420 후속 — 그래프 빌드의 **CPU 소모** 측정(응답시간 아님, [[cpu-axis-not-latency]]).

개발자 교정: "응답시간이 중요한 게 아니라 CPU가 매 요청 빌드하며 튀는 게 문제." 단일 이벤트 루프라
동기 CPU 작업(그래프 compile·도구 래핑)은 그 시간 동안 다른 모든 요청을 블록한다. 매 요청 반복되는
CPU를 버전당 1회로 상각할 수 있나가 캐시의 가치.

측정법: **서버 프로세스의 누적 CPU time(user+system)을 요청 배치 전후로 읽어** 요청당 CPU를 구한다
(psutil은 타 PID 조회 가능 — 클라가 서버 PID를 샘플). default(캐시)=CPU 상각 대조군. 모델=mock-llm.
축: 유형 × {순차 K, 동시 버스트}. 그래프 compile은 동기라 wall==CPU(확인용 wall도 병기).

실행: SERVER_PID=<uvicorn worker pid> uv run --with psutil python tests/measure_build_cpu.py
      (미지정 시 uvicorn 워커 자동탐지). 전제: 서버 8000 + 로그인 계정(ADMIN_EMAIL/PASSWORD).
"""

import asyncio
import os
import subprocess
import time

import httpx
import psutil

BASE = os.environ.get("API_BASE", "http://127.0.0.1:8000")
EMAIL = os.environ.get("ADMIN_EMAIL", "admin@example.com")
PASSWORD = os.environ.get("ADMIN_PASSWORD", "adminpass123")
K = int(os.environ.get("CPU_TURNS", "80"))  # 배치당 순차 요청 수(CPU 누적을 재려면 크게)
BURST = int(os.environ.get("BURST", "40"))  # 동시 버스트 총 요청 수


def _find_server_pid() -> int:
    env = os.environ.get("SERVER_PID")
    if env:
        return int(env)
    out = subprocess.run(["ps", "ax", "-o", "pid=,command="], capture_output=True, text=True).stdout
    for line in out.splitlines():
        if "uvicorn api.main:app" in line and "uv run" not in line:
            return int(line.split()[0])
    raise SystemExit("uvicorn 워커 PID를 못 찾음 — SERVER_PID로 지정")


def _cpu_s(proc: psutil.Process) -> float:
    t = proc.cpu_times()
    return t.user + t.system  # 초


async def _make_agent(cli: httpx.AsyncClient, name: str, config: dict) -> str:
    j = (await cli.post("/agents", json={"name": name, "config": config})).json()
    ver = (j.get("versions") or [{}])[0].get("version")
    await cli.post(f"/agents/{j['id']}/activate", json={"version": ver})
    return j["id"]


async def _chat(cli: httpx.AsyncClient, aid: str) -> bool:
    try:
        r = await cli.post(f"/agents/{aid}/chat", json={"messages": [{"role": "user", "content": "cpu"}]})
        return r.status_code < 400
    except httpx.HTTPError:
        return False


def _configs(delegate: str) -> dict[str, dict]:
    m = "mock-llm"

    def node(i: int) -> dict:
        return {"name": f"n{i}", "model": m, "prompt": "짧게.", "tools": []}

    return {
        "default(cached)": {"model": m, "prompt": "", "mcps": []},
        "route": {"model": m, "impl": "route"},
        "plan_execute": {"model": m, "impl": "plan_execute"},
        "orchestrate": {"model": m, "impl": "orchestrate", "capabilities": [delegate]},
        "pipeline-3": {"model": m, "impl": "pipeline", "nodes": [node(i) for i in range(3)]},
        "pipeline-8": {"model": m, "impl": "pipeline", "nodes": [node(i) for i in range(8)]},
    }


async def main() -> None:
    pid = _find_server_pid()
    proc = psutil.Process(pid)
    print(f"서버 PID={pid} CPU 측정 · 순차 K={K} · 동시 버스트={BURST}\n")
    async with httpx.AsyncClient(base_url=BASE, timeout=180.0) as cli:
        r = await cli.post("/auth/login", data={"username": EMAIL, "password": PASSWORD})
        if r.status_code >= 400 or "agentauth" not in cli.cookies:
            raise SystemExit(f"로그인 실패({r.status_code})")
        import uuid

        tag = uuid.uuid4().hex[:6]
        delegate = await _make_agent(cli, f"cpu420-delegate-{tag}", {"model": "mock-llm", "prompt": "", "mcps": []})
        made: dict[str, str] = {}
        rows = []
        try:
            for key, cfg in _configs(delegate).items():
                made[key] = await _make_agent(cli, f"cpu420-{key.replace('_', '-').replace('(', '-').replace(')', '')}-{tag}", cfg)

            for key, aid in made.items():
                await _chat(cli, aid)  # 워밍업
                # 순차 K회 — 서버 CPU 누적 델타.
                c0 = _cpu_s(proc)
                ok = 0
                for _ in range(K):
                    ok += await _chat(cli, aid)
                cpu_seq = _cpu_s(proc) - c0
                per_req_cpu = (cpu_seq / ok * 1000) if ok else 0.0  # ms CPU/요청
                # 동시 버스트 — 같은 CPU가 짧은 창에 몰림(루프 점유율).
                c1, w1 = _cpu_s(proc), time.perf_counter()
                res = await asyncio.gather(*[_chat(cli, aid) for _ in range(BURST)])
                cpu_burst = _cpu_s(proc) - c1
                wall_burst = time.perf_counter() - w1
                okb = sum(res)
                busy = (cpu_burst / wall_burst * 100) if wall_burst else 0.0  # CPU 점유율 %
                rows.append((key, per_req_cpu, cpu_seq, ok, busy, okb, BURST))
        finally:
            await cli.delete(f"/agents/{delegate}")
            for aid in made.values():
                await cli.delete(f"/agents/{aid}")

    base = next((r[1] for r in rows if r[0].startswith("default")), 0.0)
    print(f"{'유형':<18}{'CPU/요청(ms)':>14}{'순빌드CPU':>12}{'K회CPU(s)':>12}{'버스트점유%':>12}{'ok':>10}")
    for key, per_req, cpu_seq, _ok, busy, okb, burst in rows:
        build = per_req - base  # default(캐시) 대비 = 순수 빌드 CPU
        print(f"{key:<18}{per_req:>13.2f}{build:>11.2f}{cpu_seq:>12.2f}{busy:>11.0f}{f'{okb}/{burst}':>10}")
    print("\n해석: 'CPU/요청'=서버가 한 요청에 태우는 CPU-ms(mock 모델이라 대부분 빌드+프레임워크). "
          "'순빌드CPU'=default(캐시) 뺀 순수 그래프 빌드 CPU. 캐시는 이걸 버전당 1회로 상각.")
    print("누적 투영: 순빌드 CPU × 요청수 = 낭비 CPU. 예) pipeline-8이 요청당 5ms면 1000req=5s CPU 낭비.")


if __name__ == "__main__":
    asyncio.run(main())

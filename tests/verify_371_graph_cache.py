"""스펙 371 검증 — 버전 키 캐시(D1 MCP 사양·D3 그래프 팩토리) 동작 정합.

  V1  캐시 적중: 같은 에이전트 2턴째 buildMs.graph ≤ 0.5ms(재컴파일 0)·mcp ≤ 0.5ms(재디스커버리 0).
  V2  동시 트레이스 격리(C5): 공유 그래프에 동시 8턴, 각 턴 trace.mcp가 **자기 호출 1건만**
      (config sink — args의 자기 인덱스로 판별, 교차 오염 0).
  V3  promptless 그래프에서도 시스템 프롬프트 동작(sentMessages에 system 존재·응답 정상).
  V4  블록 새 버전 채택 후 도구 목록 반영(무효화=새 키) — pin 에이전트는 불변(370 freeze는 verify_370).

전제: 서버 8000(스펙 371 코드). 실행: .venv/bin/python tests/verify_371_graph_cache.py
"""

import asyncio
import json
import os
import sys
import uuid

import httpx

BASE = os.environ.get("VERIFY_BASE", "http://127.0.0.1:8000")  # 스펙 390: 격리 서버 주입
EMAIL = os.environ.get("ADMIN_EMAIL", "admin@example.com")
PASSWORD = os.environ.get("ADMIN_PASSWORD", "adminpass123")

_fails: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def sse_trace(body: str) -> dict | None:
    for f in body.split("\n\n"):
        if "event: trace" in f:
            for line in f.split("\n"):
                if line.startswith("data: "):
                    return json.loads(line[6:])
    return None


def main() -> None:
    tag = uuid.uuid4().hex[:6]
    cli = httpx.Client(base_url=BASE, timeout=120.0)
    cli.post("/auth/login", data={"username": EMAIL, "password": PASSWORD})

    # failing_op 전용 임시 서버(스펙 320 패턴) — '실패' 트리거·HIL 없음·인자에 user 텍스트가 실림.
    lt = next(m for m in cli.get("/mcp-servers").json() if m["name"] == "local-tools")
    srv = cli.post(
        "/mcp-servers",
        json={
            "name": f"v371-{tag}",
            "source": "local",
            "transport": "http",
            "url": lt.get("url"),
            "tools": ["failing_op", "echo"],
            "enabled_tools": ["failing_op", "echo"],
        },
    ).json()
    p = cli.post(
        "/prompts", json={"name": f"v371p-{tag}", "tone": "t", "body": "너는 V371 검증봇이다."}
    ).json()
    a = cli.post(
        "/agents",
        json={
            "name": f"v371a-{tag}",
            "config": {
                "model": "mock-llm",
                "prompt": f"v371p-{tag}",
                "memories": [],
                "vectorTables": [],
                "mcps": [f"v371-{tag}"],
                "historyDepth": 10,
            },
        },
    ).json()
    aid = a["id"]
    cli.post(f"/agents/{aid}/activate", json={"version": "v1"}).raise_for_status()

    try:

        def chat_sync(msg: str) -> dict | None:
            r = cli.post(
                f"/agents/{aid}/chat", json={"messages": [{"role": "user", "content": msg}]}
            )
            r.raise_for_status()
            return sse_trace(r.text)

        # V1 — 1턴(웜업·miss) → 2턴(적중)
        t1 = chat_sync("워밍업")
        b1 = (t1 or {}).get("buildMs") or {}
        t2 = chat_sync("두 번째")
        b2 = (t2 or {}).get("buildMs") or {}
        check(
            b2.get("graph", 99) <= 0.5, f"V1 2턴째 graph ≤0.5ms(재컴파일 0) (got {b2.get('graph')})"
        )
        check(
            b2.get("mcp", 99) <= 0.5, f"V1 2턴째 mcp ≤0.5ms(재디스커버리 0) (got {b2.get('mcp')})"
        )

        # V3 — promptless 그래프에서 시스템 프롬프트 동작
        sysmsgs = [m for m in (t2 or {}).get("sentMessages") or [] if m.get("role") == "system"]
        check(len(sysmsgs) == 1, f"V3 system 메시지 정확히 1개 (got {len(sysmsgs)})")
        check(
            "V371 검증봇" in (sysmsgs[0].get("content") or "") if sysmsgs else False,
            "V3 system에 프롬프트 본문",
        )

        # V2 — 동시 8턴 트레이스 격리(공유 그래프 + config sink)
        async def race() -> list[dict | None]:
            async with httpx.AsyncClient(base_url=BASE, timeout=120.0, cookies=cli.cookies) as ac:

                async def one(i: int) -> dict | None:
                    r = await ac.post(
                        f"/agents/{aid}/chat",
                        json={
                            "messages": [{"role": "user", "content": f"실패 테스트 ISOLATE-{i}"}]
                        },
                    )
                    return sse_trace(r.text)

                return list(await asyncio.gather(*[one(i) for i in range(8)]))

        traces = asyncio.run(race())
        iso_ok = 0
        for i, tr in enumerate(traces):
            calls = (tr or {}).get("mcp") or []
            fired = [c for c in calls if "failing_op" in str(c.get("tool") or "")]
            mine = [
                c
                for c in fired
                if f"ISOLATE-{i}" in json.dumps(c.get("args") or {}, ensure_ascii=False)
            ]
            if len(fired) == 1 and len(mine) == 1:
                iso_ok += 1
        check(iso_ok == 8, f"V2 동시 8턴 트레이스 격리(자기 호출 1건만) — {iso_ok}/8")

        # V4 — 블록 편집(새 버전) → 채택 → 오픈 → 새 도구 목록 반영(새 키)
        srv_edit = {
            "name": f"v371-{tag}",
            "source": "local",
            "transport": "http",
            "url": lt.get("url"),
            "tools": ["failing_op", "echo"],
            "enabled_tools": ["echo"],
        }
        cli.put(f"/mcp-servers/{srv['id']}", json=srv_edit).raise_for_status()
        cli.post(f"/agents/{aid}/adopt").raise_for_status()
        adj = cli.get(f"/agents/{aid}").json()
        scratch = next(v["version"] for v in adj["versions"] if not v["everOpened"])
        cli.post(f"/agents/{aid}/activate", json={"version": scratch}).raise_for_status()
        t4 = chat_sync("실패 테스트 AFTER-ADOPT")
        fired4 = [
            c for c in (t4 or {}).get("mcp") or [] if "failing_op" in str(c.get("tool") or "")
        ]
        check(
            len(fired4) == 0,
            f"V4 채택+오픈 후 failing_op 미발동(새 버전=enabled서 제거) (got {len(fired4)})",
        )
    finally:
        cli.delete(f"/agents/{aid}")
        cli.delete(f"/mcp-servers/{srv['id']}")
        cli.delete(f"/prompts/{p['id']}")
        cli.close()

    print()
    if _fails:
        print(f"FAILED ({len(_fails)}):")
        for f in _fails:
            print("  - " + f)
        sys.exit(1)
    print("ALL PASS (verify_371)")


if __name__ == "__main__":
    main()

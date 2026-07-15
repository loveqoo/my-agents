"""스펙 370 검증 — 복합 에이전트 버전(pins freeze·오픈 포인터·충돌 규칙) 실서버 통합 rung.

  C1  freeze: 오픈 후 밑 블록(prompt body·mcp enabled_tools) 편집 → 채팅 동작 불변(SSE 실측).
  C2  충돌 규칙: 스크래치 대체(행 수 불변) / 오픈이력 보호(롤백 후 편집 → max+1, 기존 버전 바이트 불변).
  C3  롤백: 채택→오픈(새 pin 동작) → 예전 버전 오픈 → 예전 pin 동작 복귀(시스템 프롬프트 실측).
  C4  채택: stalePins 배지 데이터 → adopt → 새 스크래치 pins=head.
  C6  이관: ui 에이전트 버전 pins 백필(빈 pins 0).

전제: 서버 8000(스펙 370 코드). 실행: .venv/bin/python tests/verify_370_composite_version.py
"""

import json
import os
import sys
import uuid

import httpx
from sqlalchemy import create_engine, text

BASE = os.environ.get("API_BASE", "http://127.0.0.1:8000")
EMAIL = os.environ.get("ADMIN_EMAIL", "admin@example.com")
PASSWORD = os.environ.get("ADMIN_PASSWORD", "adminpass123")
DB = os.environ.get(
    "DATABASE_URL", "postgresql+asyncpg://agent:agent@localhost:5432/agents"
).replace("+asyncpg", "+psycopg")

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


def system_prompt_of(trace: dict | None) -> str:
    for m in (trace or {}).get("sentMessages") or []:
        if m.get("role") == "system":
            return m.get("content") or ""
    return ""


def main() -> None:  # noqa: PLR0915
    tag = uuid.uuid4().hex[:6]
    cli = httpx.Client(base_url=BASE, timeout=120.0)
    r = cli.post("/auth/login", data={"username": EMAIL, "password": PASSWORD})
    check(r.status_code < 400, f"로그인 ({r.status_code})")

    pname = f"p370-{tag}"
    aname = f"a370-{tag}"
    p = cli.post("/prompts", json={"name": pname, "tone": "t", "body": "PIN-BODY-1"}).json()
    a = cli.post(
        "/agents",
        json={
            "name": aname,
            "config": {
                "model": "mock-llm",
                "prompt": pname,
                "memories": [],
                "vectorTables": [],
                "mcps": ["calc-tools"],
                "historyDepth": 10,
            },
        },
    ).json()
    aid = a["id"]

    try:
        # 생성 = v1 스크래치 + pins freeze
        v1 = a["versions"][0]
        check(v1["version"] == "v1" and v1["everOpened"] is False, "생성 → v1 스크래치")
        check(v1["pins"].get(f"prompt:{pname}") == 1, f"v1 pins에 prompt v1 (got {v1['pins']})")
        check(f"mcp-server:calc-tools" in v1["pins"], "v1 pins에 calc-tools")

        # 오픈 v1
        cli.post(f"/agents/{aid}/activate", json={"version": "v1"}).raise_for_status()

        def chat(msg: str) -> dict | None:
            resp = cli.post(f"/agents/{aid}/chat", json={"messages": [{"role": "user", "content": msg}]})
            resp.raise_for_status()
            return sse_trace(resp.text)

        t = chat("안녕")
        check("PIN-BODY-1" in system_prompt_of(t), "C1 오픈 v1 채팅 시스템 프롬프트 = pin body(v1)")

        # ── C1 freeze: 밑 블록 편집 후에도 동작 불변 ─────────────────────────────
        cli.put(f"/prompts/{p['id']}", json={"name": pname, "tone": "t", "body": "PIN-BODY-2"}).raise_for_status()
        t = chat("프롬프트 편집 후")
        check("PIN-BODY-1" in system_prompt_of(t), "C1 프롬프트 head v2로 편집해도 채팅 = PIN-BODY-1(freeze)")

        # mcp freeze — 전용 임시 서버(스펙 320 패턴): local-tools URL에 enabled=[failing_op]
        # ('실패' 트리거·HIL 없음)로 배선 → pin 확보 → head에서 failing_op 제거 → pin 에이전트는
        # 못박은 enabled_tools로 여전히 발동.
        mcps = cli.get("/mcp-servers").json()
        lt = next(m for m in mcps if m["name"] == "local-tools")
        srv_name = f"pin370-{tag}"
        srv = cli.post(
            "/mcp-servers",
            json={
                "name": srv_name, "source": "local", "transport": "http", "url": lt.get("url"),
                "tools": ["failing_op", "echo"], "enabled_tools": ["failing_op", "echo"],
            },
        ).json()
        cfg_lt = {
            "model": "mock-llm", "prompt": pname, "memories": [], "vectorTables": [],
            "mcps": [srv_name], "historyDepth": 10,
        }
        a2 = cli.post("/agents", json={"name": f"a370lt-{tag}", "config": cfg_lt}).json()
        cli.post(f"/agents/{a2['id']}/activate", json={"version": "v1"}).raise_for_status()
        srv_edit = {"name": srv_name, "source": "local", "transport": "http", "url": lt.get("url"),
                    "tools": ["failing_op", "echo"], "enabled_tools": ["echo"]}
        cli.put(f"/mcp-servers/{srv['id']}", json=srv_edit).raise_for_status()
        try:
            resp = cli.post(
                f"/agents/{a2['id']}/chat",
                json={"messages": [{"role": "user", "content": "실패 테스트 한 번"}]},
            )
            t2 = sse_trace(resp.text)
            fired = [str(c.get("tool") or c.get("name") or "") for c in (t2 or {}).get("mcp") or []]
            check(
                any("failing_op" in f for f in fired),
                f"C1 head서 failing_op 제거 후에도 pin 에이전트는 발동 (got {fired})",
            )
        finally:
            cli.delete(f"/agents/{a2['id']}")
            cli.delete(f"/mcp-servers/{srv['id']}")

        # ── C4 채택: stalePins → adopt → 스크래치 pins=head ─────────────────────
        detail = cli.get(f"/agents/{aid}").json()
        stale = detail.get("stalePins") or []
        check(
            any(s["kind"] == "prompt" and s["name"] == pname and s["head"] >= 2 for s in stale),
            f"C4 stalePins에 prompt head>pin (got {stale})",
        )
        ad = cli.post(f"/agents/{aid}/adopt")
        check(ad.status_code == 200, f"C4 adopt 200 (got {ad.status_code})")
        adj = ad.json()
        scratch = next(v for v in adj["versions"] if not v["everOpened"])
        check(scratch["version"] == "v2", f"C4 채택 스크래치 = v2 (got {scratch['version']})")
        check(scratch["pins"].get(f"prompt:{pname}") == 2, "C4 스크래치 pins=prompt v2(head)")

        # ── C3 롤백: v2 오픈(새 pin 동작) → v1 재오픈(예전 pin 동작) ─────────────
        cli.post(f"/agents/{aid}/activate", json={"version": "v2"}).raise_for_status()
        t = chat("v2에서")
        check("PIN-BODY-2" in system_prompt_of(t), "C3 v2 오픈 → 채팅 = PIN-BODY-2")
        cli.post(f"/agents/{aid}/activate", json={"version": "v1"}).raise_for_status()  # 롤백
        t = chat("롤백 후")
        check("PIN-BODY-1" in system_prompt_of(t), "C3 v1 롤백 → 채팅 = PIN-BODY-1(예전 pin 복귀)")

        # ── C2 충돌 규칙 ─────────────────────────────────────────────────────────
        # 현재: v1 오픈, v2 오픈이력. 편집 → 슬롯 v2 보호 → v3 스크래치 신설.
        v2_before = json.dumps(
            next(v for v in cli.get(f"/agents/{aid}").json()["versions"] if v["version"] == "v2"),
            sort_keys=True,
        )
        cfg = dict(a["versions"][0]["config"])
        cli.put(
            f"/agents/{aid}", json={"name": aname, "config": {**cfg, "historyDepth": 15}}
        ).raise_for_status()
        vers = cli.get(f"/agents/{aid}").json()["versions"]
        vmap = {v["version"]: v for v in vers}
        check("v3" in vmap and not vmap["v3"]["everOpened"], "C2 롤백 후 편집 → v2 보호·v3 스크래치")
        v2_after = json.dumps(vmap["v2"], sort_keys=True)
        check(v2_before == v2_after, "C2 오픈이력 v2 바이트 불변")
        # 스크래치 대체: 재편집 → 여전히 v3 하나(행 수 불변)
        n_before = len(vers)
        cli.put(
            f"/agents/{aid}", json={"name": aname, "config": {**cfg, "historyDepth": 17}}
        ).raise_for_status()
        vers2 = cli.get(f"/agents/{aid}").json()["versions"]
        check(len(vers2) == n_before, f"C2 재편집 → 스크래치 대체(행 수 {n_before} 불변)")
        v3 = next(v for v in vers2 if v["version"] == "v3")
        check(v3["config"]["historyDepth"] == 17, "C2 대체된 v3에 새 내용")

        # ── C6 이관: ui 에이전트 버전 pins 백필 ─────────────────────────────────
        # 빈 pins 허용 예외: 해석 가능한 참조가 하나도 없는 config(테스트 잔해 등)는 pins {}가 정답.
        # 시드 에이전트(실참조 보유)는 전 버전 pins 보유 — 이관 불변식.
        eng = create_engine(DB)
        with eng.connect() as c:
            n_empty = c.execute(
                text(
                    "select count(*) from agent_versions av join agents ag on ag.id = av.agent_pk "
                    "where ag.source = 'ui' and av.pins = '{}'::jsonb "
                    "and ag.name in ('research-assistant','personal-secretary','research-pipeline-demo')"
                )
            ).scalar()
        check((n_empty or 0) == 0, f"C6 시드 에이전트 버전 빈 pins 0 (got {n_empty})")
    finally:
        cli.delete(f"/agents/{aid}")
        cli.delete(f"/prompts/{p['id']}")
        cli.close()

    print()
    if _fails:
        print(f"FAILED ({len(_fails)}):")
        for f in _fails:
            print("  - " + f)
        sys.exit(1)
    print("ALL PASS (verify_370)")


if __name__ == "__main__":
    main()

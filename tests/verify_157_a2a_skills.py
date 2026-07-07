"""verify_157 — A2A skills 확장: 카드가 실제 능력 광고 (스펙 157, 실사용 #7).

카드 skills[]가 chat 외에 에이전트의 실제 MCP 도구·서브에이전트 위임·RAG를 정직하게 광고하는지,
dangling은 스킵하는지, 노출 게이트/민감정보/캡을 실측(ASGI 카드 fetch).

  V1 MCP 에이전트: skills에 chat + mcp:local-tools/<tool>(설명 포함).
  V2 조율형: capabilities agent:/mcp:/rag: → delegate·mcp·rag 스킬.
  V3 dangling(없는 agent/mcp/rag) → chat만(죽은 참조 스킵).
  V4 노출 안 된 에이전트 카드 404(무회귀).
  V5 스킬 캡(_MAX_A2A_SKILLS) — 60개 mcp cap이어도 상한.
  V6 카드 민감정보 미노출(auth/token/복호화 없음).
실행: uv run --project packages/api --env-file .env python tests/verify_157_a2a_skills.py
"""
import asyncio
import os
import sys
import uuid as _uuid

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "packages", "api", "src"))

import httpx  # noqa: E402
from sqlalchemy import select  # noqa: E402

from api.db import SessionLocal as async_session  # noqa: E402
from api.models import Agent, Collection, McpServer  # noqa: E402

_fails = []
passed = 0
TOKEN = os.environ.get("API_AUTH_TOKEN", "")


def check(cond, msg):
    global passed
    print(("  ok  " if cond else " FAIL ") + msg)
    if cond:
        passed += 1
    else:
        _fails.append(msg)


async def _mk(tag, suffix, config, exposed=True, source="ui", endpoint=None, description=None):
    async with async_session() as s:
        a = Agent(agent_id=f"{tag}-{suffix}", name=f"{tag}-{suffix}", description=description, source=source,
                  owner_id=None, config=config, exposed={"a2a": exposed}, endpoint=endpoint)
        s.add(a)
        await s.commit()
        await s.refresh(a)
        return a.id


async def _card(client, agent_id):
    r = await client.get(f"/agents/{agent_id}/.well-known/agent-card.json")
    return r.status_code, (r.json() if r.status_code == 200 else None)


async def main():
    from api.authz import init_authz
    from api.main import app
    await init_authz()
    tag = f"v157-{_uuid.uuid4().hex[:6]}"
    made = []
    made_mcp = []
    transport = httpx.ASGITransport(app=app)
    try:
        # 실 컬렉션 이름 하나 확보(rag 광고 검증용) — 없으면 rag 검증 스킵.
        async with async_session() as s:
            coll = (await s.execute(select(Collection.name))).scalars().first()

        # ---- V1 MCP 에이전트 ----
        v1 = await _mk(tag, "mcp", {"mcps": ["local-tools"], "persona": "", "model": ""})
        made.append(v1)
        # ---- V2 조율형(agent+mcp+rag) — 위임 대상은 remote(code+endpoint)여야 광고됨(codex High) ----
        sub = await _mk(tag, "sub", {"mcps": [], "persona": "", "model": ""}, exposed=False,
                        source="code", endpoint="http://127.0.0.1:8000/_remote/a2a")
        made.append(sub)
        sub_aid = f"{tag}-sub"
        caps = [f"agent:{sub_aid}", "mcp:local-tools/echo"]
        if coll:
            caps.append(f"rag:{coll}")
        v2 = await _mk(tag, "orch", {"mcps": [], "capabilities": caps, "persona": "", "model": ""})
        made.append(v2)
        # ---- V7 누출 봉인: ui(미노출) 서브에이전트는 delegate로 광고 안 됨(이름 누출·거짓 능력 차단) ----
        hidden_sub = await _mk(tag, "hidsub", {"mcps": [], "persona": "", "model": ""}, exposed=False,
                               source="ui", description="Secret HR Agent")
        made.append(hidden_sub)
        v7 = await _mk(tag, "leakparent", {"mcps": [], "capabilities": [f"agent:{tag}-hidsub"],
                                           "persona": "", "model": ""})
        made.append(v7)
        # ---- V3 dangling ----
        v3 = await _mk(tag, "dang", {"mcps": ["nope-server"],
                                     "capabilities": [f"agent:{tag}-ghost", "mcp:ghost/x", "rag:no-such-coll"],
                                     "persona": "", "model": ""})
        made.append(v3)
        # ---- V4 미노출 ----
        v4 = await _mk(tag, "hidden", {"mcps": [], "persona": "", "model": ""}, exposed=False)
        made.append(v4)
        # ---- V5 캡: 60개 실 도구를 가진 MCP 서버 → 60 mcp 스킬 + chat = 61 → 50으로 잘림 ----
        big_tools = [f"tool{i}" for i in range(60)]
        big_srv = f"{tag}-bigsrv"
        async with async_session() as s:
            ms = McpServer(name=big_srv, source="local", transport="http",
                           url="http://127.0.0.1:8000/_remote/mcp/", tools=list(big_tools),
                           enabled_tools=list(big_tools), status="connected", published=False, owner_id=None)
            s.add(ms)
            await s.commit()
            made_mcp.append(big_srv)
        v5 = await _mk(tag, "big", {"mcps": [big_srv], "persona": "", "model": ""})
        made.append(v5)

        # ---- V8 stdio transport 서버는 광고 안 함(runtime 미연결과 일치, codex Med1) ----
        stdio_srv = f"{tag}-stdio"
        async with async_session() as s:
            s.add(McpServer(name=stdio_srv, source="local", transport="stdio", tools=["s_tool"],
                            enabled_tools=["s_tool"], status="connected", published=False, owner_id=None))
            await s.commit()
            made_mcp.append(stdio_srv)
        v8 = await _mk(tag, "stdioagent", {"mcps": [stdio_srv], "persona": "", "model": ""})
        made.append(v8)

        # ---- V9 enabled_tools=[]는 런타임서 "서버 전체" → 카드도 tools 스냅샷으로 광고(codex Med2) ----
        allsrv = f"{tag}-allsrv"
        async with async_session() as s:
            s.add(McpServer(name=allsrv, source="local", transport="http",
                            url="http://127.0.0.1:8000/_remote/mcp/", tools=["alpha", "beta"],
                            enabled_tools=[], status="connected", published=False, owner_id=None))
            await s.commit()
            made_mcp.append(allsrv)
        v9 = await _mk(tag, "allagent", {"mcps": [allsrv], "persona": "", "model": ""})
        made.append(v9)

        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000", timeout=60) as c:
            code, card = await _card(c, v1)
            ids = [s["id"] for s in (card or {}).get("skills", [])]
            has_tool = any(i.startswith("mcp:local-tools/") for i in ids)
            desc_ok = any(s["id"].startswith("mcp:local-tools/") and len(s.get("description", "")) > 0
                          for s in (card or {}).get("skills", []))
            check(code == 200 and "chat" in ids and has_tool and desc_ok,
                  f"V1 MCP 스킬 광고(chat+mcp tool+설명) — ids={ids}")

            code, card = await _card(c, v2)
            ids = [s["id"] for s in (card or {}).get("skills", [])]
            tags = {t for s in (card or {}).get("skills", []) for t in s.get("tags", [])}
            deleg = f"agent:{sub_aid}" in ids
            mcp_cap = "mcp:local-tools/echo" in ids
            rag_ok = (not coll) or (f"rag:{coll}" in ids)
            check(deleg and mcp_cap and rag_ok and "delegate" in tags,
                  f"V2 조율형 delegate/mcp/rag 스킬 — deleg={deleg} mcp={mcp_cap} rag={rag_ok}")

            code, card = await _card(c, v3)
            ids = [s["id"] for s in (card or {}).get("skills", [])]
            check(ids == ["chat"], f"V3 dangling 전부 스킵 → chat만 (got {ids})")

            code, _ = await _card(c, v4)
            check(code == 404, f"V4 미노출 카드 404 (got {code})")

            code, card = await _card(c, v5)
            n = len((card or {}).get("skills", []))
            check(code == 200 and n <= 50, f"V5 스킬 캡 ≤50 (got {n})")

            code, card = await _card(c, v1)
            blob = str(card).lower()
            leaked = any(k in blob for k in ("token", "auth", "secret", "bearer", "•", "password"))
            check(not leaked, "V6 카드에 민감정보(token/auth/secret) 미노출")

            # V7 누출 봉인: ui 미노출 서브에이전트 이름이 공개 카드에 안 나옴(codex High)
            code, card = await _card(c, v7)
            ids = [s["id"] for s in (card or {}).get("skills", [])]
            blob = str(card)
            check(ids == ["chat"] and "Secret HR Agent" not in blob and f"{tag}-hidsub" not in blob,
                  f"V7 ui 미노출 서브에이전트 delegate 미광고·이름 미누출 (ids={ids})")

            # V8 stdio 서버는 광고 안 함(runtime 미연결과 일치)
            code, card = await _card(c, v8)
            ids = [s["id"] for s in (card or {}).get("skills", [])]
            check(ids == ["chat"], f"V8 stdio transport 서버 미광고 → chat만 (got {ids})")

            # V9 enabled_tools=[] → tools 스냅샷(alpha,beta)으로 광고
            code, card = await _card(c, v9)
            ids = [s["id"] for s in (card or {}).get("skills", [])]
            has_both = f"mcp:{allsrv}/alpha" in ids and f"mcp:{allsrv}/beta" in ids
            check(has_both, f"V9 빈 enabled → tools 스냅샷 광고(alpha,beta) (got {ids})")
    finally:
        async with async_session() as s:
            for aid in made:
                a = await s.get(Agent, aid)
                if a is not None:
                    await s.delete(a)
            for mname in made_mcp:
                m = (await s.execute(select(McpServer).where(McpServer.name == mname))).scalar_one_or_none()
                if m is not None:
                    await s.delete(m)
            await s.commit()

    print(f"\n{passed} passed, {len(_fails)} failed")
    if _fails:
        sys.exit(1)


asyncio.run(main())

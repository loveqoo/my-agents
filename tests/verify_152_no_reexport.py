"""verify_152 — 외부 유래 재공개 금지 (스펙 152, 실사용 #5).

  V1 publish: external 켜기 400 · 끄기 항상 허용 · local 켜기 정상.
  V2 생성: published=True + source=external → 400.
  V3 update 우회: published 켜기 400 · source→external과 published 동시 변경 400.
  V4 에이전트 기존 봉인 핀(083·147): external/code expose 400 · 끄기 허용.
  V5 유래 세탁 차단(codex High): update로 source 변경 → 400(불변).
  V6 소비 지점 fail-closed(codex Medium): 오염 행(external+published, ORM 직접)이 member 에이전트
     배선(_load_context)에서 걸러짐 — 쓰기 게이트 우회 데이터도 런타임서 재확인.
실행: uv run --project packages/api --env-file .env python tests/verify_152_no_reexport.py
"""
import asyncio
import os
import sys
import uuid as _uuid

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "packages", "api", "src"))

from fastapi import HTTPException  # noqa: E402
from sqlalchemy import select  # noqa: E402

from api.db import SessionLocal as async_session  # noqa: E402
from api import agents as AG  # noqa: E402
from api import blocks as BL  # noqa: E402
from api.models import Agent, McpServer  # noqa: E402
from api.schemas import ExposeIn, McpPublishIn, McpServerIn  # noqa: E402

_fails = []
passed = 0


def check(cond, msg):
    global passed
    print(("  ok  " if cond else " FAIL ") + msg)
    if cond:
        passed += 1
    else:
        _fails.append(msg)


class _P:
    id = _uuid.uuid4()
    is_superuser = True


async def main():
    from api.authz import init_authz
    await init_authz()
    admin = _P()
    tag = f"v152-{_uuid.uuid4().hex[:6]}"
    made_mcp: list = []
    made_agents: list = []

    try:
        # 준비: external MCP 1개(published=False), local MCP 1개
        async with async_session() as s:
            ext = await BL.create_mcp_server(McpServerIn(name=f"{tag}-ext", source="external", transport="http",
                                                         url="http://127.0.0.1:9"), session=s, principal=admin)
            made_mcp.append(_uuid.UUID(str(ext.id)))
            loc = await BL.create_mcp_server(McpServerIn(name=f"{tag}-loc", source="local"), session=s, principal=admin)
            made_mcp.append(_uuid.UUID(str(loc.id)))

        # V1 publish 게이트
        async with async_session() as s:
            try:
                await BL.publish_mcp_server(made_mcp[0], McpPublishIn(published=True), session=s, principal=admin)
                check(False, "V1a external publish 켜기 → 400이어야")
            except HTTPException as e:
                check(e.status_code == 400, f"V1a external publish 400 (got {e.status_code})")
        async with async_session() as s:
            out = await BL.publish_mcp_server(made_mcp[0], McpPublishIn(published=False), session=s, principal=admin)
            check(out.published is False, "V1b 끄기는 항상 허용(멱등 청소)")
        async with async_session() as s:
            out = await BL.publish_mcp_server(made_mcp[1], McpPublishIn(published=True), session=s, principal=admin)
            check(out.published is True, "V1c local publish 정상")
        async with async_session() as s:
            await BL.publish_mcp_server(made_mcp[1], McpPublishIn(published=False), session=s, principal=admin)

        # V2 생성 경로
        async with async_session() as s:
            try:
                await BL.create_mcp_server(McpServerIn(name=f"{tag}-ext2", source="external", published=True),
                                           session=s, principal=admin)
                check(False, "V2 external+published 생성 → 400이어야")
            except HTTPException as e:
                check(e.status_code == 400, f"V2 external+published 생성 400 (got {e.status_code})")

        # V3 update 우회
        async with async_session() as s:
            try:
                await BL.update_mcp_server(made_mcp[0],
                                           McpServerIn(name=f"{tag}-ext", source="external", transport="http",
                                                       url="http://127.0.0.1:9", published=True),
                                           session=s, principal=admin)
                check(False, "V3a update로 external published 켜기 → 400이어야")
            except HTTPException as e:
                check(e.status_code == 400, f"V3a update 우회 400 (got {e.status_code})")
        async with async_session() as s:
            # local을 external로 바꾸면서 published 동시 켜기 — 결과 상태 기준 판정
            try:
                await BL.update_mcp_server(made_mcp[1],
                                           McpServerIn(name=f"{tag}-loc", source="external", transport="http",
                                                       url="http://127.0.0.1:9", published=True),
                                           session=s, principal=admin)
                check(False, "V3b source·published 동시 변경 → 400이어야")
            except HTTPException as e:
                check(e.status_code == 400, f"V3b 동시 변경 400 (got {e.status_code})")

        # V4 에이전트 기존 봉인 핀
        async with async_session() as s:
            ext_agent = Agent(agent_id=f"{tag}-ea", name=f"{tag}-ea", source="external",
                              config={"model": "", "persona": ""}, exposed={"a2a": False})
            code_agent = Agent(agent_id=f"{tag}-ca", name=f"{tag}-ca", source="code",
                               config={"model": "", "persona": ""}, exposed={"a2a": False})
            s.add_all([ext_agent, code_agent])
            await s.commit()
            made_agents.extend([ext_agent.id, code_agent.id])
        for aid, label in ((made_agents[0], "external"), (made_agents[1], "code")):
            async with async_session() as s:
                try:
                    await AG.expose_agent(aid, ExposeIn(a2a=True), session=s, principal=admin)
                    check(False, f"V4 {label} 에이전트 A2A 켜기 → 400이어야")
                except HTTPException as e:
                    check(e.status_code == 400, f"V4 {label} 에이전트 A2A 400 (got {e.status_code})")
        async with async_session() as s:
            out = await AG.expose_agent(made_agents[0], ExposeIn(a2a=False), session=s, principal=admin)
            check(out is not None, "V4 끄기는 허용(멱등 청소)")

        # V5 유래 세탁 차단 — external→local 전이 400
        async with async_session() as s:
            try:
                await BL.update_mcp_server(made_mcp[0],
                                           McpServerIn(name=f"{tag}-ext", source="local"),
                                           session=s, principal=admin)
                check(False, "V5 source 변경 → 400이어야")
            except HTTPException as e:
                check(e.status_code == 400 and "source" in str(e.detail), f"V5 source 불변 400 (got {e.status_code})")

        # V6 소비 지점 fail-closed — 오염 행(external+published=True, ORM 직접)이 배선에서 걸러짐
        from api import chat as CH
        member_id = str(_uuid.uuid4())
        async with async_session() as s:
            polluted = McpServer(name=f"{tag}-dirty", source="external", transport="http",
                                 url="http://127.0.0.1:9", tools=["x"], enabled_tools=["x"],
                                 published=True, owner_id=str(_uuid.uuid4()))  # 타인 소유
            s.add(polluted)
            member_agent = Agent(agent_id=f"{tag}-ma", name=f"{tag}-ma", owner_id=member_id,
                                 config={"model": "", "persona": "", "mcps": [f"{tag}-dirty"],
                                         "memories": [], "vectorTables": [],
                                         "historyDepth": 5})
            s.add(member_agent)
            await s.commit()
            made_mcp.append(polluted.id)
            made_agents.append(member_agent.id)
        ctx = await CH._load_context(made_agents[-1], None)
        wired = [m["name"] for m in ctx["mcp_servers"]]
        check(f"{tag}-dirty" not in wired, f"V6 오염 행 배선 차단(published이지만 external) — wired={wired}")
    finally:
        async with async_session() as s:
            for mid in made_mcp:
                m = await s.get(McpServer, mid)
                if m is not None:
                    await s.delete(m)
            for aid in made_agents:
                a = await s.get(Agent, aid)
                if a is not None:
                    await s.delete(a)
            await s.commit()

    print(f"\n{passed} passed, {len(_fails)} failed")
    if _fails:
        sys.exit(1)


asyncio.run(main())

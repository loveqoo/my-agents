"""verify_156 — 내부(커스텀) MCP 외부 공개 (스펙 156, 실사용 #4).

우리가 외부 MCP를 등록해 붙는 것의 **반대편** — 우리가 서빙하고 외부(MultiServerMCPClient)가 붙는다.
실 서버(127.0.0.1:8000)로 루프백 검증(ASGI 아님 — 서빙 마운트/lifespan/가드를 실제로 태운다).

  V1 커스텀 MCP 행 존재·source=custom.
  V2 공개 게이트: 비소유 member 404-fold, admin 허용(assert_may_manage).
  V3 루프백: published=True → MultiServerMCPClient로 서빙 URL 접속, 도구 목록+add(2,3)=5 실호출.
  V4 미공개: published=False → 서빙 404(연결 실패).
  V5 봉인: (a) external publish 400(152 무회귀), (b) 레지스트리 없는 custom 이름 published → 서빙 404.
실행: uv run --project packages/api --env-file .env python tests/verify_156_custom_mcp.py
※ 실 서버가 새 코드로 떠 있어야 한다(API 재기동 후).
"""
import asyncio
import os
import sys
import uuid as _uuid

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "packages", "api", "src"))

from fastapi import HTTPException  # noqa: E402
from sqlalchemy import select  # noqa: E402

from api.db import SessionLocal as async_session  # noqa: E402
from api import blocks as BL  # noqa: E402
from api.models import McpServer  # noqa: E402
from api.schemas import McpPublishIn  # noqa: E402
from api.served_mcp import SERVED_MCP_TOOLS, served_url  # noqa: E402

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
    def __init__(self, superuser=False):
        self.id = _uuid.uuid4()
        self.is_superuser = superuser


async def _get_by_name(name):
    async with async_session() as s:
        return (await s.execute(select(McpServer).where(McpServer.name == name))).scalar_one_or_none()


async def _client_tools(url):
    """외부 소비자처럼 우리 서빙 URL에 붙는다(runtime과 동일 MultiServerMCPClient)."""
    from langchain_mcp_adapters.client import MultiServerMCPClient

    client = MultiServerMCPClient({"calc": {"transport": "streamable_http", "url": url}})
    return await client.get_tools()


async def main():
    from api.authz import init_authz
    await init_authz()
    admin = _P(superuser=True)
    member = _P()
    made = []
    NAME = "calc-tools"
    try:
        # calc-tools 행 보장(시드는 테이블 비었을 때만 넣으므로 라이브엔 없을 수 있음). 없으면 생성(정리 추적).
        row = await _get_by_name(NAME)
        if row is None:
            async with async_session() as s:
                r = McpServer(name=NAME, source="custom", transport="http", url=served_url(NAME),
                              tools=list(SERVED_MCP_TOOLS[NAME]), enabled_tools=list(SERVED_MCP_TOOLS[NAME]),
                              status="connected", published=False, owner_id=None)
                s.add(r)
                await s.commit()
                made.append(("name", NAME))
            row = await _get_by_name(NAME)
        calc_id = row.id
        # 시작 상태 저장(원복용)
        start_pub = row.published

        check(row.source == "custom", f"V1 커스텀 MCP 행 source=custom (got {row.source})")

        # ---- V2 공개 게이트 ----
        async with async_session() as s:
            try:
                await BL.publish_mcp_server(calc_id, McpPublishIn(published=True), session=s, principal=member)
                check(False, "V2a 비소유 member 공개 → 404-fold이어야")
            except HTTPException as e:
                check(e.status_code == 404, f"V2a 비소유 member 공개 404-fold (got {e.status_code})")
        async with async_session() as s:
            out = await BL.publish_mcp_server(calc_id, McpPublishIn(published=True), session=s, principal=admin)
            check(out.published is True, "V2b admin 공개 허용")

        # ---- V3 루프백(외부 클라이언트로 우리 서빙에 붙기) ----
        tools = await _client_tools(served_url(NAME))
        names = sorted(t.name for t in tools)
        check(names == ["add", "echo", "multiply"], f"V3a 서빙 도구 목록 (got {names})")
        add_tool = next(t for t in tools if t.name == "add")
        res = await add_tool.ainvoke({"a": 2, "b": 3})
        # 결과는 문자열 또는 content-block 리스트([{type:text,text:"5"}]) — 텍스트를 추출해 비교.
        def _text(r):
            if isinstance(r, list):
                return "".join(b.get("text", "") for b in r if isinstance(b, dict))
            return str(r)
        check(_text(res).strip() == "5", f"V3b add(2,3)=5 실호출 (got {res!r})")

        # ---- V4 미공개 → 서빙 404 ----
        async with async_session() as s:
            await BL.publish_mcp_server(calc_id, McpPublishIn(published=False), session=s, principal=admin)
        try:
            await _client_tools(served_url(NAME))
            check(False, "V4 미공개 서빙 → 연결 실패해야(404)")
        except Exception as e:
            check(True, f"V4 미공개 → 서빙 차단({type(e).__name__})")

        # ---- V5a external publish 400(152 무회귀) ----
        async with async_session() as s:
            ext = McpServer(name=f"v156-ext-{_uuid.uuid4().hex[:6]}", source="external", transport="http",
                            url="http://127.0.0.1:8000/_remote/mcp/", tools=[], enabled_tools=[],
                            status="connected", published=False, owner_id=None)
            s.add(ext)
            await s.commit()
            made.append(("id", ext.id))
            ext_id = ext.id
        async with async_session() as s:
            try:
                await BL.publish_mcp_server(ext_id, McpPublishIn(published=True), session=s, principal=admin)
                check(False, "V5a external publish → 400이어야(152)")
            except HTTPException as e:
                check(e.status_code == 400, f"V5a external publish 400 (got {e.status_code})")

        # ---- V6 High 봉인: 사용자는 source=custom 생성 불가(선점·자가선언 우회 차단) ----
        from api.schemas import McpServerIn
        async with async_session() as s:
            try:
                await BL.create_mcp_server(
                    McpServerIn(name=f"v156-hijack-{_uuid.uuid4().hex[:6]}", source="custom",
                                transport="http", tools=["add"], enabled_tools=["add"], published=True),
                    session=s, principal=member)
                check(False, "V6 member의 source=custom 생성 → 400이어야(선점 봉인)")
            except HTTPException as e:
                check(e.status_code == 400, f"V6 source=custom 사용자 생성 400 (got {e.status_code})")

        # ---- V5b 레지스트리 없는 custom 이름 published → 서빙 404(정의 없는 이름은 서빙 안 됨) ----
        ghost = f"ghost-tools-{_uuid.uuid4().hex[:6]}"
        async with async_session() as s:
            g = McpServer(name=ghost, source="custom", transport="http", url=served_url(ghost),
                          tools=[], enabled_tools=[], status="connected", published=True, owner_id=None)
            s.add(g)
            await s.commit()
            made.append(("id", g.id))
        # served_url(ghost)는 마운트조차 없어 실 서버가 404/미라우트 — 연결 실패면 통과.
        try:
            await _client_tools(served_url(ghost))
            check(False, "V5b 레지스트리 없는 custom 서빙 → 실패해야")
        except Exception as e:
            check(True, f"V5b 정의 없는 custom 이름 서빙 차단({type(e).__name__})")

        # 원복: calc-tools published 시작 상태로
        async with async_session() as s:
            await BL.publish_mcp_server(calc_id, McpPublishIn(published=bool(start_pub)), session=s, principal=admin)
    finally:
        async with async_session() as s:
            for kind, val in made:
                if kind == "id":
                    obj = await s.get(McpServer, val)
                else:
                    obj = (await s.execute(select(McpServer).where(McpServer.name == val))).scalar_one_or_none()
                if obj is not None:
                    await s.delete(obj)
            await s.commit()

    print(f"\n{passed} passed, {len(_fails)} failed")
    if _fails:
        sys.exit(1)


asyncio.run(main())

"""verify_151 — MCP 도구 상세 정보 (스펙 151, 실사용 버그 #2).

  V1 _tool_info 순수 파생: 이름/설명(캡)/params(type·required·개수 캡)·스키마 실패 fail-safe.
  V2 discover 라이브(local-tools self-call): toolsDetail에 설명·파라미터 포함.
  V3 rediscover 라우트: 실 local-tools 행의 tools_meta 채움 + enabled_tools 교집합 보존.
  V4 저장 라운드트립: tools_meta 저장 · 편집 시 None=미변경 보존.
  V5 직접 저장 경계(codex High): 101개/거대 설명/비구조 tools_meta → 검증기 거부(422 경로).
  V6 재탐색 참조 가드(codex Medium): 제거될 도구를 에이전트 capabilities가 참조하면 409.
실행: uv run --project packages/api --env-file .env python tests/verify_151_mcp_tool_detail.py
※ local-tools MCP가 자기 서비스(127.0.0.1:8000)라 API 서버가 떠 있어야 한다.
"""
import asyncio
import os
import sys
import uuid as _uuid

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "packages", "api", "src"))

from sqlalchemy import select  # noqa: E402

from api.db import SessionLocal as async_session  # noqa: E402
from api import blocks as BL  # noqa: E402
from api.mock_mcp import MOCK_MCP_SERVER_NAME, MOCK_MCP_URL  # noqa: E402
from api.models import McpServer  # noqa: E402
from api.schemas import McpDiscoverIn, McpServerIn  # noqa: E402

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


class _FakeSchema:
    def __init__(self, required):
        self._r = required

    def model_json_schema(self):
        return {"required": self._r}


class _FakeTool:
    def __init__(self, name, description, args, required):
        self.name = name
        self.description = description
        self.args = args
        self.tool_call_schema = _FakeSchema(required)


async def main():
    from api.authz import init_authz
    await init_authz()
    admin = _P()

    # ---- V1 순수 파생 ----
    t = _FakeTool("web_search", "웹 검색", {"query": {"type": "string"}, "top": {"anyOf": [{"type": "integer"}, {"type": "null"}]}}, ["query"])
    info = BL._tool_info(t)
    check(info["name"] == "web_search" and info["description"] == "웹 검색", "V1a 이름·설명")
    pq = next(p for p in info["params"] if p["name"] == "query")
    pt = next(p for p in info["params"] if p["name"] == "top")
    check(pq["type"] == "string" and pq["required"] is True, "V1b query: string·필수")
    check("integer" in pt["type"] and pt["required"] is False, f"V1c anyOf 타입 합성: {pt['type']}")
    long_desc = BL._tool_info(_FakeTool("x", "d" * 900, {}, []))
    check(len(long_desc["description"]) == BL.TOOL_DESC_CAP, "V1d 설명 캡")
    many = BL._tool_info(_FakeTool("x", "", {f"p{i}": {"type": "string"} for i in range(50)}, []))
    check(len(many["params"]) == BL.TOOL_PARAMS_CAP, "V1e 파라미터 수 캡")

    class _Broken:
        name = "broken"
        description = "d"

        @property
        def args(self):
            raise RuntimeError("boom")

    check(BL._tool_info(_Broken())["params"] == [], "V1f 스키마 실패 fail-safe(params=[])")
    meta = BL._tools_meta_from_details([{"name": f"t{i}", "description": "", "params": []} for i in range(150)])
    check(len(meta) == BL.TOOLS_META_CAP, "V1g 서버당 메타 상한")

    # ---- V2 discover 라이브 ----
    r = await BL.discover_mcp_tools(McpDiscoverIn(url=MOCK_MCP_URL, transport="http"))
    # 스펙 320이 mock에 failing_op(라이브 등록·시드 제외)를 추가해 라이브 탐색은 4건이다.
    check(r.ok and len(r.toolsDetail) == 4, f"V2a 라이브 탐색 ok+메타 4건 (got ok={r.ok}, {len(r.toolsDetail)})")
    ws = next((d for d in r.toolsDetail if d.name == "web_search"), None)
    check(ws is not None and "검색" in ws.description and any(p.name == "query" and p.required for p in ws.params),
          "V2b web_search 설명·query 필수 파라미터")

    # ---- V3 rediscover 라우트(실 local-tools 행) ----
    async with async_session() as s:
        row = (await s.execute(select(McpServer).where(McpServer.name == MOCK_MCP_SERVER_NAME))).scalar_one()
        row_id = row.id
        before_enabled = list(row.enabled_tools or [])
    async with async_session() as s:
        out = await BL.rediscover_mcp_server(row_id, session=s, principal=admin)
        check(out.tools_meta is not None and "web_search" in out.tools_meta, "V3a 재탐색으로 tools_meta 채움")
        check(out.enabled_tools == [t for t in before_enabled if t in out.tools], "V3b enabled 교집합 보존")

    # ---- V4 저장 라운드트립 ----
    tag = f"v151-{_uuid.uuid4().hex[:6]}"
    async with async_session() as s:
        created = await BL.create_mcp_server(
            McpServerIn(name=f"{tag}-mcp", tools=["a"], enabled_tools=["a"],
                        tools_meta={"a": {"description": "도구 a", "params": []}}),
            session=s, principal=admin)
        check(created.tools_meta == {"a": {"description": "도구 a", "params": []}}, "V4a 생성 시 메타 저장")
        mcp_id = _uuid.UUID(str(created.id))
    try:
        async with async_session() as s:
            updated = await BL.update_mcp_server(
                mcp_id, McpServerIn(name=f"{tag}-mcp", tools=["a"], enabled_tools=["a"]),
                session=s, principal=admin)
            check(updated.tools_meta == {"a": {"description": "도구 a", "params": []}},
                  "V4b 편집 시 tools_meta=None → 기존 보존(미변경)")
    finally:
        async with async_session() as s:
            m = await s.get(McpServer, mcp_id)
            if m is not None:
                await s.delete(m)
            await s.commit()

    # ---- V5 직접 저장 경계(검증기) ----
    from pydantic import ValidationError
    for bad, why in [
        ({f"t{i}": {"description": "", "params": []} for i in range(101)}, "101개"),
        ({"a": {"description": "x" * 501, "params": []}}, "설명 501자"),
        ({"a": {"description": "", "params": [{"name": f"p{i}"} for i in range(31)]}}, "params 31개"),
        ({"a": "문자열"}, "비구조 항목"),
        ({"a": {"description": "", "params": "not-a-list"}}, "params 비리스트"),
    ]:
        try:
            McpServerIn(name="x", tools_meta=bad)
            check(False, f"V5 거부돼야: {why}")
        except ValidationError:
            check(True, f"V5 검증기 거부: {why}")
    ok_in = McpServerIn(name="x", tools_meta={"a": {"description": "d", "params": [{"name": "q", "type": "string", "required": True}]}})
    check(ok_in.tools_meta["a"]["params"][0]["required"] is True, "V5 정상 구조는 정규화 통과")

    # ---- V6 재탐색 참조 가드 — local-tools에 유령 도구를 심고 참조 에이전트 생성 → 409 ----
    from api.models import Agent
    tag6 = f"v151-{_uuid.uuid4().hex[:6]}"
    async with async_session() as s:
        row = (await s.execute(select(McpServer).where(McpServer.name == MOCK_MCP_SERVER_NAME))).scalar_one()
        row_id = row.id
        orig_enabled = list(row.enabled_tools or [])
        row.enabled_tools = orig_enabled + ["ghost-tool"]  # 원격엔 없는 도구(재탐색 시 제거 대상)
        ref_agent = Agent(agent_id=f"{tag6}-ref", name=f"{tag6}-ref",
                          config={"capabilities": [f"mcp:{MOCK_MCP_SERVER_NAME}/ghost-tool"]})
        s.add(ref_agent)
        await s.commit()
        ref_id = ref_agent.id
    try:
        async with async_session() as s:
            try:
                await BL.rediscover_mcp_server(row_id, session=s, principal=admin)
                check(False, "V6a 참조 도구 제거 재탐색 → 409이어야")
            except Exception as e:
                code = getattr(e, "status_code", None)
                check(code == 409, f"V6a 참조 도구 제거 409 (got {code})")
        async with async_session() as s:
            a = await s.get(Agent, ref_id)
            await s.delete(a)
            await s.commit()
        async with async_session() as s:
            out = await BL.rediscover_mcp_server(row_id, session=s, principal=admin)
            check("ghost-tool" not in out.enabled_tools and out.enabled_tools == [t for t in orig_enabled if t in out.tools],
                  "V6b 참조 해제 후 재탐색 통과 + 유령 도구 제거·원상 복원")
    finally:
        async with async_session() as s:
            a = await s.get(Agent, ref_id)
            if a is not None:
                await s.delete(a)
            row = await s.get(McpServer, row_id)
            if row is not None and "ghost-tool" in (row.enabled_tools or []):
                row.enabled_tools = orig_enabled
            await s.commit()

    print(f"\n{passed} passed, {len(_fails)} failed")
    if _fails:
        sys.exit(1)


asyncio.run(main())

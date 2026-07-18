"""verify_326 — MCP 도구 시험 (스펙 326).

  U1 echo 성공: ok=True + result에 입력 반향 + ms>0.
  U2 실패 사유 표면: 임시 서버(failing_op)로 ok=False + error에 타입·사유(스펙 320 경로 재사용).
  U3 미허용 도구 400: enabled_tools 밖 도구는 거부.
  U4 승인 도구 confirm 게이트: delete_record confirm 없이 400(백엔드 강제).
  U5 승인 도구 confirm=True: 실행됨(mock — 부수효과 없음).
  U6 결과 마스킹: 시크릿 패턴을 echo로 반향해도 result에 원문 미노출.
  U7 인자 스키마 오류: 필수 인자 누락 → 500 아닌 ok=False + error(검증 사유).
실행: uv run --project packages/api --env-file .env python tests/verify_326_mcp_tool_test.py
※ local-tools MCP가 자기 서비스(127.0.0.1:8000)라 API 서버가 떠 있어야 한다.
"""

import asyncio
import os
import sys

sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "packages", "api", "src"
    ),
)

from fastapi import HTTPException  # noqa: E402
from sqlalchemy import select  # noqa: E402

from api import blocks as BL  # noqa: E402
from api.db import SessionLocal as async_session  # noqa: E402
from api.mock_mcp import MOCK_MCP_URL  # noqa: E402
from api.models import McpServer  # noqa: E402
from api.schemas import McpToolTestIn  # noqa: E402

_fails = []
passed = 0


def check(cond, msg):
    global passed
    print(("  ok  " if cond else " FAIL ") + msg)
    if cond:
        passed += 1
    else:
        _fails.append(msg)


async def _local_tools_id(s):
    row = (await s.execute(select(McpServer).where(McpServer.name == "local-tools"))).scalar_one()
    return row.id


async def main():
    async with async_session() as s:
        lt_id = await _local_tools_id(s)

        # U1 — echo 성공
        out = await BL.test_mcp_tool(
            lt_id, McpToolTestIn(tool="echo", args={"text": "326-ping"}), s
        )
        check(
            out.ok and "326-ping" in (out.result or "") and out.ms > 0,
            f"U1 echo 성공+반향+ms>0 (ms={out.ms})",
        )

        # U3 — 미허용 도구 400
        try:
            await BL.test_mcp_tool(lt_id, McpToolTestIn(tool="failing_op", args={"reason": "x"}), s)
            check(False, "U3 미허용 도구 400")
        except HTTPException as e:
            check(
                e.status_code == 400 and "활성 도구" in e.detail,
                f"U3 미허용 도구 400 ({e.detail[:40]})",
            )

        # U4 — 승인 도구 confirm 없이 400
        try:
            await BL.test_mcp_tool(
                lt_id, McpToolTestIn(tool="delete_record", args={"record_id": "v326"}), s
            )
            check(False, "U4 승인 confirm 게이트 400")
        except HTTPException as e:
            check(
                e.status_code == 400 and "승인 정책" in e.detail,
                f"U4 승인 confirm 게이트 400 ({e.detail[:40]})",
            )

        # U5 — confirm=True면 실행(mock, 부수효과 없음)
        out = await BL.test_mcp_tool(
            lt_id, McpToolTestIn(tool="delete_record", args={"record_id": "v326"}, confirm=True), s
        )
        check(
            out.ok and out.error is None, f"U5 confirm=True 실행 (result={str(out.result)[:40]!r})"
        )

        # U6 — 결과 마스킹(시크릿 반향)
        secret = "Bearer abcdefghijklmnop1234"
        out = await BL.test_mcp_tool(
            lt_id, McpToolTestIn(tool="echo", args={"text": f"tok={secret}"}), s
        )
        check(
            out.ok and secret not in (out.result or ""),
            f"U6 결과 마스킹 (result={str(out.result)[:60]!r})",
        )

        # U7 — 인자 스키마 오류는 500 아닌 시험 결과
        out = await BL.test_mcp_tool(lt_id, McpToolTestIn(tool="echo", args={}), s)
        check(
            (not out.ok) and bool(out.error), f"U7 인자 오류 표면화 (error={str(out.error)[:60]!r})"
        )

        # U2 — 실패 사유 표면(임시 서버, failing_op만 활성 — seed 오염 없이 hermetic)
        tmp = McpServer(
            name="v326-fail-probe",
            source="external",
            transport="http",
            url=MOCK_MCP_URL,
            tools=["failing_op"],
            enabled_tools=["failing_op"],
            tools_meta={},
            status="connected",
        )
        s.add(tmp)
        await s.commit()
        await s.refresh(tmp)
        try:
            out = await BL.test_mcp_tool(
                tmp.id, McpToolTestIn(tool="failing_op", args={"reason": "의도된 326 실패"}), s
            )
            check(
                (not out.ok) and "의도된 326 실패" in (out.error or ""),
                f"U2 실패 사유 표면 (error={str(out.error)[:80]!r})",
            )
        finally:
            await s.delete(tmp)
            await s.commit()

    print()
    if _fails:
        print(f"FAIL {len(_fails)}건: {_fails}")
        sys.exit(1)
    print(f"VERIFY326_OK — {passed}건 전부 통과")


asyncio.run(main())

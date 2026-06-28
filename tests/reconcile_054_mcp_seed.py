"""스펙 054 P3-G — MCP 시드 양층 정합(라이브 DB). **기본은 dry-run(읽기 전용 리포트)**.

seed.py 소스는 이미 가짜 6행을 self-host 실 mock 1행(local-tools)으로 교체했다. 이 스크립트는
**이미 시드된 라이브 DB**를 같은 상태로 끌어온다(learning 025 — 소스와 라이브 둘 다 고쳐야 드리프트
가 안 생긴다). seed_if_empty는 비어있을 때만 시드하므로 비어있지 않은 라이브 DB는 별도 reconcile 필요.

하는 일(멱등):
  1. McpServer `local-tools`(http, MOCK_MCP_URL, [web_search,echo,delete_record]) upsert.
  2. 가짜 6행(tavily/gcal/gmail/notion/acme-weather/partner-crm) DELETE.
  3. 모든 에이전트 config·version.config의 mcps 참조에서 가짜 이름 → local-tools 재매핑(dedup).
파괴적·비가역(행 삭제 + config JSON 재작성)이므로 먼저 리포트로 검토 후 --apply.

McpServer는 다른 테이블의 FK 대상이 아니다(에이전트는 mcps를 JSON 이름 리스트로만 참조) →
삭제는 연쇄 없음. config 재매핑이 dangling 참조를 없애는 역할.

실행:
  A2A_ALLOWED_HOSTS=127.0.0.1,localhost .venv/bin/python tests/reconcile_054_mcp_seed.py          # dry-run
  A2A_ALLOWED_HOSTS=127.0.0.1,localhost .venv/bin/python tests/reconcile_054_mcp_seed.py --apply   # 실행
"""
import asyncio
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))

from sqlalchemy import delete, select  # noqa: E402
from sqlalchemy.orm import selectinload  # noqa: E402
from sqlalchemy.orm.attributes import flag_modified  # noqa: E402

from api.db import SessionLocal  # noqa: E402
from api.mock_mcp import MOCK_MCP_SERVER_NAME, MOCK_MCP_TOOLS, MOCK_MCP_URL  # noqa: E402
from api.models import Agent, McpServer  # noqa: E402

OLD_MCPS = {"tavily", "gcal", "gmail", "notion", "acme-weather", "partner-crm"}
NEW_NAME = MOCK_MCP_SERVER_NAME  # "local-tools"
NEW_TOOLS = list(MOCK_MCP_TOOLS)  # 시드와 동일 단일 소스(mock_mcp) — 평행 리터럴 드리프트 방지


def _remap(mcps: list) -> list:
    """config mcps 리스트에서 가짜 이름 → local-tools 재매핑(순서 보존·dedup)."""
    out: list[str] = []
    for m in mcps or []:
        repl = NEW_NAME if m in OLD_MCPS else m
        if repl not in out:
            out.append(repl)
    return out


async def _gather(sess) -> dict:
    mcps = (await sess.execute(select(McpServer))).scalars().all()
    agents = (
        await sess.execute(select(Agent).options(selectinload(Agent.versions)))
    ).scalars().all()

    mcp_del = [m for m in mcps if m.name in OLD_MCPS]
    existing_new = next((m for m in mcps if m.name == NEW_NAME), None)

    # config·version.config 재매핑 계획(변경 있는 것만).
    remap_plan = []
    for a in agents:
        before = list((a.config or {}).get("mcps", []))
        after = _remap(before)
        vers = []
        for v in a.versions:
            vb = list((v.config or {}).get("mcps", []))
            va = _remap(vb)
            if vb != va:
                vers.append((v.version, vb, va))
        if before != after or vers:
            remap_plan.append((a, before, after, vers))

    return {
        "mcp_all": mcps, "mcp_del": mcp_del, "existing_new": existing_new,
        "remap_plan": remap_plan,
    }


def _report(plan: dict) -> None:
    print("=" * 68)
    print("스펙 054 MCP 시드 정합 — DRY-RUN 리포트 (변경 없음)")
    print("=" * 68)

    print(f"\n[MCP] 현재 {len(plan['mcp_all'])}행: {sorted(m.name for m in plan['mcp_all'])}")
    print(f"[MCP] 삭제 대상(가짜) {len(plan['mcp_del'])}: {sorted(m.name for m in plan['mcp_del'])}")
    if plan["existing_new"]:
        m = plan["existing_new"]
        print(f"[MCP] '{NEW_NAME}' 이미 존재 → UPDATE (url={m.url}, transport={m.transport}, "
              f"tools={m.enabled_tools})")
    else:
        print(f"[MCP] '{NEW_NAME}' 없음 → CREATE (http, {MOCK_MCP_URL}, {NEW_TOOLS}, published=True)")

    print(f"\n[config 재매핑] {len(plan['remap_plan'])}개 에이전트:")
    for a, before, after, vers in plan["remap_plan"]:
        if before != after:
            print(f"  - {a.agent_id} {a.name!r}: config mcps {before} → {after}")
        for ver, vb, va in vers:
            print(f"      version {ver}: mcps {vb} → {va}")
    if not plan["remap_plan"]:
        print("  (없음 — 이미 정합)")

    print("\n" + "=" * 68)
    print("적용하려면: ... tests/reconcile_054_mcp_seed.py --apply")
    print("=" * 68)


async def _apply(sess, plan: dict) -> None:
    # 1) local-tools upsert.
    m = plan["existing_new"]
    if m is None:
        sess.add(McpServer(
            name=NEW_NAME, source="local", transport="http", url=MOCK_MCP_URL, endpoint=None,
            tools=list(NEW_TOOLS), enabled_tools=list(NEW_TOOLS), status="connected",
            published=True, auth=None,
        ))
    else:
        m.source = "local"
        m.transport = "http"
        m.url = MOCK_MCP_URL
        m.endpoint = None
        m.tools = list(NEW_TOOLS)
        m.enabled_tools = list(NEW_TOOLS)
        m.status = "connected"
        m.published = True
        # auth는 보존(운영자가 토큰을 붙였을 수 있음 — 시드 reconcile이 비밀을 지우지 않는다).

    # 2) config·version.config 재매핑(JSONB 재대입 + flag_modified).
    #    리포트==apply 계약(적대 리뷰 H2): dry-run이 보여준 것만 정확히 건드린다 —
    #    config는 before!=after일 때만, 버전은 plan의 vers(=실제 바뀌는 버전)만 재작성한다.
    for a, before, after, vers in plan["remap_plan"]:
        if before != after:
            cfg = dict(a.config or {})
            cfg["mcps"] = after
            a.config = cfg
            flag_modified(a, "config")
        if vers:
            by_ver = {v.version: v for v in a.versions}
            for ver, _vb, va in vers:
                v = by_ver.get(ver)
                if v is None:
                    continue
                vcfg = dict(v.config or {})
                vcfg["mcps"] = va
                v.config = vcfg
                flag_modified(v, "config")

    # 3) 가짜 행 삭제(FK 연쇄 없음 — 이름 참조는 위에서 재매핑됨).
    if plan["mcp_del"]:
        await sess.execute(delete(McpServer).where(McpServer.name.in_([m.name for m in plan["mcp_del"]])))

    await sess.commit()
    print(f"\n✅ 적용 완료 — 가짜 {len(plan['mcp_del'])}행 삭제, "
          f"'{NEW_NAME}' {'생성' if m is None else '갱신'}, "
          f"에이전트 {len(plan['remap_plan'])}개 재매핑.")


async def main() -> None:
    apply = "--apply" in sys.argv
    async with SessionLocal() as sess:
        plan = await _gather(sess)
        _report(plan)
        if apply:
            await _apply(sess, plan)
        else:
            print("\n(dry-run — 변경하려면 --apply)")


if __name__ == "__main__":
    asyncio.run(main())

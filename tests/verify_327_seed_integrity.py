"""verify_327 — 하드코딩 데모 정리 후 시드 무결 (스펙 327).

  S1 노드형 데모: research-pipeline-demo가 impl=pipeline·노드 2·도구는 런타임명(web-fetch__*).
  S2 구 plan-execute-demo 이름 부재(대체 완료).
  S3 targeting-catalog 시드 부재(reconcile 포함).
  S4 레지스트리: artifact_slotfill·artifact_targeting 미등록, 유지 대상(plan_execute·route·
     orchestrate·orchestrate_ranked·artifact_form·pipeline) 등록.
  S5 reconcile 고아 정리: 레지스트리에 없는 custom 행은 미참조면 삭제·참조 중이면 보존.
실행: uv run python tests/_throwaway_db.py tests/verify_327_seed_integrity.py
      (virgin DB — alembic+seed 후 이 스크립트가 그 DB를 검사)
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
sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "packages", "agent", "src"
    ),
)

from sqlalchemy import select  # noqa: E402

from api.db import SessionLocal as async_session  # noqa: E402
from api.models import Agent, McpServer  # noqa: E402

_fails = []
passed = 0


def check(cond, msg):
    global passed
    print(("  ok  " if cond else " FAIL ") + msg)
    if cond:
        passed += 1
    else:
        _fails.append(msg)


async def main():
    async with async_session() as s:
        # S1 — 노드형 데모
        a = (
            await s.execute(select(Agent).where(Agent.name == "research-pipeline-demo"))
        ).scalar_one_or_none()
        check(a is not None, "S1a research-pipeline-demo 시드됨")
        if a is not None:
            cfg = a.config or {}
            nodes = cfg.get("nodes") or []
            check(cfg.get("impl") == "pipeline", f"S1b impl=pipeline (got {cfg.get('impl')})")
            check(len(nodes) == 2, f"S1c 노드 2개 (got {len(nodes)})")
            all_tools = [t for n in nodes for t in (n.get("tools") or [])]
            check(
                all_tools and all(t.startswith("web-fetch__") for t in all_tools),
                f"S1d 노드 도구 전부 런타임명 (got {all_tools})",
            )
            check(cfg.get("mcps") == ["web-fetch"], f"S1e mcps=[web-fetch] (got {cfg.get('mcps')})")

        # S2 — 구 이름 부재
        old = (
            await s.execute(select(Agent).where(Agent.name == "plan-execute-demo"))
        ).scalar_one_or_none()
        check(old is None, "S2 plan-execute-demo 부재(대체 완료)")

        # S3 — targeting-catalog 부재
        t = (
            await s.execute(select(McpServer).where(McpServer.name == "targeting-catalog"))
        ).scalar_one_or_none()
        check(t is None, "S3 targeting-catalog 시드 부재")

    # S5 — reconcile 고아 정리(스펙 327): 레지스트리 밖 custom 행 삭제 / 참조 중이면 보존
    from api.seed import _reconcile_served_mcp

    async with async_session() as s:
        s.add(
            McpServer(
                name="v327-stale-custom",
                source="custom",
                transport="http",
                url="http://127.0.0.1:8000/_served/mcp/v327-stale-custom/",
                tools=["ghost"],
                enabled_tools=["ghost"],
                status="connected",
            )
        )
        await s.commit()
        await _reconcile_served_mcp(s)
        await s.commit()
        gone = (
            await s.execute(select(McpServer).where(McpServer.name == "v327-stale-custom"))
        ).scalar_one_or_none()
        check(gone is None, "S5a 미참조 stale custom 행 삭제")

        # 참조 중이면 보존 — 에이전트 config.mcps가 배선한 stale custom
        s.add(
            McpServer(
                name="v327-stale-wired",
                source="custom",
                transport="http",
                url="http://127.0.0.1:8000/_served/mcp/v327-stale-wired/",
                tools=["ghost"],
                enabled_tools=["ghost"],
                status="connected",
            )
        )
        ref = (
            await s.execute(select(Agent).where(Agent.name == "research-pipeline-demo"))
        ).scalar_one()
        cfg = dict(ref.config)
        cfg["mcps"] = [*(cfg.get("mcps") or []), "v327-stale-wired"]
        ref.config = cfg
        await s.commit()
        await _reconcile_served_mcp(s)
        await s.commit()
        kept = (
            await s.execute(select(McpServer).where(McpServer.name == "v327-stale-wired"))
        ).scalar_one_or_none()
        check(kept is not None, "S5b 참조 중 stale custom 행 보존")
        # 원복(throwaway DB라 필수는 아니나 스크립트 재사용 대비 정직 정리)
        cfg = dict(ref.config)
        cfg["mcps"] = [m for m in (cfg.get("mcps") or []) if m != "v327-stale-wired"]
        ref.config = cfg
        if kept is not None:
            await s.delete(kept)
        await s.commit()

    # S4 — 레지스트리
    from agent.runtime import list_agent_impls

    keys = set(list_agent_impls())
    check(
        not ({"artifact_slotfill", "artifact_targeting"} & keys),
        f"S4a 데모 impl 미등록 (keys={sorted(keys)})",
    )
    keep = {"plan_execute", "route", "orchestrate", "orchestrate_ranked", "artifact_form", "pipeline"}
    check(keep <= keys, f"S4b 유지 impl 전부 등록 (missing={sorted(keep - keys)})")

    print()
    if _fails:
        print(f"FAIL {len(_fails)}건: {_fails}")
        sys.exit(1)
    print(f"VERIFY327_OK — {passed}건 전부 통과")


asyncio.run(main())

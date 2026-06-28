"""스펙 046 검증 — 빌딩블록 정리 후 참조 무결성(apply 후 실행).

검증(완료 조건):
  I1. 제거 권한 5개가 permissions 테이블에 부재, 유지 3개 존재.
  I2. 제거 MCP 4개가 mcp_servers 테이블에 부재, 유지 6개 존재.
  I3. 제거 에이전트 2개(Code Reviewer·Ops Copilot) 부재, 유지 에이전트 존재.
  I4. dangling 0 — 어떤 agents.config / agent_versions.config 에도 제거 권한/MCP 이름이
      남아있지 않다(soft JSON 참조까지 전수).
  I5. 제거 권한을 참조하는 **pending** 승인 0 (045 배지 불변 — resolved 이력은 050 유예).
  I6. seed_if_empty 멱등 — 재호출이 제거분을 되살리지 않는다(테이블 비어있지 않으므로 무동작).

실행: uv run python tests/verify_046_integrity.py
"""

import asyncio
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))

from sqlalchemy import select  # noqa: E402

from api.db import SessionLocal  # noqa: E402
from api.models import Agent, AgentVersion, Approval, McpServer, Permission  # noqa: E402
from api import seed  # noqa: E402

REMOVED_PERMS = {"files.read", "repo.read", "repo.merge", "k8s.read", "k8s.write"}
REMOVED_MCPS = {"filesystem", "github", "prometheus", "kubernetes"}
KEEP_PERMS = {"web.search", "calendar.rw", "mail.send"}
KEEP_MCPS = {"tavily", "gcal", "gmail", "notion", "acme-weather", "partner-crm"}
REMOVED_AGENT_IDS = {"agt_rvw_2b91c4", "agt_ops_5c0833"}

_fails: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


async def main() -> None:
    async with SessionLocal() as sess:
        perm_names = {p.name for p in (await sess.execute(select(Permission))).scalars()}
        mcp_names = {m.name for m in (await sess.execute(select(McpServer))).scalars()}
        agents = (await sess.execute(select(Agent))).scalars().all()
        agent_ids = {a.agent_id for a in agents}
        versions = (await sess.execute(select(AgentVersion))).scalars().all()

        # I1
        check(not (REMOVED_PERMS & perm_names), f"I1 제거 권한 부재 (잔존: {REMOVED_PERMS & perm_names})")
        check(KEEP_PERMS <= perm_names, f"I1 유지 권한 3개 존재 (현재: {sorted(perm_names)})")

        # I2
        check(not (REMOVED_MCPS & mcp_names), f"I2 제거 MCP 부재 (잔존: {REMOVED_MCPS & mcp_names})")
        check(KEEP_MCPS <= mcp_names, f"I2 유지 MCP 6개 존재 (현재: {sorted(mcp_names)})")

        # I3
        check(not (REMOVED_AGENT_IDS & agent_ids), f"I3 제거 에이전트 부재 (잔존: {REMOVED_AGENT_IDS & agent_ids})")
        check("agt_rsch_7f3a91" in agent_ids and "agt_sec_9d4417" in agent_ids,
              "I3 유지 에이전트(Research·Secretary) 존재")

        # I4 — dangling: config + version.config 전수
        dangling = []
        for a in agents:
            cfg = a.config or {}
            bad_p = REMOVED_PERMS & set(cfg.get("permissions", []))
            bad_m = REMOVED_MCPS & set(cfg.get("mcps", []))
            if bad_p or bad_m:
                dangling.append(f"agent {a.agent_id} perms{bad_p} mcps{bad_m}")
        for v in versions:
            cfg = v.config or {}
            bad_p = REMOVED_PERMS & set(cfg.get("permissions", []))
            bad_m = REMOVED_MCPS & set(cfg.get("mcps", []))
            if bad_p or bad_m:
                dangling.append(f"version {v.id} perms{bad_p} mcps{bad_m}")
        check(not dangling, f"I4 dangling 0 (발견: {dangling[:5]})")

        # I5 — pending 승인 중 제거 권한 참조 0 (resolved 이력은 050 유예)
        pending_bad = (await sess.execute(
            select(Approval).where(Approval.permission.in_(REMOVED_PERMS),
                                   Approval.status == "pending")
        )).scalars().all()
        check(not pending_bad, f"I5 제거권한 pending 승인 0 (발견: {[a.approval_id for a in pending_bad]})")

        # I6 — seed 멱등(재호출 무동작): 테이블 비어있지 않으므로 _empty=False
        await seed.seed_if_empty(sess)
        perm_after = {p.name for p in (await sess.execute(select(Permission))).scalars()}
        mcp_after = {m.name for m in (await sess.execute(select(McpServer))).scalars()}
        check(not (REMOVED_PERMS & perm_after) and not (REMOVED_MCPS & mcp_after),
              "I6 seed_if_empty 재호출이 제거분을 되살리지 않음(멱등)")

    print()
    if _fails:
        print(f"검증 실패 {len(_fails)}건:")
        for f in _fails:
            print(f"  - {f}")
        sys.exit(1)
    print("스펙 046 무결성 검증 — 전부 통과.")


if __name__ == "__main__":
    asyncio.run(main())

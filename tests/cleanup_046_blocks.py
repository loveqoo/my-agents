"""스펙 046 — 빌딩블록 재료 정리(라이브 DB). **기본은 dry-run(읽기 전용 리포트)**.

코드/인프라 권한·MCP를 카탈로그(permissions·mcp_servers 테이블)에서 지우고, 그 권한 전용
데모 에이전트(Code Reviewer·Ops Copilot)를 삭제하며, 유지 에이전트 config(+version.config)의
dangling 이름 참조를 strip한다. 파괴적·비가역이므로 먼저 리포트로 검토 후 --apply.

연쇄(models.py FK, DB DDL):
  agent_versions.agent_pk → CASCADE (버전 자동 삭제)
  sessions.agent_pk       → CASCADE (세션 + messages 자동 삭제)
  approvals.agent_pk      → SET NULL (승인 행 보존, agent_pk만 NULL)
에이전트 삭제는 core delete로 DB FK가 위 연쇄를 처리한다(ORM relationship 로드 불필요).

실행:
  uv run python tests/cleanup_046_blocks.py            # dry-run 리포트(기본)
  uv run python tests/cleanup_046_blocks.py --apply    # 트랜잭션 실행
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
from api.models import Agent, Approval, McpServer, Permission, Session  # noqa: E402

# 스펙 046 명세 — 제거 대상(측정 가능).
REMOVED_PERMS = {"files.read", "repo.read", "repo.merge", "k8s.read", "k8s.write"}
REMOVED_MCPS = {"filesystem", "github", "prometheus", "kubernetes"}
REMOVED_AGENT_IDS = {"agt_rvw_2b91c4", "agt_ops_5c0833"}  # Code Reviewer, Ops Copilot
KEEP_PERMS = {"web.search", "calendar.rw", "mail.send"}
KEEP_MCPS = {"tavily", "gcal", "gmail", "notion", "acme-weather", "partner-crm"}


def _strip(names: list, removed: set) -> list:
    return [n for n in (names or []) if n not in removed]


def _cfg_dangling(cfg: dict) -> tuple[list, list]:
    """config dict에서 제거 권한/MCP 참조를 골라낸다(리포트용)."""
    perms = [p for p in (cfg or {}).get("permissions", []) if p in REMOVED_PERMS]
    mcps = [m for m in (cfg or {}).get("mcps", []) if m in REMOVED_MCPS]
    return perms, mcps


async def _gather(sess):
    """현 상태를 읽어 계획을 만든다(리포트·apply 공용)."""
    perms = (await sess.execute(select(Permission))).scalars().all()
    mcps = (await sess.execute(select(McpServer))).scalars().all()
    agents = (
        await sess.execute(select(Agent).options(selectinload(Agent.versions)))
    ).scalars().all()

    perm_del = [p for p in perms if p.name in REMOVED_PERMS]
    mcp_del = [m for m in mcps if m.name in REMOVED_MCPS]
    agent_del = [a for a in agents if a.agent_id in REMOVED_AGENT_IDS]
    keep_agents = [a for a in agents if a.agent_id not in REMOVED_AGENT_IDS]

    # 유지 에이전트 중 dangling 참조를 가진 것(config + 각 version.config).
    strip_plan = []
    for a in keep_agents:
        ap, am = _cfg_dangling(a.config)
        vers = []
        for v in a.versions:
            vp, vm = _cfg_dangling(v.config)
            if vp or vm:
                vers.append((v.version, vp, vm))
        if ap or am or vers:
            strip_plan.append((a, ap, am, vers))

    # 삭제 에이전트에 묶인 세션/승인(연쇄 가시화).
    del_pks = [a.id for a in agent_del]
    sess_cascade, appr_setnull = [], []
    if del_pks:
        sess_cascade = (
            await sess.execute(select(Session).where(Session.agent_pk.in_(del_pks)))
        ).scalars().all()
        appr_setnull = (
            await sess.execute(select(Approval).where(Approval.agent_pk.in_(del_pks)))
        ).scalars().all()

    # 라이브 승인 중 제거 권한 참조(정리는 050로 유예 — 인지용 리포트).
    appr_perm = (
        await sess.execute(select(Approval).where(Approval.permission.in_(REMOVED_PERMS)))
    ).scalars().all()

    return {
        "perm_del": perm_del, "mcp_del": mcp_del, "agent_del": agent_del,
        "keep_agents": keep_agents, "strip_plan": strip_plan,
        "sess_cascade": sess_cascade, "appr_setnull": appr_setnull,
        "appr_perm": appr_perm,
        "perm_all": perms, "mcp_all": mcps,
    }


def _report(plan: dict) -> None:
    print("=" * 68)
    print("스펙 046 빌딩블록 정리 — DRY-RUN 리포트 (변경 없음)")
    print("=" * 68)

    print(f"\n[권한] 삭제 대상 {len(plan['perm_del'])}/5:")
    for p in sorted(plan["perm_del"], key=lambda x: x.name):
        print(f"  - DELETE  {p.name:14s} ({p.scope}/{p.approver})")
    remaining = sorted(p.name for p in plan["perm_all"] if p.name not in REMOVED_PERMS)
    print(f"  유지 후보({len(remaining)}): {remaining}")

    print(f"\n[MCP] 삭제 대상 {len(plan['mcp_del'])}/4:")
    for m in sorted(plan["mcp_del"], key=lambda x: x.name):
        print(f"  - DELETE  {m.name:14s} ({m.transport}, {m.status})")
    remaining_m = sorted(m.name for m in plan["mcp_all"] if m.name not in REMOVED_MCPS)
    print(f"  유지 후보({len(remaining_m)}): {remaining_m}")

    print(f"\n[에이전트] 삭제 대상 {len(plan['agent_del'])}/2:")
    for a in plan["agent_del"]:
        print(f"  - DELETE  {a.agent_id}  {a.name!r}  (versions={len(a.versions)})")
    print(f"  연쇄: 세션 {len(plan['sess_cascade'])}개 CASCADE 삭제 "
          f"→ {[s.session_id for s in plan['sess_cascade']]}")
    print(f"        승인 {len(plan['appr_setnull'])}개 agent_pk=SET NULL "
          f"→ {[a.approval_id for a in plan['appr_setnull']]}")

    print(f"\n[유지 에이전트 dangling strip] {len(plan['strip_plan'])}개:")
    for a, ap, am, vers in plan["strip_plan"]:
        print(f"  - {a.agent_id} {a.name!r}: config perms-{ap} mcps-{am}")
        for ver, vp, vm in vers:
            print(f"      version {ver}: perms-{vp} mcps-{vm}")
    if not plan["strip_plan"]:
        print("  (없음 — 유지 에이전트가 제거 재료를 참조하지 않음)")

    pending_bad = [a for a in plan["appr_perm"] if a.status == "pending"]
    print(f"\n[참고/050 유예] 제거 권한을 참조하는 라이브 승인 {len(plan['appr_perm'])}개 "
          f"(pending {len(pending_bad)}개):")
    for a in plan["appr_perm"]:
        flag = "  ⚠ PENDING(045 배지 영향!)" if a.status == "pending" else ""
        print(f"  ! {a.approval_id} perm={a.permission} status={a.status}{flag} "
              f"(046은 건드리지 않음 — 050 데이터 정리)")
    if pending_bad:
        print("  ⚠ 경고: pending 승인이 제거 권한을 참조 — 045 pending 배지/큐에 노출됨. "
              "050에서 정리하거나 본 작업 전 확인 필요.")

    print("\n" + "=" * 68)
    print("적용하려면: uv run python tests/cleanup_046_blocks.py --apply")
    print("=" * 68)


async def _apply(sess, plan: dict) -> None:
    # 1) 유지 에이전트 config·version.config strip (JSONB 재대입 + flag_modified).
    for a, _ap, _am, _vers in plan["strip_plan"]:
        cfg = dict(a.config or {})
        cfg["permissions"] = _strip(cfg.get("permissions"), REMOVED_PERMS)
        cfg["mcps"] = _strip(cfg.get("mcps"), REMOVED_MCPS)
        a.config = cfg
        flag_modified(a, "config")
        for v in a.versions:
            vcfg = dict(v.config or {})
            vcfg["permissions"] = _strip(vcfg.get("permissions"), REMOVED_PERMS)
            vcfg["mcps"] = _strip(vcfg.get("mcps"), REMOVED_MCPS)
            v.config = vcfg
            flag_modified(v, "config")

    # 2) 데모 에이전트 삭제 — core delete, DB FK가 versions/sessions/messages CASCADE,
    #    approvals SET NULL 처리.
    if plan["agent_del"]:
        await sess.execute(
            delete(Agent).where(Agent.agent_id.in_(REMOVED_AGENT_IDS))
        )

    # 3) 권한·MCP 카탈로그 행 삭제.
    if plan["perm_del"]:
        await sess.execute(delete(Permission).where(Permission.name.in_(REMOVED_PERMS)))
    if plan["mcp_del"]:
        await sess.execute(delete(McpServer).where(McpServer.name.in_(REMOVED_MCPS)))

    await sess.commit()
    print("APPLIED — 트랜잭션 커밋 완료. verify_046_integrity로 검증하세요.")


async def main() -> None:
    apply = "--apply" in sys.argv
    async with SessionLocal() as sess:
        plan = await _gather(sess)
        _report(plan)
        if apply:
            print("\n>>> --apply 지정됨: 실행합니다...\n")
            await _apply(sess, plan)
        else:
            print("\n(dry-run: 아무 것도 바꾸지 않았습니다.)")


if __name__ == "__main__":
    asyncio.run(main())

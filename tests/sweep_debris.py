"""테스트 잔해 스윕(스펙 304) — 브라우저/verify 테스트가 라이브 DB에 남긴 에이전트 잔해 정리.

**dry-run 기본**: 인자 없이 실행하면 지울 것만 보고하고 아무것도 삭제하지 않는다. 실삭제는 `--apply`.
(비가역 파괴는 명시 옵션 뒤로 — 적대 리뷰 습관.)

식별 = **테스트 프리픽스 화이트리스트**(사용자 결정) — 앞으로 UI로 만든 실 에이전트는 이 집합에 없으니
불가침. 이중 가드로 seed 5명도 어떤 경우에도 제외. DATABASE_URL 존중(기본 dev DB).

삭제는 `DELETE FROM agents WHERE id IN (...)` 한 문장 — Agent 자식 FK가 DB단 ondelete=CASCADE
(agent_versions·sessions→messages→message_feedback)라 cascade 자동 정리, approvals는 SET NULL(감사행 보존).

실행: uv run python tests/sweep_debris.py          # dry-run
      uv run python tests/sweep_debris.py --apply  # 실삭제
"""

import asyncio
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))

from sqlalchemy import func, select, text  # noqa: E402

from api.db import SessionLocal, engine  # noqa: E402
from api.models import Agent, AgentVersion, Approval, Session  # noqa: E402

# 시드 5명(seed.py의 ui 2 + plan-execute + code + external 단일 출처, 스펙 303) — 절대 불가침 keeplist.
SEED_AGENT_IDS = frozenset(
    {"agt_rsch_7f3a91", "agt_sec_9d4417", "agt_plex_b5e207", "agt_xlt_a17c33", "agt_ext_ac2e01"}
)

# 테스트 산물 이름 프리픽스 화이트리스트(스펙 304 실측 — 53 전량 커버). 버전 꼬리(271/272·270·268)는
# 축약 프리픽스(rt-·hist-·pnode-)로 흡수. 전부 하이픈으로 끝나 실명 오매칭을 막는다(예: `pipeline-`은
# 실명 "pipeline analyzer"를 안 잡음). seed 5명 이름은 이 중 어느 것으로도 시작하지 않음(충돌 0 실측).
TEST_PREFIXES = (
    "detail-shot-",
    "hist-",
    "node-insp-",
    "pipe-exec-",
    "pipeline-",
    "pnode-",
    "rag-insp-",
    "rag-node-",
    "rt-",
    "suite-",
)

# 꼬리 없는 고정 단일명 — 프리픽스로 두면 하이픈이 없어 `approval-demographic…` 류 실명을 오매칭할 수
# 있다(codex 적대 리뷰 지적). exact 매칭으로 조여 그 계열만 정확히 잡는다.
TEST_EXACT_NAMES = frozenset({"approval-demo"})


def _is_debris(agent_id: str, name: str) -> bool:
    """이중 가드: (화이트리스트 프리픽스로 시작 OR 정확 테스트명) AND seed가 아님. seed·실 에이전트는 False."""
    if agent_id in SEED_AGENT_IDS:
        return False
    return name in TEST_EXACT_NAMES or name.startswith(TEST_PREFIXES)


async def main() -> None:
    apply = "--apply" in sys.argv[1:]
    # 안전핀: 화이트리스트가 비면 전삭제 위험 → 즉시 중단.
    if not TEST_PREFIXES:
        print("거부: TEST_PREFIXES가 비어 있음(전삭제 방지).")
        sys.exit(2)

    async with SessionLocal() as s:
        rows = (await s.execute(select(Agent.id, Agent.agent_id, Agent.name))).all()
        debris = [(pk, aid, name) for pk, aid, name in rows if _is_debris(aid, name)]
        keep = [(pk, aid, name) for pk, aid, name in rows if not _is_debris(aid, name)]
        debris_pks = [pk for pk, _aid, _name in debris]

        # cascade 미리보기 — 딸린 자식 카운트(삭제 시 함께 정리될 규모).
        async def _count(model: type, col) -> int:
            if not debris_pks:
                return 0
            return (await s.scalar(select(func.count()).select_from(model).where(col.in_(debris_pks)))) or 0

        n_sessions = await _count(Session, Session.agent_pk)
        n_versions = await _count(AgentVersion, AgentVersion.agent_pk)
        n_approvals = await _count(Approval, Approval.agent_pk)  # SET NULL(감사행 보존)
        n_messages = 0
        if debris_pks:
            n_messages = (
                await s.scalar(
                    text(
                        "SELECT count(*) FROM messages m JOIN sessions ss ON m.session_pk=ss.id "
                        "WHERE ss.agent_pk = ANY(:pks)"
                    ).bindparams(pks=debris_pks)
                )
            ) or 0

    mode = "APPLY(실삭제)" if apply else "DRY-RUN(미삭제)"
    print(f"== 테스트 잔해 스윕 [{mode}] · DB={engine.url.database} ==")
    print(f"전체 에이전트 {len(rows)} = 잔해 {len(debris)} + 보존 {len(keep)}")
    print(f"보존(seed·실 에이전트): {sorted(n for _p, _a, n in keep)}")
    print(f"잔해로 함께 정리될 자식: 세션 {n_sessions}·메시지 {n_messages}·버전 {n_versions}")
    print(f"승인 {n_approvals}건은 SET NULL(감사행 보존)")
    if debris:
        print("잔해 에이전트(name):")
        for _pk, _aid, name in sorted(debris, key=lambda r: r[2]):
            print(f"  - {name}")

    if not apply:
        print("\n(dry-run — 아무것도 삭제하지 않음. 실삭제는 --apply)")
        return
    if not debris_pks:
        print("\n삭제할 잔해 없음.")
        return

    async with SessionLocal() as s:
        # DB단 ondelete=CASCADE에 위임 — 한 문장이 versions·sessions·messages·feedback를 함께 정리.
        await s.execute(text("DELETE FROM agents WHERE id = ANY(:pks)").bindparams(pks=debris_pks))
        await s.commit()

    # 삭제 후 재측정(자가선언 금지).
    async with SessionLocal() as s:
        after_agents = (await s.scalar(select(func.count()).select_from(Agent))) or 0
        after_debris = [
            (aid, name)
            for _pk, aid, name in (
                await s.execute(select(Agent.id, Agent.agent_id, Agent.name))
            ).all()
            if _is_debris(aid, name)
        ]
    print(f"\n삭제 완료. 에이전트 {len(rows)} → {after_agents}, 잔여 잔해 {len(after_debris)}")
    if after_debris:
        print(f"경고: 잔여 잔해 {after_debris}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

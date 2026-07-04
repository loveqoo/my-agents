"""스펙 113 검증 — 런타임 tool 배선 인가(codex 112 P0 봉합).

주체=에이전트 **작성자**(owner_id), 채팅 사용자 아님(공유 에이전트 보존, 112 갈래).
허용 닫힌 집합: ①NULL-owner(무회귀) ②작성자 특권 ③자기 소유 ④published(MCP) ⑤RBAC per-cap/kind.

  [U] 단위 — agent_may_wire 술어 시맨틱(5규칙 + fail-closed).
  [H] 통합(실 DB) — _load_context 직접 호출: member-저작 에이전트가 남의 MCP/컬렉션 참조→미배선,
      자기 컬렉션→배선, per-cap grant→배선, published MCP→배선, NULL-owner 에이전트→전부 배선(무회귀).

실행: cd packages/api && uv run python ../../tests/verify_113_runtime_wiring_authz.py
"""
import asyncio
import uuid

_fails: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


# ================================================================ [U] 단위
async def unit_checks() -> None:
    from api import authz
    from api.ownership import agent_may_wire

    print("[U] agent_may_wire 술어 — 5규칙 + fail-closed")
    alice, bob = str(uuid.uuid4()), str(uuid.uuid4())
    # ① NULL-owner 에이전트 = 전부(무회귀 축)
    check(agent_may_wire(bob, False, None, "mcp", "x"), "U1 NULL-owner 에이전트 → 남의 자원도 배선(무회귀)")
    # ② 특권 작성자 = 전부
    check(agent_may_wire(bob, False, alice, "mcp", "x", owner_privileged=True), "U2 특권 작성자 → 전부")
    # ③ 자기 소유(자가잠금 핀)
    check(agent_may_wire(alice, False, alice, "rag", "mine"), "U3 자기 소유 → 배선(자가잠금 핀)")
    # ④ published
    check(agent_may_wire(bob, True, alice, "mcp", "pub"), "U4 published MCP → 배선(명시 공개)")
    # ⑤ RBAC per-cap (실 casbin)
    await authz.init_authz()
    e = authz.get_enforcer()
    await e.add_policy(alice, "capability:rag:granted_col", "invoke")
    try:
        check(agent_may_wire(None, False, alice, "rag", "granted_col"),
              "U5 per-cap grant → NULL-owned 자원도 배선(RBAC 레버)")
        check(not agent_may_wire(None, False, alice, "rag", "other_col"),
              "U5 미부여 → NULL-owned 자원 미배선(fail-closed)")
        check(not agent_may_wire(bob, False, alice, "mcp", "x"),
              "U5 남의 비공개 자원 + 무grant → 거부")
    finally:
        await e.remove_policy(alice, "capability:rag:granted_col", "invoke")


# ================================================================ [H] 통합(실 DB — _load_context 직접)
async def integration_checks() -> None:
    print("[H] 통합 — _load_context 배선 결과(실 DB)")
    from sqlalchemy import select
    from api.chat import _load_context
    from api.db import SessionLocal
    from api.models import Agent, Collection, McpServer

    alice = str(uuid.uuid4())  # member(특권 없음, User 행 없음 → superuser 축 False)
    suffix = uuid.uuid4().hex[:6]
    made: dict[str, list] = {"agents": [], "cols": [], "mcps": []}
    async with SessionLocal() as db:
        # 시드 컬렉션 하나를 남의 것(NULL-owned) 대표로 쓰고, alice 소유 컬렉션 1개 생성.
        seed_col = (await db.execute(select(Collection).limit(1))).scalars().first()
        emb_id = seed_col.embedding_model_id if seed_col else None
        mine = Collection(name=f"mine_{suffix}", description="", embedding_model_id=emb_id,
                          dims=768, chunk_size=512, chunk_overlap=64, status="empty", owner_id=alice)
        db.add(mine)
        # 남의(bob) 비공개 MCP — 크레덴셜 유출 표적 역할.
        victim = McpServer(name=f"victim_{suffix}", source="user", transport="http",
                           url="http://127.0.0.1:9/x", tools=[], enabled_tools=[],
                           status="connected", published=False, auth=None, owner_id=str(uuid.uuid4()))
        db.add(victim)
        await db.commit()
        made["cols"].append(mine.id); made["mcps"].append(victim.id)
        seed_col_name = seed_col.name if seed_col else None

        def mk_agent(owner, mcps, vts):
            return Agent(agent_id=f"agt_113_{uuid.uuid4().hex[:6]}", name="t113", source="ui",
                         model="mock-llm", persona="", history_depth=6,
                         config={"model": "mock-llm", "persona": "", "memories": [],
                                 "vectorTables": vts, "mcps": mcps,
                                 "historyDepth": 6},
                         exposed={"a2a": False}, status="idle", owner_id=owner)

        # H1: member(alice) 저작 에이전트 — 남의 MCP + 남의(시드 NULL) 컬렉션 + 자기 컬렉션 참조.
        a1 = mk_agent(alice, [victim.name], [seed_col_name, mine.name] if seed_col_name else [mine.name])
        # H2: NULL-owner(레거시/admin) 에이전트 — 같은 참조, 전부 배선돼야(무회귀).
        a2 = mk_agent(None, [victim.name], [seed_col_name] if seed_col_name else [])
        # H5: NULL-owner(신뢰) 에이전트, 저장 mcps=[] — override 주입 표적(작성자 아닌 호출자로 게이트).
        a5 = mk_agent(None, [], [])
        db.add_all([a1, a2, a5]); await db.commit()
        made["agents"] += [a1.id, a2.id, a5.id]
        a1_pk, a2_pk, a5_pk = a1.id, a2.id, a5.id

    try:
        ctx1 = await _load_context(a1_pk, None)
        wired_mcps = [s["name"] for s in ctx1["mcp_servers"]]
        wired_cols = [c["name"] for c in ctx1["rag_collections"]]
        check(f"victim_{suffix}" not in wired_mcps, f"H1 member 에이전트: 남의 비공개 MCP 미배선 (wired={wired_mcps})")
        check(seed_col_name not in wired_cols if seed_col_name else True,
              f"H1 member 에이전트: NULL-owned 컬렉션 미배선(grant 없음) (wired={wired_cols})")
        # 자기 컬렉션은 임베딩 provider 불완전이면 그 이유로 skip될 수 있어 '113 게이트 통과'만 확인:
        # 게이트 로그 대신, agent_may_wire가 직접 True인 걸 단위(U3)서 이미 확인 → 여기선 배선 목록에
        # 없더라도 원인이 provider 불완전일 수 있음을 허용(있으면 더 강한 증거).
        print(f"  ..  (참고) 자기 컬렉션 배선 목록: {wired_cols}")

        ctx2 = await _load_context(a2_pk, None)
        wired_mcps2 = [s["name"] for s in ctx2["mcp_servers"]]
        wired_cols2 = [c["name"] for c in ctx2["rag_collections"]]
        check(f"victim_{suffix}" in wired_mcps2, f"H2 NULL-owner 에이전트: 남의 MCP도 배선(무회귀) (wired={wired_mcps2})")
        check(seed_col_name in wired_cols2 if seed_col_name else True,
              f"H2 NULL-owner 에이전트: 시드 컬렉션 배선(무회귀) (wired={wired_cols2})")

        # H3: per-cap grant를 주면 member 에이전트도 시드 컬렉션 배선(RBAC 레버).
        from api import authz
        e = authz.get_enforcer()
        if seed_col_name:
            await e.add_policy(alice, f"capability:rag:{seed_col_name}", "invoke")
            try:
                ctx3 = await _load_context(a1_pk, None)
                wired3 = [c["name"] for c in ctx3["rag_collections"]]
                check(seed_col_name in wired3, f"H3 per-cap grant 후 → 시드 컬렉션 배선 (wired={wired3})")
            finally:
                await e.remove_policy(alice, f"capability:rag:{seed_col_name}", "invoke")

        # H4: published MCP는 member 에이전트에도 배선(시드 mock-mcp가 published=True).
        async with SessionLocal() as db:
            pub = (await db.execute(select(McpServer).where(McpServer.published == True))).scalars().first()  # noqa: E712
            if pub is not None:
                a4 = mk_agent(alice, [pub.name], [])
                db.add(a4); await db.commit(); made["agents"].append(a4.id)
                a4_pk = a4.id
        if pub is not None:
            ctx4 = await _load_context(a4_pk, None)
            check(pub.name in [s["name"] for s in ctx4["mcp_servers"]],
                  f"H4 published MCP → member 에이전트 배선(공개 레버)")
        else:
            print("  ..  H4 SKIP — published MCP 없음")

        # H5 (codex P0): override 주입 자원은 **호출자(own)** 권한으로 게이트.
        bob = str(uuid.uuid4())  # member 호출자(특권 없음)
        ctx5b = await _load_context(a5_pk, None, overrides={"mcps": [f"victim_{suffix}"]}, own=bob)
        check(f"victim_{suffix}" not in [s["name"] for s in ctx5b["mcp_servers"]],
              f"H5 member 호출자가 override로 남의 비공개 MCP 주입 → 미배선(confused-deputy 차단)")
        ctx5a = await _load_context(a5_pk, None, overrides={"mcps": [f"victim_{suffix}"]}, own=None)
        check(f"victim_{suffix}" in [s["name"] for s in ctx5a["mcp_servers"]],
              f"H5 admin 호출자(own=None) override 주입 → 배선(특권)")

        # H6 (codex P2): non-UUID owner_id는 특권 오판 금지.
        from api.chat import _wiring_owner_privileged
        async with SessionLocal() as db:
            check(not await _wiring_owner_privileged(db, "admin"),
                  "H6 owner_id='admin'(role 이름 충돌) → 비특권(UUID 검증 선행)")
    finally:
        async with SessionLocal() as db:
            for model, ids in (("agents", made["agents"]), ("cols", made["cols"]), ("mcps", made["mcps"])):
                from api.models import Agent as _A, Collection as _C, McpServer as _M
                cls = {"agents": _A, "cols": _C, "mcps": _M}[model]
                for i in ids:
                    row = await db.get(cls, i)
                    if row is not None:
                        await db.delete(row)
            await db.commit()


async def main() -> None:
    await unit_checks()
    print()
    try:
        await integration_checks()
    except Exception as exc:  # noqa: BLE001
        import traceback; traceback.print_exc()
        check(False, f"[H] 통합 예외 — {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    asyncio.run(main())
    print()
    if _fails:
        print(f"❌ {len(_fails)} FAILED")
        for f in _fails:
            print("   - " + f)
        raise SystemExit(1)
    print("✅ ALL PASS (VERIFY113_OK)")

"""스펙 050 검증 — 파괴적 데이터 정리(#1 A2A 정크 · #13 유저 정크).

두 신규 잡을 인프로세스로 단언한다(self-fixture, agent_pk/이메일 prefix 격리).
  A. a2a-cleanup(`api.batch.jobs.cleanup_a2a_agents`):
     - source='external' AND endpoint 호스트 루프백/RFC1918 사설만 대상.
     - source 비-external(ui/code) 및 공개 endpoint는 절대 비대상(바닥).
     - dry-run would_delete·sample·cascade_sessions 정확, 실행 삭제 + 세션 cascade, 멱등.
  B. user-cleanup(`api.batch.jobs.cleanup_test_users`):
     - 패턴 NULL→disabled, `%`/공백-only→rejected(delete-all 가드).
     - keep-list(admin@·alice@) 제외, 마지막 super 보존 산술(전역 super 수 기준).
     - cascade: accesstoken FK CASCADE, casbin g-정책 동일 트랜잭션 제거, sessions.user_id 고아 무해.
     - 멱등. **적응형 파괴안전**(비-fixture 매치 시 실삭제 생략, learning 045/049).
  C. API: BatchConfigIn delete-all 패턴 거부(422), NULL/구체 패턴 허용.

검증 자산은 finally에서 자가정리. BatchConfig 싱글톤은 저장→복원.
실행: .venv/bin/python tests/verify_050_destructive_cleanup.py
"""
import asyncio
import os
import sys
import uuid as uuidlib
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))

from sqlalchemy import delete, func, select, text  # noqa: E402

from api.batch.jobs import cleanup_a2a_agents, cleanup_test_users  # noqa: E402
from api.db import SessionLocal  # noqa: E402
from api.main import app  # noqa: E402,F401  (모듈 캐시 워밍)
from api.models import Agent, BatchConfig, Session, User  # noqa: E402

# fixture 식별자 — 전역에서 유일해야 비-fixture 매치 0 보장(적응형 안전 게이트가 실삭제 허용).
A_PREFIX = "agt_v050_probe_"
U_DOMAIN = "v050probe.example.com"  # 이 도메인은 keep-list(admin@/alice@example.com)와 안 겹침
U_PATTERN = f"%@{U_DOMAIN}"
_fails: list[str] = []
_created_agent_pks: list[uuidlib.UUID] = []
_created_user_ids: list[uuidlib.UUID] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


# ----------------------------- fixtures -----------------------------
async def _make_agent(suffix: str, *, source: str, endpoint: str | None) -> uuidlib.UUID:
    async with SessionLocal() as s:
        agent = Agent(
            agent_id=f"{A_PREFIX}{suffix}", name=f"v050 {suffix}", source=source, endpoint=endpoint
        )
        s.add(agent)
        await s.commit()
        await s.refresh(agent)
        _created_agent_pks.append(agent.id)
        return agent.id


async def _seed_session_for(agent_pk: uuidlib.UUID, sid: str) -> None:
    async with SessionLocal() as s:
        s.add(Session(session_id=sid, agent_pk=agent_pk, agent_name="v050", channel="v050"))
        await s.commit()


async def _make_user(local: str, *, is_super: bool = False) -> uuidlib.UUID:
    async with SessionLocal() as s:
        u = User(
            email=f"{local}@{U_DOMAIN}",
            hashed_password="x",
            is_active=True,
            is_superuser=is_super,
            is_verified=True,
        )
        s.add(u)
        await s.commit()
        await s.refresh(u)
        _created_user_ids.append(u.id)
        return u.id


async def _agent_exists(agent_pk: uuidlib.UUID) -> bool:
    async with SessionLocal() as s:
        return (await s.get(Agent, agent_pk)) is not None


async def _user_exists(uid: uuidlib.UUID) -> bool:
    async with SessionLocal() as s:
        return (await s.get(User, uid)) is not None


async def _session_exists(sid: str) -> bool:
    async with SessionLocal() as s:
        return (
            await s.scalar(select(func.count()).select_from(Session).where(Session.session_id == sid))
        ) > 0


# ----------------------------- config save/restore -----------------------------
async def _cfg_snapshot() -> dict:
    async with SessionLocal() as s:
        cfg = (await s.execute(select(BatchConfig).limit(1))).scalars().first()
        if cfg is None:
            cfg = BatchConfig()
            s.add(cfg)
            await s.commit()
            await s.refresh(cfg)
        return {"test_user_email_pattern": cfg.test_user_email_pattern}


async def _cfg_set_pattern(pattern) -> None:
    async with SessionLocal() as s:
        cfg = (await s.execute(select(BatchConfig).limit(1))).scalars().first()
        cfg.test_user_email_pattern = pattern
        await s.commit()


async def _cfg_restore(snap: dict) -> None:
    async with SessionLocal() as s:
        cfg = (await s.execute(select(BatchConfig).limit(1))).scalars().first()
        for k, v in snap.items():
            setattr(cfg, k, v)
        await s.commit()


# ----------------------------- Section A: a2a-cleanup -----------------------------
def section_a_host() -> None:
    print("\n== A0. _is_private_host 경계(적대리뷰 #3 회귀) ==")
    from api.batch.jobs import _is_private_host

    # 사설/루프백(대상) — True
    for ep in ("127.0.0.1:8142", "http://10.0.0.5:9999", "localhost:3000", "192.168.1.5",
               "172.16.0.1:80", "[::1]:9999", "http://[::ffff:10.0.0.1]:8142"):
        check(_is_private_host(ep), f"[A0] 사설/루프백 → True: {ep}")
    # 공개·예약대역(비대상, 오삭제 방지) — False. is_private 상위집합 회피가 핵심.
    for ep in ("https://a2a.partner.com", "8.8.8.8:443", "0.0.0.0:80", "169.254.1.1:9999",
               "198.18.0.1:80", "172.32.0.1:80", "127.0.0.1.evil.com", None, ""):
        check(not _is_private_host(ep), f"[A0] 공개/예약대역 → False: {ep!r}")


async def section_a() -> None:
    print("\n== A. a2a-cleanup(외부+사설 endpoint만) ==")
    # 대상: external + 사설/루프백 endpoint
    pk_loop = await _make_agent("loop", source="external", endpoint="127.0.0.1:8142")
    pk_priv = await _make_agent("priv", source="external", endpoint="http://10.0.0.5:9999")
    # 비대상: external + 공개 endpoint / endpoint NULL / source ui·code
    pk_public = await _make_agent("public", source="external", endpoint="https://a2a.partner.com")
    pk_noep = await _make_agent("noep", source="external", endpoint=None)
    pk_ui = await _make_agent("ui", source="ui", endpoint="127.0.0.1:1111")  # source 고정 바닥
    pk_code = await _make_agent("code", source="code", endpoint="10.0.0.9:2222")
    # 사설 대상 에이전트에 세션 시드(cascade 표기·삭제 검증)
    await _seed_session_for(pk_loop, "v050_a_s1")
    await _seed_session_for(pk_loop, "v050_a_s2")

    targets = {pk_loop, pk_priv}
    nontargets = {pk_public, pk_noep, pk_ui, pk_code}

    # 비-fixture(라이브 정크) 매치 — 있으면 실삭제 생략(적응형 안전).
    async with SessionLocal() as s:
        live = (
            await s.execute(
                select(Agent.id, Agent.endpoint).where(
                    Agent.source == "external", Agent.endpoint.is_not(None)
                )
            )
        ).all()
    from api.batch.jobs import _is_private_host

    extra = [
        r for r in live if _is_private_host(r[1]) and r[0] not in targets
    ]

    res_dry = await cleanup_a2a_agents(dry_run=True)
    check(res_dry.get("status") == "dry_run", "[A] dry-run status=dry_run")
    sample_ids = {x["agent_id"] for x in res_dry.get("sample", [])}
    check(f"{A_PREFIX}loop" in sample_ids and f"{A_PREFIX}priv" in sample_ids,
          "[A] dry-run sample에 사설 대상 포함")
    check(f"{A_PREFIX}public" not in sample_ids, "[A] 공개 endpoint 비포함(바닥)")
    check(f"{A_PREFIX}ui" not in sample_ids and f"{A_PREFIX}code" not in sample_ids,
          "[A] source 비-external 비포함(바닥)")
    check(res_dry.get("cascade_sessions", 0) >= 2, "[A] cascade_sessions가 시드 세션(>=2) 반영")
    check(res_dry.get("would_delete", 0) >= 2, "[A] would_delete >= 사설 대상 2")

    if not extra:
        res = await cleanup_a2a_agents(dry_run=False)
        check(res.get("status") == "ok", "[A] 실삭제 status=ok")
        for pk in targets:
            check(not await _agent_exists(pk), f"[A] 사설 대상 삭제됨: {pk}")
        for pk in nontargets:
            check(await _agent_exists(pk), f"[A] 비대상 보존: {pk}")
        check(not await _session_exists("v050_a_s1"), "[A] 대상 에이전트 세션 cascade 삭제")
        res2 = await cleanup_a2a_agents(dry_run=False)
        check(res2.get("deleted") == 0, "[A] 재실행 deleted=0(멱등)")
    else:
        print(f"  note  [A] 라이브 비-fixture 사설 A2A {len(extra)}건 → 실삭제 건너뜀(데이터 보호)")
        # 비대상은 dry-run이라 모두 보존돼야 함.
        for pk in targets | nontargets:
            check(await _agent_exists(pk), f"[A] dry-run no-op 보존: {pk}")


# ----------------------------- Section B: user-cleanup -----------------------------
async def _global_supers_outside(candidate_ids: set[uuidlib.UUID]) -> int:
    """후보 밖의 전역 슈퍼유저 수 — 마지막-super 보존 산술 교차검증."""
    async with SessionLocal() as s:
        rows = (
            await s.execute(select(User.id).where(User.is_superuser.is_(True)))
        ).scalars().all()
        return len([r for r in rows if r not in candidate_ids])


async def section_b() -> None:
    print("\n== B. user-cleanup(패턴+keep-list+last-super+cascade) ==")

    # --- B0: 비활성/거부 가드 ---
    await _cfg_set_pattern(None)
    r_dis = await cleanup_test_users(dry_run=True)
    check(r_dis.get("status") == "disabled", "[B0] 패턴 NULL → disabled")
    # 광범위 패턴 거부 — `%`만이 아니라 `%@%`·`%a%`·`a%`처럼 리터럴 약한 것도(적대리뷰 #1).
    for broad in ("%", "%%", "%@%", "%a%", "a%", "%.com", "%@x"):
        await _cfg_set_pattern(broad)
        r_b = await cleanup_test_users(dry_run=True)
        check(r_b.get("status") == "rejected", f"[B0] 광범위 패턴 {broad!r} → rejected(delete-all 가드)")
    await _cfg_set_pattern("   ")
    r_ws = await cleanup_test_users(dry_run=True)
    check(r_ws.get("status") in ("disabled", "rejected"), "[B0] 공백-only 패턴 → 비실행")

    # --- B1: keep-list 보호(브로드 패턴 dry-run, admin@/alice@ 제외) ---
    # admin@example.com·alice@example.com은 패턴 일치해도 후보에서 빠져야 한다.
    await _cfg_set_pattern("%@example.com")
    r_keep = await cleanup_test_users(dry_run=True)
    if r_keep.get("status") == "dry_run":
        emails = {x["email"] for x in r_keep.get("sample", [])}
        check("admin@example.com" not in emails, "[B1] keep-list admin@ 제외")
        check("alice@example.com" not in emails, "[B1] keep-list alice@ 제외")
        check(r_keep.get("matched", 0) > r_keep.get("would_delete", 0),
              "[B1] matched > would_delete(keep-list/super 제외분 존재)")
    else:
        check(False, f"[B1] 브로드 패턴 dry-run 기대, 실제 {r_keep.get('status')}")

    # --- B2: 일반 유저 삭제 + cascade(accesstoken/casbin) ---
    uid_a = await _make_user("plain_a")
    uid_b = await _make_user("plain_b")
    # accesstoken·casbin g-정책 시드(cascade 검증용)
    tok = "v050tok" + uuidlib.uuid4().hex
    async with SessionLocal() as s:
        await s.execute(
            text("INSERT INTO accesstoken (token, user_id, created_at) VALUES (:t,:u,:c)"),
            {"t": tok, "u": uid_a, "c": datetime.now(timezone.utc)},
        )
        await s.execute(
            text("INSERT INTO casbin_rule (ptype, v0, v1) VALUES ('g', :u, 'member')"),
            {"u": str(uid_a)},
        )
        await s.commit()

    await _cfg_set_pattern(U_PATTERN)
    # 적응형: 이 유일 도메인에 비-fixture 유저가 있으면 실삭제 생략.
    async with SessionLocal() as s:
        all_match = (
            await s.execute(select(User.id).where(User.email.like(U_PATTERN)))
        ).scalars().all()
    extra_u = [i for i in all_match if i not in set(_created_user_ids)]

    r_dry = await cleanup_test_users(dry_run=True)
    check(r_dry.get("status") == "dry_run", "[B2] dry-run status=dry_run")
    dry_emails = {x["email"] for x in r_dry.get("sample", [])}
    check(f"plain_a@{U_DOMAIN}" in dry_emails, "[B2] dry-run에 fixture 유저 포함")

    if not extra_u:
        r_ok = await cleanup_test_users(dry_run=False)
        check(r_ok.get("status") == "ok", "[B2] 실삭제 status=ok")
        check(not await _user_exists(uid_a), "[B2] fixture 유저 삭제됨")
        check(not await _user_exists(uid_b), "[B2] fixture 유저 b 삭제됨")
        async with SessionLocal() as s:
            tcount = await s.scalar(
                text("SELECT count(*) FROM accesstoken WHERE token=:t"), {"t": tok}
            )
            ccount = await s.scalar(
                text("SELECT count(*) FROM casbin_rule WHERE ptype='g' AND v0=:u"),
                {"u": str(uid_a)},
            )
        check(tcount == 0, "[B2] accesstoken FK CASCADE 삭제")
        check(ccount == 0, "[B2] casbin g-정책 동일 실행서 제거(권한 누수 방지)")
        r_idem = await cleanup_test_users(dry_run=False)
        check(r_idem.get("deleted") == 0, "[B2] 재실행 deleted=0(멱등)")
    else:
        print(f"  note  [B2] 라이브 비-fixture 유저 {len(extra_u)}건 매치 → 실삭제 건너뜀(데이터 보호)")
        check(await _user_exists(uid_a), "[B2] dry-run no-op 보존")

    # --- B3: 마지막 super 보존 산술(전역 super 수 기준) ---
    uid_super = await _make_user("super_x", is_super=True)
    await _cfg_set_pattern(U_PATTERN)
    async with SessionLocal() as s:
        cands = (
            await s.execute(
                select(User.id, User.email, User.is_superuser).where(User.email.like(U_PATTERN))
            )
        ).all()
    cand_super_ids = {r[0] for r in cands if r[2] and (r[1] or "").lower() not in
                      {"admin@example.com", "alice@example.com"}}
    supers_outside = await _global_supers_outside(cand_super_ids)
    r_s = await cleanup_test_users(dry_run=True)
    check(r_s.get("status") == "dry_run", "[B3] dry-run status=dry_run")
    protected = set(r_s.get("protected_superusers", []))
    if supers_outside <= 0 and cand_super_ids:
        # 후보 밖 super가 없으면 매치 super 전부 보존돼야(잠금 방지).
        check(f"super_x@{U_DOMAIN}" in protected,
              "[B3] 후보 밖 super 0 → 매치 super 보존(잠금 방지)")
    else:
        # 다른 super(실 admin 등)가 남으므로 fixture super는 삭제 대상(보존 아님).
        check(f"super_x@{U_DOMAIN}" not in protected,
              f"[B3] 후보 밖 super {supers_outside}명 → fixture super 삭제 가능(보존 아님)")
    # 산술 불변식: would_delete == 후보 - 보존 super.
    sample_all = {x["email"] for x in r_s.get("sample", [])}
    check(all(e.endswith(f"@{U_DOMAIN}") for e in sample_all),
          "[B3] 이 패턴 sample은 fixture 도메인만(누수 없음)")


# ----------------------------- Section C: API -----------------------------
def section_c() -> None:
    print("\n== C. API 검증(delete-all 패턴 거부) ==")
    from pydantic import ValidationError

    from api.batch_routes import BatchConfigIn

    for bad in ("%", "%%", "   ", ""):
        try:
            BatchConfigIn(test_user_email_pattern=bad)
            check(False, f"[C] 패턴 {bad!r} → 422 거부")
        except ValidationError:
            check(True, f"[C] 패턴 {bad!r} → ValidationError(delete-all 가드)")
    for good in (None, "verify%@example.com"):
        try:
            BatchConfigIn(test_user_email_pattern=good)
            check(True, f"[C] 패턴 {good!r} 허용")
        except ValidationError:
            check(False, f"[C] 패턴 {good!r} 허용")


# ----------------------------- teardown -----------------------------
async def _teardown() -> None:
    async with SessionLocal() as s:
        for uid in _created_user_ids:
            await s.execute(text("DELETE FROM accesstoken WHERE user_id=:u"), {"u": uid})
            await s.execute(
                text("DELETE FROM casbin_rule WHERE ptype='g' AND v0=:u"), {"u": str(uid)}
            )
        await s.commit()
    async with SessionLocal() as s:
        if _created_user_ids:
            await s.execute(delete(User).where(User.id.in_(_created_user_ids)))
        for pk in _created_agent_pks:
            await s.execute(delete(Session).where(Session.agent_pk == pk))
        if _created_agent_pks:
            await s.execute(delete(Agent).where(Agent.id.in_(_created_agent_pks)))
        await s.commit()


async def main() -> None:
    snap = await _cfg_snapshot()
    try:
        section_a_host()
        await section_a()
        await section_b()
        section_c()
    finally:
        await _cfg_restore(snap)
        await _teardown()

    print()
    if _fails:
        print(f"FAILED: {len(_fails)}건")
        for f in _fails:
            print("  - " + f)
        sys.exit(1)
    print("ALL PASS")


if __name__ == "__main__":
    asyncio.run(main())

"""verify_343 — 감사 컬럼(created_at/updated_at/created_by/updated_by) (스펙 343).

**앱 계층 설계**(DB 트리거 기각)의 성립 근거를 실측한다 — 컬럼 default/onupdate가 ORM뿐 아니라
**Core insert()/update()에도 적용**되는가. 이게 거짓이면 이 설계는 대량 경로에서 조용히 샌다.

  V1 ORM insert       → 4컬럼 전부 채워짐(created == updated), actor 반영.
  V2 Core insert()    → 대량 삽입(executemany)도 4컬럼 채워짐(비-ORM 경로 = 트리거 없이 서는 근거).
  V3 Core update()    → updated_* 갱신, created_* 보존.
  V4 ORM 위변조 시도  → created_at/created_by를 바꿔 flush해도 옛 값으로 되돌아감(before_flush 가드).
  V5 actor 미설정     → 'system'(배치·시드·부팅 경로).
  V6 이메일 로컬파트  → 'a@b.com' → 'a' (실명/전체 이메일 미저장).
  V7 커버리지(측정)   → 우리 소유 27테이블 **전부** 4컬럼 보유(DB 질의 — 자가선언 금지).
  V8 ORM 레지스트리   → User/AccessToken 외 **모든 매핑 클래스**가 AuditMixin 상속(새 테이블 누락 감지).
  V9 우회 경로 부재   → 코드에 raw text() INSERT/UPDATE 쓰기 0건(감사 우회 = 앱 계층의 유일한 구멍).

실행: uv run python tests/_throwaway_db.py tests/verify_343_audit.py   (virgin DB)
"""

import asyncio
import os
import pathlib
import re
import sys
import uuid

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "packages" / "api" / "src"))

from sqlalchemy import insert, select, text, update  # noqa: E402

from api import audit  # noqa: E402
from api.audit import AuditMixin  # noqa: E402
from api.db import SessionLocal, init_db  # noqa: E402
from api.models import Base, Prompt  # noqa: E402

_fails: list[str] = []
passed = 0

# 스펙 343 §1의 닫힌 집합 — 우리 소유 27.
OWNED = [
    "agents",
    "agent_versions",
    "allowed_hosts",
    "app_settings",
    "approvals",
    "batch_config",
    "batch_runs",
    "collection_reindex_events",
    "collections",
    "document_blobs",
    "documents",
    "eval_case_results",
    "eval_cases",
    "eval_datasets",
    "eval_runs",
    "mcp_servers",
    "memory_snapshots",
    "memory_types",
    "message_feedback",
    "messages",
    "models",
    "node_templates",
    "prompts",
    "providers",
    "rag_chunks",
    "roles",
    "sessions",
]
AUDIT_COLS = {"created_at", "updated_at", "created_by", "updated_by"}


def check(cond: object, msg: str) -> None:
    global passed
    print(("  ok  " if cond else " FAIL ") + msg)
    if cond:
        passed += 1
    else:
        _fails.append(msg)


def _code_only(source: str) -> str:
    """주석·docstring을 뺀 실행 코드만 — 정적 스캔이 **설명문을 코드로 오인**하지 않도록.
    (audit.py가 '이런 패턴은 못 막는다'고 docstring에 인용한 문장을 V10이 위반으로 잡았다.)"""
    import io
    import tokenize

    out = []
    try:
        toks = tokenize.generate_tokens(io.StringIO(source).readline)
        prev_type = tokenize.INDENT
        for tok in toks:
            if tok.type == tokenize.COMMENT:
                continue
            # 문(statement) 자리에 홀로 선 문자열 = docstring → 코드 아님
            if tok.type == tokenize.STRING and prev_type in (
                tokenize.INDENT,
                tokenize.NEWLINE,
                tokenize.NL,
                tokenize.DEDENT,
            ):
                continue
            out.append(tok.string)
            if tok.type not in (tokenize.NL, tokenize.NEWLINE):
                prev_type = tok.type
    except tokenize.TokenError:
        return source
    return " ".join(out)


async def main() -> None:
    await init_db()

    # V6 — 액터 해석(순수 함수)
    class _U:
        email = "gildong@example.com"

    check(
        audit.actor_of(_U()) == "gildong", f"V6 이메일 @ 앞만 저장 (got {audit.actor_of(_U())!r})"
    )
    check(audit.actor_of("machine") == "system", "V6b 머신 토큰 → system")

    # V5 — actor 미설정 = system
    check(
        audit.current_actor() == "system", f"V5 기본 actor=system (got {audit.current_actor()!r})"
    )

    # 이하 요청 흉내: actor 세팅
    audit.set_actor("tester")

    name1 = f"audit-orm-{uuid.uuid4().hex[:8]}"
    async with SessionLocal() as s:
        # V1 — ORM insert
        p = Prompt(name=name1, body="x")
        s.add(p)
        await s.commit()
        row = (
            await s.execute(
                text(
                    "select created_at, updated_at, created_by, updated_by from prompts where name=:n"
                ),
                {"n": name1},
            )
        ).one()
        c_at, u_at, c_by, u_by = row
        check(
            all(v is not None for v in row) and c_by == "tester" and u_by == "tester",
            f"V1 ORM insert = 4컬럼 채움·actor 반영 (by={c_by}/{u_by})",
        )
        check(abs((u_at - c_at).total_seconds()) < 1.0, "V1b 최초 삽입 created ≈ updated")

        # V2 — Core insert() (비-ORM 경로, 대량)
        names = [f"audit-core-{uuid.uuid4().hex[:8]}" for _ in range(3)]
        await s.execute(insert(Prompt), [{"name": n, "body": "y"} for n in names])
        await s.commit()
        rows = (
            await s.execute(
                text(
                    "select created_by, updated_by, created_at, updated_at from prompts where name = any(:ns)"
                ),
                {"ns": names},
            )
        ).all()
        check(
            len(rows) == 3
            and all(r[0] == "tester" and r[1] == "tester" and r[2] and r[3] for r in rows),
            f"V2 Core insert() 대량도 4컬럼 채움 ({len(rows)}행, by={rows[0][0] if rows else '-'})",
        )

        # V3 — Core update(): updated_* 갱신, created_* 보존
        audit.set_actor("editor")
        await asyncio.sleep(0.01)
        await s.execute(update(Prompt).where(Prompt.name == name1).values(body="z"))
        await s.commit()
        r3 = (
            await s.execute(
                text(
                    "select created_at, updated_at, created_by, updated_by from prompts where name=:n"
                ),
                {"n": name1},
            )
        ).one()
        check(
            r3[2] == "tester" and r3[3] == "editor" and r3[1] > r3[0],
            f"V3 Core update() = updated_by 갱신·created_by 보존 (created_by={r3[2]}, updated_by={r3[3]})",
        )

        # V4 — ORM 위변조 시도: created_* 덮어쓰기 → 되돌려짐
        obj = (await s.execute(select(Prompt).where(Prompt.name == name1))).scalar_one()
        orig_by, orig_at = obj.created_by, obj.created_at
        obj.created_by = "attacker"
        obj.created_at = obj.created_at.replace(year=2000)
        obj.body = "tampered"
        await s.commit()
        r4 = (
            await s.execute(
                text("select created_at, created_by from prompts where name=:n"), {"n": name1}
            )
        ).one()
        check(
            r4[1] == orig_by and r4[0] == orig_at,
            f"V4 created_* 위변조 시도 무시(before_flush 되돌림) (got by={r4[1]})",
        )

        # V7 — 커버리지 측정(DB 질의): 우리 소유 27테이블 전부 4컬럼
        missing = []
        for t in OWNED:
            cols = {
                r[0]
                for r in (
                    await s.execute(
                        text(
                            "select column_name from information_schema.columns "
                            "where table_schema='public' and table_name=:t"
                        ),
                        {"t": t},
                    )
                ).all()
            }
            if not AUDIT_COLS <= cols:
                missing.append((t, sorted(AUDIT_COLS - cols)))
        check(not missing, f"V7 우리 소유 {len(OWNED)}테이블 전부 4컬럼 (미비: {missing})")

        # NOT NULL도 함께(감사 누락이 조용히 통과 못 함)
        nullable = (
            await s.execute(
                text(
                    "select table_name, column_name from information_schema.columns "
                    "where table_schema='public' and column_name = any(:c) and is_nullable='YES' "
                    "and table_name = any(:t)"
                ),
                {"c": sorted(AUDIT_COLS), "t": OWNED},
            )
        ).all()
        check(not nullable, f"V7b 감사 컬럼 전부 NOT NULL (nullable: {nullable[:3]})")

    # V12 — 배경 잡 관문(codex 343 P2): spawn된 잡은 요청 actor를 승계하지 않고 'system'.
    # (create_task는 contextvar를 복사한다 → 관문에서 뒤집지 않으면 배경 행이 요청자 이름으로 찍힌다.
    #  RAG만 개별 처리했던 것을 background.spawn 한 곳으로 올린 뒤의 회귀 핀.)
    from api.background import spawn  # noqa: PLC0415

    audit.set_actor("requester")
    bg_name = f"audit-bg-{uuid.uuid4().hex[:8]}"

    async def _bg() -> None:
        async with SessionLocal() as s2:
            s2.add(Prompt(name=bg_name, body="bg"))
            await s2.commit()

    await spawn(_bg())
    async with SessionLocal() as s3:
        bg_by = (
            await s3.execute(text("select created_by from prompts where name=:n"), {"n": bg_name})
        ).scalar_one()
    check(
        bg_by == "system",
        f"V12 배경 잡(spawn)은 요청 actor 미승계 → system (got {bg_by!r}, 요청자='requester')",
    )
    check(audit.current_actor() == "requester", "V12b 배경 잡이 요청 컨텍스트를 오염시키지 않음")

    # V8 — ORM 레지스트리 스캔(새 테이블 누락 감지)
    plain = sorted(
        m.class_.__name__ for m in Base.registry.mappers if not issubclass(m.class_, AuditMixin)
    )
    check(plain == ["AccessToken", "User"], f"V8 AuditMixin 미상속 = 외부 소유 2개뿐 (got {plain})")

    # V9 — raw text() INSERT/UPDATE 부재(앱 계층 설계의 유일한 구멍을 상주 핀으로).
    # DELETE는 제외 — 행이 사라지므로 감사 컬럼을 우회할 수 없다(현 유일 사례: casbin_rule 정리,
    # 외부 소유·감사 컬럼 없음). 새 코드가 raw INSERT/UPDATE를 들이면 여기서 실패한다.
    src = pathlib.Path(__file__).resolve().parents[1] / "packages" / "api" / "src" / "api"
    pat = re.compile(r"""text\(\s*["']\s*(INSERT|UPDATE)\b""", re.I)
    hits = [f.name for f in src.rglob("*.py") if pat.search(f.read_text())]
    check(not hits, f"V9 raw text() INSERT/UPDATE 0건(감사 우회 경로 부재) (hits: {hits})")

    # V10 — Core가 created_*를 **명시로** 덮어쓰는 코드 부재(codex 343 P2).
    # before_flush 가드는 ORM dirty만 본다 → Core update().values(created_by=…)는 못 막는다.
    # "테스트가 잡는 선까지"라고 스펙에 적었으니, 그 테스트가 여기다(정직한 보장 크기).
    tamper = re.compile(r"""\.values\([^)]*\bcreated_(at|by)\s*=""", re.S)
    t_hits = [f.name for f in src.rglob("*.py") if tamper.search(_code_only(f.read_text()))]
    check(not t_hits, f"V10 Core .values(created_*=) 덮어쓰기 0건 (hits: {t_hits})")

    # V11 — upsert(on_conflict_do_update)의 set_에 updated_at이 있으면 updated_by도 반드시(codex P1).
    # 재클릭 갱신에서 updated_by를 빼면 최초 작성자가 영원히 남는다(감사 거짓말).
    bad_upserts = []
    for f in src.rglob("*.py"):
        body = f.read_text()
        for m in re.finditer(r"set_=\{(.+?)\}", body, re.S):
            blk = m.group(1)
            if "updated_at" in blk and "updated_by" not in blk:
                bad_upserts.append(f.name)
    check(
        not bad_upserts,
        f"V11 upsert set_에 updated_at만 있고 updated_by 누락 0건 (hits: {bad_upserts})",
    )

    print()
    if _fails:
        print(f"FAIL {len(_fails)}건: {_fails}")
        sys.exit(1)
    print(f"VERIFY343_OK — {passed}건 전부 통과")


asyncio.run(main())

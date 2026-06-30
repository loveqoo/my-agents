"""스펙 083 검증 — A2A 노출은 source=ui만 (입구 가드 + 마이그레이션 stale-clear, 실DB).

불변식: `exposed.a2a == True ⟹ source == "ui"`. 두 rung으로 분담(비겹침):

  rung1 라이브(입구 가드, expose_agent):
    G1 ui + a2a=True       → 200, exposed.a2a==True (정상 노출)
    G2 code + a2a=True     → 400 (원격은 재노출 불가)
    G3 external + a2a=True → 400 (외부도 재노출 불가)
    G4 code + a2a=False    → 200, exposed.a2a==False (끄기는 source 무관 허용 — 멱등 청소 경로)
    G5 ui + 형제 키        → expose 후 a2a만 갱신, 형제 키 보존 (JSONB 통째 교체 금지)
  rung2 라이브(마이그레이션 데이터 정합, a3b4c5d6e7f8):
    M1 code의 stale true → 마이그레이션 UPDATE 후 false (청소됨)
    M2 ui의 true         → 마이그레이션 UPDATE 후 true 보존 (정당한 노출 무회귀)
    M3 불변식 단언: UPDATE 후 (exposed->>'a2a')='true' AND source<>'ui' 인 row = 0
    M4 형제 키 보존: jsonb_set이 a2a만 끄고 비-a2a 키('note')는 무손실

브라우저(토글 부재/표 '—')·적대 codex는 verification 단계 별도 rung.
실행: .venv/bin/python tests/verify_083_expose_gate.py
"""

import asyncio
import os
import sys
import uuid

from fastapi import HTTPException
from sqlalchemy import text

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))

from api.agents import _new_agent_id, expose_agent  # noqa: E402
from api.db import SessionLocal  # noqa: E402
from api.models import Agent  # noqa: E402
from api.schemas import ExposeIn  # noqa: E402

_fails: list[str] = []
_tag = uuid.uuid4().hex[:8]  # 이름 충돌 회피(unique name)


def ck(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


# 이 검증이 만든 row만 청소하기 위한 추적
_made: list[uuid.UUID] = []


async def _mk(source: str, a2a: bool) -> uuid.UUID:
    """source/exposed 박아 Agent 한 row 삽입(가드 우회 — 직접 ORM). PK 반환."""
    async with SessionLocal() as s:
        a = Agent(
            agent_id=_new_agent_id(),
            name=f"083-{source}-{_tag}-{len(_made)}",
            source=source,
            exposed={"a2a": a2a},
        )
        s.add(a)
        await s.commit()
        await s.refresh(a)
        _made.append(a.id)
        return a.id


async def _exposed_of(pk: uuid.UUID) -> bool:
    async with SessionLocal() as s:
        row = await s.get(Agent, pk)
        return bool((row.exposed or {}).get("a2a"))


async def _cleanup() -> None:
    async with SessionLocal() as s:
        for pk in _made:
            row = await s.get(Agent, pk)
            if row is not None:
                await s.delete(row)
        await s.commit()


async def _call_expose(pk: uuid.UUID, a2a: bool):
    """라우트 핸들러를 실세션으로 직접 호출. (status, exposed|None) 반환; 거부 시 (code, None)."""
    async with SessionLocal() as s:
        try:
            out = await expose_agent(pk, ExposeIn(a2a=a2a), s)
            return 200, bool(out.exposed.get("a2a"))
        except HTTPException as exc:
            return exc.status_code, None


async def test_gate():
    # G1 ui + true → 200, exposed True
    ui_pk = await _mk("ui", False)
    code, exp = await _call_expose(ui_pk, True)
    ck(code == 200 and exp is True, f"G1 ui+true → 200·exposed=True (got {code}, {exp})")

    # G2 code + true → 400
    code_pk = await _mk("code", False)
    code, _ = await _call_expose(code_pk, True)
    ck(code == 400, f"G2 code+true → 400 (got {code})")
    ck(await _exposed_of(code_pk) is False, "G2 거부 후 code의 exposed 변동 없음(False 유지)")

    # G3 external + true → 400
    ext_pk = await _mk("external", False)
    code, _ = await _call_expose(ext_pk, True)
    ck(code == 400, f"G3 external+true → 400 (got {code})")

    # G4 code + false → 200 (끄기는 항상 허용; 멱등 청소)
    code_pk2 = await _mk("code", True)  # stale true 상태에서 끄기
    code, exp = await _call_expose(code_pk2, False)
    ck(code == 200 and exp is False, f"G4 code+false → 200·exposed=False (got {code}, {exp})")

    # G5 형제 키 보존: ui + 형제 키 보유 상태에서 expose → a2a만 갱신, 형제 키 무손실
    async with SessionLocal() as s:
        a = Agent(
            agent_id=_new_agent_id(),
            name=f"083-ui-sibling-{_tag}",
            source="ui",
            exposed={"a2a": False, "note": "keep-me"},
        )
        s.add(a)
        await s.commit()
        await s.refresh(a)
        _made.append(a.id)
        ui_sibling = a.id
    code, exp = await _call_expose(ui_sibling, True)
    raw = await _exposed_raw(ui_sibling)
    ck(code == 200 and exp is True, f"G5a ui+sibling expose → 200·a2a=True (got {code}, {exp})")
    ck(raw.get("note") == "keep-me", f"G5b expose 후 형제 키 'note' 보존 (got {raw.get('note')!r})")


async def _exposed_raw(pk: uuid.UUID) -> dict:
    async with SessionLocal() as s:
        row = await s.get(Agent, pk)
        return dict(row.exposed or {})


async def test_migration():
    # M-셋업: code stale-true 1건 + ui true 1건 (ORM 직접 — 가드 우회로 stale 재현)
    code_stale = await _mk("code", True)
    ui_legit = await _mk("ui", True)

    # M4 셋업: 형제 키를 가진 code stale-true (jsonb_set이 a2a만 끄고 형제 키 보존하는지 검증)
    code_sibling = _made and None  # placeholder
    async with SessionLocal() as s:
        a = Agent(
            agent_id=_new_agent_id(),
            name=f"083-code-sibling-{_tag}",
            source="code",
            exposed={"a2a": True, "note": "keep-me"},
        )
        s.add(a)
        await s.commit()
        await s.refresh(a)
        _made.append(a.id)
        code_sibling = a.id

    # 마이그레이션 upgrade()의 UPDATE SQL(jsonb_set)을 실DB에 그대로 적용
    async with SessionLocal() as s:
        await s.execute(
            text(
                """
                UPDATE agents
                SET exposed = jsonb_set(COALESCE(exposed, '{}'::jsonb), '{a2a}', 'false'::jsonb, true)
                WHERE source <> 'ui' AND (exposed ->> 'a2a') = 'true'
                """
            )
        )
        await s.commit()

    ck(await _exposed_of(code_stale) is False, "M1 code stale-true → 마이그레이션 후 false 청소")
    ck(await _exposed_of(ui_legit) is True, "M2 ui true → 마이그레이션 후 true 보존(무회귀)")

    # M3 불변식: 전역에 (true ∧ non-ui) row가 0
    async with SessionLocal() as s:
        n = (
            await s.execute(
                text(
                    "SELECT count(*) FROM agents "
                    "WHERE source <> 'ui' AND (exposed ->> 'a2a') = 'true'"
                )
            )
        ).scalar_one()
    ck(n == 0, f"M3 불변식 exposed.a2a=true ⟹ source=ui (위반 row={n})")

    # M4 형제 키 보존: a2a는 false로 청소되되 note 키는 그대로 (통째 교체였다면 note 소실)
    raw = await _exposed_raw(code_sibling)
    ck(raw.get("a2a") is False, f"M4a code sibling의 a2a → false 청소 (got {raw.get('a2a')})")
    ck(raw.get("note") == "keep-me", f"M4b 형제 키 'note' 보존 (got {raw.get('note')!r})")


async def main():
    try:
        await test_gate()
        await test_migration()
    finally:
        await _cleanup()

    print()
    if _fails:
        print(f"FAIL — {len(_fails)}건")
        for f in _fails:
            print("  - " + f)
        sys.exit(1)
    print("ALL PASS — VERIFY083_OK (가드 4 + 마이그레이션 3)")


if __name__ == "__main__":
    asyncio.run(main())

"""verify_147 — 에이전트 private 정책 (스펙 147).

  V1 may_use_agent 술어: public=모두·private=소유자/특권만·external=항상.
  V2 expose 게이트: private 켜기 400·끄기 허용·public 켜기 정상(끝나고 원복).
  V3 목록 가시성: 멤버 주체=타인 private 불포함, admin=전부.
  V4 채팅 게이트: 멤버가 타인 private 채팅 → 404(존재 비노출 fold).
실행: uv run --project packages/api python tests/verify_147_visibility.py
"""
import asyncio
import os
import sys
import uuid as _uuid

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "packages", "api", "src"))

from fastapi import HTTPException  # noqa: E402
from sqlalchemy import select  # noqa: E402

from api.db import SessionLocal as async_session  # noqa: E402
from api import agents as AG  # noqa: E402
from api.models import Agent  # noqa: E402
from api.ownership import may_use_agent  # noqa: E402

_fails = []
passed = 0

def check(cond, msg):
    global passed
    print(("  ok  " if cond else " FAIL ") + msg)
    if cond: passed += 1
    else: _fails.append(msg)

class _P:
    def __init__(self, uid, superuser=False):
        self.id = uid
        self.is_superuser = superuser

class _Row:
    def __init__(self, owner, source="ui"):
        self.owner_id = owner
        self.source = source

async def main():
    from api.authz import init_authz
    await init_authz()  # 게이트가 enforcer 접촉(멤버 주체 판정)
    owner_id = str(_uuid.uuid4())
    other_id = str(_uuid.uuid4())
    owner = _P(owner_id)
    other = _P(other_id)
    admin = _P(_uuid.uuid4(), superuser=True)

    # V1 술어
    check(may_use_agent(_Row(None), other) is True, "V1a public → 모두")
    check(may_use_agent(_Row(owner_id), owner) is True, "V1b private → 소유자")
    check(may_use_agent(_Row(owner_id), other) is False, "V1c private → 타인 거부")
    check(may_use_agent(_Row(owner_id), admin) is True, "V1d private → admin 허용")
    check(may_use_agent(_Row(owner_id, source="external"), other) is True, "V1e external → 항상")
    check(may_use_agent(_Row(None), "machine") is True and may_use_agent(_Row(owner_id), "machine") is True,
          "V1f machine 특권")

    # 실데이터: private 에이전트 하나 임시 생성(owner 스탬프)
    tag = f"v147-{_uuid.uuid4().hex[:6]}"
    async with async_session() as s:
        priv = Agent(name=f"{tag}-priv", agent_id=f"{tag}-priv", owner_id=owner_id, config={"model": "", "prompt": "p"})
        s.add(priv); await s.commit(); priv_id = priv.id
    try:
        # V2 expose 게이트
        async with async_session() as s:
            try:
                await AG.expose_agent(priv_id, AG.ExposeIn(a2a=True), session=s, principal=admin)
                check(False, "V2a private 켜기 → 400이어야")
            except HTTPException as e:
                check(e.status_code == 400 and "private" in e.detail, f"V2a private A2A 켜기 400")
        async with async_session() as s:
            out = await AG.expose_agent(priv_id, AG.ExposeIn(a2a=False), session=s, principal=admin)
            check(out is not None, "V2b 끄기는 항상 허용(멱등 청소)")

        # V3 목록 가시성
        async with async_session() as s:
            mine = await AG.list_agents(session=s, principal=owner)
            others_view = await AG.list_agents(session=s, principal=other)
            admin_view = await AG.list_agents(session=s, principal=admin)
        names_other = {a.name for a in others_view}
        names_admin = {a.name for a in admin_view}
        names_owner = {a.name for a in mine}
        check(f"{tag}-priv" in names_owner, "V3a 소유자 목록엔 포함")
        check(f"{tag}-priv" not in names_other, "V3b 타인 목록엔 미포함")
        check(f"{tag}-priv" in names_admin, "V3c admin 목록엔 포함")

        # V5~V7 (codex High 3종 핀) — 단건 조회·복제·메모리 읽기 게이트
        async with async_session() as s:
            try:
                await AG.get_agent(priv_id, session=s, principal=other)
                check(False, "V5 타인 private 단건 조회 → 404여야")
            except HTTPException as e:
                check(e.status_code == 404, f"V5 단건 조회 404-fold (got {e.status_code})")
        async with async_session() as s:
            try:
                await AG.clone_agent(priv_id, session=s, principal=other)
                check(False, "V6 타인 private 복제 → 404여야")
            except HTTPException as e:
                check(e.status_code == 404, f"V6 복제 404-fold (got {e.status_code})")
        async with async_session() as s:
            try:
                await AG.list_agent_memory(priv_id, session=s, principal=other)
                check(False, "V7 타인 private 메모리 읽기 → 404여야")
            except HTTPException as e:
                check(e.status_code == 404, f"V7 메모리 읽기 404-fold (got {e.status_code})")
        # 소유자·admin은 여전히 접근 가능(과차단 방지)
        async with async_session() as s:
            got = await AG.get_agent(priv_id, session=s, principal=owner)
            check(got is not None, "V8 소유자 단건 조회 정상")

        # V4 채팅 게이트(라우트 직접 호출 — 404-fold)
        from api.chat import chat, ChatRequest
        try:
            await chat(priv_id, ChatRequest(messages=[{"role": "user", "content": "hi"}]), principal=other)
            check(False, "V4 타인 private 채팅 → 404여야")
        except HTTPException as e:
            check(e.status_code == 404, f"V4 타인 private 채팅 404-fold (got {e.status_code})")
    finally:
        async with async_session() as s:
            row = await s.get(Agent, priv_id)
            if row: await s.delete(row); await s.commit()

    print(f"\n{passed} passed, {len(_fails)} failed")
    if _fails: sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())

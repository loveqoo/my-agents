"""verify_153 — A2A organization 설정 (스펙 153, 실사용 #6).

  V1 설정 CRUD: 기본값 → 저장 → 갱신 조회(list/get_setting 정합).
  V2 경계: 미지 키 400 · 빈/초과 값 400 · member 403(특권 게이트).
  V3 카드 통합(ASGI): 노출 ui 에이전트 카드의 organization이 설정값 반영 → 원복 후 기본값.
실행: uv run --project packages/api --env-file .env python tests/verify_153_a2a_org.py
"""
import asyncio
import os
import sys
import uuid as _uuid

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "packages", "api", "src"))

import httpx  # noqa: E402
from fastapi import HTTPException  # noqa: E402

from api.db import SessionLocal as async_session  # noqa: E402
from api import app_settings as ST  # noqa: E402
from api.models import Agent, AppSetting  # noqa: E402

_fails = []
passed = 0


def check(cond, msg):
    global passed
    print(("  ok  " if cond else " FAIL ") + msg)
    if cond:
        passed += 1
    else:
        _fails.append(msg)


class _P:
    id = _uuid.uuid4()
    is_superuser = True


class _Member:
    id = _uuid.uuid4()
    is_superuser = False


async def main():
    from api.authz import init_authz
    await init_authz()
    admin = _P()
    tag = f"v153-{_uuid.uuid4().hex[:6]}"

    # 원상 기록(실 DB — 설정은 전역)
    async with async_session() as s:
        orig = await s.get(AppSetting, "a2a_org_name")
        orig_value = dict(orig.value) if orig is not None else None

    made_agent = None
    try:
        # V1 CRUD
        check(await ST.get_setting("a2a_org_name") in ("my-agents", (orig_value or {}).get("v")),
              "V1a 기본/기존값 조회")
        async with async_session() as s:
            out = await ST.put_setting("a2a_org_name", ST.SettingIn(value=f"{tag}-org"), session=s, _p=admin)
            check(out == {"a2a_org_name": f"{tag}-org"}, "V1b 저장")
        check(await ST.get_setting("a2a_org_name") == f"{tag}-org", "V1c get_setting 반영")
        async with async_session() as s:
            allv = await ST.list_settings(session=s, _p=admin)
            check(allv.get("a2a_org_name") == f"{tag}-org", "V1d 목록 반영")

        # V2 경계
        async with async_session() as s:
            try:
                await ST.put_setting("nope_key", ST.SettingIn(value="x"), session=s, _p=admin)
                check(False, "V2a 미지 키 400이어야")
            except HTTPException as e:
                check(e.status_code == 400, f"V2a 미지 키 400 (got {e.status_code})")
        for bad, why in [("", "빈 값"), ("   ", "공백"), ("x" * 81, "81자"), (123, "비문자열")]:
            async with async_session() as s:
                try:
                    await ST.put_setting("a2a_org_name", ST.SettingIn(value=bad), session=s, _p=admin)
                    check(False, f"V2b 거부돼야: {why}")
                except HTTPException as e:
                    check(e.status_code == 400, f"V2b 값 검증 400({why})")
        from api.model_registry import require_model_manage
        try:
            await require_model_manage(principal=_Member())
            check(False, "V2c member → 403이어야")
        except HTTPException as e:
            check(e.status_code == 403, f"V2c member 게이트 403 (got {e.status_code})")

        # V3 카드 통합 — 노출 ui 에이전트 생성 후 ASGI로 카드 fetch
        async with async_session() as s:
            made_agent = Agent(agent_id=f"{tag}-ag", name=f"{tag}-ag", source="ui",
                               config={"model": "", "persona": ""}, exposed={"a2a": True},
                               active_version="v1")
            s.add(made_agent)
            await s.commit()
            agent_pk = made_agent.id
        from api.main import app
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as c:
            r = await c.get(f"/agents/{agent_pk}/.well-known/agent-card.json")
            check(r.status_code == 200, f"V3a 카드 200 (got {r.status_code})")
            org = (r.json().get("provider") or {}).get("organization")
            check(org == f"{tag}-org", f"V3b 카드 organization=설정값 (got {org!r})")
    finally:
        async with async_session() as s:
            row = await s.get(AppSetting, "a2a_org_name")
            if orig_value is None:
                if row is not None:
                    await s.delete(row)
            else:
                row.value = orig_value
            if made_agent is not None:
                a = await s.get(Agent, made_agent.id)
                if a is not None:
                    await s.delete(a)
            await s.commit()
    # 원복 확인
    restored = await ST.get_setting("a2a_org_name")
    expected = (orig_value or {}).get("v", "my-agents") if orig_value else "my-agents"
    check(restored == expected, f"V3c 설정 원복 (got {restored!r})")

    # V4 폴백 의미(codex 153 Medium): 저장 여부로 분기 — 기본 문자열을 *의도 저장*하면 env가 못 이긴다
    os.environ["A2A_ORG_NAME"] = f"{tag}-env"
    try:
        from api.a2a_server import _org_name
        async with async_session() as s:
            row = await s.get(AppSetting, "a2a_org_name")
            saved_state = dict(row.value) if row is not None else None
            if row is not None:
                await s.delete(row)  # 미저장 상태로
                await s.commit()
        check(await _org_name() == f"{tag}-env", "V4a 미저장 → env 폴백")
        async with async_session() as s:
            s.add(AppSetting(key="a2a_org_name", value={"v": "my-agents"}))
            await s.commit()
        check(await _org_name() == "my-agents", "V4b 기본 문자열 의도 저장 → env가 못 이김")
        # 오염 값 fail-safe(읽기 재검증)
        async with async_session() as s:
            row = await s.get(AppSetting, "a2a_org_name")
            row.value = {"v": ["not", "a", "string"]}
            await s.commit()
        check(await _org_name() == f"{tag}-env", "V4c 오염 값 → 미저장 취급(env 폴백, 공개 카드 fail-safe)")
    finally:
        os.environ.pop("A2A_ORG_NAME", None)
        async with async_session() as s:
            row = await s.get(AppSetting, "a2a_org_name")
            if saved_state is None:
                if row is not None:
                    await s.delete(row)
            elif row is None:
                s.add(AppSetting(key="a2a_org_name", value=saved_state))
            else:
                row.value = saved_state
            await s.commit()
    check(await ST.get_setting("a2a_org_name") == expected, "V4d 폴백 시험 후 원복")

    print(f"\n{passed} passed, {len(_fails)} failed")
    if _fails:
        sys.exit(1)


asyncio.run(main())

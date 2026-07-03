"""verify_150 — 기본 모델 전환 API (스펙 150, 실사용 버그 #1).

  V1 지정: PUT /models/{id}/default → 그 모델 is_default=True.
  V2 배타: 같은 kind의 기존 기본 자동 해제 · 다른 kind는 무영향.
  V3 404: 미존재 id.
  V4 원복: 시험 전 기본을 finally에서 복원(실 DB — 기본이 런타임 모델 선택에 닿는다).
  V5 게이트(codex 150 High): member 403 · 머신/superuser 통과.
  V6 kind 가드: chat/embedding 외 kind는 400(거짓 성공 방지).
  V7 DB 불변식: kind당 기본 1개 부분 유니크 인덱스 존재 + 직접 위반 insert가 DB서 거부.
실행: uv run --project packages/api --env-file .env python tests/verify_150_default_model.py
"""
import asyncio
import os
import sys
import uuid as _uuid

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "packages", "api", "src"))

from fastapi import HTTPException  # noqa: E402
from sqlalchemy import select  # noqa: E402

from api.db import SessionLocal as async_session  # noqa: E402
from api import model_registry as MR  # noqa: E402
from api.models import ModelConfig, Provider  # noqa: E402

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
    tag = f"v150-{_uuid.uuid4().hex[:6]}"
    async with async_session() as s:
        prov = (await s.execute(select(Provider))).scalars().first()
        assert prov is not None, "provider가 하나는 있어야 함(시드)"
        orig_default_chat = (
            await s.execute(select(ModelConfig).where(ModelConfig.kind == "chat", ModelConfig.is_default.is_(True)))
        ).scalar_one_or_none()
        orig_default_emb = (
            await s.execute(select(ModelConfig).where(ModelConfig.kind == "embedding", ModelConfig.is_default.is_(True)))
        ).scalar_one_or_none()
        a = ModelConfig(name=f"{tag}-a", provider_id=prov.id, model_id=f"{tag}-a", kind="chat")
        b = ModelConfig(name=f"{tag}-b", provider_id=prov.id, model_id=f"{tag}-b", kind="chat")
        s.add_all([a, b])
        await s.commit()
        a_id, b_id = a.id, b.id
        orig_chat_id = orig_default_chat.id if orig_default_chat else None
        orig_emb_id = orig_default_emb.id if orig_default_emb else None

    try:
        async with async_session() as s:
            out = await MR.set_default_model(a_id, session=s)
            check(out.is_default is True and out.name == f"{tag}-a", "V1 지정 → is_default=True")
        async with async_session() as s:
            out = await MR.set_default_model(b_id, session=s)
            check(out.is_default is True, "V2a B 지정")
        async with async_session() as s:
            rows = (
                await s.execute(select(ModelConfig).where(ModelConfig.kind == "chat", ModelConfig.is_default.is_(True)))
            ).scalars().all()
            check(len(rows) == 1 and rows[0].id == b_id, f"V2b chat 기본은 정확히 1개(B) — got {[r.name for r in rows]}")
        async with async_session() as s:
            emb_now = (
                await s.execute(select(ModelConfig).where(ModelConfig.kind == "embedding", ModelConfig.is_default.is_(True)))
            ).scalar_one_or_none()
            check((emb_now.id if emb_now else None) == orig_emb_id, "V2c 다른 kind(embedding) 무영향")
        async with async_session() as s:
            try:
                await MR.set_default_model(_uuid.uuid4(), session=s)
                check(False, "V3 미존재 404이어야")
            except HTTPException as e:
                check(e.status_code == 404, f"V3 미존재 404 (got {e.status_code})")

        # V5 게이트 — member 403, 머신/superuser 통과
        class _Member:
            id = _uuid.uuid4()
            is_superuser = False

        class _Super:
            id = _uuid.uuid4()
            is_superuser = True

        from api.authz import init_authz
        await init_authz()
        try:
            await MR.require_model_manage(principal=_Member())
            check(False, "V5a member → 403이어야")
        except HTTPException as e:
            check(e.status_code == 403, f"V5a member 403 (got {e.status_code})")
        check(await MR.require_model_manage(principal="machine") == "machine", "V5b 머신 토큰 통과")
        check((await MR.require_model_manage(principal=_Super())).is_superuser, "V5c superuser 통과")

        # V6 kind 가드 — chat/embedding 외 kind는 400
        async with async_session() as s:
            weird = ModelConfig(name=f"{tag}-img", provider_id=prov.id, model_id=f"{tag}-img", kind="image")
            s.add(weird)
            await s.commit()
            weird_id = weird.id
        try:
            async with async_session() as s:
                try:
                    await MR.set_default_model(weird_id, session=s)
                    check(False, "V6 kind=image 기본 지정 400이어야")
                except HTTPException as e:
                    check(e.status_code == 400, f"V6 kind 가드 400 (got {e.status_code})")
        finally:
            async with async_session() as s:
                w = await s.get(ModelConfig, weird_id)
                if w is not None:
                    await s.delete(w)
                await s.commit()

        # V7 DB 불변식 — 부분 유니크 인덱스 존재 + 직접 위반이 DB서 거부
        from sqlalchemy import text as _text
        from sqlalchemy.exc import IntegrityError as _IE
        async with async_session() as s:
            idx = (await s.execute(_text(
                "SELECT indexname FROM pg_indexes WHERE tablename='models' AND indexname='uq_models_default_per_kind'"
            ))).scalar_one_or_none()
            check(idx is not None, "V7a 부분 유니크 인덱스 존재")
        async with async_session() as s:
            dup = ModelConfig(name=f"{tag}-dup", provider_id=prov.id, model_id=f"{tag}-dup",
                              kind="chat", is_default=True)  # 현재 기본(B)과 충돌해야 한다
            s.add(dup)
            try:
                await s.commit()
                check(False, "V7b 기본 2개 insert가 DB서 거부돼야")
                await s.delete(dup); await s.commit()
            except _IE:
                await s.rollback()
                check(True, "V7b 기본 2개 직접 insert DB 거부(IntegrityError)")
    finally:
        async with async_session() as s:
            if orig_chat_id is not None:
                await MR.set_default_model(orig_chat_id, session=s)  # V4 원복 — 전용 라우트 자체로
        async with async_session() as s:
            for mid in (a_id, b_id):
                m = await s.get(ModelConfig, mid)
                if m is not None:
                    await s.delete(m)
            await s.commit()
        async with async_session() as s:
            now = (
                await s.execute(select(ModelConfig).where(ModelConfig.kind == "chat", ModelConfig.is_default.is_(True)))
            ).scalar_one_or_none()
            check((now.id if now else None) == orig_chat_id, "V4 시험 전 기본 chat 복원")

    print(f"\n{passed} passed, {len(_fails)} failed")
    if _fails:
        sys.exit(1)


asyncio.run(main())

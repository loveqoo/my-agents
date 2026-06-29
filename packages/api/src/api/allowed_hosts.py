"""SSRF allowlist 관리 엔드포인트(admin 보호). 스펙 064.

`net_guard.guard_url`(스펙 042)의 allowlist 진실원은 DB `allowed_hosts` 테이블이다. 이 라우터로
무재시작 추가/제거하면 그 워커 캐시를 즉시 무효화(`invalidate_allowed_hosts_cache`)하고, 다른 워커는
TTL(≤10s) 내 수렴한다. **allowlist 편집 = SSRF 예외를 여는 행위**라 batch/user_admin과 동일한 admin
게이트(슈퍼유저 또는 ("allowed_hosts","manage") 정책)로 보호한다(스펙 064 §3). 입력은
`net_guard.normalize_allowed_host`로 *정확 host*만 통과(와일드카드/CIDR/스킴/포트/userinfo 거부 —
allow-all 둔갑 차단, learning 037/066).
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from . import authz, net_guard
from .db import get_session
from .models import AllowedHost

router = APIRouter(prefix="/admin/allowed-hosts", tags=["allowed-hosts"])

_manage = Depends(authz.require("allowed_hosts", "manage"))


class AllowedHostOut(BaseModel):
    id: str
    host: str
    note: str | None
    created_at: str | None


class AllowedHostIn(BaseModel):
    host: str
    note: str | None = None


def _out(r: AllowedHost) -> AllowedHostOut:
    return AllowedHostOut(
        id=str(r.id),
        host=r.host,
        note=r.note,
        created_at=r.created_at.isoformat() if r.created_at else None,
    )


@router.get("", dependencies=[_manage])
async def list_hosts(session: AsyncSession = Depends(get_session)):
    rows = (
        await session.execute(
            select(AllowedHost).order_by(AllowedHost.created_at.desc())
        )
    ).scalars().all()
    return [_out(r) for r in rows]


@router.post("", dependencies=[_manage], status_code=201)
async def add_host(body: AllowedHostIn, session: AsyncSession = Depends(get_session)):
    try:
        host = net_guard.normalize_allowed_host(body.host)
    except ValueError as exc:
        # 정확 host가 아니면 422 — 사유(위반값+규칙)를 그대로 노출(learning 063/065).
        raise HTTPException(status_code=422, detail=str(exc)) from None
    note = (body.note or "").strip() or None
    if note and len(note) > 200:
        note = note[:200]
    row = AllowedHost(host=host, note=note)
    session.add(row)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail=f"이미 등록된 호스트입니다: {host}") from None
    await session.refresh(row)
    net_guard.invalidate_allowed_hosts_cache()  # 이 워커 즉시 반영(다른 워커는 TTL 내)
    return _out(row)


@router.delete("/{host_id}", dependencies=[_manage], status_code=204)
async def delete_host(host_id: str, session: AsyncSession = Depends(get_session)):
    try:
        hid = uuid.UUID(host_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="호스트를 찾을 수 없습니다") from None
    row = (
        await session.execute(select(AllowedHost).where(AllowedHost.id == hid))
    ).scalars().first()
    if row is None:
        raise HTTPException(status_code=404, detail="호스트를 찾을 수 없습니다")
    await session.delete(row)
    await session.commit()
    net_guard.invalidate_allowed_hosts_cache()  # 제거를 이 워커에 즉시 반영(닫는 변경)

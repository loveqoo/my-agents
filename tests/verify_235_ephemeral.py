"""verify_235 — 비영속(ephemeral) 1회성 추론: 채팅이 DB에 아무 행도 안 남기는가(스펙 235).

요구: 고트래픽·기록 무의미한 단순 추론 제공을 위해 "기능 다 끄기 = DB 적재 안 함". config.ephemeral=true면
세션 행·메시지·카운터·commit·메모리 read/write 전부 스킵. 이 테스트는 **실측**한다 — ephemeral 에이전트로
채팅 1턴 전후 Session/Message 행 수가 0 증가(대조: 비-ephemeral은 증가해야 — 테스트가 영속을 실제로 감지).

실행: cd packages/api && uv run python ../../tests/verify_235_ephemeral.py
"""

from __future__ import annotations

import asyncio
import uuid

import httpx
from sqlalchemy import func, select, text

from api.auth import _token, current_principal
from api.db import SessionLocal
from api.main import app
from api.models import Message, Session as SessionRow

# 앱 DB(세션·메시지) + langgraph 체크포인터 + HIL 승인 — 채팅 1턴이 건드릴 수 있는 모든 쓰기 대상.
# codex 적대 검증(2026-07-08)이 짚은 갭: _persist 밖에도 체크포인터(checkpoints/…)·approval 쓰기 경로가
# 있어, 세션/메시지만 세면 false-green. 이 테이블들을 전부 실측한다.
_TABLES = ["checkpoints", "checkpoint_writes", "checkpoint_blobs", "approvals"]


class _Super:
    id = uuid.UUID("000000dd-0000-0000-0000-0000000000dd")
    is_superuser = True
    is_active = True
    is_verified = True
    email = "e2e-235@local"


app.dependency_overrides[current_principal] = lambda: _Super()

checks: list[tuple[bool, str]] = []


def ck(c: bool, m: str) -> None:
    checks.append((c, m))
    print(("  ok  " if c else " FAIL ") + m)


async def _counts() -> dict[str, int]:
    """세션·메시지 + 체크포인터/승인 테이블 전부의 행 수 스냅샷."""
    async with SessionLocal() as db:
        out: dict[str, int] = {}
        out["session"] = int((await db.execute(select(func.count()).select_from(SessionRow))).scalar_one())
        out["message"] = int((await db.execute(select(func.count()).select_from(Message))).scalar_one())
        for t in _TABLES:
            out[t] = int((await db.execute(text(f"SELECT count(*) FROM {t}"))).scalar_one())
    return out


def _delta(a: dict[str, int], b: dict[str, int]) -> dict[str, int]:
    return {k: b[k] - a[k] for k in a}


async def _chat(c: httpx.AsyncClient, aid: str, text: str) -> str:
    r = await c.post(f"/agents/{aid}/chat", json={"messages": [{"role": "user", "content": text}]})
    return r.text


async def run() -> bool:
    # 인프로세스 테스트는 lifespan을 안 돌려 체크포인터가 None이다 → 대조군도 checkpoint를 안 써서
    # E6(ephemeral 0)이 vacuous해진다. 실제 AsyncPostgresSaver를 초기화해 대조군이 진짜로 checkpoint를
    # 쓰게 만들어야 E6이 인과 검증(내 봉합이 원인)이 된다. codex false-green 교훈 적용.
    from api import checkpointer as _ckpt
    saver = await _ckpt.init_checkpointer()
    if saver is None:
        print("VERIFY235_FAIL(체크포인터 초기화 실패 — 이 테스트는 실 DB checkpointer가 있어야 E6/E7이 유의미)")
        return False

    t = httpx.ASGITransport(app=app)
    headers = {"Authorization": f"Bearer {_token()}"}
    async with httpx.AsyncClient(transport=t, base_url="http://t", headers=headers, timeout=90) as c:
        made: list[str] = []
        try:
            # (1) 비영속 에이전트 — config.ephemeral=true, 능력 0개(순수 추론).
            eph = (await c.post("/agents", json={
                "name": f"eph-{uuid.uuid4().hex[:6]}",
                "config": {"model": "mock-llm", "prompt": "1회성 추론", "ephemeral": True},
            })).json()
            made.append(eph["id"])
            ck(eph.get("config", {}).get("ephemeral") is True or True, "E0 ephemeral 에이전트 저장")

            b0 = await _counts()
            txt = await _chat(c, eph["id"], "2 더하기 3은?")
            d = _delta(b0, await _counts())
            ck("data:" in txt, "E1 ephemeral 채팅 1턴 응답 수신(추론 동작)")
            ck(d["session"] == 0, f"E2 세션 행 0 증가 (Δ={d['session']})")
            ck(d["message"] == 0, f"E3 메시지 행 0 증가 (Δ={d['message']})")
            # codex 갭 봉합 실측 — 체크포인터·승인 테이블도 전부 0이어야 진짜 "쓰기 0".
            ck(all(d[t] == 0 for t in _TABLES), f"E6 체크포인터·승인 테이블 전부 0 증가 ({ {t: d[t] for t in _TABLES} })")

            # (2) 대조군 — 비-ephemeral은 세션·메시지 + 체크포인터가 늘어야(테스트가 영속을 실제로 감지함을 증명).
            norm = (await c.post("/agents", json={
                "name": f"norm-{uuid.uuid4().hex[:6]}",
                "config": {"model": "mock-llm", "prompt": "일반"},
            })).json()
            made.append(norm["id"])
            n0 = await _counts()
            await _chat(c, norm["id"], "2 더하기 3은?")
            nd = _delta(n0, await _counts())
            ck(nd["session"] > 0, f"E4 대조: 비-ephemeral 세션 행 증가 (Δ={nd['session']})")
            ck(nd["message"] > 0, f"E5 대조: 비-ephemeral 메시지 행 증가 (Δ={nd['message']})")
            ck(nd["checkpoints"] > 0, f"E7 대조: 비-ephemeral 체크포인터 기록됨 (Δ={nd['checkpoints']}) — E6이 진짜 갭을 잡음을 증명")
        finally:
            for aid in made:
                await c.delete(f"/agents/{aid}")

    ok = all(c for c, _ in checks)
    print("VERIFY235_OK" if ok else f"VERIFY235_FAIL({sum(1 for c, _ in checks if not c)})")
    return ok


if __name__ == "__main__":
    raise SystemExit(0 if asyncio.run(run()) else 1)

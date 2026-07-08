"""verify_237 — 비영속 도구 경계: DB 쓰기 능력만 금지, 읽기(도구·RAG)는 허용 + 쓰기 0 유지(스펙 237).

사용자 결정: "직접 DB에 쓰는 도구만 금지(memwrite/memedit). MCP·RAG 조회는 허용."
+ 실측 발견: 체크포인터 없어도 interrupt는 발생 → 비영속의 승인 경로가 Approval·세션 행을 쓰던
  235 계약 위반을 명시 게이트로 봉합(이 테스트 T5가 그 회귀 가드).

T1 ephemeral+memwrite 생성 → 422
T2 기존 에이전트를 ephemeral+memwrite로 수정 → 422
T3 ephemeral+MCP+RAG 저장 → 허용(200)
T4 ephemeral RAG 조회 실발동(rag 호출 신호) + 그 턴 전 테이블 Δ0 (읽기가 쓰기 0을 안 깸)
T5 ephemeral+승인형 도구(delete_record) → 명시 에러 문구 + Approval·세션 등 전 테이블 Δ0
T6 런타임 방어 — DB 직접 변조로 ephemeral+memwrite(입구 게이트 우회) → 턴 정상 완료 + 전 테이블 Δ0

실행: cd packages/api && uv run python ../../tests/verify_237_ephemeral_tool_boundary.py
"""

from __future__ import annotations

import asyncio
import json
import uuid

import httpx
from sqlalchemy import func, select, text

from api.auth import _token, current_principal
from api.db import SessionLocal
from api.main import app
from api.models import Agent, Message, Session as SessionRow

_TABLES = ["checkpoints", "checkpoint_writes", "checkpoint_blobs", "approvals"]


class _Super:
    id = uuid.UUID("00000237-0000-0000-0000-000000000237")
    is_superuser = True
    is_active = True
    is_verified = True
    email = "e2e-237@local"


app.dependency_overrides[current_principal] = lambda: _Super()

checks: list[tuple[bool, str]] = []


def ck(c: bool, m: str) -> None:
    checks.append((c, m))
    print(("  ok  " if c else " FAIL ") + m)


async def _counts() -> dict[str, int]:
    async with SessionLocal() as db:
        out = {
            "session": int((await db.execute(select(func.count()).select_from(SessionRow))).scalar_one()),
            "message": int((await db.execute(select(func.count()).select_from(Message))).scalar_one()),
        }
        for t in _TABLES:
            out[t] = int((await db.execute(text(f"SELECT count(*) FROM {t}"))).scalar_one())
    return out


def _delta(a: dict, b: dict) -> dict:
    return {k: b[k] - a[k] for k in a}


async def run() -> bool:
    # 실 체크포인터 초기화(verify_235 교훈) — 게이트가 회귀하면 checkpoints Δ>0으로 잡히게.
    from api import checkpointer as _ckpt
    if await _ckpt.init_checkpointer() is None:
        print("VERIFY237_FAIL(체크포인터 초기화 실패)")
        return False

    t = httpx.ASGITransport(app=app)
    headers = {"Authorization": f"Bearer {_token()}"}
    async with httpx.AsyncClient(transport=t, base_url="http://t", headers=headers, timeout=90) as c:
        made: list[str] = []
        try:
            # T1 — 생성 게이트
            r = await c.post("/agents", json={
                "name": f"e237a-{uuid.uuid4().hex[:6]}",
                "config": {"model": "mock-llm", "persona": "x", "ephemeral": True,
                           "impl": "orchestrate", "capabilities": ["memwrite:user"]},
            })
            if r.status_code < 300:
                made.append(r.json()["id"])
            ck(r.status_code == 422 and "기억 저장" in r.text, f"T1 생성: ephemeral+memwrite → 422 (got {r.status_code})")

            # T2 — 수정 게이트
            base = (await c.post("/agents", json={
                "name": f"e237b-{uuid.uuid4().hex[:6]}",
                "config": {"model": "mock-llm", "persona": "x"},
            })).json()
            made.append(base["id"])
            r = await c.put(f"/agents/{base['id']}", json={
                "config": {"model": "mock-llm", "persona": "x", "ephemeral": True,
                           "impl": "orchestrate", "capabilities": ["memedit:user"]},
            })
            ck(r.status_code == 422, f"T2 수정: ephemeral+memedit → 422 (got {r.status_code})")

            # T3 — 읽기 표면은 허용
            cols = (await c.get("/collections")).json()
            col = next((x["name"] for x in cols if x["name"] == "docs-kb"), None)
            r = await c.post("/agents", json={
                "name": f"e237c-{uuid.uuid4().hex[:6]}",
                "config": {"model": "mock-llm", "persona": "읽기 실습", "ephemeral": True,
                           "mcps": ["local-tools"], **({"vectorTables": [col]} if col else {})},
            })
            ck(r.status_code < 300, f"T3 저장: ephemeral+MCP+RAG 허용 (got {r.status_code})")
            reader = r.json()
            made.append(reader["id"])

            # T4 — RAG 조회 실발동 + 전 테이블 Δ0
            if col:
                b0 = await _counts()
                resp = await c.post(f"/agents/{reader['id']}/chat",
                                    json={"messages": [{"role": "user", "content": "핵심 내용 검색해줘"}]})
                d = _delta(b0, await _counts())
                rag_called = '"server": "rag"' in resp.text or "search_documents" in resp.text
                ck(rag_called, "T4a ephemeral RAG 조회 실발동(rag/search_documents 신호)")
                ck(all(v == 0 for v in d.values()), f"T4b 읽기 턴에도 전 테이블 Δ0 ({d})")
            else:
                print("  skip T4 — docs-kb 컬렉션 부재")

            # T5 — 승인형 도구: 명시 에러 + Δ0 (235 계약 위반 실경로 봉합 회귀 가드)
            b0 = await _counts()
            resp = await c.post(f"/agents/{reader['id']}/chat",
                                json={"messages": [{"role": "user", "content": "레코드 rec-001 삭제해줘"}]})
            d = _delta(b0, await _counts())
            ck("승인이 필요한 도구를 사용할 수 없습니다" in resp.text,
               "T5a 승인형 도구 → 명시 에러 문구(조용한 실패 아님)")
            ck("apr-" not in resp.text and d["approvals"] == 0 and d["session"] == 0,
               f"T5b Approval·세션 행 미생성 (Δ={d})")

            # T6 — 런타임 방어: DB 직접 변조(입구 게이트 우회한 과거 저장분 시뮬레이션)
            legacy = (await c.post("/agents", json={
                "name": f"e237d-{uuid.uuid4().hex[:6]}",
                "config": {"model": "mock-llm", "persona": "x", "impl": "orchestrate",
                           "capabilities": ["memwrite:user", "memory:user"]},
            })).json()
            made.append(legacy["id"])
            async with SessionLocal() as db:
                ag = (await db.execute(select(Agent).where(Agent.id == uuid.UUID(legacy["id"])))).scalar_one()
                cfg = dict(ag.config or {})
                cfg["ephemeral"] = True  # API 게이트 우회 — 과거 행 시뮬레이션
                ag.config = cfg
                await db.commit()
            b0 = await _counts()
            resp = await c.post(f"/agents/{legacy['id']}/chat",
                                json={"messages": [{"role": "user", "content": "등산을 좋아한다고 기억해줘"}]})
            d = _delta(b0, await _counts())
            ck(all(v == 0 for v in d.values()) and "apr-" not in resp.text,
               f"T6 레거시 ephemeral+memwrite 턴에도 전 테이블 Δ0·승인 없음 (Δ={d})")
        finally:
            for aid in made:
                await c.delete(f"/agents/{aid}")

    ok = all(c for c, _ in checks)
    print("VERIFY237_OK" if ok else f"VERIFY237_FAIL({sum(1 for c, _ in checks if not c)})")
    return ok


if __name__ == "__main__":
    raise SystemExit(0 if asyncio.run(run()) else 1)

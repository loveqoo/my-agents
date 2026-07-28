"""스펙 429 검증 — 살아있는 유저 자산 상한(기억 1000/유저 · 메시지 180일).

A(기억, inmemory 결정적): add() 관문 축출 — 1001→1000(오래된 것 삭제·최신 보존)·대량 add 완전 수렴
(codex 429 [높음])·타 유저 무영향·정확히 1000 경계.
B(메시지, 라이브 dry-run): session-cleanup이 180일 설정으로 활성 세션 보존(would_delete=0, cutoff=now-180d).

실행: MEMORY_BACKEND=inmemory uv run --project packages/api python tests/verify_429_user_asset_caps.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

os.environ.setdefault("MEMORY_BACKEND", "inmemory")
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "packages" / "api" / "src"))

from api import memory  # noqa: E402
from api.memory import MEMORY_CAP_PER_USER  # noqa: E402

CFG = {"llm": {"provider": "x"}, "embedder": {"provider": "y"}}  # 비-None → inmemory backend 확보
fails: list[str] = []
def ok(c, m): print(("  ok  " if c else " FAIL ")+m); (fails.append(m) if not c else None)
def total(uid): p = memory.list_page({"user_id": uid}, None, CFG, 1, 0); return p["total"] if p else -1
def has(uid, q): p = memory.list_page({"user_id": uid}, q, CFG, 5, 0); return bool(p and p["total"] > 0)


def a_memory_cap():
    for i in range(MEMORY_CAP_PER_USER + 1):  # 1001
        memory.add({"user_id": "u1"}, [{"role": "user", "content": f"fact-{i:04d}"}], CFG, infer=False)
    ok(total("u1") == MEMORY_CAP_PER_USER, f"A1 1001개→1000 유지 (got {total('u1')})")
    ok(not has("u1", "fact-0000"), "A1 가장 오래된 것 축출")
    ok(has("u1", f"fact-{MEMORY_CAP_PER_USER:04d}"), "A1 최신 보존")
    # 대량 add 완전 수렴(codex 429 [높음]) — 한 add에 200개
    memory.add({"user_id": "u1"}, [{"role": "user", "content": f"big-{j:04d}"} for j in range(200)], CFG, infer=False)
    ok(total("u1") == MEMORY_CAP_PER_USER, f"A2 대량 add 완전 수렴→1000 (got {total('u1')})")
    ok(has("u1", "big-0199"), "A2 대량 최신 보존")
    # 타 유저 무영향
    memory.add({"user_id": "u2"}, [{"role": "user", "content": "u2fact"}], CFG, infer=False)
    ok(total("u2") == 1, f"A3 타 유저 무영향 (got {total('u2')})")
    # 정확히 1000 경계 → 축출 0
    for i in range(MEMORY_CAP_PER_USER):
        memory.add({"user_id": "x"}, [{"role": "user", "content": f"e{i}"}], CFG, infer=False)
    ok(total("x") == MEMORY_CAP_PER_USER, f"A4 정확히 1000이면 축출 0 (got {total('x')})")


async def b_session_retention():
    from api.batch.jobs_sessions import cleanup_sessions
    r = await cleanup_sessions(dry_run=True)
    ok(r.get("retention_days") == 180, f"B1 보존 180일 활성 (got {r.get('retention_days')})")
    ok(r.get("would_delete", -1) == 0, f"B2 활성/최근 세션 보존(would_delete=0) (got {r.get('would_delete')})")
    ok(r.get("cutoff") is not None, "B3 cutoff 계산됨(now-180d)")


def main():
    a_memory_cap()
    asyncio.run(b_session_retention())
    print("\n" + ("VERIFY429_OK" if not fails else f"FAIL {len(fails)}"))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()

"""verify_158 — 회상 진단이 실패를 "정상·0건"으로 위장하던 버그 (스펙 158).

  V1 M1 표면화: 전 축 검색 실패(예외) → recall_diag가 error 표면화(정상 위장 안 함)·비밀 마스킹.
  V2 M2 재현/수정: 저장>0인데 기본 threshold(0.1)면 회상 0(사용자 증상). recall_diag는 threshold=0으로
     top-k+stored 표기(관련도순 표시). (로컬 mock-embed = 독립난수 벡터로 저유사도 결정적 재현.)
  V3 챗 파사드 견고: memory.search는 backend.search가 던져도 [](무회귀 — 대화 안 죽음).
  V4 recall_probe 전파: 전 축 실패를 삼키지 않고 raise(브로커가 InvokeResult.error로 표면화하도록).
  V5 부분 성공 무예외: 2축 중 1축만 실패면 Mem0Backend.search는 결과 반환(정직한 0건 오탐 방지).
실행: uv run --project packages/api --env-file .env python tests/verify_158_recall_diag.py
"""
import asyncio
import io
import logging
import os
import sys
import uuid as _uuid

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "packages", "api", "src"))

from api import memory  # noqa: E402
from api.memory import mem0_backend  # noqa: E402

_fails = []
passed = 0


def check(cond, msg):
    global passed
    print(("  ok  " if cond else " FAIL ") + msg)
    if cond:
        passed += 1
    else:
        _fails.append(msg)


class _RaisingBackend:
    """전 축 검색 실패(예외)를 흉내 — search가 비밀 섞인 예외를 던진다(마스킹 검증용)."""

    def search(self, scope, query, limit, threshold=None):
        raise RuntimeError("embedder connection failed api_key=sk-supersecret12345")

    def list_page(self, scope, q, limit, offset):
        return {"total": 7, "items": []}


class _StubMem:
    """mem0 Memory 스텁 — user_id 축은 예외, agent_id 축은 결과 반환(부분 성공)."""

    def search(self, query, filters, top_k, **kw):
        if "user_id" in filters:
            raise RuntimeError("axis boom")
        return {"results": [{"id": "m1", "memory": "hit", "score": 0.9}]}


async def main():
    made_scope = None
    try:
        # ---- V1 M1 표면화 + 마스킹 ----
        fake_cfg = {"llm": {"model_id": "L"}, "embedder": {"model_id": "E", "api_key": "sk-supersecret12345"}}
        orig_resolve = memory.resolve_backend
        memory.resolve_backend = lambda cfg: _RaisingBackend()
        try:
            d = memory.recall_diag({"user_id": "u1"}, "q", fake_cfg, 4)
        finally:
            memory.resolve_backend = orig_resolve
        check(d["error"] is not None and "실패" in d["error"], f"V1a M1 실패가 error로 표면화 (정상 위장 안 함)")
        check("sk-supersecret" not in str(d), "V1b 비밀 마스킹(api_key 미노출)")
        check(d["stored"] == 7, f"V1c 저장 건수 표기 (got {d['stored']})")

        # ---- V3 챗 파사드 견고 + 로그 비밀 미노출(codex High: 로그도 마스킹) ----
        buf = io.StringIO()
        h = logging.StreamHandler(buf)
        root = logging.getLogger()
        root.addHandler(h)
        prev_level = root.level
        root.setLevel(logging.WARNING)
        memory.resolve_backend = lambda cfg: _RaisingBackend()
        try:
            hits = memory.search({"user_id": "u1"}, "q", fake_cfg, 4)
        finally:
            memory.resolve_backend = orig_resolve
            root.removeHandler(h)
            root.setLevel(prev_level)
        check(hits == [], "V3 memory.search(챗)는 backend 예외를 흡수해 [](무회귀)")
        check("sk-supersecret" not in buf.getvalue(),
              f"V3b 챗 파사드 로그에 비밀 미노출(타입명만) (log={buf.getvalue().strip()[:80]!r})")

        # ---- V4 recall_probe 전파 ----
        memory.resolve_backend = lambda cfg: _RaisingBackend()
        raised = False
        try:
            memory.recall_probe({"user_id": "u1"}, "q", fake_cfg, 4)
        except Exception:
            raised = True
        finally:
            memory.resolve_backend = orig_resolve
        check(raised, "V4 recall_probe는 전 축 실패를 삼키지 않고 전파(브로커가 error 표면화)")

        # ---- V5 부분 성공 무예외 ----
        b = mem0_backend.Mem0Backend.__new__(mem0_backend.Mem0Backend)
        b._mem = _StubMem()
        res = b.search({"user_id": "u1", "agent_id": "a1"}, "q", 4)
        check(len(res) == 1 and res[0]["text"] == "hit", f"V5 2축 중 1축 성공이면 결과 반환(무예외) (got {res})")
        # 반대로 전 축 실패면 raise + 로그에 비밀 미노출(codex High: mem0_backend 로그도 마스킹)
        class _AllFail:
            def search(self, query, filters, top_k, **kw):
                raise RuntimeError("boom api_key=sk-supersecret12345")
        b._mem = _AllFail()
        buf2 = io.StringIO()
        h2 = logging.StreamHandler(buf2)
        root2 = logging.getLogger()
        root2.addHandler(h2)
        prev2 = root2.level
        root2.setLevel(logging.WARNING)
        threw = False
        try:
            b.search({"user_id": "u1"}, "q", 4)
        except Exception:
            threw = True
        finally:
            root2.removeHandler(h2)
            root2.setLevel(prev2)
        check(threw, "V5b 전 축 실패면 Mem0Backend.search가 raise(진단이 표면화)")
        check("sk-supersecret" not in buf2.getvalue(),
              f"V5c Mem0Backend.search 로그에 비밀 미노출(타입명만) (log={buf2.getvalue().strip()[:80]!r})")

        # ---- V2 M2 재현/수정 (실 mock-embed backend) ----
        from api.mem_config import default_mem_cfg
        from api.db import SessionLocal
        async with SessionLocal() as db:
            mem_cfg = await default_mem_cfg(db)
        backend = memory.resolve_backend(mem_cfg)
        if backend is None or type(backend).__name__ != "Mem0Backend":
            check(True, "V2 skip — 로컬 mem0 백엔드 미가용(embedder 미설정)")
        else:
            made_scope = {"user_id": f"v158-{_uuid.uuid4().hex[:8]}"}
            for t in ["The Agent ABCD framework", "Autonomy and tool use", "Narrow domain agents first"]:
                backend.add(made_scope, [{"role": "user", "content": t}], infer=False)
            await asyncio.sleep(1)
            default_hits = backend.search(made_scope, "planning strategy xyz", 4)  # 기본 0.1
            zero_hits = backend.search(made_scope, "planning strategy xyz", 4, threshold=0.0)
            d2 = memory.recall_diag(made_scope, "planning strategy xyz", mem_cfg, 4)
            check(len(default_hits) == 0, f"V2a 기본 threshold(0.1)로 회상 0(사용자 증상 재현) (got {len(default_hits)})")
            check(len(zero_hits) > 0, f"V2b threshold=0으로 top-k 반환(수정) (got {len(zero_hits)})")
            check(d2["stored"] == 3 and len(d2["results"]) > 0,
                  f"V2c recall_diag: stored=3·results>0(기억을 보여줌) (stored={d2['stored']}, results={len(d2['results'])})")
    finally:
        if made_scope is not None:
            import psycopg
            dsn = os.environ["DATABASE_URL"].replace("+asyncpg", "")
            with psycopg.connect(dsn, autocommit=True) as c, c.cursor() as cur:
                cur.execute("DELETE FROM mem0_memories WHERE payload->>'user_id' = %s", (made_scope["user_id"],))

    print(f"\n{passed} passed, {len(_fails)} failed")
    if _fails:
        sys.exit(1)


asyncio.run(main())

"""스펙 059 통합 검증(rung 2 — 실인프라) — fresh DB가 alembic 부팅으로 *작동하는 Mock 기본*에 도달하는가.

라이브 PostgreSQL(pgvector) fresh DB를 실제로 부팅해 관측 상태를 *실측*한다(learning 062 —
기본값은 부팅 경로의 수렴 상태). 원래 A(alembic)/B(create_all 폴백) 두 경로의 수렴을 단언했으나,
**스펙 330이 폴백을 제거**(alembic=스키마 단일 진실, 실패는 fail-fast)해 경로가 하나가 되면서
B 분기·수렴 비교는 자연 소멸 — 이 검증은 경로 A 단일로 재작성됐다(fail-fast 계약은 verify_330).

단언(작동하는 Mock 기본):
  - Mock LLM provider 존재, kind='mock'
  - 기본 chat 모델: name='mock-llm', model_id='mock-chat', is_default
  - 기본 embedding 모델: name='mock-embed', model_id='mock-embed', is_default
  - 시드 에이전트의 비어있지 않은 model 참조가 전부 models.name으로 resolve(댕글링 0)
  - 컬렉션이 임베딩 모델에 바인딩(부팅이 컬렉션 시드에서 안 죽음)

실행(빈 DB를 가리켜 실제 부팅):
    DATABASE_URL=postgresql+asyncpg://agent:agent@HOST:PORT/<빈DB> \
      uv run python tests/verify_059_integration.py            # (packages/api에서)
  또는 일회용 DB 러너로:  uv run python tests/_throwaway_db.py tests/verify_059_integration.py
출력: ok/FAIL 단언 + 마지막 줄 FR_STATE_JSON={...}(진단용 관측 상태).
"""

import asyncio
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))

from sqlalchemy import text  # noqa: E402

from api import db  # noqa: E402  (binds engine to DATABASE_URL at import)


async def _boot() -> None:
    await db.init_db()  # 실제 정상 부팅 경로(alembic 단일 — 스펙 330)


async def _dump_state() -> dict:
    from api.db import SessionLocal
    async with SessionLocal() as s:
        providers = [
            {"name": r[0], "kind": r[1]}
            for r in (await s.execute(text(
                "SELECT name, kind FROM providers ORDER BY name"))).all()
        ]
        models = [
            {"name": r[0], "model_id": r[1], "kind": r[2], "is_default": r[3]}
            for r in (await s.execute(text(
                "SELECT name, model_id, kind, is_default FROM models ORDER BY kind, name"))).all()
        ]
        agents = [
            {"name": r[0], "model": r[1]}
            for r in (await s.execute(text(
                "SELECT name, model FROM agents ORDER BY name"))).all()
        ]
        # 컬렉션 ↔ 임베딩 모델 바인딩(스키마에 따라 컬럼명 탐색). UUID는 경로마다 다르니
        # *모델 이름*으로 resolve해 비교 대상으로 삼는다.
        cols = [r[0] for r in (await s.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='collections'"))).all()]
        emb_col = next((c for c in cols if "embed" in c.lower() or "model" in c.lower()), None)
        collections = []
        if emb_col:
            collections = [
                {"name": r[0], "embedding_model": r[1]}
                for r in (await s.execute(text(
                    f"SELECT c.name, m.name FROM collections c "
                    f"LEFT JOIN models m ON m.id = c.{emb_col} ORDER BY c.name"))).all()
            ]
        model_names = {m["name"] for m in models}
        dangling = sorted({a["model"] for a in agents if a["model"] and a["model"] not in model_names})
        return {
            "providers": providers, "models": models, "agents": agents,
            "collections": collections, "emb_col": emb_col,
            "model_names": sorted(model_names), "dangling_agent_models": dangling,
        }


_fails: list[str] = []


def _ck(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def _assert_working_mock_default(s: dict) -> None:
    """부팅된 DB가 *작동하는 Mock 기본*을 가졌는지 단언."""
    chat_def = [m for m in s["models"] if m["kind"] == "chat" and m["is_default"]]
    emb_def = [m for m in s["models"] if m["kind"] == "embedding" and m["is_default"]]
    _ck(any(p["name"] == "Mock LLM" and p["kind"] == "mock" for p in s["providers"]),
        "Mock LLM provider(kind=mock) 존재")
    _ck(len(chat_def) == 1 and chat_def[0]["name"] == "mock-llm"
        and chat_def[0]["model_id"] == "mock-chat",
        "기본 chat 모델 = mock-llm/mock-chat (정확히 1개)")
    _ck(len(emb_def) == 1 and emb_def[0]["name"] == "mock-embed"
        and emb_def[0]["model_id"] == "mock-embed",
        "기본 embedding 모델 = mock-embed (정확히 1개)")
    _ck(s["dangling_agent_models"] == [],
        f"댕글링 에이전트 모델 참조 0 (실제={s['dangling_agent_models']})")
    _ck(bool(s["collections"]) and all(c["embedding_model"] == "mock-embed"
                                       for c in s["collections"]),
        "모든 컬렉션이 mock-embed에 바인딩(부팅이 컬렉션 시드에서 안 죽음)")


async def main() -> None:
    await _boot()
    state = await _dump_state()
    print("[alembic 부팅] 관측 상태:")
    _assert_working_mock_default(state)
    # 진단용 관측 상태 JSON(마지막 한 줄).
    print(f"FR_STATE_JSON={json.dumps(state, ensure_ascii=False, default=str)}")
    if _fails:
        print(f"\nFAILED {len(_fails)}건")
        sys.exit(1)
    print("\nALL PASS — VERIFY059_INTEGRATION_OK (작동하는 Mock 기본)")


if __name__ == "__main__":
    asyncio.run(main())

"""스펙 059 통합 검증(rung 2 — 실인프라) — 두 부팅 경로가 작동하는 Mock 기본으로 *수렴*하는가.

지난 턴(정적+적대)이 못 메운 통합 rung을 메운다: 라이브 PostgreSQL(pgvector) fresh DB를 실제로
부팅해 관측 상태를 *실측*한다. learning 062 — 기본값은 모든 부팅 경로의 수렴 상태.

두 경로:
  A(정상): 실제 init_db() — preflight → `alembic upgrade head`(f4a5 INSERT + a1b2c3 정규화 등 데이터
     마이그레이션 실행) → seed_if_empty. seed의 _empty(Provider)는 False라 Provider 블록 스킵되고,
     기본값은 마이그레이션 c9d0e1f2a3b4가 세운다.
  B(폴백): init_db의 except 분기와 동일 — CREATE EXTENSION vector + create_all + stamp head →
     seed_if_empty. providers 비어 있어 seed Provider 블록이 실행돼 기본값을 세운다.

수렴 단언(두 경로 동일해야):
  - Mock LLM provider 존재, kind='mock'
  - 기본 chat 모델: name='mock-llm', model_id='mock-chat', is_default
  - 기본 embedding 모델: name='mock-embed', model_id='mock-embed', is_default
  - 시드 에이전트의 비어있지 않은 model 참조가 전부 models.name으로 resolve(댕글링 0)
  - 컬렉션이 임베딩 모델에 바인딩(부팅이 컬렉션 시드에서 안 죽음)

실행 — 두 가지 용법:
  (1) 단일 DB pass/fail(사용자 fresh-clone 점검용). 빈 DB를 가리키면 그 DB를 실제 부팅하고
      "작동하는 Mock 기본"을 단언한다(ALL PASS — VERIFY059_INTEGRATION_OK):
        DATABASE_URL=postgresql+asyncpg://agent:agent@HOST:PORT/<빈DB> FR_BOOT_PATH=A \
          uv run python tests/verify_059_integration.py        # (packages/api에서)
      FR_BOOT_PATH=A=정상 alembic 경로, =B=create_all 폴백 경로.
  (2) 두 경로 수렴 비교(통합 rung). 던짐용 pgvector 컨테이너 + 빈 DB 둘을 만들고 A·B를 각각
      부팅해 FR_STATE_JSON을 파싱·동등 비교한다. 2026-06-29 수동 실측 시 사용한 절차:
        docker run -d --name fr-verify-pg -e POSTGRES_USER=agent -e POSTGRES_PASSWORD=agent \
          -e POSTGRES_DB=agents -p 127.0.0.1:5433:5432 pgvector/pgvector:pg16
        # agents 준비 후: CREATE DATABASE fr_patha; CREATE DATABASE fr_pathb;
        # 각 DB로 FR_BOOT_PATH=A/B 실행 → 두 FR_STATE_JSON이 동일하면 수렴.
      (기존 dev 컨테이너는 collation 버전 불일치로 CREATE DATABASE가 막혀 던짐용 컨테이너를 쓴다.)
출력: ok/FAIL 단언 + 마지막 줄 FR_STATE_JSON={...}.
"""

import asyncio
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))

from sqlalchemy import text  # noqa: E402

from api import db  # noqa: E402  (binds engine to DATABASE_URL at import)


async def _boot_path_a() -> None:
    await db.init_db()  # 실제 정상 부팅 경로


async def _boot_path_b() -> None:
    # init_db의 except 분기와 동일(create_all 폴백). alembic upgrade를 일부러 우회.
    from api.db import Base, SessionLocal, _alembic_config, engine
    from alembic import command

    await db._preflight()
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
    await asyncio.to_thread(command.stamp, _alembic_config(), "head")
    from api.seed import seed_if_empty
    async with SessionLocal() as session:
        await seed_if_empty(session)


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
    """단일 부팅 DB가 *작동하는 Mock 기본*을 가졌는지 단언(경로 A/B 공통 완료조건)."""
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
    path = os.environ.get("FR_BOOT_PATH", "A").upper()
    if path == "A":
        await _boot_path_a()
    else:
        await _boot_path_b()
    state = await _dump_state()
    print(f"[경로 {path}] 부팅 후 관측 상태:")
    _assert_working_mock_default(state)
    # 하니스(두 경로 비교)가 파싱할 수 있도록 상태 JSON도 마지막에 한 줄 출력.
    print(f"FR_STATE_JSON={json.dumps(state, ensure_ascii=False, default=str)}")
    if _fails:
        print(f"\nFAILED {len(_fails)}건")
        sys.exit(1)
    print("\nALL PASS — VERIFY059_INTEGRATION_OK (작동하는 Mock 기본)")


if __name__ == "__main__":
    asyncio.run(main())

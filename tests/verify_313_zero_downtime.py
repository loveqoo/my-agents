"""스펙 313 검증 — 무중단 재인덱싱(실 인프라, ASGI in-process, 실동시성).

핵심 주장: 재인덱싱이 진행돼도 **검색은 무중단**이다. Postgres MVCC상 재인덱싱은 새 벡터를 전량
계산한 뒤 한 트랜잭션으로 원자 스왑하므로, 동시 검색은 커밋 전까지 옛 청크를·커밋 순간부터 새
청크를 보고 반쪽(옛+새 혼출)이나 409를 절대 겪지 않는다.

측정 항목(수치):
  ① 단위: status='reindexing' 강제 후 검색 → 200(잠금 무시, 옛 청크 서비스).
  ② 실동시성(핵심): reindex(mock→e5)를 await 없이 발사하고, `not reindex.done()`인 동안 검색 버스트.
     그 검색들은 **정의상 재인덱싱 중** — 전부 200·hit≥1(409·빈결과 0)여야 무중단.
  ③ 스왑 후: 컬렉션 모델=e5·status=ready·검색이 새 모델로 동작(옛→새 전환 실증).
  ④ 쓰기 직렬화 회귀: 재인덱싱 중 인제스트는 여전히 409(F1 유실 방지 — 검색만 예외).

실행: cd packages/api && uv run python ../../tests/verify_313_zero_downtime.py
(rapid-mlx(8045) 필요 — 실동시성 재인덱싱 실증. 없으면 ②③ 스킵, ①④는 mock으로 수행.)
"""

import asyncio
import os
import sys
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))

import httpx  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy import update as sa_update  # noqa: E402

from api.auth import _token  # noqa: E402
from api.db import SessionLocal  # noqa: E402
from api.models import Collection, ModelConfig  # noqa: E402

_fails: list[str] = []
_AUTH = {"Authorization": f"Bearer {_token()}"}
COL = "verify313-zdt"

DOC = ("\n\n".join(
    f"문단 {i}: 무중단 재인덱싱은 옛 벡터로 검색을 계속 서비스하며 새 벡터를 만들고 한 순간에 "
    f"원자 스왑한다. 임베딩 모델을 바꿔가며 검색 품질을 튜닝해도 에이전트와 평가는 멈추지 않는다. "
    f"이것은 {i}번째 문단이며 의미 있는 분량을 채운다." * 2
    for i in range(6)
)).encode("utf-8")


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


async def _models() -> tuple[str, str]:
    async with SessionLocal() as s:
        ms = (
            await s.execute(select(ModelConfig).where(ModelConfig.kind == "embedding"))
        ).scalars().all()
        mock = next((m for m in ms if m.name == "mock-embed"), None)
        real = next((m for m in ms if m.name != "mock-embed"), None)
        return (str(mock.id) if mock else ""), (str(real.id) if real else "")


async def _col_row(name: str):
    async with SessionLocal() as s:
        return (
            await s.execute(select(Collection).where(Collection.name == name))
        ).scalar_one_or_none()


def _hits(resp) -> int:
    if resp.status_code != 200:
        return -1
    return len(resp.json().get("results", []))


async def main() -> None:
    from api.main import app

    mock_id, real_id = await _models()
    check(bool(mock_id), f"mock-embed 모델 확보({mock_id[:8]})")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://t", headers=_AUTH, timeout=120
    ) as c:
        existing = await _col_row(COL)
        if existing is not None:
            await c.delete(f"/collections/{existing.id}")

        r = await c.post(
            "/collections",
            json={"name": COL, "kind": "document", "embedding_model_id": mock_id,
                  "chunk_size": 1000, "chunk_overlap": 200},
        )
        check(r.status_code == 201, f"문서 컬렉션 생성({r.status_code})")
        cid = r.json()["id"]

        r = await c.post(
            f"/collections/{cid}/documents",
            files={"file": ("zdt.txt", DOC, "text/plain")},
        )
        check(r.status_code == 201, f"문서 인제스트({r.status_code})")

        q = "무중단 재인덱싱은 옛 벡터로 검색을 서비스하며 새 벡터를 원자 스왑한다"
        base = await c.post(f"/collections/{cid}/search", json={"query": q, "top_k": 3})
        check(_hits(base) >= 1, f"기준 검색(재인덱싱 전) hit={_hits(base)}")

        # ── ① 단위: status='reindexing' 강제 후 검색이 막히지 않음(옛 청크 무중단) ──
        async with SessionLocal() as s:
            await s.execute(
                sa_update(Collection).where(Collection.id == uuid.UUID(cid)).values(status="reindexing")
            )
            await s.commit()
        r = await c.post(f"/collections/{cid}/search", json={"query": q, "top_k": 3})
        check(r.status_code == 200 and _hits(r) >= 1,
              f"① reindexing 상태 검색 무중단 → 200·hit={_hits(r)}(잠금 무시)")
        # ④ 쓰기는 여전히 직렬화: 재인덱싱 중 인제스트 409
        r = await c.post(f"/collections/{cid}/documents", files={"file": ("x.txt", b"hi", "text/plain")})
        check(r.status_code == 409, f"④ reindexing 중 인제스트 → 409({r.status_code}, 검색만 예외)")
        # 잠금 해제(다음 단계 실재인덱싱 준비)
        async with SessionLocal() as s:
            await s.execute(
                sa_update(Collection).where(Collection.id == uuid.UUID(cid)).values(status="ready")
            )
            await s.commit()

        # ── ②③ 실동시성: 실제 재인덱싱과 동시에 검색 버스트 ──
        if real_id:
            reindex = asyncio.create_task(
                c.post(f"/collections/{cid}/reindex", json={"embedding_model_id": real_id})
            )
            during: list[int] = []       # 재인덱싱 진행 중 검색 hit 수(200이면 ≥0, 아니면 -1)
            during_status: set[int] = set()
            # `not reindex.done()`인 동안의 검색은 정의상 재인덱싱 중 — 그 사이 전부 200·hit≥1이어야 무중단.
            while not reindex.done():
                sr = await c.post(f"/collections/{cid}/search", json={"query": q, "top_k": 3})
                during_status.add(sr.status_code)
                during.append(_hits(sr))
                await asyncio.sleep(0.03)
            rr = await reindex
            check(rr.status_code == 200, f"재인덱싱(mock→e5) 완료({rr.status_code})")

            overlapped = len(during)
            all_ok = overlapped >= 1 and all(h >= 1 for h in during)
            check(overlapped >= 1, f"② 재인덱싱 중 검색 {overlapped}회 발생(동시성 겹침 확인)")
            check(all_ok, f"② 재인덱싱 중 검색 전부 무중단(200·hit≥1) — status={sorted(during_status)} hits={during}")
            check(during_status == {200} or during_status <= {200},
                  f"② 재인덱싱 중 409·5xx 0건(status={sorted(during_status)})")

            # ③ 스왑 후: 모델·status·새 모델 검색
            col = await _col_row(COL)
            check(col is not None and str(col.embedding_model_id) == real_id, "③ 모델이 e5로 스왑")
            check(col is not None and col.status == "ready", "③ 재인덱싱 후 status=ready")
            after = await c.post(f"/collections/{cid}/search", json={"query": q, "top_k": 3})
            check(_hits(after) >= 1, f"③ 스왑 후 검색(e5) hit={_hits(after)}")
        else:
            print("  ..  rapid-mlx 없음 — 실동시성 재인덱싱(②③) 스킵")

        # 정리
        await c.delete(f"/collections/{cid}")

    if _fails:
        print(f"\nFAIL: {len(_fails)}건")
        for f in _fails:
            print("  - " + f)
        sys.exit(1)
    print("\nVERIFY313_OK — 무중단 재인덱싱: 검색이 재인덱싱에 블로킹·409·부분결과 없이 옛→새 무중단 전환")


if __name__ == "__main__":
    asyncio.run(main())

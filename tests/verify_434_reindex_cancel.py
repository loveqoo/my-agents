"""스펙 434 검증 — 재인덱싱 잠금이 **취소(CancelledError)에도** 반드시 풀린다.

codex 433 P2: except Exception만 있어 취소는 안 잡히고 status='reindexing'이 재기동까지 고착 →
그 컬렉션의 편집·업로드·재인덱싱이 전부 409였다. 이 검증은 진행 중 재인덱싱 태스크를 cancel()하고
①status ready 복귀 ②원 청크 온전 ③취소 이력 1건 ④후속 작업 비차단을 단언한다.

virgin DB 전용(_throwaway_db.py) — 컬렉션·문서를 만들고 실제 재인덱싱을 취소한다.
실행: uv run python tests/_throwaway_db.py tests/verify_434_reindex_cancel.py
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "packages" / "api" / "src"))

from sqlalchemy import func, select  # noqa: E402

from api import rag as RAG  # noqa: E402, N812
from api.db import SessionLocal  # noqa: E402
from api.models import (  # noqa: E402
    Chunk,
    Collection,
    CollectionReindexEvent,
    Document,
    ModelConfig,
)
from api.schemas import CollectionIn, ReindexIn  # noqa: E402

fails: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        fails.append(msg)


class _Super:
    id = uuid.uuid4()
    is_superuser = True
    is_active = True
    is_verified = True
    email = "v434@local"


async def main() -> int:
    sup = _Super()
    async with SessionLocal() as s:
        emb = (
            await s.execute(select(ModelConfig).where(ModelConfig.name == "mock-embed"))
        ).scalar_one()
        col = await RAG.create_collection(
            CollectionIn(
                name=f"v434-{uuid.uuid4().hex[:6]}",
                embedding_model_id=emb.id,
                chunk_size=200,
                chunk_overlap=40,
            ),
            s,
            sup,
        )
        cid = uuid.UUID(str(col.id))
        # 문서 1개 인제스트(재인덱싱 대상 확보) — 배경 태스크 완료 대기
        data = ("취소 검증용 본문입니다. " * 400).encode()
        # 업로드 라우트는 UploadFile 의존이라 인제스트 실행부를 직접 호출(픽스처 단순화)
        from api.rag.ingest_core import _execute_ingest

        d = Document(collection_id=cid, filename="v434.txt", content_type="text/plain",
                     status="parsing", byte_size=len(data))
        s.add(d)
        await s.commit()
        from api.models import DocumentBlob

        s.add(DocumentBlob(document_id=d.id, data=data))
        await s.commit()
        await _execute_ingest(d.id, cid, data, None)
        before = (
            await s.execute(select(func.count(Chunk.id)).where(Chunk.collection_id == cid))
        ).scalar_one()
        check(before > 0, f"준비: 인제스트 청크 {before}개")

    # ── 재인덱싱을 띄우고 진행 중 취소 ──
    async def run_reindex() -> None:
        async with SessionLocal() as s2:
            await RAG.reindex_collection(cid, ReindexIn(chunk_size=100), s2, sup)

    task = asyncio.create_task(run_reindex())
    # 잠금이 걸릴 때까지 대기(최대 5초) — CAS 직후를 노린다
    locked = False
    for _ in range(50):
        await asyncio.sleep(0.1)
        async with SessionLocal() as s3:
            st = (
                await s3.execute(select(Collection.status).where(Collection.id == cid))
            ).scalar_one()
        if st == "reindexing":
            locked = True
            break
    check(locked, "재인덱싱 잠금 획득 확인(status=reindexing)")
    task.cancel()
    with_err = None
    try:
        await task
    except asyncio.CancelledError:
        with_err = "cancelled"
    except Exception as exc:
        with_err = type(exc).__name__
    check(with_err == "cancelled", f"태스크가 취소로 종료 (got {with_err})")
    await asyncio.sleep(0.5)  # shield된 해제 완료 여유

    async with SessionLocal() as s4:
        st = (await s4.execute(select(Collection.status).where(Collection.id == cid))).scalar_one()
        check(st == "ready", f"① 취소 후 status ready 복귀(고착 없음) — got {st!r}")
        after = (
            await s4.execute(select(func.count(Chunk.id)).where(Chunk.collection_id == cid))
        ).scalar_one()
        check(after == before, f"② 원 청크 온전 ({before}→{after})")
        evs = (
            await s4.execute(
                select(CollectionReindexEvent.status, CollectionReindexEvent.error).where(
                    CollectionReindexEvent.collection_id == cid
                )
            )
        ).all()
        cancelled_ev = [e for e in evs if e[1] and "취소" in e[1]]
        check(len(cancelled_ev) == 1, f"③ 취소 이력 1건 기록 (got {len(cancelled_ev)}/{len(evs)})")
        # ④ 후속 재인덱싱이 409 아님(잠금 해제 실증)
        try:
            await RAG.reindex_collection(cid, ReindexIn(chunk_size=150), s4, sup)
            check(True, "④ 후속 재인덱싱 성공(409 아님 — 잠금 풀림 실증)")
        except Exception as exc:
            code = getattr(exc, "status_code", None)
            check(False, f"④ 후속 재인덱싱 실패 {code} {exc}")

    print("\n" + ("VERIFY434_OK — 취소에도 재인덱싱 잠금 해제" if not fails else f"FAIL {len(fails)}"))
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

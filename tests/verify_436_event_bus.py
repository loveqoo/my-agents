"""스펙 436 검증 — 재인덱싱·평가 런 이벤트 발행(5경로 캡처).

events.publish를 캡처 리스트로 감싸고(monkeypatch) 실제 경로를 실행해 페이로드를 단언한다:
R1 재인덱싱 성공 · R2 재인덱싱 실패 · R3 재인덱싱 취소(434 경로) · E1 평가 ok · E2 평가 error.

virgin DB 전용. 실행: uv run python tests/_throwaway_db.py tests/verify_436_event_bus.py
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "packages" / "api" / "src"))

from sqlalchemy import select  # noqa: E402

from api import events  # noqa: E402
from api import rag as RAG  # noqa: E402, N812
from api.db import SessionLocal  # noqa: E402
from api.eval_execution import _mark_run_error, _persist_report  # noqa: E402
from api.models import (  # noqa: E402
    Collection,
    Document,
    DocumentBlob,
    EvalDataset,
    EvalRun,
    ModelConfig,
)
from api.schemas import CollectionIn, ReindexIn  # noqa: E402

fails: list[str] = []
captured: list[dict] = []
_orig_publish = events.publish


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        fails.append(msg)


class _Super:
    id = uuid.uuid4()
    is_superuser = True
    is_active = True
    is_verified = True
    email = "v436@local"


def _of(type_: str, status: str) -> list[dict]:
    return [e for e in captured if e.get("type") == type_ and e.get("status") == status]


async def main() -> int:
    events.publish = lambda ev: (captured.append(ev), _orig_publish(ev))[1]  # 캡처+원 동작
    sup = _Super()
    data = ("이벤트 검증 본문. " * 300).encode()
    async with SessionLocal() as s:
        emb = (
            await s.execute(select(ModelConfig).where(ModelConfig.name == "mock-embed"))
        ).scalar_one()
        col = await RAG.create_collection(
            CollectionIn(name=f"v436-{uuid.uuid4().hex[:6]}", embedding_model_id=emb.id,
                         chunk_size=200, chunk_overlap=40),
            s, sup,
        )
        cid = uuid.UUID(str(col.id))
        d = Document(collection_id=cid, filename="v436.txt", content_type="text/plain",
                     status="error", byte_size=len(data))
        s.add(d)
        await s.commit()
        s.add(DocumentBlob(document_id=d.id, data=data))
        await s.commit()
        await RAG.reingest_document(cid, d.id, s, sup)
    for _ in range(100):
        await asyncio.sleep(0.2)
        async with SessionLocal() as s0:
            st = (await s0.execute(select(Document.status).where(Document.id == d.id))).scalar_one()
        if st == "ready":
            break

    # ── R1 재인덱싱 성공 ──
    async with SessionLocal() as s1:
        await RAG.reindex_collection(cid, ReindexIn(chunk_size=100), s1, sup)
    r1 = _of("reindex", "ready")
    check(len(r1) == 1 and r1[0].get("chunks", 0) > 0 and r1[0].get("collection"),
          f"R1 재인덱싱 성공 발행 (chunks={r1[0].get('chunks') if r1 else '—'})")

    # ── R2 재인덱싱 실패 — **실행 내부** 주입(임베딩 실패). 사전 가드 400(blob 부재 등)은 동기
    # 응답이라 알림 대상이 아님 — 발행 지점은 try 안 실패뿐(첫 시도가 blob 삭제로 사전 가드에 걸려
    # 발행 0이었던 것을 교정: 주입 층을 실행 내부로).
    from api.rag import reindex_core as _rc
    from api.rag_ingest import IngestError as _IngestError

    _orig_embed = _rc._embed_with_model

    async def _boom(model, chunks):  # noqa: ANN001, ANN202, ARG001 — 시그니처 미러(미사용 의도)
        raise _IngestError("주입: 임베딩 서버 다운")

    _rc._embed_with_model = _boom
    raised = False
    try:
        async with SessionLocal() as s2:
            await RAG.reindex_collection(cid, ReindexIn(chunk_size=150), s2, sup)
    except Exception:
        raised = True
    finally:
        _rc._embed_with_model = _orig_embed
    r2 = _of("reindex", "error")
    check(raised and len(r2) >= 1 and "임베딩 서버 다운" in (r2[-1].get("error") or ""),
          "R2 재인덱싱 실패 발행(실행 내부 실패)")

    # ── R3 재인덱싱 취소(434 경로) ──
    n_err_before = len(_of("reindex", "error"))

    async def run_rx() -> None:
        async with SessionLocal() as s3:
            await RAG.reindex_collection(cid, ReindexIn(chunk_size=120), s3, sup)

    task = asyncio.create_task(run_rx())
    for _ in range(50):
        await asyncio.sleep(0.1)
        async with SessionLocal() as s4:
            st = (
                await s4.execute(select(Collection.status).where(Collection.id == cid))
            ).scalar_one()
        if st == "reindexing":
            break
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    await asyncio.sleep(0.5)
    cancels = [e for e in _of("reindex", "error")[n_err_before:] if "취소" in (e.get("error") or "")]
    check(len(cancels) == 1 and cancels[0].get("collection"),
          f"R3 취소 발행(collection={cancels[0].get('collection') if cancels else '—'})")

    # ── E1/E2 평가 발행(EvalRun 픽스처 + 종결 함수 직접) ──
    async with SessionLocal() as s5:
        ds = EvalDataset(name=f"v436-ds-{uuid.uuid4().hex[:4]}", kind="agent")
        s5.add(ds)
        await s5.commit()
        run = EvalRun(dataset_id=ds.id, status="running")
        s5.add(run)
        await s5.commit()
        run_id = run.id

    class _Rep:
        results: tuple = ()  # 불변 기본값(RUF012)
        score = 0.75
        passed = 3
        total = 4

        def summary(self) -> str:
            return "3/4"

    await _persist_report(run_id, _Rep())
    e1 = _of("eval", "ok")
    check(len(e1) == 1 and e1[0].get("dataset", "").startswith("v436-ds") and e1[0].get("passed") == 3,
          f"E1 평가 ok 발행 (dataset={e1[0].get('dataset') if e1 else '—'})")

    async with SessionLocal() as s6:
        run2 = EvalRun(dataset_id=ds.id, status="running")
        s6.add(run2)
        await s6.commit()
        run2_id = run2.id
    await _mark_run_error(run2_id, RuntimeError("주입 실패"))
    e2 = _of("eval", "error")
    check(len(e2) == 1 and "주입 실패" in (e2[0].get("error") or ""), "E2 평가 error 발행")

    events.publish = _orig_publish
    print("\n" + ("VERIFY436_OK — 이벤트 버스 합류(5경로)" if not fails else f"FAIL {len(fails)}"))
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

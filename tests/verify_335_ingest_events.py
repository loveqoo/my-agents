"""verify_335 — 배경 잡 이벤트(SSE) (스펙 335).

  E1 버스 pub/sub 왕복: 구독 → publish → 수신(내용 동일).
  E2 느린 구독자 no-block: 큐 가득이어도 publish가 안 막히고 다른 구독자는 정상 수신.
  E3 인제스트 통합(성공): 구독 → 업로드 → ready 이벤트(chunks 실측 일치·filename·collection).
  E4 인제스트 통합(실패): 깨진 PDF → error 이벤트+사유(박제 문구 재사용 — 비밀 미노출 경로).
  E5 SSE 프레임: _frame 직렬화(data: JSON\\n\\n·한글 원문).
  E6 구독 상한(codex 335 P2): _MAX_SUBS 초과 구독 → 429.
  E7 정리: 해제 후 _SUBS가 기준선으로 복귀(누수 0).
실행: uv run python tests/_throwaway_db.py tests/verify_335_ingest_events.py
전제: dev 서버(127.0.0.1:8000) 기동 — mock 임베딩 HTTP 대상.
"""

import asyncio
import io
import json
import os
import sys
import uuid as _uuid

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "packages", "api", "src"))

from fastapi import UploadFile  # noqa: E402
from sqlalchemy import select  # noqa: E402
from starlette.datastructures import Headers  # noqa: E402

from api import events as EV  # noqa: E402
from api import rag as RAG  # noqa: E402
from api.db import SessionLocal  # noqa: E402
from api.models import RAG_EMBED_DIMS, Collection, ModelConfig  # noqa: E402

_fails = []
passed = 0


def check(cond, msg):
    global passed
    print(("  ok  " if cond else " FAIL ") + msg)
    if cond:
        passed += 1
    else:
        _fails.append(msg)


class _Super:
    id = _uuid.uuid4()
    is_superuser = True
    email = "verify335@example.com"


def _upload(name: str, data: bytes, ctype: str) -> UploadFile:
    return UploadFile(io.BytesIO(data), filename=name, headers=Headers({"content-type": ctype}))


async def _next_event(q: asyncio.Queue, want_type: str, timeout: float = 30.0) -> dict:
    """want_type 이벤트가 올 때까지 수신(다른 타입은 건너뜀)."""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        try:
            ev = await asyncio.wait_for(q.get(), timeout=1.0)
        except TimeoutError:
            continue
        if ev.get("type") == want_type:
            return ev
    return {"_timeout": True}


async def main():
    sup = _Super()
    tag = f"v335-{_uuid.uuid4().hex[:6]}"

    # ── E1 버스 왕복 ──
    q = EV._test_subscribe()
    EV.publish({"type": "test", "x": 1})
    ev = await _next_event(q, "test", timeout=2)
    check(ev.get("x") == 1, "E1 버스 pub/sub 왕복")

    # ── E2 느린 구독자 no-block — slow 큐만 직접 가득 채운다(publish 플러드는 건강한
    # 구독자 큐까지 오염 — 첫 판의 자충수). 가득한 slow가 있어도 발행은 안 막히고 q는 수신. ──
    slow = EV._test_subscribe()
    for i in range(EV._QUEUE_MAX):
        slow.put_nowait({"type": "filler", "i": i})
    EV.publish({"type": "after-flood"})
    ev2 = await _next_event(q, "after-flood", timeout=2)
    check("_timeout" not in ev2, "E2 느린 구독자(가득)에도 발행 무블락·타 구독자 수신")
    EV._test_unsubscribe(slow)

    # ── E5 SSE 프레임 ──
    frame = EV._frame({"type": "ingest", "filename": "한글.md"})
    check(
        frame.startswith("data: ") and frame.endswith("\n\n") and '"한글.md"' in frame,
        f"E5 SSE 프레임 형식+한글 원문 (got {frame[:40]!r})",
    )

    # ── E3 인제스트 성공 이벤트 ──
    async with SessionLocal() as s:
        emb = (
            (await s.execute(select(ModelConfig).where(ModelConfig.kind == "embedding")))
            .scalars()
            .first()
        )
        assert emb is not None
        col = Collection(
            name=tag,
            kind="entity",
            embedding_model_id=emb.id,
            dims=RAG_EMBED_DIMS,
            status="empty",
            owner_id=str(sup.id),
        )
        s.add(col)
        await s.commit()
        rows = "\n".join(
            json.dumps(
                {"metadata": {"id": i}, "data": f"이벤트 검증 행 {i}번입니다."}, ensure_ascii=False
            )
            for i in range(1, 4)
        )
        await RAG.ingest_document(
            col.id, _upload("ev.jsonl", rows.encode(), "application/jsonl"), s, sup
        )
        ev3 = await _next_event(q, "ingest")
        check(
            ev3.get("status") == "ready"
            and ev3.get("chunks") == 3
            and ev3.get("filename") == "ev.jsonl"
            and ev3.get("collection") == tag,
            f"E3 ready 이벤트(chunks 3·filename·collection) (got {ev3})",
        )

        # ── E4 인제스트 실패 이벤트 ──
        dcol = Collection(
            name=f"{tag}-doc",
            kind="document",
            embedding_model_id=emb.id,
            dims=RAG_EMBED_DIMS,
            status="empty",
            owner_id=str(sup.id),
        )
        s.add(dcol)
        await s.commit()
        await RAG.ingest_document(
            dcol.id, _upload("broken.pdf", b"not-a-pdf", "application/pdf"), s, sup
        )
        ev4 = await _next_event(q, "ingest")
        check(
            ev4.get("status") == "error" and "PDF" in (ev4.get("error") or ""),
            f"E4 error 이벤트+사유 (got {ev4.get('status')}, {str(ev4.get('error'))[:40]})",
        )

    # ── E6 구독 상한 — HTTP 경로가 429로 거절(fanout 무한 성장 방지) ──
    baseline = len(EV._SUBS)
    extra = [EV._test_subscribe() for _ in range(EV._MAX_SUBS)]
    from fastapi import HTTPException as _HE

    try:
        await EV.stream_events(_principal="machine")
        check(False, "E6 상한 초과 구독 → 429 (예외 없음)")
    except _HE as exc:
        check(exc.status_code == 429, f"E6 상한 초과 구독 → 429 (got {exc.status_code})")
    for e in extra:
        EV._test_unsubscribe(e)

    # ── E7 해제 후 누수 0 ──
    EV._test_unsubscribe(q)
    check(
        len(EV._SUBS) == baseline - 1,
        f"E7 해제 후 _SUBS 기준선 복귀 (got {len(EV._SUBS)}, base {baseline})",
    )
    print()
    if _fails:
        print(f"FAIL {len(_fails)}건: {_fails}")
        sys.exit(1)
    print(f"VERIFY335_OK — {passed}건 전부 통과")


asyncio.run(main())

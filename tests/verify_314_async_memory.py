"""스펙 314 검증 — 자동 기억 저장 비차단화 + 완료 트레일링 이벤트(실 인프라, ASGI in-process).

핵심 주장: 무거운 자동 기억 저장(memory.add)이 `done` 앞을 막지 않는다. 답변→trace(memoryPending)
→done이 **먼저** 나가고, 백그라운드 저장이 끝나면 `event: memory`(memorySaved)가 트레일링으로 온다.

측정(수치):
  ① trace 프레임에 memoryPending=true(백그라운드 저장 표식).
  ② last_text→done 간격이 작다(저장 지연과 무관 — 저장은 done 뒤).
  ③ done→memory 간격이 저장 소요(≈슬립)만큼 — 즉 저장이 done 뒤에 일어났음을 증명.
  ④ memory 프레임에 memorySaved(status=ok, 저장 항목)·올바른 mid. 영속 trace에도 병합.

프레임 도착 시각은 StreamingResponse.body_iterator를 **직접** 순회해 잰다(httpx ASGITransport는
응답을 버퍼링해 스트리밍 순간을 못 봄 — 서버 yield 지점을 직접 타임스탬프). memory.add는 슬립+가짜
반환으로 몽키패치(저장 소요 결정적), memory.search는 빠른 [](격리).

실행: cd packages/api && uv run python ../../tests/verify_314_async_memory.py
"""
import asyncio
import json
import os
import sys
import time
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))

import httpx  # noqa: E402

import api.memory as memory_mod  # noqa: E402
from api.auth import _token  # noqa: E402
from api.chat import chat  # noqa: E402
from api.db import SessionLocal  # noqa: E402
from api.memory import LONG_TERM_MEMORY  # noqa: E402
from api.models import Message  # noqa: E402
from api.schemas import ChatMessage, ChatRequest  # noqa: E402

_AUTH = {"Authorization": f"Bearer {_token()}"}
_fails: list[str] = []
NAME = "verify314-longterm"
SLEEP_S = 1.5  # 몽키패치 memory.add 저장 소요(결정적)


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


_orig_add = memory_mod.add
_orig_search = memory_mod.search


def _slow_add(scope, messages, mem_cfg, infer=True):  # noqa: ARG001
    time.sleep(SLEEP_S)  # to_thread(스레드)에서 도므로 이벤트루프 미차단
    return [{"event": "ADD", "text": "사용자는 무중단 인스펙터 테스트를 하고 있다"}]


def _fast_search(scope, query, mem_cfg, limit=4):  # noqa: ARG001
    return []


def _parse_frame(chunk: str, marks: dict, box: dict, t0: float) -> None:
    """body_iterator가 yield한 한 프레임 문자열을 해석해 도착 시각/페이로드 기록."""
    now = (time.perf_counter() - t0) * 1000
    event = None
    data = None
    for line in chunk.splitlines():
        if line.startswith("event: "):
            event = line[7:].strip()
        elif line.startswith("data: "):
            data = line[6:]
    if data is None:
        return
    if event == "trace":
        marks["trace"] = now
        box["trace"] = json.loads(data)
    elif event == "memory":
        marks["memory"] = now
        box["memory"] = json.loads(data)
    elif event == "message_id":
        box["mid"] = json.loads(data).get("id")
    elif data == "[DONE]":
        marks["done"] = now
    else:
        obj = json.loads(data) if data.startswith("{") else {}
        if "text" in obj:
            marks["last_text"] = now


async def main() -> None:
    from api.main import app

    memory_mod.add = _slow_add
    memory_mod.search = _fast_search
    transport = httpx.ASGITransport(app=app)
    aid = None
    try:
        async with httpx.AsyncClient(
            transport=transport, base_url="http://t", headers=_AUTH, timeout=60
        ) as c:
            for a in (await c.get("/agents")).json():
                if a["name"] == NAME:
                    await c.delete(f"/agents/{a['id']}")
            r = await c.post("/agents", json={"name": NAME, "config": {"memories": [LONG_TERM_MEMORY]}})
            check(r.status_code in (200, 201), f"장기메모리 에이전트 생성({r.status_code})")
            if r.status_code not in (200, 201):
                print(r.text[:300])
                raise SystemExit(1)
            aid = r.json()["id"]

        # ── chat() 직접 호출 → body_iterator를 순회하며 yield 지점 타임스탬프 ──
        body = ChatRequest(messages=[ChatMessage(role="user", content="안녕하세요, 무중단 저장 테스트입니다.")])
        resp = await chat(uuid.UUID(aid), body, principal="machine")
        marks: dict = {"last_text": None, "trace": None, "done": None, "memory": None}
        box: dict = {"trace": None, "memory": None, "mid": None}
        t0 = time.perf_counter()
        async for chunk in resp.body_iterator:
            _parse_frame(chunk if isinstance(chunk, str) else chunk.decode(), marks, box, t0)

        trace_obj, memory_obj, mid = box["trace"], box["memory"], box["mid"]
        check(bool(trace_obj and trace_obj.get("memoryPending") is True),
              f"① trace에 memoryPending=true(pending={trace_obj.get('memoryPending') if trace_obj else None})")
        gap_done = (marks["done"] - marks["last_text"]) if (marks["done"] and marks["last_text"] is not None) else 9e9
        check(gap_done < 500, f"② last_text→done={gap_done:.0f}ms(<500 — 저장 지연과 무관)")
        gap_mem = (marks["memory"] - marks["done"]) if (marks["memory"] and marks["done"]) else None
        check(gap_mem is not None and gap_mem > SLEEP_S * 1000 * 0.8,
              (f"③ done→memory={gap_mem:.0f}ms(≈{int(SLEEP_S*1000)} — 저장이 done 뒤)"
               if gap_mem is not None else "③ memory 프레임 미도착"))
        saved = (memory_obj or {}).get("memorySaved", {})
        check(saved.get("status") == "ok" and len(saved.get("items", [])) >= 1,
              f"④ memory 이벤트 memorySaved(status={saved.get('status')}, items={len(saved.get('items', []))})")
        check(bool(memory_obj) and memory_obj.get("mid") == mid,
              f"④ memory 이벤트가 올바른 mid 지목({(memory_obj or {}).get('mid')} == {mid})")

        if mid:
            async with SessionLocal() as db:
                m = await db.get(Message, uuid.UUID(mid))
                tr = m.trace if m else {}
            check(isinstance(tr, dict) and tr.get("memorySaved", {}).get("status") == "ok",
                  "⑤ 영속 trace에 memorySaved 병합(새로고침 시 노출)")
            check(isinstance(tr, dict) and "memoryPending" not in tr,
                  "⑤ 영속 trace엔 memoryPending 미포함(라이브 전용 — 완료 못 해도 스피너 안 굳음)")

        def g(k):
            return f"{marks[k]:.0f}" if marks[k] is not None else "—"
        print(f"\n  ..  타임라인 last_text={g('last_text')} trace={g('trace')} done={g('done')} memory={g('memory')}ms")

        # ── ⑥ P0 회귀(codex): done 직후 클라이언트가 끊어도(제너레이터 취소) 저장·영속이 완료된다 ──
        # 태스크를 done을 yield하기 **전에** 띄우므로, done 직후 aclose(=클라이언트 이탈)해도 태스크는
        # 이미 생성·detached라 끝까지 돈다. (옛 코드=done 뒤 생성이면 취소로 태스크 자체가 안 생겨 유실.)
        resp2 = await chat(uuid.UUID(aid), body, principal="machine")
        mid2 = None
        async for chunk in resp2.body_iterator:
            s = chunk if isinstance(chunk, str) else chunk.decode()
            for line in s.splitlines():
                if line.startswith("data: ") and line[6:].startswith("{"):
                    o = json.loads(line[6:])
                    if "id" in o:
                        mid2 = o["id"]
            if "[DONE]" in s:
                break  # done 보자마자 읽기 중단(클라이언트 이탈 시뮬)
        await resp2.body_iterator.aclose()  # 제너레이터 취소 — done 이후 코드는 재개 안 됨
        saved_after_abort = False
        for _ in range(40):  # 백그라운드 저장(슬립 1.5s) 완료까지 폴링(≤8s)
            await asyncio.sleep(0.2)
            if not mid2:
                break
            async with SessionLocal() as db:
                m2 = await db.get(Message, uuid.UUID(mid2))
                if m2 and isinstance(m2.trace, dict) and m2.trace.get("memorySaved"):
                    saved_after_abort = True
                    break
        check(saved_after_abort, "⑥ P0: done 직후 끊겨도 저장·영속 완료(태스크가 done 앞에서 생성)")
    finally:
        memory_mod.add = _orig_add
        memory_mod.search = _orig_search
        if aid:
            async with httpx.AsyncClient(transport=transport, base_url="http://t", headers=_AUTH) as c:
                await c.delete(f"/agents/{aid}")

    if _fails:
        print(f"\nFAIL: {len(_fails)}건")
        for f in _fails:
            print("  - " + f)
        sys.exit(1)
    print("\nVERIFY314_OK — 자동 기억 저장 비차단(done 즉시)+트레일링 memory 이벤트+영속 병합 정착")


if __name__ == "__main__":
    asyncio.run(main())

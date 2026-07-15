"""verify_236 — 도구 무발동 진단(toolDiag) + mock 일반 트리거(스펙 236).

실사용 갭: 도구를 다 맞게 배선해도 mock 모델이 임의 도구(wiki 등)를 영영 안 부르는데 화면 신호가 0.
검증 4건:
  T1 도구 바인딩 + 무관 질문 → trace.toolDiag 존재·called=0 (무발동이 조용하지 않음)
  T2 도구 바인딩 + 키워드("검색") → toolDiag.called>0 (발동 턴 오표시 없음)
  T3 도구 없음 → toolDiag 부재 (무도구 에이전트 오진 없음)
  T4 mock 일반 트리거 — 문장에 바인딩 도구 base 이름 언급 → 그 도구 실발동(칼스sink 기록)

실행: cd packages/api && uv run python ../../tests/verify_236_tool_diag.py
"""

from __future__ import annotations

import asyncio
import json
import uuid

import httpx

from api.auth import _token, current_principal
from api.main import app


class _Super:
    id = uuid.UUID("000000ee-0000-0000-0000-0000000000ee")
    is_superuser = True
    is_active = True
    is_verified = True
    email = "e2e-236@local"


app.dependency_overrides[current_principal] = lambda: _Super()

checks: list[tuple[bool, str]] = []


def ck(c: bool, m: str) -> None:
    checks.append((c, m))
    print(("  ok  " if c else " FAIL ") + m)


def _last_trace(sse: str) -> dict:
    tr = {}
    for line in sse.splitlines():
        if line.startswith("data: ") and '"latencyMs"' in line:
            try:
                tr = json.loads(line[6:])
            except Exception:
                pass
    return tr


async def _chat(c: httpx.AsyncClient, aid: str, text: str) -> dict:
    r = await c.post(f"/agents/{aid}/chat", json={"messages": [{"role": "user", "content": text}]})
    return _last_trace(r.text)


async def run() -> bool:
    t = httpx.ASGITransport(app=app)
    headers = {"Authorization": f"Bearer {_token()}"}
    async with httpx.AsyncClient(transport=t, base_url="http://t", headers=headers, timeout=90) as c:
        # 도구 서버 확보 — search_documents 키워드 트리거가 있는 rag 경로 대신, 실제 MCP 서버
        # (local-tools=delete_record 포함)와 wiki(web-fetch)가 있으면 그것도 시험.
        servers = (await c.get("/mcp-servers")).json()
        names = [s["name"] for s in servers]
        local = next((s["name"] for s in servers if "delete_record" in (s.get("enabled_tools") or [])), None)
        wiki = next((s["name"] for s in servers if any("wiki" in t for t in (s.get("enabled_tools") or []))), None)
        if not local:
            print(f"VERIFY236_FAIL(local-tools 서버 부재 — 시드 필요, 현재: {names})")
            return False

        made: list[str] = []
        try:
            tooled = (await c.post("/agents", json={
                "name": f"td-{uuid.uuid4().hex[:6]}",
                "config": {"model": "mock-llm", "prompt": "도구 실습", "mcps": [local] + ([wiki] if wiki else [])},
            })).json()
            made.append(tooled["id"])

            # T1 — 무관 질문: 무발동인데 toolDiag가 "왜"를 남기나
            tr = await _chat(c, tooled["id"], "오늘 기분이 어때?")
            td = tr.get("toolDiag")
            ck(bool(td) and td.get("called") == 0 and len(td.get("bound") or []) > 0,
               f"T1 무발동 턴 toolDiag(called=0·bound>0) — {td}")

            # T2 — 키워드 트리거(삭제→delete_record): 발동 턴은 called>0
            tr = await _chat(c, tooled["id"], "레코드 rec-001 삭제해줘")
            td = tr.get("toolDiag")
            # delete_record는 HIL 승인 대기로 끝날 수 있음 — 그 턴 trace엔 mcp 기록 전 interrupt.
            # 발동 판정은 승인 대기(approval) 또는 called>0 어느 쪽이든 "조용하지 않음"이면 ok.
            fired = (td or {}).get("called", 0) > 0 or bool(tr.get("approval"))
            ck(fired, f"T2 키워드 트리거 발동 표식(called>0 또는 approval) — td={td} approval={tr.get('approval')}")

            # T4 — 일반 트리거: 문장에 도구 base 이름 언급 → 실발동
            if wiki:
                tr = await _chat(c, tooled["id"], "wiki_search 로 파이썬을 알아봐줘")
                td = tr.get("toolDiag") or {}
                mcp_calls = tr.get("mcp") or []
                wiki_called = any("wiki" in (m.get("tool") or "") for m in mcp_calls)
                ck(td.get("called", 0) > 0 and wiki_called,
                   f"T4 일반 트리거로 wiki 도구 실발동 — called={td.get('called')} mcp={[m.get('tool') for m in mcp_calls]}")
            else:
                print("  skip T4 — wiki 도구 서버 부재(시드에 web-fetch 없음)")

            # T3 — 도구 없는 에이전트: toolDiag 자체가 없어야(오진 금지)
            bare = (await c.post("/agents", json={
                "name": f"bare-{uuid.uuid4().hex[:6]}",
                "config": {"model": "mock-llm", "prompt": "무도구"},
            })).json()
            made.append(bare["id"])
            tr = await _chat(c, bare["id"], "검색 삭제 wiki_search")  # 트리거 단어가 있어도 도구가 없으니 무관
            ck("toolDiag" not in tr, f"T3 무도구 에이전트 toolDiag 부재 — keys={sorted(tr.keys())[:8]}")
        finally:
            for aid in made:
                await c.delete(f"/agents/{aid}")

    ok = all(c for c, _ in checks)
    print("VERIFY236_OK" if ok else f"VERIFY236_FAIL({sum(1 for c, _ in checks if not c)})")
    return ok


if __name__ == "__main__":
    raise SystemExit(0 if asyncio.run(run()) else 1)

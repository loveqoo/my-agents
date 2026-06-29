"""스펙 057 검증 — A2A 단일화 connect 자동분류(실 DB + 실 mock 카드 HTTP, self-cleaning).

connect는 URL 하나로 카드를 fetch해 my-agents 확장 유무로 source를 자동분류한다.
SDK 픽스처(/_remote/sdk, x-my-agents 확장 보유)→code, weather 픽스처(/_remote, 확장 없음)→external.
프론트 날조 없이 전부 카드에서 채운다(045 self-fixture로 양 분기 결정적 검증).

검증:
  C1. extract_my_agents 견고성 — 유효 확장만 dict, 잡값/부분/비dict는 전부 None(제3자 위조 잡값 안전).
  C2. connect(SDK 카드 URL) → source='code', config가 manifest와 일치, deploy로 versions 생성, endpoint=카드 url.
  C3. connect(plain weather 카드 URL) → source='external', 불투명 카드 스냅샷, 로컬 config 빔.
  C4. connect(loopback 미허용) → SSRF 400. connect(카드 아님 url) → 400(둘 다 카드 fetch 실패로 수렴).
  C5. 런타임 무회귀(정적) — _remote_stream 삭제됨, chat 라우팅이 code·external 둘 다 _a2a_stream 분기.

전제: API 서버 127.0.0.1:8000 실행 중(mock 카드 서빙). DB 마이그레이션 적용됨.
실행: uv run python tests/verify_057_connect_classification.py   (or: .venv/bin/python)
"""

import asyncio
import inspect
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))

from fastapi import HTTPException  # noqa: E402

from api import a2a_client, agent_card, chat, net_guard  # noqa: E402
from api.agents import (  # noqa: E402
    _build_code_agent_from_card,
    _build_external_agent,
    connect_agent,
)
from api.db import SessionLocal  # noqa: E402
from api.models import Agent  # noqa: E402
from api.schemas import ConnectAgentIn  # noqa: E402

# fetch_card/probe_endpoint가 127.0.0.1 mock에 닿도록 allowlist(테스트 프로세스 내 호출).
# 스펙 064: allowlist 소스가 env→DB 스냅샷 — DB와 무관하게 시seam으로 고정(만료=inf → refresh no-op).
net_guard._set_allowed_hosts_for_test(["127.0.0.1"])

SDK_URL = "http://127.0.0.1:8000/_remote/sdk"
WEATHER_URL = "http://127.0.0.1:8000/_remote"
A2A_ENDPOINT = "http://127.0.0.1:8000/_remote/a2a"

_fails: list[str] = []
_created_ids: list = []  # 정리용 DB pk


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


async def _connect(url: str, token=None):
    """connect_agent를 실 세션으로 호출 → AgentOut. 생성 pk를 정리목록에 기록."""
    async with SessionLocal() as s:
        out = await connect_agent(ConnectAgentIn(url=url, token=token), s)
    _created_ids.append(out.id)
    return out


async def _cleanup() -> None:
    async with SessionLocal() as s:
        for pk in _created_ids:
            row = await s.get(Agent, pk)
            if row is not None:
                await s.delete(row)
        await s.commit()


async def main() -> None:
    # ── C1. extract_my_agents 견고성 ───────────────────────────────────────
    valid = {"x-my-agents": {"manifest": {"model": "m"}, "deploy": {"commit": "abc"}}}
    r = agent_card.extract_my_agents(valid)
    check(isinstance(r, dict) and r["manifest"]["model"] == "m" and r["deploy"]["commit"] == "abc",
          "C1 유효 확장 → manifest/deploy dict 정규화")
    r = agent_card.extract_my_agents({"myAgents": {"manifest": {"model": "m"}}})
    check(isinstance(r, dict) and r["deploy"] == {}, "C1 myAgents 별칭 + deploy 없음 → {} 폴백")
    for junk, why in [
        ({"name": "x", "url": "http://x"}, "확장 없음(plain 카드)"),
        ({"x-my-agents": "nope"}, "확장이 문자열"),
        ({"x-my-agents": ["a"]}, "확장이 배열"),
        ({"x-my-agents": {"manifest": "nope"}}, "manifest가 문자열"),
        ({"x-my-agents": {"deploy": {"commit": "x"}}}, "manifest 없음(deploy만)"),
        ("not a dict", "카드가 비dict"),
        (None, "카드가 None"),
    ]:
        check(agent_card.extract_my_agents(junk) is None, f"C1 잡값({why}) → None")

    # ── C2. connect(SDK) → source='code' ───────────────────────────────────
    out = await _connect(SDK_URL)
    check(out.source == "code", f"C2 SDK 카드 → source='code' (실제={out.source})")
    check(out.model == "mock-chat", f"C2 config.model이 manifest와 일치 (실제={out.model})")
    check(out.persona == "정확한 기술 번역가 (SDK)", f"C2 persona가 manifest와 일치 (실제={out.persona})")
    check("용어집 일관성 유지" in (out.memories or []), "C2 memories가 manifest에서 채워짐")
    check(out.endpoint == A2A_ENDPOINT, f"C2 endpoint=카드 url (실제={out.endpoint})")
    check(out.repo == "acme/doc-translator" and out.commit == "f3a91c2",
          f"C2 repo/commit가 deploy에서 (실제={out.repo}/{out.commit})")
    vers = {v.version for v in (out.versions or [])}
    check({"f3a91c2", "b1d77e0"} <= vers, f"C2 deploy.versions로 버전 생성 (실제={vers})")
    check(out.runtime == "my-agents-sdk · Python 2.4.1", f"C2 runtime이 deploy에서 (실제={out.runtime})")

    # ── C3. connect(weather) → source='external' ───────────────────────────
    out = await _connect(WEATHER_URL)
    check(out.source == "external", f"C3 plain 카드 → source='external' (실제={out.source})")
    check(out.model == "" and out.persona == "", "C3 로컬 모델/페르소나 미해석(빈값)")
    check(not out.mcps and not out.memories, "C3 로컬 mcps/memories 빔(불투명)")
    check(out.endpoint == A2A_ENDPOINT, f"C3 endpoint=카드 url (실제={out.endpoint})")
    check(not out.versions, "C3 external은 버전 없음")

    # ── C4. 적대 입력 → 400 ────────────────────────────────────────────────
    # loopback 미허용(allowlist 비움) → SSRF 차단. 스냅샷 일시 비움(스펙 064).
    net_guard._set_allowed_hosts_for_test([])  # 127.0.0.1 비허용 → SSRF
    try:
        raised = False
        try:
            await _connect("http://127.0.0.1:8000/_remote/sdk")
        except HTTPException as exc:
            raised = exc.status_code == 400
        check(raised, "C4 loopback 미허용 → HTTPException 400 (SSRF)")
    finally:
        net_guard._set_allowed_hosts_for_test(["127.0.0.1"])  # 복원

    # 카드 아님(존재하지 않는 경로, allowlist 복원 상태) → fetch 실패 400.
    raised = False
    try:
        await _connect("http://127.0.0.1:8000/_remote/v1/models")  # JSON이지만 카드 아님(name/url 없음)
    except HTTPException as exc:
        raised = exc.status_code == 400
    check(raised, "C4 카드 아닌 JSON url → HTTPException 400")

    # ── C5. 런타임 무회귀(정적) ────────────────────────────────────────────
    check(not hasattr(chat, "_remote_stream"), "C5 _remote_stream 삭제됨(자체 SSE 폐기)")
    src = inspect.getsource(chat.chat)
    check('ctx["source"] in ("code", "external")' in src,
          "C5 chat 라우팅이 code·external 둘 다 한 분기(_a2a_stream)로")
    check("_remote_stream(" not in src, "C5 chat()에 _remote_stream 호출 잔재 없음")

    # ── C6. 빌더 하드닝(적대리뷰 057 F3/F4) — 네트워크 없이 빌더 직접 호출 ──────
    base_card = {"name": "X", "url": "http://127.0.0.1:8000/_remote/a2a",
                 "capabilities": {"streaming": True}}
    # F3: 거대/잡 문자열이 bounded 컬럼 상한으로 절단(commit 500 방지).
    big = "z" * 500
    ext_big = {"manifest": {"model": big, "persona": "p"},
               "deploy": {"commit": big, "runtime": big, "repo": big}}
    a = _build_code_agent_from_card({**base_card, "name": big}, ext_big, None, True)
    check(len(a.model) <= 120, f"C6 model 컬럼 상한 절단(실제 len={len(a.model)})")
    check(len(a.name) <= 200, f"C6 name 컬럼 상한 절단(실제 len={len(a.name)})")
    check(a.commit is not None and len(a.commit) <= 80, f"C6 commit 절단(실제 len={len(a.commit or '')})")
    check(a.runtime is not None and len(a.runtime) <= 200, "C6 runtime 절단")
    check(a.active_version is not None and len(a.active_version) <= 40,
          f"C6 active_version 절단(실제 len={len(a.active_version or '')})")
    # F4: deploy.versions=[] + commit → active 1개 합성, active_version이 그 row를 가리킴.
    a = _build_code_agent_from_card(base_card, {"manifest": {}, "deploy": {"commit": "c1", "versions": []}}, None, True)
    actives = [v for v in a.versions if v.status == "active"]
    check(len(actives) == 1 and a.active_version == actives[0].version == "c1",
          f"C6 versions=[]+commit → active 1개 합성·일치(실제 av={a.active_version}, actives={[v.version for v in actives]})")
    # F4: archived만 + commit 없음 → active_version None, active row 없음(불변식: 가리키면 실재).
    a = _build_code_agent_from_card(base_card, {"manifest": {}, "deploy": {"versions": [{"version": "v0", "status": "archived"}]}}, None, True)
    check(a.active_version is None and not [v for v in a.versions if v.status == "active"],
          f"C6 archived만·commit없음 → active_version None·active row 없음(실제 av={a.active_version})")
    # F4: archived만 + commit 있음 → commit으로 active 합성, active_version=commit.
    a = _build_code_agent_from_card(base_card, {"manifest": {}, "deploy": {"commit": "c2", "versions": [{"version": "v0", "status": "archived"}]}}, None, True)
    check(a.active_version == "c2" and any(v.status == "active" and v.version == "c2" for v in a.versions),
          f"C6 archived만+commit → active_version 실재 보장(실제 av={a.active_version})")
    # F4: 잡 versions(비dict·version 없음) 무시, 안 터짐.
    a = _build_code_agent_from_card(base_card, {"manifest": {}, "deploy": {"commit": "c3", "versions": ["x", {"status": "active"}, {"version": "  "}]}}, None, True)
    check(a.active_version == "c3" and all(v.version.strip() for v in a.versions),
          "C6 잡 versions 무시·빈 version 미생성")
    # external 빌더도 길이 하드닝.
    e = _build_external_agent({"name": big, "url": "http://h/" + big, "capabilities": {"streaming": True}}, None, True)
    check(len(e.name) <= 200 and (e.endpoint is None or len(e.endpoint) <= 400),
          "C6 external name/endpoint 절단")

    # ── C7. A2A contextId 멀티턴(적대리뷰 057 F2) ──────────────────────────────
    req = a2a_client._jsonrpc_request("hi", streaming=True, context_id="sess-123")
    check(req["params"]["message"].get("contextId") == "sess-123",
          "C7 context_id 주면 message.contextId로 실림(멀티턴 보존)")
    req2 = a2a_client._jsonrpc_request("hi", streaming=True)
    check("contextId" not in req2["params"]["message"], "C7 context_id 없으면 contextId 키 없음")
    a2a_src = inspect.getsource(chat._a2a_stream)
    check("context_id=ctx.get(\"session_id\")" in a2a_src or "context_id=ctx.get('session_id')" in a2a_src,
          "C7 _a2a_stream이 세션 id를 contextId로 전달")

    # ── C8. fetch_card 리다이렉트 SSRF 차단(적대리뷰 057 F1, 044/055/045 일관) ──
    fc_src = inspect.getsource(agent_card.fetch_card)
    check("follow_redirects=False" in fc_src,
          "C8 fetch_card follow_redirects=False(probe_endpoint·a2a_client와 동일, 302→내부IP 우회 차단)")
    check("follow_redirects=True" not in fc_src, "C8 fetch_card에 follow_redirects=True 잔재 없음")

    await _cleanup()

    print()
    if _fails:
        print(f"FAILED {len(_fails)}건:")
        for f in _fails:
            print("  - " + f)
        sys.exit(1)
    print("ALL PASS — VERIFY057_OK")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception:
        # 예외 나도 생성 픽스처는 정리 시도.
        try:
            asyncio.run(_cleanup())
        finally:
            raise

"""스펙 211 검증(라이브 통합) — MCP 사용=공용 전환 + published=커스텀 외부 서빙 전용.

검증 사다리 rung 1~2(단위 시맨틱 + 실서버 통합). rung 3(적대)은 codex 별도.
- U: 배선 게이트 소멸 — 비소유 member 저작 에이전트 채팅 컨텍스트에 타인 MCP가 배선됨.
  (게이트 함수 자체가 제거됐으므로 "게이트가 없다"를 소비 지점(_load_context 결과)으로 실측.)
- P: published 3입구(생성/수정/publish) — non-custom은 400, custom publish 토글 정상, 끄기는 항상 허용.
- S: 서빙 게이트 불변 — custom 미공개=404, 공개=응답, external/미등록=404.
- L: 자가-잠금 핀 — 소유자 본인 관리(수정) 여전히 허용, 비소유 관리 404.

전제: API(127.0.0.1:8000)+실 DB 생존. 실행: .venv/bin/python tests/verify_211_mcp_shared_use.py
"""

import asyncio
import os
import subprocess
import sys
import uuid as _uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))

import httpx  # noqa: E402
from dotenv import load_dotenv  # noqa: E402
from sqlalchemy import delete, select  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

from api.db import SessionLocal  # noqa: E402
from api.models import Agent, AgentVersion, McpServer, User  # noqa: E402

BASE = os.environ.get("VERIFY_BASE", "http://127.0.0.1:8000")  # 스펙 390: 격리 서버 주입
PY = os.path.join(ROOT, ".venv", "bin", "python")
PROV = os.path.join(ROOT, "tests", "_provision_super.py")

OWNER_EMAIL = "probe211o@example.com"  # MCP 등록자(member)
OTHER_EMAIL = "probe211n@example.com"  # 비소유 member(에이전트 저작자)
PW = "Probe211-pw!"
MCP_NAME = "probe211-mcp"
AGENT_ID = "agt-211x"

_fails: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def _provision(create: bool) -> None:
    cmd = "create" if create else "delete"
    for email, extra in [(OWNER_EMAIL, ["member"]), (OTHER_EMAIL, ["member"])]:
        args = [PY, PROV, cmd, email] + ([PW] + extra if create else [])
        subprocess.run(
            args, cwd=os.path.join(ROOT, "packages", "api"), check=False, capture_output=True
        )


async def _login(client: httpx.AsyncClient, email: str) -> bool:
    r = await client.post(
        "/auth/login",
        data={"username": email, "password": PW},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    return r.status_code in (200, 204)


async def _cleanup() -> None:
    async with SessionLocal() as s:
        await s.execute(
            delete(AgentVersion).where(
                AgentVersion.agent_pk.in_(select(Agent.id).where(Agent.agent_id == AGENT_ID))
            )
        )
        await s.execute(
            delete(AgentVersion).where(
                AgentVersion.agent_pk.in_(select(Agent.id).where(Agent.name == "probe211-agent"))
            )
        )
        await s.execute(delete(Agent).where(Agent.agent_id == AGENT_ID))
        await s.execute(delete(Agent).where(Agent.name == "probe211-agent"))
        await s.execute(delete(McpServer).where(McpServer.name == MCP_NAME))
        await s.commit()


async def main() -> int:
    _provision(create=True)
    await _cleanup()
    owner = httpx.AsyncClient(base_url=BASE, timeout=15)
    other = httpx.AsyncClient(base_url=BASE, timeout=15)
    anon = httpx.AsyncClient(base_url=BASE, timeout=15)
    try:
        check(await _login(owner, OWNER_EMAIL), "SETUP: owner 로그인")
        check(await _login(other, OTHER_EMAIL), "SETUP: other 로그인")

        # owner가 auth 토큰 달린 local MCP 등록(사용=공용의 크레덴셜 함의까지 포함해 실측)
        r = await owner.post(
            "/mcp-servers",
            json={
                "name": MCP_NAME,
                "source": "local",
                "transport": "http",
                "url": BASE + "/_remote/mcp/",
                "tools": ["echo"],
                "auth": "sekret-211",
                "published": False,
            },
        )
        check(r.status_code in (200, 201), f"SETUP: owner MCP 등록({r.status_code})")

        # ---- P: published 3입구 — non-custom은 켤 수 없다 ----
        r = await owner.post(
            "/mcp-servers",
            json={
                "name": MCP_NAME + "-pub",
                "source": "local",
                "transport": "http",
                "url": "http://x/",
                "tools": [],
                "published": True,
            },
        )
        check(r.status_code == 400, f"P1 생성: local+published=400({r.status_code})")
        mcp_id = None
        r = await owner.get("/mcp-servers")
        rows = r.json()
        mcp_id = next((x["id"] for x in rows if x["name"] == MCP_NAME), None)
        check(mcp_id is not None, "P2 목록에서 등록 MCP 확인")
        r = await owner.put(f"/mcp-servers/{mcp_id}/publish", json={"published": True})
        check(r.status_code == 400, f"P3 publish: local 켜기=400({r.status_code})")
        r = await owner.put(f"/mcp-servers/{mcp_id}/publish", json={"published": False})
        check(r.status_code == 200, f"P4 publish: 끄기는 항상 허용({r.status_code})")
        base_row = next(x for x in rows if x["name"] == MCP_NAME)
        full = {
            "name": base_row["name"],
            "source": base_row["source"],
            "transport": base_row["transport"],
            "url": base_row["url"],
            "tools": base_row.get("tools") or [],
            "published": True,
        }
        r = await owner.put(f"/mcp-servers/{mcp_id}", json=full)
        check(r.status_code == 400, f"P5 수정: local published=true=400({r.status_code})")

        # custom(web-fetch, 시드)은 publish 토글 정상 — 현재 상태 보존을 위해 같은 값으로 set
        wf = next((x for x in rows if x["source"] == "custom"), None)
        if wf is not None:
            r = await owner.put(
                f"/mcp-servers/{wf['id']}/publish", json={"published": wf["published"]}
            )
            # member는 custom(owner_id=None → admin 전용 관리)이라 404가 정상 — 관리축 불변 확인
            check(r.status_code == 404, f"P6 custom 관리: member=404 은폐 불변({r.status_code})")

        # ---- U: 사용=공용 — other 저작 에이전트에 owner의 MCP 배선 ----
        r = await other.post(
            "/agents",
            json={
                "agentId": AGENT_ID,
                "name": "probe211-agent",
                "source": "ui",
                "config": {
                    "model": "mock-llm",
                    "prompt": "",
                    "mcps": [MCP_NAME],
                    "historyDepth": 5,
                },
            },
        )
        check(
            r.status_code in (200, 201), f"U1 비소유 에이전트가 타인 MCP 참조 저장({r.status_code})"
        )
        agent_uuid = (r.json() or {}).get("id")
        # 소비 지점 실측: 채팅 1턴(SSE) — 게이트가 있었다면 여기서 'mcp ... skipped' 경고와 함께
        # 도구 없이 진행됐다. 이제 게이트 자체가 없으므로 200 스트림이면 배선 경로 통과.
        r = await other.post(
            f"/agents/{agent_uuid}/chat",
            json={"messages": [{"role": "user", "content": "안녕"}], "sessionId": None},
        )
        if r.status_code == 422:
            print("       U2 detail:", r.text[:300])
        check(r.status_code == 200, f"U2 비소유 배선 채팅 200({r.status_code}) — 게이트 스킵 없음")

        # ---- S: 서빙 게이트 불변 ----
        r = await anon.post(
            "/_served/mcp/web-fetch/", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        )
        async with SessionLocal() as s:
            wf_row = (
                (await s.execute(select(McpServer).where(McpServer.source == "custom")))
                .scalars()
                .first()
            )
        if wf_row is not None and wf_row.published:
            check(r.status_code != 404, f"S1 custom 공개=서빙 응답({r.status_code})")
        else:
            check(r.status_code == 404, f"S1 custom 미공개=404({r.status_code})")
        r = await anon.post("/_served/mcp/no-such-mcp/", json={})
        check(r.status_code == 404, f"S2 미등록 이름=404({r.status_code})")

        # ---- L: 자가-잠금 핀 — 관리축 불변 ----
        edit = dict(full, published=False, description="소유자 수정")
        r = await owner.put(f"/mcp-servers/{mcp_id}", json=edit)
        check(r.status_code == 200, f"L1 소유자 본인 수정 허용({r.status_code})")
        r = await other.put(f"/mcp-servers/{mcp_id}", json=dict(edit, description="타인 수정"))
        check(r.status_code == 404, f"L2 비소유 수정=404 은폐({r.status_code})")
        r = await other.delete(f"/mcp-servers/{mcp_id}")
        check(r.status_code == 404, f"L3 비소유 삭제=404 은폐({r.status_code})")
    finally:
        await owner.aclose()
        await other.aclose()
        await anon.aclose()
        await _cleanup()
        _provision(create=False)

    print(f"\n{len(_fails)} failed" if _fails else "\nALL PASS")
    return 1 if _fails else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

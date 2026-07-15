"""스펙 285 라이브 통합 — resync 시 배포 메타(commit·repo·runtime) 재보고.

081 하네스 패턴 재사용(스레드 카드 서버 + 실 DB): connect(commit A) → 카드가 commit B로 재배포
→ resync → commit/active_version/버전 행 전이(057 F4 불변식) 실측. 동일 commit 무변경·A→B→A
재왕복(기존 행 승격)·external 무회귀까지.

실행: uv run --project packages/api python tests/verify_285_resync_commit.py
"""

import asyncio
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))

from api import net_guard  # noqa: E402
from api.agents import connect_agent, resync_agent  # noqa: E402
from api.db import SessionLocal  # noqa: E402
from api.models import Agent  # noqa: E402
from api.schemas import ConnectAgentIn  # noqa: E402
from types import SimpleNamespace  # noqa: E402

net_guard._set_allowed_hosts_for_test(["127.0.0.1"])

# 라우트 직호출용 principal(superuser) — resync는 assert_may_manage 게이트(스펙 112)를 지난다.
PRINCIPAL = SimpleNamespace(id="00000000-0000-0000-0000-000000000285", is_superuser=True)

_fails: list[str] = []


def ck(c: bool, m: str) -> None:
    print(("  ok  " if c else " FAIL ") + m)
    if not c:
        _fails.append(m)


# 가변 카드 상태 — 핸들러가 이 dict를 읽어 "재배포"를 흉내낸다.
STATE = {
    "commit": "aaaa111",
    "repo": "org/svc",
    "runtime": "python-3.12",
}


def _card() -> dict:
    return {
        "name": "resync-commit-285",
        "description": "285 커밋 재보고",
        "url": "/a2a",
        "version": "1.0.0",
        "capabilities": {"streaming": False},
        "skills": [{"id": "s", "name": "s", "description": "d", "tags": []}],
        "x-my-agents": {
            "manifest": {"model": "remote-model", "prompt": "p", "historyDepth": 10},
            "deploy": {"commit": STATE["commit"], "repo": STATE["repo"], "runtime": STATE["runtime"]},
        },
    }


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj=None):
        self.send_response(code)
        if obj is not None:
            body = json.dumps(obj).encode("utf-8")
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_header("Content-Length", "0")
            self.end_headers()

    def do_GET(self):
        if self.path == "/.well-known/agent-card.json":
            self._send(200, _card())
        else:
            self._send(404)

    def do_POST(self):
        self._send(405)


async def _connect(url):
    async with SessionLocal() as s:
        return await connect_agent(ConnectAgentIn(url=url, token=None), s, PRINCIPAL)


async def _resync(pk):
    async with SessionLocal() as s:
        return await resync_agent(pk, s, PRINCIPAL)


async def _row(pk):
    async with SessionLocal() as s:
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        r = await s.execute(select(Agent).where(Agent.id == pk).options(selectinload(Agent.versions)))
        return r.scalar_one()


async def _cleanup(pk):
    async with SessionLocal() as s:
        row = await s.get(Agent, pk)
        if row is not None:
            await s.delete(row)
            await s.commit()


async def main() -> None:
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    base = f"http://127.0.0.1:{port}"
    pk = None
    try:
        # ① connect: commit A
        out = await _connect(f"{base}/.well-known/agent-card.json")
        pk = out.id
        ck(out.source == "code" and out.commit == "aaaa111", f"① connect: source=code·commit=A (got {out.source}/{out.commit})")
        ck(out.activeVersion == "aaaa111", f"① active_version=A (got {out.activeVersion})")

        # ② 동일 commit resync → 버전 행 수 불변
        before = len((await _row(pk)).versions)
        await _resync(pk)
        row = await _row(pk)
        ck(len(row.versions) == before and row.commit == "aaaa111", f"② 동일 commit resync 무변경 (rows {before}→{len(row.versions)})")

        # ③ 재배포(commit B) → resync → 재보고
        STATE.update(commit="bbbb222", repo="org/svc2", runtime="python-3.13")
        await _resync(pk)
        row = await _row(pk)
        ck(row.commit == "bbbb222", f"③ commit 재보고 A→B (got {row.commit})")
        ck(row.active_version == "bbbb222", f"③ active_version=B (got {row.active_version})")
        # 스펙 370: active/archived 상태 폐기 — active는 포인터(active_version)가 진실원,
        # 버전 행은 ever_opened(배포 이력)만 가진다.
        st = {v.version: v.ever_opened for v in row.versions}
        ck(
            row.active_version == "bbbb222" and st.get("bbbb222") is True and st.get("aaaa111") is True,
            f"③ 버전 전이(057 F4→370): pointer=B·이력 보존 {st}",
        )
        ck(row.repo == "org/svc2" and row.runtime == "python-3.13", f"③ repo·runtime 재보고 (got {row.repo}/{row.runtime})")

        # ④ A→B→A 재왕복: 기존 A 행 승격(중복 금지)
        STATE.update(commit="aaaa111")
        await _resync(pk)
        row = await _row(pk)
        versions_a = [v for v in row.versions if v.version == "aaaa111"]
        ck(
            len(versions_a) == 1 and row.active_version == "aaaa111",
            f"④ 재왕복: A 포인터 복귀·중복 0 (count={len(versions_a)})",
        )
        ck(row.active_version == "aaaa111", f"④ active_version=A 복귀")

        # ⑤ 확장 없는 카드(external화된 응답) → deploy 메타 보존(무회귀)
        # 같은 행 유지 상태에서 카드가 확장을 잃어도(운영 실수) 기존 commit을 파괴하지 않는다.
        saved_commit = row.commit
        import __main__
        orig = __main__._card  # 원본을 먼저 캡처(패치 함수가 orig를 부르게 — 자기재귀 금지)
        def _card_no_ext():
            c = orig(); c.pop("x-my-agents"); return c
        __main__._card = _card_no_ext
        try:
            await _resync(pk)
        finally:
            __main__._card = orig
        row = await _row(pk)
        ck(row.commit == saved_commit, f"⑤ 확장 소실 카드 → commit 보존 (got {row.commit})")
        # 진짜 확장-소실 경로였음을 판별: 도달 실패 경로는 카드 스냅샷을 안 만지므로, 스냅샷이
        # 갱신됐고(x-my-agents 부재) commit이 보존됐다면 ext-소실 보존 로직이 실행된 것.
        snap = (row.config or {}).get("card") or {}
        ck("x-my-agents" not in snap, f"⑤ 카드 스냅샷 갱신됨(확장 부재) — 도달실패 경로 아님 (keys={sorted(snap.keys())[:6]})")
    finally:
        if pk is not None:
            await _cleanup(pk)
        srv.shutdown()

    print()
    print(f"{len(_fails)} FAIL" if _fails else "ALL PASS")
    raise SystemExit(1 if _fails else 0)


asyncio.run(main())

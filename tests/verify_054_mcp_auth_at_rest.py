"""스펙 054 P3-F 검증 — MCP auth at-rest(누출-안전).

인프로세스 httpx(ASGI) + 실 DB로 불변식 단언. 검증용 MCP 서버를 고유 prefix(mcp_v054f_)로
삽입 → 단언 → **삭제**(자가정리). provider.api_key와 동형 시맨틱(스펙 010)을 MCP에 이식했는지 확인.

단언:
  1. 생성: 평문 Bearer 토큰 POST → 응답 auth == 마스킹(••). 평문·암호문(gAAAAA) 비노출.
  2. DB 저장: 저장값은 Fernet 암호문(gAAAAA로 시작), decrypt → 원본 평문.
  3. 목록/단건/집계(GET /mcp-servers·/{id}·/blocks) 모두 auth 마스킹 — 어디서도 평문/암호문 누출 없음.
  4. 마스킹 수정: auth=마스킹값으로 PUT → 기존 토큰 보존(DB decrypt 동일).
  5. 신규 토큰 수정: auth=새 평문으로 PUT → 재암호화(DB decrypt == 새 값).
  6. 명시 제거: auth="" 로 PUT → DB auth None(헤더 생략 경로).
  7. 런타임 배선(chat._load_context 규칙): 암호문 저장 → token=decrypt(평문), 마스킹 저장 → token=None.
     runtime.build_mcp_tools는 `if token`으로 Bearer 헤더를 거니, 이 둘이 헤더 유무를 결정한다.

실행: A2A_ALLOWED_HOSTS=127.0.0.1,localhost .venv/bin/python tests/verify_054_mcp_auth_at_rest.py
"""
import asyncio
import os
import sys
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))

import httpx  # noqa: E402
from sqlalchemy import delete  # noqa: E402

from api import crypto  # noqa: E402
from api.auth import _token  # noqa: E402
from api.crypto import SECRET_MASK  # noqa: E402
from api.db import SessionLocal  # noqa: E402
from api.main import app  # noqa: E402
from api.models import McpServer  # noqa: E402

_AUTH = {"Authorization": f"Bearer {_token()}"}
_fails: list[str] = []
NP = "mcp_v054f_"
TOKEN = "sk-secret-abc-123"
TOKEN2 = "sk-rotated-xyz-789"


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def _secret_safe(v) -> bool:
    """비밀 출력 안전 — null 또는 마스킹만. 평문/암호문(gAAAAA) 금지."""
    return v is None or v == SECRET_MASK


async def _cleanup() -> None:
    async with SessionLocal() as s:
        await s.execute(delete(McpServer).where(McpServer.name.like(f"{NP}%")))
        await s.commit()


async def _db_auth(mid: str) -> str | None:
    async with SessionLocal() as s:
        obj = await s.get(McpServer, uuid.UUID(mid))
        return obj.auth if obj else "<missing>"


async def main() -> None:
    await _cleanup()
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://t", headers=_AUTH) as c:
            # --- (1) 생성: 평문 토큰 → 응답 마스킹 ---
            print("[create] 평문 Bearer 토큰 POST → 응답 마스킹")
            pc = await c.post("/mcp-servers", json={
                "name": f"{NP}a", "source": "external", "transport": "http",
                "url": "http://127.0.0.1:8000/_remote/mcp/", "auth": TOKEN,
                "tools": ["echo"], "enabled_tools": ["echo"],
            })
            check(pc.status_code == 201, f"생성 201 (got {pc.status_code})")
            body = pc.json()
            mid = body["id"]
            check(body["auth"] == SECRET_MASK, f"생성 응답 auth 마스킹 (got {body['auth']!r})")
            check(_secret_safe(body["auth"]), "생성 응답에 평문/암호문 비노출")

            # --- (2) DB 암호문 + 복호화 왕복 ---
            print("[at-rest] DB는 암호문, decrypt → 원본")
            stored = await _db_auth(mid)
            check(isinstance(stored, str) and stored.startswith("gAAAAA"),
                  f"DB 저장값이 Fernet 암호문 (got prefix {str(stored)[:6]!r})")
            check(crypto.decrypt(stored) == TOKEN, "decrypt(저장값) == 원본 평문")

            # --- (3) 모든 GET 경로 마스킹 ---
            print("[no-leak] list·단건·집계 전부 마스킹")
            lst = (await c.get("/mcp-servers")).json()
            mine = [m for m in lst if m["name"] == f"{NP}a"]
            check(bool(mine) and _secret_safe(mine[0]["auth"]), "GET /mcp-servers auth 마스킹")
            one = (await c.get(f"/mcp-servers/{mid}")).json()
            check(_secret_safe(one["auth"]), "GET /mcp-servers/{id} auth 마스킹")
            blocks = (await c.get("/blocks")).json()
            mcp_items = blocks.get("mcp", {}).get("items", [])
            agg = [m for m in mcp_items if m["name"] == f"{NP}a"]
            check(bool(agg) and _secret_safe(agg[0]["auth"]), "GET /blocks 집계 auth 마스킹")
            # 어떤 응답 본문에도 평문 토큰 문자열이 없어야 함(전역 누출 스캔).
            for label, raw in [("list", lst), ("one", one), ("blocks", mcp_items)]:
                check(TOKEN not in str(raw), f"{label} 본문에 평문 토큰 미포함")

            # --- (4) 마스킹 수정 → 보존 ---
            print("[preserve] 마스킹값 PUT → 기존 토큰 보존")
            await c.put(f"/mcp-servers/{mid}", json={
                "name": f"{NP}a", "source": "external", "transport": "http",
                "url": "http://127.0.0.1:8000/_remote/mcp/", "auth": SECRET_MASK,
                "tools": ["echo"], "enabled_tools": ["echo"],
            })
            check(crypto.decrypt(await _db_auth(mid)) == TOKEN, "마스킹 수정 후 기존 토큰 유지")

            # --- (5) 새 토큰 수정 → 재암호화 ---
            print("[rotate] 새 평문 PUT → 재암호화")
            await c.put(f"/mcp-servers/{mid}", json={
                "name": f"{NP}a", "source": "external", "transport": "http",
                "url": "http://127.0.0.1:8000/_remote/mcp/", "auth": TOKEN2,
                "tools": ["echo"], "enabled_tools": ["echo"],
            })
            rot = await _db_auth(mid)
            check(rot.startswith("gAAAAA") and crypto.decrypt(rot) == TOKEN2, "새 토큰으로 재암호화")
            check(crypto.decrypt(rot) != TOKEN, "이전 토큰은 더 이상 복호화되지 않음")

            # --- (6) 명시 제거 ---
            print("[remove] auth='' PUT → 제거")
            await c.put(f"/mcp-servers/{mid}", json={
                "name": f"{NP}a", "source": "external", "transport": "http",
                "url": "http://127.0.0.1:8000/_remote/mcp/", "auth": "",
                "tools": ["echo"], "enabled_tools": ["echo"],
            })
            check(await _db_auth(mid) is None, "빈 문자열 수정 → DB auth None(헤더 생략 경로)")

            # --- (7) 런타임 배선 규칙(chat._load_context) ---
            print("[runtime] 복호화→token, 마스킹→None")
            enc = crypto.encrypt(TOKEN)
            tok_from_enc = None if crypto.is_masked(enc) else crypto.decrypt(enc)
            check(tok_from_enc == TOKEN, "암호문 저장 → token=평문(Bearer 헤더 설정 경로)")
            tok_from_mask = None if crypto.is_masked(SECRET_MASK) else crypto.decrypt(SECRET_MASK)
            check(tok_from_mask is None, "마스킹 저장 → token=None(헤더 생략)")
            tok_from_none = None if crypto.is_masked(None) else crypto.decrypt(None)
            check(tok_from_none is None, "빈 저장 → token=None(헤더 생략)")
    finally:
        await _cleanup()


if __name__ == "__main__":
    asyncio.run(main())
    print()
    if _fails:
        print(f"❌ {len(_fails)} FAILED")
        for f in _fails:
            print("   - " + f)
        sys.exit(1)
    print("✅ ALL PASS")

"""적대 검증 발견 수선 증명 — /approvals/{id}/resolve가 admin만 통과하는지 실 HTTP로 검증.

비-admin 멤버·머신 토큰이 위험 도구를 승인·실행할 수 있던 홀(스펙 041 불변식 위반)을 admin 인가
추가로 막았다. ASGITransport로 실제 라우트·의존성을 태운다(목 없음).

검증:
  A1. admin 로그인 → resolve(없는 id) → 404 (게이트 통과, 핸들러까지 도달).
  A2. 비-admin member 로그인 → resolve → 403 (게이트 차단, 핸들러 미도달).
  A3. 머신 토큰(API_AUTH_TOKEN) → resolve → 401 (current_active_user 실패 = 쿠키 admin만).

실행: uv run python .dev/probe_resolve_authz.py
"""

import asyncio
import os
import sys

os.environ["ADMIN_EMAIL"] = "admin041@example.com"
os.environ["ADMIN_PASSWORD"] = "Admin041!pw"
os.environ["API_AUTH_TOKEN"] = "machine-tok-041"
# 테스트는 http://test(평문)로 ASGITransport를 태운다. CookieTransport 기본 cookie_secure=true면
# 쿠키에 Secure가 붙어 httpx가 평문 요청에 재전송하지 않는다(로그인 204지만 후속 401) — 하니스
# 한정 이슈(프로덕션은 HTTPS/tailscale). 인가 게이트 자체를 검증하려고 평문에서 쿠키를 흐르게 한다.
os.environ["AUTH_COOKIE_SECURE"] = "false"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))

import httpx  # noqa: E402
from httpx import ASGITransport  # noqa: E402

from api.main import app, lifespan  # noqa: E402

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


async def login(client, email, password):
    r = await client.post("/auth/login", data={"username": email, "password": password})
    return r.status_code


async def main():
    async with lifespan(app):
        transport = ASGITransport(app=app)
        base = "http://test"

        # A1: admin
        async with httpx.AsyncClient(transport=transport, base_url=base) as ac:
            sc = await login(ac, "admin041@example.com", "Admin041!pw")
            check(sc == 204, f"admin 로그인 204 (got {sc})")
            r = await ac.post("/approvals/nonexistent-id/resolve", json={"decision": "approve"})
            check(r.status_code == 404, f"A1: admin → resolve(없는 id) → 404 게이트 통과 (got {r.status_code})")

            # admin이 member 생성(admin API). 역할 미부여 = 비-admin.
            r = await ac.post(
                "/admin/users",
                json={"email": "member041@example.com", "password": "Member041!pw"},
            )
            # 409 = 이전 실행에서 이미 생성됨(dev DB 영속) — 멱등 허용. 이후 로그인·403이 실 검증.
            created = r.status_code in (200, 201, 409)
            check(created, f"member 생성/기존 (got {r.status_code})")

        # A2: member (non-admin)
        async with httpx.AsyncClient(transport=transport, base_url=base) as mc:
            sc = await login(mc, "member041@example.com", "Member041!pw")
            check(sc == 204, f"member 로그인 204 (got {sc})")
            r = await mc.post("/approvals/nonexistent-id/resolve", json={"decision": "approve"})
            check(r.status_code == 403, f"A2: 비-admin member → resolve → 403 차단 (got {r.status_code})")

        # A3: machine token
        async with httpx.AsyncClient(transport=transport, base_url=base) as tc:
            r = await tc.post(
                "/approvals/nonexistent-id/resolve",
                json={"decision": "approve"},
                headers={"Authorization": "Bearer machine-tok-041"},
            )
            check(r.status_code == 401, f"A3: 머신 토큰 → resolve → 401 (쿠키 admin만) (got {r.status_code})")

    print()
    if _fails:
        print(f"❌ {len(_fails)} FAIL")
        sys.exit(1)
    print("✅ resolve admin 인가 게이트 검증 통과 (적대 검증 홀 수선됨)")


asyncio.run(main())

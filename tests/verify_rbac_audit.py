"""RBAC 감사(라이브 통합) — 메뉴/버튼/기능 권한이 *백엔드에서 실제로 강제*되는지 실 HTTP로 실측.

배경: 정적 읽기 기반 감사가 "엔드포인트 대다수가 무방비"라고 보고했으나, 이는 라우터 include
시점의 `dependencies=_auth`(main.py: `_auth=[Depends(current_principal)]`)를 놓친 *오측*이다.
이 테스트는 그 주장을 라이브로 교정하고, 프론트 메뉴 게이트(AdminShell: 공통 vs `is_superuser`
관리자 그룹)가 백엔드 강제와 일치하는지 증명한다.

3 계층 × 4 주체 매트릭스:
- 계층 A "로그인한 누구나"(`dependencies=_auth`): 카탈로그 CRUD(agents/blocks/providers/models/
  sessions/collections/memory/approvals). 단일 워크스페이스 모델(spec 011).
- 계층 B "admin 전용"(`authz.require(obj,act)`): /admin/users·/admin/roles·/admin/batch·
  /admin/allowed-hosts. 프론트는 `is_superuser`로만 노출(UX 편의), 서버가 독립 강제.

기대:
- anonymous(쿠키·토큰 없음)        → 모든 경로 401 (전역 인증 게이트)
- member(로그인·비-super·정책 0)   → 계층 A 200, 계층 B 403 (require enforce 거부)
- super(로그인·is_superuser)        → 계층 A 200, 계층 B 200 (superuser 우회)
- machine(Bearer 토큰)             → 계층 A 200, 계층 B 401 (require=current_active_user 세션 전용)

전제: API(127.0.0.1:8000)+실 DB 생존. 던짐용 계정(probe…@example.com) 즉석 생성/삭제. 실 데이터 무오염.
실행: .venv/bin/python tests/verify_rbac_audit.py
"""
import asyncio
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))

import httpx  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

BASE = "http://127.0.0.1:8000"
MACHINE = (os.environ.get("API_AUTH_TOKEN") or "").strip()
PY = os.path.join(ROOT, ".venv", "bin", "python")
PROV = os.path.join(ROOT, "tests", "_provision_super.py")

MEMBER_EMAIL = "probe-rbac-m@example.com"
SUPER_EMAIL = "probe-rbac-s@example.com"
PW = "Probe-rbac-pw!"

# 계층 A — 로그인한 누구나(읽기 GET만 골라 부수효과 0). _auth 게이트.
TIER_A = ["/agents", "/blocks", "/providers", "/models", "/sessions",
          "/collections", "/memory/users", "/approvals"]
# 계층 B — admin 전용(require). 읽기 GET만.
TIER_B = ["/admin/users", "/admin/roles", "/admin/batch/jobs", "/admin/allowed-hosts"]

_fails: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def _provision(create: bool) -> None:
    cmd = "create" if create else "delete"
    for email, extra in [(MEMBER_EMAIL, ["member"]), (SUPER_EMAIL, [])]:
        args = [PY, PROV, cmd, email] + ([PW] + extra if create else [])
        subprocess.run(args, check=False, capture_output=True, text=True)


async def _login(client: httpx.AsyncClient, email: str) -> bool:
    r = await client.post("/auth/login", data={"username": email, "password": PW},
                          headers={"Content-Type": "application/x-www-form-urlencoded"})
    return r.status_code in (200, 204)


async def _codes(client: httpx.AsyncClient, paths: list[str]) -> dict[str, int]:
    out = {}
    for p in paths:
        out[p] = (await client.get(p)).status_code
    return out


async def main() -> None:
    if not MACHINE:
        print("❌ 전제 실패 — API_AUTH_TOKEN 미설정(.env). 종료.")
        sys.exit(1)

    # ---- 0. anonymous: 쿠키·토큰 없이 모든 경로 → 401 ----
    async with httpx.AsyncClient(base_url=BASE, timeout=10) as anon:
        # 서버 생존 겸 무인증 확인.
        a = await _codes(anon, TIER_A)
        b = await _codes(anon, TIER_B)
    for p, c in {**a, **b}.items():
        check(c == 401, f"anonymous {p} → 401 (전역 인증 게이트) — got {c}")

    _provision(create=True)
    try:
        member = httpx.AsyncClient(base_url=BASE, timeout=10)
        superc = httpx.AsyncClient(base_url=BASE, timeout=10)
        machine = httpx.AsyncClient(base_url=BASE, timeout=10)
        machine.headers["Authorization"] = f"Bearer {MACHINE}"
        try:
            check(await _login(member, MEMBER_EMAIL), "SETUP: member 로그인(쿠키)")
            check(await _login(superc, SUPER_EMAIL), "SETUP: super 로그인(쿠키)")

            # ---- 1. member: 계층 A → 200, 계층 B → 403 ----
            ma = await _codes(member, TIER_A)
            mb = await _codes(member, TIER_B)
            for p, c in ma.items():
                check(c == 200, f"member 계층A {p} → 200 (로그인=카탈로그 접근) — got {c}")
            for p, c in mb.items():
                check(c == 403, f"member 계층B {p} → 403 (require enforce 거부, 정책 0=fail-closed) — got {c}")

            # ---- 2. super: 계층 A → 200, 계층 B → 200 ----
            sa = await _codes(superc, TIER_A)
            sb = await _codes(superc, TIER_B)
            for p, c in sa.items():
                check(c == 200, f"super 계층A {p} → 200 — got {c}")
            for p, c in sb.items():
                check(c == 200, f"super 계층B {p} → 200 (is_superuser 우회) — got {c}")

            # ---- 3. machine: 계층 A → 200, 계층 B → 401(require=세션 유저 전용) ----
            ca = await _codes(machine, TIER_A)
            cb = await _codes(machine, TIER_B)
            for p, c in ca.items():
                check(c == 200, f"machine 계층A {p} → 200 (머신=전체 접근) — got {c}")
            for p, c in cb.items():
                check(c == 401, f"machine 계층B {p} → 401 (require=current_active_user 세션 전용, 머신 토큰 불가) — got {c}")
        finally:
            await member.aclose(); await superc.aclose(); await machine.aclose()
    finally:
        _provision(create=False)

    print()
    if _fails:
        print(f"❌ {len(_fails)} FAIL")
        for f in _fails:
            print("   -", f)
        sys.exit(1)
    n_a, n_b = len(TIER_A), len(TIER_B)
    print(f"✅ RBAC 감사 라이브 통과 — anonymous {n_a + n_b}×401, member 계층A {n_a}×200·계층B {n_b}×403, "
          f"super 전체 200, machine 계층A 200·계층B 401. "
          f"'대다수 무방비'는 오측(라우터 dependencies=_auth 미관측).")


asyncio.run(main())

"""스펙 064 라이브 통합 — 실 DB(agents) 대상 무재시작 반영·TTL staleness(§3·§5 통합 rung).

전제: postgres(agents DB)가 떠 있고 alembic이 `d0e1f2a3b4c5`까지 올라가 있다(앱 부팅 1회).
이 스크립트는 **테스트 프로세스 안에서** net_guard 스냅샷↔실 DB를 직접 돌려, 서버 재기동 없이
DB 변경이 guard_url에 반영됨을 단언한다(D3). 실 DB에 임시 행을 넣고 **반드시 정리**한다.

검증:
  L1 force refresh → env 부트스트랩 시드(127.0.0.1)가 스냅샷에 로드, guard 통과.
  L2 시드 밖 사설(10.99.x)은 차단(allowlist는 정확 host 예외 목록일 뿐).
  L3 DB에 host 추가 → force refresh → **재기동 없이** guard 통과로 전환(무재시작 반영).
  L4 staleness 창: 추가 후 TTL 내 non-force refresh는 DB 재조회 안 함(디바운스) — 닫는 변경(제거)이
     TTL 동안 늦게 반영되는 창이 ≤TTL임을 단언(§3 removed-but-cached).
  L5 제거 + force refresh(=invalidate 후 재조회 등가) → 다시 차단(닫는 변경 반영).

실행: .venv/bin/python tests/verify_064_live.py
"""

import asyncio
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))
os.chdir(ROOT)  # load_dotenv()가 루트 .env를 찾도록

from sqlalchemy import delete, select  # noqa: E402

from api import db, net_guard  # noqa: E402
from api.models import AllowedHost  # noqa: E402

_fails: list[str] = []
TEST_HOST = "10.99.0.7"  # 사설 IP — 시드에 없음, 테스트 후 삭제


def check(cond: bool, label: str) -> None:
    print(f"  {'ok ' if cond else 'FAIL'} {label}")
    if not cond:
        _fails.append(label)


async def _purge_test_host() -> None:
    async with db.SessionLocal() as s:
        await s.execute(delete(AllowedHost).where(AllowedHost.host == TEST_HOST))
        await s.commit()


async def _insert_test_host() -> None:
    async with db.SessionLocal() as s:
        s.add(AllowedHost(host=TEST_HOST, note="verify064 live(임시)"))
        await s.commit()


def _passes(url: str) -> bool:
    try:
        net_guard.guard_url(url)
        return True
    except net_guard.SsrfBlocked:
        return False


async def main() -> None:
    await _purge_test_host()  # 잔여 정리(이전 실패 흔적)
    try:
        # L1 — force refresh로 env 부트스트랩 시드 로드.
        await net_guard.refresh_allowed_hosts(force=True)
        snap = net_guard._allowed_hosts()
        check("127.0.0.1" in snap, f"L1 force refresh → 시드 127.0.0.1 스냅샷 로드 (snap={sorted(snap)})")
        check(_passes("http://127.0.0.1:8000/x"), "L1 guard 통과(시드 host)")

        # L2 — 시드 밖 사설은 차단.
        check(not _passes(f"http://{TEST_HOST}/x"), f"L2 시드 밖 사설 {TEST_HOST} 차단")

        # L3 — DB 추가 → force refresh → 무재시작 통과 전환.
        await _insert_test_host()
        await net_guard.refresh_allowed_hosts(force=True)
        check(_passes(f"http://{TEST_HOST}/x"),
              f"L3 DB 추가 후 refresh → {TEST_HOST} 무재시작 통과(재기동 없음)")

        # L4 — staleness: 추가 직후 TTL 내 non-force refresh는 DB 재조회 안 함(디바운스).
        #   여기서 DB에서 host를 제거하고 non-force refresh를 불러도 스냅샷이 그대로면,
        #   닫는 변경(제거)이 TTL 동안 늦게 반영되는 창(≤TTL)을 확인한 것.
        await _purge_test_host()
        await net_guard.refresh_allowed_hosts(force=False)  # 만료 전 → no-op
        check(_passes(f"http://{TEST_HOST}/x"),
              f"L4 제거 후 TTL 내 non-force refresh는 디바운스(아직 {TEST_HOST} 허용=staleness 창 ≤TTL)")

        # L5 — force refresh(=만료/invalidate 후 재조회 등가) → 닫는 변경 반영, 다시 차단.
        await net_guard.refresh_allowed_hosts(force=True)
        check(not _passes(f"http://{TEST_HOST}/x"),
              f"L5 force refresh → 제거 반영, {TEST_HOST} 다시 차단(닫는 변경 ≤TTL 내 수렴)")
    finally:
        await _purge_test_host()  # 반드시 정리
        net_guard._set_allowed_hosts_for_test([])  # 스냅샷 누수 방지

    print()
    if _fails:
        print(f"❌ FAIL — {len(_fails)}건:")
        for f in _fails:
            print(f"   - {f}")
        sys.exit(1)
    print("ALL PASS — VERIFY064_LIVE_OK")


asyncio.run(main())

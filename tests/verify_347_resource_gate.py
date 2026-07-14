"""verify_347 — 자원 예산 게이트 (스펙 347).

**이 게이트가 존재하는 이유**: 스펙 346에서 체크포인트가 턴당 3~9행씩 무한 누적되고 있었는데
**기능 테스트는 전부 초록이었다** — 아무도 행 수를 안 셌기 때문이다. 여기서 그 질문을 상설한다.

  G1 **커버리지**: models.py의 테이블 전수가 정책 대장에 분류돼 있다(미분류 = 실패).
     → 새 테이블을 회수 경로 없이 추가하면 **여기서 걸린다**(사람의 기억이 아니라 게이트가 기억).
  G2 **회수 주체 실재**: `reclaimed`가 가리키는 청소부가 진짜 있나 —
     배치 잡 이름 ∈ JOBS · `cascade:부모`는 FK ondelete=CASCADE 실측 · 관문 심볼은 임포트 가능.
     (없는 청소부를 가리키는 선언은 "치운다"는 거짓말이다.)
  G3 **자백 강제**: `leaking`은 반드시 `fix_spec`을 갖는다(샌다는 걸 알고, 누가 고칠지까지가 한 세트).
  G4 **성장 예산(실측)**: 채팅 1턴을 **실제로 돌려** 잔여 행 증가를 예산과 대조(체크포인트 계열 +0).
  G5 **스코어보드**: 회수 경로 없는 테이블 수를 출력. **0이 자원 감사 캠페인의 완료 조건.**

실행: uv run python tests/verify_347_resource_gate.py   (dev 서버 8000 필요)
      또는 make resource
"""

import asyncio
import importlib
import json
import pathlib
import sys
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "api" / "src"))

from sqlalchemy import text  # noqa: E402

from api import resource_policy as RP  # noqa: E402
from api.batch.jobs import JOBS  # noqa: E402
from api.db import SessionLocal  # noqa: E402
from api.models import Base  # noqa: E402

BASE = "http://127.0.0.1:8000"
EMAIL, PW = "admin@example.com", "adminpass123"

_fails: list[str] = []
passed = 0


def check(cond: object, msg: str) -> None:
    global passed
    print(("  ok  " if cond else " FAIL ") + msg)
    if cond:
        passed += 1
    else:
        _fails.append(msg)


_cookie = ""


def login() -> None:
    global _cookie
    req = urllib.request.Request(
        BASE + "/auth/login", data=f"username={EMAIL}&password={PW}".encode(), method="POST"
    )
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=20) as r:
        _cookie = "; ".join(c.split(";")[0] for c in r.headers.get_all("Set-Cookie") or [])


def _chat_turn() -> None:
    req = urllib.request.Request(BASE + "/agents", method="GET")
    req.add_header("Cookie", _cookie)
    agent = json.load(urllib.request.urlopen(req, timeout=20))[0]
    body = json.dumps({"messages": [{"role": "user", "content": "자원 예산 측정 턴"}]}).encode()
    q = urllib.request.Request(BASE + f"/agents/{agent['id']}/chat", data=body, method="POST")
    q.add_header("Content-Type", "application/json")
    q.add_header("Cookie", _cookie)
    with urllib.request.urlopen(q, timeout=60) as r:
        for _ in r:  # 끝까지 소비해야 관문(finally)이 돈다
            pass


async def _counts(tables: list[str]) -> dict[str, int]:
    async with SessionLocal() as s:
        return {
            t: (await s.execute(text(f"select count(*) from {t}"))).scalar_one()  # noqa: S608 — 상수 목록
            for t in tables
        }


async def main() -> None:
    # ---- G1 커버리지: 우리 테이블 전수가 분류돼 있나
    ours = set(Base.metadata.tables)
    declared = set(RP.TABLES)
    missing = sorted(ours - declared)
    extra = sorted(declared - ours)
    check(not missing, f"G1a 모든 테이블이 정책 대장에 분류됨 (미분류: {missing})")
    check(not extra, f"G1b 대장에 유령 테이블 없음 (models.py에 없는 키: {extra})")

    # ---- G2 회수 주체 실재
    ghosts = []
    for name, p in {**RP.TABLES, **RP.EXTERNAL}.items():
        if not p.by:
            continue
        kind, _, target = p.by.partition(":")
        if kind == "batch" and target not in JOBS:
            ghosts.append(f"{name} → 없는 배치 잡 {target!r}")
        elif kind == "cascade":
            tb = Base.metadata.tables.get(name)
            if tb is None:
                continue  # EXTERNAL(우리 메타데이터 밖)은 FK 검사 불가
            parents = {
                fk.column.table.name
                for c in tb.columns
                for fk in c.foreign_keys
                if fk.ondelete == "CASCADE"
            }
            if target not in parents:
                ghosts.append(f"{name} → {target}에 CASCADE FK 없음(실제: {sorted(parents)})")
        elif kind == "chokepoint":
            mod, _, fn = target.rpartition(".")
            try:
                m = importlib.import_module(f"api.{mod}")
                if not hasattr(m, fn):
                    ghosts.append(f"{name} → 관문 심볼 {target} 없음")
            except ImportError:
                ghosts.append(f"{name} → 관문 모듈 {mod} 임포트 불가")
    check(not ghosts, f"G2 회수 주체가 전부 실재(없는 청소부 가리키지 않음) (허수: {ghosts})")

    # ---- G3 자백 강제: leaking엔 fix_spec이 반드시 있다
    unowned = [n for n, p in RP.leaking().items() if not p.fix_spec]
    check(not unowned, f"G3 leaking은 전부 담당 스펙 명시(방치된 자백 0) (누락: {unowned})")

    # ---- G4 성장 예산 실측: 채팅 1턴
    login()
    tables = sorted(RP.TURN_BUDGET)
    before = await _counts(tables)
    _chat_turn()
    await asyncio.sleep(0.6)  # 관문 finally + 트레일링 이벤트
    after = await _counts(tables)
    over = {
        t: (after[t] - before[t], RP.TURN_BUDGET[t])
        for t in tables
        if after[t] - before[t] > RP.TURN_BUDGET[t]
    }
    grew = {t: after[t] - before[t] for t in tables if after[t] != before[t]}
    check(not over, f"G4 채팅 1턴 성장 예산 준수 (초과: {over}) — 실제 증가: {grew}")

    # ---- G5 스코어보드
    leaks = RP.leaking()
    print()
    print(f"  ── 자원 스코어보드: 회수 경로 없는 테이블 **{len(leaks)}개** (0이 캠페인 완료 조건)")
    for n, p in sorted(leaks.items(), key=lambda kv: kv[1].fix_spec):
        print(f"     · {n:20} → 스펙 {p.fix_spec}")

    print()
    if _fails:
        print(f"FAIL {len(_fails)}건: {_fails}")
        sys.exit(1)
    print(f"VERIFY347_OK — {passed}건 통과 · 남은 누수 {len(leaks)}개")


asyncio.run(main())

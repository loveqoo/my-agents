"""verify_256 — 로컬 위임 경계 봉합 (codex 적대 리뷰 후속).

  P1 사용 게이트: AgentProvider.candidates/load가 may_use_agent를 적용 —
     타인 private 로컬 에이전트는 후보·로드에서 존재조차 접힘(chat 본경로와 정합).
  P2a principal-None 가드: 로컬 invoke에 principal 없으면 크래시 대신 정직 에러.
  P2b 위임 총량 예산: 공유 카운터가 DELEGATION_MAX_TOTAL 초과 시 정직 에러로 접음.

실행: uv run --project packages/api python tests/verify_256_delegation_gate.py
"""
import asyncio
import os
import sys
import uuid as _uuid

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "packages", "api", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "packages", "agent", "src"))

from api import broker as B  # noqa: E402

_fails = []
passed = 0

def check(cond, msg):
    global passed
    print(("  ok  " if cond else " FAIL ") + msg)
    if cond: passed += 1
    else: _fails.append(msg)


class _P:
    def __init__(self, uid, superuser=False):
        self.id = uid
        self.is_superuser = superuser


class _Agent:
    """AgentProvider가 읽는 필드만 갖춘 가짜 행."""
    def __init__(self, agent_id, name, owner_id=None, source="ui", active_version=True, endpoint=None, config=None):
        self.agent_id = agent_id
        self.id = _uuid.uuid4()
        self.name = name
        self.prompt = name  # _hook_for가 읽음
        self.owner_id = owner_id
        self.source = source
        self.active_version = active_version
        self.endpoint = endpoint
        self.config = config or {}


class _Result:
    def __init__(self, rows):
        self._rows = rows
    def scalars(self):
        return self
    def all(self):
        return self._rows
    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class _DB:
    def __init__(self, rows):
        self._rows = rows
    async def __aenter__(self):
        return self
    async def __aexit__(self, *a):
        return False
    async def execute(self, stmt):
        # candidates=in_(...) / load=agent_id==cap_id 둘 다 전체 행을 돌려주고
        # load는 scalar_one_or_none로 1건만 취한다(가짜라 필터는 provider 로직에 위임).
        return _Result(self._rows)


def _factory(rows):
    return lambda: _DB(rows)


async def main():
    from api.authz import init_authz
    await init_authz()

    owner = _P(str(_uuid.uuid4()))
    other = _P(str(_uuid.uuid4()))
    admin = _P(str(_uuid.uuid4()), superuser=True)

    secret = _Agent("agt_secret", "비밀조수", owner_id=owner.id, source="ui")
    mine = _Agent("agt_mine", "내조수", owner_id=other.id, source="ui")   # other 소유(other 관점 '내것')
    public = _Agent("agt_pub", "공용조수", owner_id=None, source="ui")

    allow = {"agt_secret", "agt_mine", "agt_pub"}

    # ---- P1: candidates 사용 게이트 (주체=other) ----
    prov = B.AgentProvider(_factory([secret, mine, public]), principal=other)
    caps = await prov.candidates(allow)
    ids = {c.id for c in caps}
    check("agt_secret" not in ids, "P1a candidates: 타인 private(secret) 후보 제외")
    check("agt_mine" in ids, "P1b candidates: 자기 소유 private(mine) 후보 포함")
    check("agt_pub" in ids, "P1c candidates: public 후보 포함")

    # admin은 전부 봄
    prov_admin = B.AgentProvider(_factory([secret, mine, public]), principal=admin)
    caps_admin = await prov_admin.candidates(allow)
    check("agt_secret" in {c.id for c in caps_admin}, "P1d candidates: admin은 타인 private도 포함(특권)")

    # ---- P1: load 사용 게이트 재검증 ----
    prov_secret = B.AgentProvider(_factory([secret]), principal=other)
    check(await prov_secret.load("agt_secret") is None, "P1e load: 타인 private → None(존재 비노출)")
    prov_secret_owner = B.AgentProvider(_factory([secret]), principal=owner)
    check(await prov_secret_owner.load("agt_secret") is not None, "P1f load: 소유자는 로드 성공")

    # principal None(재개 유실 시나리오) — private 자동 제외(fail-closed)
    prov_none = B.AgentProvider(_factory([secret, public]), principal=None)
    ids_none = {c.id for c in await prov_none.candidates(allow)}
    check("agt_secret" not in ids_none, "P1g candidates: principal None → private 제외(fail-closed)")

    # ---- P2a: principal None + 로컬 invoke → 정직 에러(크래시 아님) ----
    res = await prov_none.invoke(public, {"text": "hi"})
    check(res.error is not None and "principal" in (res.error or ""), "P2a invoke: principal None → 정직 에러(무크래시)")

    # ---- P2b: 위임 총량 예산 ----
    budget = {"n": B.DELEGATION_MAX_TOTAL}  # 이미 소진된 상태
    prov_budget = B.AgentProvider(_factory([public]), principal=owner, delegation_budget=budget)
    res_b = await prov_budget.invoke(public, {"text": "hi"})
    check(res_b.error is not None and "총량" in (res_b.error or ""), "P2b invoke: 예산 초과 → 정직 에러")

    print(f"\n{passed} passed, {len(_fails)} failed")
    if _fails:
        for f in _fails:
            print("  FAILED:", f)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

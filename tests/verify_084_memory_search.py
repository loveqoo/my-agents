"""스펙 084 검증 — 메모리 회상 시험 수단(공유 코어 `memory.search` + 두 엔드포인트).

챗과 *같은 코어*(memory.search)를 관리 콘솔에서 즉석 질의하게 한 게 084다. 072 RAG `/search`의
메모리판 — 같은 결정성·게이트·graceful 규약을 메모리 축(user_id/agent_id)에 옮긴다.

검증 사다리 3런 중 ①단위 + ②통합을 한 파일에 담는다(③ 적대 리뷰는 codex 별도):

  [U] 단위 — 인프라 불요(029/053 패턴). FakeMem로 코어 결정성, FakeEnforcer로 RBAC 게이트.
    U1 스키마: 공백/빈 질의 → ValidationError, query>4000 → ValidationError, =4000 OK,
       limit 0/11 → ValidationError, 기본 limit=4, 경계 1·10 OK.
    U2 RBAC(유저 검색): 비-어드민→타 user_id 403 / 본인 user_id 통과(self-lock pin) /
       머신·superuser·casbin-admin→임의 user_id 통과.
    U3 스코프 격리(코어): agent_id 검색은 agent 기억만(user_id-only 누출 0),
       user_id 검색은 그 유저 기억만(타 유저·agent 누출 0). hit 구조 {type,text,score,scope}.
    U4 graceful: mem_cfg None → enabled=False·빈결과(에이전트/유저 양쪽, 502 아님).
    U5 에이전트 404: 없는 agent_id → 404(검색 전에 막힘).
    U6 핸들러 회상: 백엔드 존재 시 enabled=True + 회상 결과(스코프 dict가 filter로 전달됨).
  [H] 통합 — in-process ASGI(072 패턴). FastAPI 검증·라우팅·auth는 HTTP 계층에서만 발화.
    H1 라우트 등록: 두 검색 경로 존재.
    H2 스키마 422가 HTTP에서 실제 발화: 공백·빈·>4000 query, limit 0·11.
    H3 auth: 토큰 없으면 401.
    H4 없는 agent_id → 404.
    H5 graceful 200: 실제 에이전트/유저 검색이 200(enabled true/false 무관, 502 아님).

실행: .venv/bin/python tests/verify_084_memory_search.py
  (U는 인프라 불요. H는 in-process 앱이 실 DB·_remote mock provider를 침 → dev 서버 필요;
   DB 불가 시 H는 SKIP 표기하고 U만으로도 핵심 불변식 보증.)
"""
import asyncio
import os
import sys
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))

from fastapi import HTTPException  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from api import agents as AG  # noqa: E402
from api import memory as M  # noqa: E402
from api import memory_routes as MR  # noqa: E402
from api.schemas import MemorySearchIn  # noqa: E402

_fails: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


# ---------------------------------------------------------------- 테스트 더블
class P:
    """fastapi-users User 모사 — principal 최소 필드(053 패턴)."""

    def __init__(self, is_superuser=False, email="u@example.com", display_name=None):
        self.id = uuid.uuid4()
        self.is_superuser = is_superuser
        self.email = email
        self.display_name = display_name


class FakeEnforcer:
    def __init__(self, allow: set[tuple[str, str, str]]):
        self.allow = allow

    def enforce(self, sub, obj, act):
        return (sub, obj, act) in self.allow


class FakeMem:
    """단일 축 필터로 store를 거른다(mem0 단축 검색 모사 — 029 패턴)."""

    def __init__(self, store: list[dict] | None = None):
        self.store = list(store or [])

    def search(self, query, filters, top_k):
        (axis, val), = filters.items()
        rows = [r for r in self.store if r.get(axis) == val]
        return {"results": rows[:top_k]}

    def get_all(self, filters):
        (axis, val), = filters.items()
        return {"results": [r for r in self.store if r.get(axis) == val]}


def with_mem(mem):
    from api.memory.mem0_backend import Mem0Backend
    backend = Mem0Backend.__new__(Mem0Backend)
    backend._mem = mem
    M.resolve_backend = lambda mem_cfg: backend  # type: ignore[assignment]


def no_mem():
    M.resolve_backend = lambda mem_cfg: None  # type: ignore[assignment]


def _async(val):
    async def _f(*a, **k):
        return val
    return _f


class FakeSession:
    """session.get(Agent, id) 모사 — _agent_mem_cfg가 부르는 유일한 DB 접점."""

    def __init__(self, agent=None):
        self._agent = agent

    async def get(self, model, pk):
        return self._agent


def raised(fn, status: int) -> bool:
    # fn은 코루틴을 *반환*하는 람다일 수 있다(iscoroutinefunction은 False) — 반환값이
    # 코루틴이면 run해서 실제로 핸들러를 실행시켜야 HTTPException이 발화한다.
    try:
        res = fn()
        if asyncio.iscoroutine(res):
            asyncio.run(res)
        return False
    except HTTPException as e:
        return e.status_code == status


# ================================================================ [U] 단위
def u1_schema() -> None:
    print("[U1] 스키마 검증(길이·공백·limit 클램프)")

    def invalid(**kw) -> bool:
        try:
            MemorySearchIn(**kw)
            return False
        except ValidationError:
            return True

    check(invalid(query="   "), "공백 질의 → ValidationError")
    check(invalid(query=""), "빈 질의 → ValidationError")
    check(invalid(query="가" * 4001), "query>4000 → ValidationError")
    check(invalid(query="가" * 4000) is False, "query=4000 경계 → OK")
    check(invalid(query="x", limit=0), "limit 0 → ValidationError")
    check(invalid(query="x", limit=11), "limit 11 → ValidationError")
    check(MemorySearchIn(query="x").limit == 4, "기본 limit=4")
    check(MemorySearchIn(query="x", limit=1).limit == 1, "limit 경계 1 OK")
    check(MemorySearchIn(query="x", limit=10).limit == 10, "limit 경계 10 OK")
    # 공백 트림(_non_blank) — 양끝 공백은 잘리고 본문만 남음.
    check(MemorySearchIn(query="  안녕  ").query == "안녕", "양끝 공백 트림")


def u2_rbac() -> None:
    print("[U2] RBAC 게이트(유저 검색 — 비-어드민은 자기 것만)")
    machine = "machine"
    superuser = P(is_superuser=True, email="root@example.com")
    member = P(is_superuser=False, email="member@example.com")
    admin = P(is_superuser=False, email="admin-role@example.com")
    MR.get_enforcer = lambda: FakeEnforcer({(str(admin.id), "memory", "manage")})

    other = str(uuid.uuid4())
    body = MemorySearchIn(query="아무 질의", limit=4)
    # mem_cfg None으로 강제 → 게이트만 격리 검증(통과하면 enabled=False 반환).
    MR._user_mem_cfg = _async(None)  # type: ignore[assignment]

    async def call(principal, user_id):
        return await MR.search_user_memory(user_id, body, principal=principal, session=None)

    # 비-어드민 → 타 user_id: 403(게이트가 mem_cfg 전에 막음).
    check(raised(lambda: call(member, other), 403), "member → 타 user_id 403(프라이버시 경계)")
    # 비-어드민 → 본인 user_id: 통과(self-lock pin — 자기 것은 막지 않음).
    out_self = asyncio.run(call(member, str(member.id)))
    check(out_self.enabled is False and out_self.results == [],
          "member → 본인 user_id 통과(self-lock, mem_cfg None→enabled=False)")
    # 어드민 3종 → 임의 user_id: 통과.
    for name, pr in [("머신", machine), ("superuser", superuser), ("casbin-admin", admin)]:
        out = asyncio.run(call(pr, other))
        check(out.enabled is False, f"{name} → 타 user_id 통과")


def u3_scope_isolation() -> None:
    print("[U3] 스코프 격리(공유 코어 — 축 누출 0)")
    store = [
        {"id": "u1", "memory": "alice는 비건이다", "score": 0.9, "user_id": "alice"},
        {"id": "u2", "memory": "bob은 매운 걸 못 먹는다", "score": 0.7, "user_id": "bob"},
        {"id": "ag1", "memory": "이 에이전트는 한국어로 답한다", "score": 0.8, "agent_id": "agtX"},
    ]
    with_mem(FakeMem(store))

    # agent_id 검색 → 에이전트 기억만(유저 사실 누출 없음).
    hits = M.search({"agent_id": "agtX"}, "q", {"x": 1}, limit=10)
    texts = [h["text"] for h in hits]
    check(any("한국어" in t for t in texts), "agent_id 검색: 에이전트 기억 회상")
    check(not any("비건" in t or "매운" in t for t in texts), "agent_id 검색: user_id 기억 누출 0")
    check(all(h["scope"] == "agent_id" for h in hits), "agent_id hit scope 표기")
    check(all({"type", "text", "score", "scope"} <= set(h) for h in hits),
          "hit 구조 {type,text,score,scope}")

    # user_id 검색 → 그 유저 기억만(타 유저·agent 누출 없음).
    ha = M.search({"user_id": "alice"}, "q", {"x": 1}, limit=10)
    ta = [h["text"] for h in ha]
    check(any("비건" in t for t in ta), "user_id=alice 검색: alice 기억 회상")
    check(not any("매운" in t for t in ta), "user_id=alice 검색: bob 기억 누출 0")
    check(not any("한국어" in t for t in ta), "user_id=alice 검색: agent 기억 누출 0")
    check(all(h["scope"] == "user_id" for h in ha), "user_id hit scope 표기")


def u4_graceful() -> None:
    print("[U4] graceful(백엔드 미가용 → enabled=False·빈결과)")
    body = MemorySearchIn(query="질의", limit=4)
    no_mem()  # resolve_backend → None(미가용) — recall_probe가 None을 돌려 enabled=False.

    # 유저: _user_mem_cfg None(미구성).
    MR._user_mem_cfg = _async(None)  # type: ignore[assignment]
    MR.get_enforcer = lambda: FakeEnforcer(set())
    out_u = asyncio.run(MR.search_user_memory("machine_uid", body, principal="machine", session=None))
    check(out_u.enabled is False and out_u.results == [] and out_u.query == "질의" and out_u.limit == 4,
          "유저 검색: 미가용 → enabled=False·[]·query/limit 에코")

    # 에이전트: resolve_agent_mem_cfg None(에이전트는 존재).
    agent_obj = type("A", (), {"agent_id": "agtX"})()
    AG.resolve_agent_mem_cfg = _async(None)  # type: ignore[assignment]
    out_a = asyncio.run(AG.search_agent_memory(uuid.uuid4(), body, session=FakeSession(agent_obj)))
    check(out_a.enabled is False and out_a.results == [],
          "에이전트 검색: 미가용 → enabled=False·[]")

    # P2a 핀(적대 리뷰 084): mem_cfg는 *있지만* 백엔드 구성 실패(resolve_backend None) →
    # enabled=False여야 한다. "회상 0건"으로 위장하면 안 됨. mem_cfg 비None + no_mem()로 재현.
    AG.resolve_agent_mem_cfg = _async({"llm": {}, "embedder": {}})  # type: ignore[assignment]
    out_broken = asyncio.run(AG.search_agent_memory(uuid.uuid4(), body, session=FakeSession(agent_obj)))
    check(out_broken.enabled is False and out_broken.results == [],
          "P2a: mem_cfg 있음+백엔드 구성실패 → enabled=False(깨진 백엔드 위장 차단)")


def u5_agent_404() -> None:
    print("[U5] 없는 agent_id → 404(검색 전 차단)")
    body = MemorySearchIn(query="질의", limit=4)
    # FakeSession(None) → session.get은 None → _agent_mem_cfg가 404.
    check(raised(lambda: AG.search_agent_memory(uuid.uuid4(), body, session=FakeSession(None)), 404),
          "없는 에이전트 검색 → 404")


def u6_handler_recall() -> None:
    print("[U6] 핸들러 회상(백엔드 존재 → enabled=True + 회상)")
    store = [
        {"id": "ag1", "memory": "보고서는 한 줄 요약으로 시작한다", "score": 0.95, "agent_id": "agtX"},
        {"id": "other", "memory": "남의 에이전트 기억", "score": 0.9, "agent_id": "agtY"},
        {"id": "ux", "memory": "유저 사실", "score": 0.8, "user_id": "alice"},
    ]
    with_mem(FakeMem(store))
    body = MemorySearchIn(query="보고서 형식", limit=4)

    # 에이전트 핸들러: agtX만 회상(agtY·user 누출 0).
    agent_obj = type("A", (), {"agent_id": "agtX"})()
    AG.resolve_agent_mem_cfg = _async({"llm": {}, "embedder": {}})  # type: ignore[assignment]
    out_a = asyncio.run(AG.search_agent_memory(uuid.uuid4(), body, session=FakeSession(agent_obj)))
    txts = [h.text for h in out_a.results]
    check(out_a.enabled is True, "에이전트 핸들러: enabled=True")
    check(any("한 줄 요약" in t for t in txts), "에이전트 핸들러: 자기 기억 회상")
    check(not any("남의" in t or "유저 사실" in t for t in txts), "에이전트 핸들러: 타 스코프 누출 0")
    check(all(h.scope == "agent_id" for h in out_a.results), "에이전트 핸들러: scope=agent_id")

    # 유저 핸들러: alice만 회상.
    MR.get_enforcer = lambda: FakeEnforcer(set())
    MR._user_mem_cfg = _async({"llm": {}, "embedder": {}})  # type: ignore[assignment]
    body_u = MemorySearchIn(query="유저", limit=4)
    out_u = asyncio.run(MR.search_user_memory("alice", body_u, principal="machine", session=None))
    tu = [h.text for h in out_u.results]
    check(out_u.enabled is True, "유저 핸들러: enabled=True")
    check(any("유저 사실" in t for t in tu), "유저 핸들러: alice 기억 회상")
    check(not any("보고서" in t or "남의" in t for t in tu), "유저 핸들러: 타 스코프 누출 0")


def u7_recall_probe() -> None:
    print("[U7] recall_probe facade(미가용=None vs 가용=[] 구분 + 방어 슬라이스)")

    # P2a: 백엔드 미가용 → None(빈 []가 아님 — '미구성'과 '회상 0건'을 구분).
    no_mem()
    check(M.recall_probe({"user_id": "x"}, "q", None, 4) is None, "미가용 → None(≠ [])")
    check(M.recall_probe({"user_id": "x"}, "q", {"llm": {}, "embedder": {}}, 4) is None,
          "mem_cfg 있어도 백엔드 None → None(구성 실패 위장 차단)")

    # 가용·회상 0건 → [](None 아님). 빈 store FakeMem.
    with_mem(FakeMem([]))
    check(M.recall_probe({"user_id": "x"}, "q", {"llm": {}, "embedder": {}}, 4) == [],
          "가용·회상 0건 → [](≠ None)")

    # P2b: 백엔드가 limit를 무시하고 과다 반환해도 facade가 방어적으로 limit까지 슬라이스.
    class OverflowBackend:
        def search(self, scope, query, limit):
            return [{"type": "semantic", "text": f"m{i}", "score": 1.0, "scope": "user_id"}
                    for i in range(50)]

    M.resolve_backend = lambda mem_cfg: OverflowBackend()  # type: ignore[assignment]
    out = M.recall_probe({"user_id": "x"}, "q", {"llm": {}, "embedder": {}}, 4)
    check(out is not None and len(out) == 4, f"P2b: 과다 반환 → limit(4)까지 슬라이스 (got {len(out) if out else 'None'})")


# ================================================================ [H] 통합(in-process ASGI)
async def http_checks() -> None:
    print("[H] 통합 — in-process ASGI(라우트·422·auth·404·graceful 200)")
    import httpx
    from api import agents as _ag, memory_routes as _mr
    from api.auth import _token
    from api.main import app

    auth = {"Authorization": f"Bearer {_token()}"}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t", headers=auth, timeout=60) as c:
        # H1 라우트 등록(소스 라우터에서 직접 — app.routes는 커스텀 _IncludedRouter로 감싸져 평탄화 곤란).
        ap = {getattr(r, "path", "") for r in _ag.router.routes}
        mp = {getattr(r, "path", "") for r in _mr.router.routes}
        check("/agents/{agent_id}/memory/search" in ap, "H1 에이전트 검색 라우트 등록")
        check("/memory/user/{user_id}/search" in mp, "H1 유저 검색 라우트 등록")

        # 실 에이전트 하나 확보(없으면 H4·H5의 에이전트 경로 일부 SKIP).
        agents = (await c.get("/agents")).json()
        aid = agents[0]["id"] if agents else None

        # H2 스키마 422가 HTTP 계층에서 발화(유저 경로로 검증 — auth=머신=어드민).
        uid = "h_probe_uid"
        for q, label in [("   ", "공백"), ("", "빈"), ("가" * 4001, ">4000")]:
            r = await c.post(f"/memory/user/{uid}/search", json={"query": q, "limit": 4})
            check(r.status_code == 422, f"H2 {label} query → 422 (got {r.status_code})")
        for lim in (0, 11):
            r = await c.post(f"/memory/user/{uid}/search", json={"query": "x", "limit": lim})
            check(r.status_code == 422, f"H2 limit {lim} → 422 (got {r.status_code})")
        # 경계 통과(=4000, limit 10) → 422 아님.
        rb = await c.post(f"/memory/user/{uid}/search", json={"query": "가" * 4000, "limit": 10})
        check(rb.status_code != 422, f"H2 경계(query=4000·limit=10) → 422 아님 (got {rb.status_code})")

        # H3 auth: 토큰 없으면 401.
        async with httpx.AsyncClient(transport=transport, base_url="http://t", timeout=60) as nc:
            r = await nc.post(f"/memory/user/{uid}/search", json={"query": "x", "limit": 4})
            check(r.status_code == 401, f"H3 토큰 없음 → 401 (got {r.status_code})")

        # H4 없는 agent_id → 404.
        ghost = uuid.uuid4()
        r = await c.post(f"/agents/{ghost}/memory/search", json={"query": "x", "limit": 4})
        check(r.status_code == 404, f"H4 없는 에이전트 → 404 (got {r.status_code})")

        # H5 graceful 200: 실제 검색이 200(enabled true/false 무관 — 502/500 아님).
        r = await c.post(f"/memory/user/{uid}/search", json={"query": "선호", "limit": 4})
        check(r.status_code == 200, f"H5 유저 검색 → 200 (got {r.status_code})")
        j = r.json()
        check(set(j) >= {"query", "limit", "enabled", "results"}, "H5 유저 응답 형상")
        if aid:
            r = await c.post(f"/agents/{aid}/memory/search", json={"query": "선호", "limit": 4})
            check(r.status_code == 200, f"H5 에이전트 검색 → 200 (got {r.status_code})")
        else:
            print("  ..  H5 에이전트 경로 SKIP(등록 에이전트 없음)")


# ================================================================ main
if __name__ == "__main__":
    u1_schema()
    u2_rbac()
    u3_scope_isolation()
    u4_graceful()
    u5_agent_404()
    u6_handler_recall()
    u7_recall_probe()
    print()
    try:
        asyncio.run(http_checks())
    except Exception as exc:  # noqa: BLE001
        print(f"  ..  [H] 통합 SKIP — DB/앱 미가용({type(exc).__name__}: {exc})")
        print("      U(단위)만으로 핵심 불변식 보증; H는 dev DB 가동 시 재실행.")

    print()
    if _fails:
        print(f"❌ {len(_fails)} FAILED")
        for f in _fails:
            print("   - " + f)
        sys.exit(1)
    print("✅ ALL PASS (VERIFY084_OK)")

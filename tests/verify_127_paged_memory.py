"""verify_127 — 기억 페이지 목록(list_page) + list_all 20건 캡 수정 (스펙 127).

3런 중 ①단위 시맨틱 + ②실 인프라 통합(도커 pg의 mem0_memories 직접). ③적대는 codex 별도.

A(단위, inmemory): list_page 계약 — 최신순·q 대소문자무시 부분일치·offset/limit·합집합 dedup·빈스코프.
B(단위, mem0 fake): list_all이 get_all에 top_k=_LIST_ALL_CAP을 **명시**(미지정=20 잘림 버그 회귀 방지).
C(통합, 실 pg): 시드 25건(별도 유저) → total=25(20캡 해소)·페이지 경계·ILIKE 부분일치·
  와일드카드(%_) 이스케이프·타 유저 불가시(스코프 SQL WHERE)·최신순. 시드는 항상 정리(finally).
D(자가-잠금): 시드 유저 자신의 조회는 전부 통과(C가 겸함) + 21번째 기억이 목록에 존재.

실행: uv run --project packages/api python tests/verify_127_paged_memory.py
전제: 도커 my-agents-postgres-1 (agents DB, mem0_memories 존재).
"""

import os
import subprocess
import sys
import uuid

sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "packages", "api", "src"
    ),
)

_fails: list[str] = []
passed = 0


def check(cond: bool, msg: str) -> None:
    global passed
    print(("  ok  " if cond else " FAIL ") + msg)
    if cond:
        passed += 1
    else:
        _fails.append(msg)


# ---------- A: inmemory 단위 ----------
def part_a() -> None:
    from api.memory.inmemory_backend import InMemoryBackend

    b = InMemoryBackend()
    for i in range(1, 26):
        b.add({"user_id": "u1"}, [{"content": f"기억 번호 {i}"}], False)  # 현 시그니처: _infer 위치 인자
    b.add({"user_id": "u2"}, [{"content": "남의 기억"}], False)

    p1 = b.list_page({"user_id": "u1"}, None, 20, 0)
    check(
        p1["total"] == 25 and len(p1["items"]) == 20,
        f"A1 1페이지 20/총25 (got {p1['total']}/{len(p1['items'])})",
    )
    p2 = b.list_page({"user_id": "u1"}, None, 20, 20)
    check(len(p2["items"]) == 5, f"A2 2페이지 5건 (got {len(p2['items'])})")
    check(p1["items"][0]["text"] == "기억 번호 25", f"A3 최신순 (got {p1['items'][0]['text']!r})")
    q = b.list_page({"user_id": "u1"}, "번호 7", 20, 0)
    check(
        q["total"] == 1 and q["items"][0]["text"] == "기억 번호 7",
        f"A4 부분일치 (got {q['total']})",
    )
    check(b.list_page({"user_id": "u2"}, None, 20, 0)["total"] == 1, "A5 스코프 격리(u2=1건)")
    check(b.list_page({}, None, 20, 0) == {"items": [], "total": 0}, "A6 빈 스코프 → 빈/0")
    big = b.list_page({"user_id": "u1"}, None, 9999, -5)
    check(len(big["items"]) <= 100, "A7 limit 100 clamp·offset 음수 방어")


# ---------- B: mem0 list_all top_k 명시(회귀 핀) ----------
def part_b() -> None:
    from api.memory import mem0_backend as MB

    calls: list[dict] = []

    class FakeMem:
        def get_all(self, filters=None, **kw):
            calls.append({"filters": filters, **kw})
            return {"results": [{"id": "m1", "memory": "x"}]}

    obj = MB.Mem0Backend.__new__(MB.Mem0Backend)  # __init__(mem0 초기화) 우회 — get_all 인자만 검사
    obj._mem = FakeMem()
    rows = obj.list_all({"user_id": "u"})
    check(
        len(rows) == 1 and calls and calls[0].get("top_k") == MB._LIST_ALL_CAP,
        f"B1 list_all이 top_k={MB._LIST_ALL_CAP} 명시(미지정=20 잘림 회귀 방지) (got {calls})",
    )


# ---------- C: 실 pg 통합 ----------
# DB명은 DATABASE_URL에서 유도 — throwaway(virgin) 서버는 전용 DB를 쓴다(하드코딩 'agents' 금지).
_DBNAME = os.environ.get("DATABASE_URL", "//agents").rsplit("/", 1)[-1]
_PG = [
    "docker",
    "exec",
    "my-agents-postgres-1",
    "psql",
    "-U",
    "agent",
    "-d",
    _DBNAME,
    "-t",
    "-A",
    "-c",
]
SEED_USER = f"verify127-{uuid.uuid4().hex[:8]}"
OTHER_USER = SEED_USER + "-other"


def psql(sql: str) -> str:
    r = subprocess.run([*_PG, sql], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(f"psql 실패: {r.stderr.strip()[:200]}")
    return r.stdout.strip()


def seed() -> None:
    # virgin DB엔 mem0 테이블이 없다(mem0가 첫 백엔드 초기화 때 지연 생성) — mem0 pgvector 스키마와
    # 동형으로 선생성(IF NOT EXISTS: dev DB처럼 이미 있으면 무해). part C는 이 3컬럼만 쓴다.
    psql(
        "CREATE TABLE IF NOT EXISTS mem0_memories "
        "(id UUID PRIMARY KEY, vector vector(1024), payload JSONB)"
    )
    # 25건(+타유저 1건). 텍스트에 ILIKE 이스케이프 검증용 특수문자 행 포함(#24: 'a%b_c').
    psql(
        "INSERT INTO mem0_memories (id, vector, payload) "
        "SELECT gen_random_uuid(), array_fill(0, ARRAY[1024])::vector, "
        "jsonb_build_object('data', CASE WHEN i = 24 THEN 'seed a%b_c 특수' ELSE 'seed 기억 #' || i END, "
        f"'user_id', '{SEED_USER}', "
        "'created_at', to_char(now() - (i || ' minutes')::interval, 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"+00:00\"')) "
        "FROM generate_series(1, 25) i"
    )
    psql(
        "INSERT INTO mem0_memories (id, vector, payload) VALUES "
        f"(gen_random_uuid(), array_fill(0, ARRAY[1024])::vector, jsonb_build_object('data', '타유저 기억', 'user_id', '{OTHER_USER}'))"
    )


def cleanup() -> None:
    n = psql(
        f"WITH d AS (DELETE FROM mem0_memories WHERE payload->>'user_id' IN ('{SEED_USER}', '{OTHER_USER}') RETURNING 1) SELECT count(*) FROM d"
    )
    print(f"  (정리: {n}건 삭제)")


def part_c() -> None:
    from api.memory import mem0_backend as MB

    obj = MB.Mem0Backend.__new__(MB.Mem0Backend)  # mem0 초기화 우회 — list_page는 _dsn만 사용
    obj._dsn = MB._sync_dsn(
        os.environ.get("DATABASE_URL", "postgresql+asyncpg://agent:agent@localhost:5432/agents")
    )

    p1 = obj.list_page({"user_id": SEED_USER}, None, 20, 0)
    check(p1["total"] == 25, f"C1 total=25 — 20건 캡 해소 (got {p1['total']})")
    check(len(p1["items"]) == 20, f"C2 1페이지 20건 (got {len(p1['items'])})")
    p2 = obj.list_page({"user_id": SEED_USER}, None, 20, 20)
    check(len(p2["items"]) == 5, f"C3 2페이지 5건 (got {len(p2['items'])})")
    ids1 = {it["id"] for it in p1["items"]}
    check(not ids1 & {it["id"] for it in p2["items"]}, "C4 페이지 간 중복 없음(결정적 순서)")
    check(
        p1["items"][0]["text"] == "seed 기억 #1",
        f"C5 최신순(1분 전=#1 최신) (got {p1['items'][0]['text']!r})",
    )

    q = obj.list_page({"user_id": SEED_USER}, "기억 #7", 20, 0)
    check(q["total"] == 1, f"C6 ILIKE 부분일치 유일 매치 (got {q['total']})")
    wc = obj.list_page({"user_id": SEED_USER}, "a%b_c", 20, 0)
    check(
        wc["total"] == 1 and "a%b_c" in wc["items"][0]["text"],
        f"C7 와일드카드(%·_) 이스케이프 — 리터럴만 매치 (got {wc['total']})",
    )
    pct = obj.list_page({"user_id": SEED_USER}, "%", 20, 0)
    check(
        pct["total"] == 1,
        f"C8 '%' 단독 질의가 전체 매치로 새지 않음 (got {pct['total']}, 특수문자 행만)",
    )

    texts = [it["text"] for it in p1["items"]] + [it["text"] for it in p2["items"]]
    check("타유저 기억" not in texts, "C9 타 유저 행 불가시(스코프 SQL WHERE)")
    check(
        any("#21" in t for t in texts),
        "D1 자가-잠금: 21번째 기억이 목록에 존재(캡 버그였다면 부재)",
    )

    # C11(codex 127 #3): created_at 포맷 이탈 행('9999')이 섞여도 쿼리가 안 깨지고 맨 뒤(NULLS LAST)로.
    psql(
        "INSERT INTO mem0_memories (id, vector, payload) VALUES "
        f"(gen_random_uuid(), array_fill(0, ARRAY[1024])::vector, jsonb_build_object('data', 'seed 포맷이탈', 'user_id', '{SEED_USER}', 'created_at', '9999'))"
    )
    mixed = obj.list_page({"user_id": SEED_USER}, None, 100, 0)
    check(
        mixed["total"] == 26 and mixed["items"][-1]["text"] == "seed 포맷이탈",
        f"C11 포맷 이탈 created_at → 캐스트 가드로 맨 뒤(NULLS LAST) (got last={mixed['items'][-1]['text']!r})",
    )

    # 실패≠0건: 잘못된 DSN이면 빈 결과가 아니라 예외를 던진다(learning 125).
    bad = MB.Mem0Backend.__new__(MB.Mem0Backend)
    bad._dsn = "postgresql://agent:wrong@localhost:1/nope"
    try:
        bad.list_page({"user_id": SEED_USER}, None, 20, 0)
        check(False, "C10 실패≠0건 — 예외를 던져야 함(빈 결과 위장 금지)")
    except Exception:
        check(True, "C10 실패≠0건 — DB 실패는 예외로 표면화(빈 결과 위장 안 함)")


def main() -> None:
    print("[A] inmemory 단위")
    part_a()
    print("[B] mem0 list_all top_k 회귀 핀")
    part_b()
    print("[C/D] 실 pg 통합")
    seed()
    try:
        part_c()
    finally:
        cleanup()

    print(f"\n{passed} passed, {len(_fails)} failed")
    if _fails:
        for f in _fails:
            print("  ✗", f)
        sys.exit(1)


if __name__ == "__main__":
    main()

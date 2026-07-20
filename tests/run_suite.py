"""회귀 스위트 러너 — 죽어 있던 verify 스위트를 상시 그물로 (스펙 353).

359개 verify를 짜놓고 상시 도는 건 하나뿐이었다. 이 러너가 **기준선 측정**과 **CI 그물**을 겸한다:
카테고리별로 돌려 통과/실패/에러를 집계하고, **그물(비격리)이 전부 통과하면 exit 0**.

**설계 핵심 — 격리 목록(KNOWN_DRIFT)**: 지금 깨진 것을 그물에 넣으면 그물이 늘 빨개서 "무엇이 *새로*
깨졌나"를 못 본다. 그래서 드리프트는 여기 격리하고, 그물은 통과분만으로 초록을 유지한다. 격리는
**은폐가 아니다** — 매 실행 "N개 격리 중"을 명시 출력하고, 목표는 이 집합이 **줄어드는 것**이다.
격리된 게 갑자기 통과하면(=고쳐졌으면) 그것도 알려준다("격리 해제 후보").

카테고리(파일 내용으로 자동 분류):
  unit  — 순수 무의존(서버·DB 없이 즉시). 가장 빠른 그물.
  db    — DB 필요(SessionLocal 등).
  asgi  — ASGITransport 인프로세스(스펙 385). 서버 불필요 — 스크립트마다 virgin DB
          (_throwaway_db.py)로 격리 실행, 공유 라이브 DB 무접촉.
  http  — 서버 필요 층(스펙 390). 스크립트마다 virgin DB+**전용 uvicorn**(_throwaway_server.py)로
          격리 실행 — 라이브 dev 서버·DB 무접촉, VERIFY_BASE로 임시 포트 주입.
  (browser는 별도 러너 — playwright/vite 전제라 이 러너 밖.)

실행:
  uv run python tests/run_suite.py unit          # 순수층만
  uv run python tests/run_suite.py unit db        # 순수+DB
  uv run python tests/run_suite.py asgi           # 인프로세스층(virgin DB, 서버 불필요)
  uv run python tests/run_suite.py all            # unit+db+asgi+http (http는 서버 전제)
  uv run python tests/run_suite.py unit --list    # 분류만 보고 실행 안 함
"""

import concurrent.futures
import pathlib
import re
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))  # tests/ — _dbharness import(스펙 414)
from _dbharness import fresh_db

ROOT = pathlib.Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"

# 격리 목록 — 지금 드리프트(테스트/자산 노후, 코드 회귀 아님)라 그물에서 뺀다. 사유를 함께 적는다
# (은폐 금지). **목표는 이 집합을 줄이는 것.** 고쳐서 통과하기 시작하면 여기서 지운다.
# 스펙 400(43→5)·402(5→0) 재활 캠페인으로 격리 전량 해소(2026-07-19). 새 드리프트는 정직한
# 사유와 함께 여기 격리하고, 고치면 지운다(빈 dict 유지 — 그물의 정상 상태).
KNOWN_DRIFT: dict[str, str] = {}

# 러너 자신·인자 필요·특수 스크립트는 스위트에서 제외(그물 대상 아님).
EXCLUDE = {
    "run_suite.py",
    "verify_index_recompress.py",  # 인자(before.json) 필요 — 재압축 전용
}

_HTTP = re.compile(
    r"127\.0\.0\.1:8000|localhost:8000|urlopen|requests\.|httpx|BASE\s*=\s*['\"]http"
)
_DB = re.compile(
    r"SessionLocal|get_session|asyncpg|create_engine|import sqlalchemy|from sqlalchemy"
)
_LIVE = re.compile(r"127\.0\.0\.1:8000|localhost:8000")


def categorize(f: pathlib.Path) -> str:
    t = f.read_text(errors="ignore")
    # asgi 층(스펙 385): ASGITransport 인프로세스 — 라이브 서버(:8000)를 안 치므로 DATABASE_URL만
    # 격리하면 상태 안전. run_one이 _throwaway_db.py(virgin DB)로 감싸 실행한다.
    if "ASGITransport" in t and not _LIVE.search(t):
        return "asgi"
    if _HTTP.search(t):
        return "http"
    if _DB.search(t):
        return "db"
    return "unit"


def collect() -> dict[str, list[pathlib.Path]]:
    cats: dict[str, list[pathlib.Path]] = {"unit": [], "db": [], "asgi": [], "http": []}
    for f in sorted(TESTS.glob("verify_*.py")):
        if f.name in EXCLUDE:
            continue
        cats[categorize(f)].append(f)
    return cats


def run_one(
    f: pathlib.Path,
    isolate: bool = False,
    isolate_server: bool = False,
    env: dict | None = None,
) -> tuple[str, str, str]:
    """(name, verdict, detail). verdict ∈ pass|fail|error.

    격리 래핑 세 경로:
    - isolate_server=True(http 층, 스펙 390): virgin DB + **전용 uvicorn**(_throwaway_server.py) —
      라이브 dev 서버·DB 무접촉. 테스트는 VERIFY_BASE로 임시 포트를 주입받는다.
    - isolate=True(asgi 층, 스펙 385): 층 전체를 virgin DB로(_throwaway_db.py).
    - 파일 마커: virgin-DB 전용 테스트(자체 헤더가 `_throwaway_db.py` 사용을 명시) —
      스펙 370 실측: verify_343_downgrade를 라이브 DB에 직접 돌리면 downgrade 왕복이 369/370의
      런타임 저작 데이터(블록 이력·pins)를 지운다(손실 왕복)."""
    cmd = ["uv", "run", "python", str(f)]
    timeout = 120
    if isolate_server:
        cmd = ["uv", "run", "python", str(TESTS / "_throwaway_server.py"), str(f)]
        timeout = 300  # 서버 부팅(alembic+seed 포함) + 테스트
    elif isolate or "_throwaway_db.py" in f.read_text(errors="ignore"):
        cmd = ["uv", "run", "python", str(TESTS / "_throwaway_db.py"), str(f)]
        timeout = 180  # virgin DB 부트스트랩(CREATE DATABASE+alembic+seed) 비용 포함
    try:
        # env(스펙 414): db 그룹은 run당 virgin DB의 DATABASE_URL 주입(dev DB 무접촉). None이면 상속.
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        return f.name, "error", f"timeout({timeout}s)"
    out = r.stdout + r.stderr
    if r.returncode != 0:
        # 비결정 실패 디버깅용 전체 출력 보존(스펙 402 계측) — 그물이 한 줄 요약만 남기면
        # "배터리에서만 붉은" 실패는 영영 원인을 못 잡는다. 최근 실패만 유지(이름당 1파일 덮어씀).
        import pathlib as _pl

        _fd = _pl.Path("/tmp/run_suite_fails")
        _fd.mkdir(exist_ok=True)
        (_fd / f"{f.name}.log").write_text(out[-20000:], errors="ignore")
    if r.returncode == 0:
        return f.name, "pass", ""
    if re.search(
        r"Traceback|ImportError|ModuleNotFoundError|AttributeError|FileNotFoundError", out
    ):
        exc = [ln for ln in out.splitlines() if re.match(r"\w*(Error|Exception)", ln)]
        return f.name, "error", (exc[-1][:70] if exc else f"rc={r.returncode}")
    return f.name, "fail", f"rc={r.returncode}"


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    cats = collect()
    # 기본 그물 = unit + db. http는 **명시 요청 시에만**(all 또는 http) — http 통합 테스트는 깨끗한
    # 서버·DB를 전제하는데 한 서버에 순차로 던지면 서로(그리고 자기 재실행)를 오염시킨다(스펙 353 실측:
    # verify_037은 앞 실행이 남긴 컬렉션에 400, 346은 상태 오염 StopIteration). 각자 단독+정리 또는
    # 격리 DB가 필요해 일괄 러너에 안 맞는다. 씨앗 그물은 상태 격리가 되는 unit+db로 긋는다.
    if "all" in args:
        wanted = ["unit", "db", "asgi", "http"]
    elif not args:
        wanted = ["unit", "db"]
    else:
        wanted = args
    wanted = [c for c in wanted if c in cats]

    if "--list" in flags:
        for c in wanted:
            names = [f.name for f in cats[c]]
            drift = [n for n in names if n in KNOWN_DRIFT]
            print(f"[{c}] {len(names)}개 (그물 {len(names) - len(drift)} · 격리 {len(drift)})")
            for n in names:
                print(f"   {'격리' if n in KNOWN_DRIFT else '  net'}  {n}")
        return

    net_broken: list[tuple[str, str]] = []
    drift_now_passing: list[str] = []
    totals = {"pass": 0, "fail": 0, "error": 0}

    for c in wanted:
        files = cats[c]
        print(f"\n=== [{c}] {len(files)}개 실행 ===")
        # unit만 병렬 안전(공유 상태 없이 파일만 읽음). db/http는 **같은 DB·서버를 공유**해 병렬로
        # 돌리면 서로 시드·테이블을 밟아 **거짓 실패**를 만든다(스펙 353 실측: verify_038이 단독 exit 0인데
        # 6-병렬 판에선 error). 그래서 db/http는 직렬. asgi도 직렬 — DB는 각자 virgin이지만
        # CREATE DATABASE TEMPLATE template0이 동시 실행 시 "source database is being accessed" 충돌.
        workers = 6 if c == "unit" else 1
        isolate = c == "asgi"  # 스펙 385: asgi 층은 스크립트마다 virgin DB(_throwaway_db.py)
        iso_srv = c == "http"  # 스펙 390: http 층은 스크립트마다 virgin DB+전용 서버
        if c == "db":
            # 스펙 414: db 그룹 전체를 **run당 virgin DB 1개**로 격리(dev DB 잔재·동시활동·상호오염
            # 차단). 부트스트랩(alembic+seed) 1회 상각 후 전 db 테스트가 그 DB를 DATABASE_URL로 공유.
            # _throwaway_db.py 마커 테스트(파괴적 downgrade 등)는 run_one이 여전히 자기 per-test DB로.
            print("  [db] run당 virgin DB 격리 — dev DB 무접촉(스펙 414)")
            with fresh_db(label="run") as (_run_url, run_env):
                results = [run_one(f, env=run_env) for f in files]
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
                results = list(
                    ex.map(
                        lambda f, _i=isolate, _s=iso_srv: run_one(f, isolate=_i, isolate_server=_s),
                        files,
                    )
                )
        for name, verdict, detail in sorted(results):
            totals[verdict] += 1
            drift = name in KNOWN_DRIFT
            if verdict == "pass":
                if drift:
                    drift_now_passing.append(name)
                    print(f"  ✅→ {name}  (격리인데 통과 — 격리 해제 후보)")
            else:
                mark = "격리" if drift else "🔴그물"
                print(f"  {'· ' if drift else 'X '}{mark} {name}: {detail}")
                if not drift:
                    net_broken.append((name, detail))

    # ---- 요약
    drift_total = sum(1 for c in wanted for f in cats[c] if f.name in KNOWN_DRIFT)
    print(f"\n{'=' * 60}")
    print(f"통과 {totals['pass']} · 실패 {totals['fail']} · 에러 {totals['error']}")
    print(f"격리(KNOWN_DRIFT) {drift_total}개 — 목표는 이 수를 줄이는 것:")
    for c in wanted:
        for f in cats[c]:
            if f.name in KNOWN_DRIFT:
                print(f"   · {f.name} — {KNOWN_DRIFT[f.name]}")
    if drift_now_passing:
        print(f"\n격리 해제 후보(고쳐진 듯) {len(drift_now_passing)}개: {drift_now_passing}")
    if net_broken:
        print(f"\n🔴 그물이 깨졌다 {len(net_broken)}개 (새 회귀 — 격리 목록에 없음):")
        for n, d in net_broken:
            print(f"   X {n}: {d}")
        print("\nSUITE_FAIL")
        sys.exit(1)
    print("\nSUITE_OK — 그물(비격리) 전부 통과")


if __name__ == "__main__":
    main()

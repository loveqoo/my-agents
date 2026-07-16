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
  http  — 서버 필요(127.0.0.1:8000). dev 서버 전제.
  (browser는 별도 러너 — playwright/vite 전제라 이 러너 밖.)

실행:
  uv run python tests/run_suite.py unit          # 순수층만
  uv run python tests/run_suite.py unit db        # 순수+DB
  uv run python tests/run_suite.py all            # unit+db+http (서버 전제)
  uv run python tests/run_suite.py unit --list    # 분류만 보고 실행 안 함
"""

import concurrent.futures
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"

# 격리 목록 — 지금 드리프트(테스트/자산 노후, 코드 회귀 아님)라 그물에서 뺀다. 사유를 함께 적는다
# (은폐 금지). **목표는 이 집합을 줄이는 것.** 고쳐서 통과하기 시작하면 여기서 지운다.
KNOWN_DRIFT: dict[str, str] = {
    "verify_040_memory_backend_contract.py": "노후: 백엔드 계약 표면 변경 미반영(스펙 353 실측)",
    "verify_043_index.py": "자산 드리프트: 인덱스↔파일 번호 불일치(learning 146~151·retro 130 등)",
    "verify_059_mock_default.py": "노후: 시드 채팅모델 이름 mock-chat→mock-llm 미반영",
    "verify_130_broker_rag_visibility.py": "노후: 브로커 RAG 가시성 표면 변경(스펙 353 실측)",
    "verify_131_inspector_detail.py": "노후: 인스펙터 상세 스키마 변경 미반영",
    "verify_191_rag_threshold.py": "노후: RAG 임계 기대치 드리프트",
    "verify_029_agent_memory.py": "노후: 파일 경로 하드코딩(FileNotFound)",
    "verify_115_attribution_fence.py": "노후: 상대경로 'src' 하드코딩(FileNotFound)",
    # --- db층 드리프트(스펙 353 실측). 전부 **캠페인 346~352와 무관한 기존 노후**로 확증:
    #     나머지는 캠페인 모듈을 import조차 안 함. eval 스위트가 무더기로 노후(스키마·라우트 표면 변경).
    #     (verify_049는 스펙 382에서 해제 — _create_approval user_id 미갱신+ctx dict→DTO 동반 봉합.)
    "verify_083_expose_gate.py": "노후: expose 게이트 기대치 드리프트(캠페인 무관)",
    "verify_122_orchestrator_override_capabilities.py": "노후: 오케스트레이터 오버라이드 표면 변경",
    "verify_127_paged_memory.py": "노후: InMemoryBackend.add() 시그니처 변경 미반영",
    "verify_137_eval_crud.py": "노후: eval 라우트 Query 시그니처 변경(expected str got Query)",
    "verify_137_eval_runner.py": "노후: eval 러너 스키마 드리프트",
    "verify_139_llm_judge.py": "노후: LLM judge eval 스키마 드리프트",
    "verify_140_rag_eval.py": "노후: RAG eval 스키마 드리프트",
    "verify_141_model_matrix.py": "노후: model matrix eval 드리프트",
    "verify_148_naming.py": "노후: 네이밍 규칙 기대치 드리프트(캠페인 무관)",
    "verify_178_member_eval_ownership.py": "노후: eval 라우트 Query 시그니처(expected str got Query)",
    "verify_193_eval_ux.py": "노후: eval UX 라우트 Query 시그니처(expected str got Query)",
    "verify_329_residual_removal.py": "노후: 플랜 데모 잔여 제거 기대치 드리프트(캠페인 무관)",
    "verify_345_seed_actor.py": "환경: 처녀 DB 전제(빈 DB 필요) — 상시 그물엔 부적합, 초기화 검증 전용",
    "verify_059_integration.py": "환경: '모든 컬렉션=mock-embed' 불변식이 다른 테스트 잔여 컬렉션에 취약(깨끗한 부팅 전제)",
    # --- http 층 드리프트(2026-07-16 test-all hygiene 실측). 전부 캠페인 374(리팩터)와 무관 —
    #     baseline(2fbd224) 동일 실패 또는 데이터/환경 전제. 리팩터가 낸 회귀(rag 재수출·151·347)는
    #     별도로 고쳐 그물에 복귀. 아래는 사전존재 드리프트라 사유 달아 격리(고치면 여기서 지운다).
    "verify_114_owner_display.py": "환경: owner_id=None 레거시 에이전트 전제(현 seed 없음 → next() StopIteration)",
    "verify_143_suggest.py": "환경: '옵시디언 매니저' 시드 에이전트 전제(현 seed에 없음)",
    "verify_161_persona_sync.py": "노후: promptStale이 후속 스펙서 adopt(채택)로 일반화·대체(응답 키 없음)",
    "verify_233_capability_matrix.py": "환경: http 상태 오염 취약(단독 통과 VERIFY233_OK — orchestrate_ranked×agent PASS. 옛 '위임 갭' 사유는 오경보였다, 스펙383 실측)",
    "verify_235_ephemeral.py": "노후: 스펙346 durability=exit로 턴종료 체크포인트 정리 → 비-ephemeral 대조도 Δ=0(pre-346 기대, ephemeral 본 로직 E4/E5는 통과)",
    "verify_240_eval_version.py": "노후: eval 버전 추적 스키마 드리프트(agent_version None, baseline 동일·캠페인 무관)",
    "verify_242_version_exec.py": "노후: 버전 실행 eval 스키마/데이터 드리프트(baseline 동일)",
    "verify_244_version_ops.py": "노후: 버전 ops eval 집계 드리프트(runs/score None, baseline 동일)",
    "verify_318_node_agent_call.py": "환경/상태: 노드 에이전트 위임 brokerCalls(실 principal·세션 상태 전제, http 상태 의존)",
    "verify_369_block_versioning.py": "환경: http 상태 오염 취약(단독 통과, test-all 순서서 실패)",
    "verify_068_live.py": "인프라: D6 member resume가 'connection is closed'로 500(baseline 동일·사전존재, ctx dict→DTO는 봉합). 별도 조사(asyncpg 커넥션 수명)",
}

# 러너 자신·인자 필요·특수 스크립트는 스위트에서 제외(그물 대상 아님).
EXCLUDE = {
    "run_suite.py",
    "verify_index_recompress.py",  # 인자(before.json) 필요 — 재압축 전용
}

_HTTP = re.compile(r"127\.0\.0\.1:8000|localhost:8000|urlopen|requests\.|httpx|BASE\s*=\s*['\"]http")
_DB = re.compile(r"SessionLocal|get_session|asyncpg|create_engine|import sqlalchemy|from sqlalchemy")


def categorize(f: pathlib.Path) -> str:
    t = f.read_text(errors="ignore")
    if _HTTP.search(t):
        return "http"
    if _DB.search(t):
        return "db"
    return "unit"


def collect() -> dict[str, list[pathlib.Path]]:
    cats: dict[str, list[pathlib.Path]] = {"unit": [], "db": [], "http": []}
    for f in sorted(TESTS.glob("verify_*.py")):
        if f.name in EXCLUDE:
            continue
        cats[categorize(f)].append(f)
    return cats


def run_one(f: pathlib.Path) -> tuple[str, str, str]:
    """(name, verdict, detail). verdict ∈ pass|fail|error.

    virgin-DB 전용 테스트(자체 헤더가 `_throwaway_db.py` 사용을 명시)는 격리 러너로 감싼다 —
    스펙 370 실측: verify_343_downgrade를 라이브 DB에 직접 돌리면 downgrade 왕복이 369/370의
    런타임 저작 데이터(블록 이력·pins)를 지운다(손실 왕복). 마커=파일 본문의 `_throwaway_db.py`."""
    cmd = ["uv", "run", "python", str(f)]
    if "_throwaway_db.py" in f.read_text(errors="ignore"):
        cmd = ["uv", "run", "python", str(TESTS / "_throwaway_db.py"), str(f)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return f.name, "error", "timeout(120s)"
    out = r.stdout + r.stderr
    if r.returncode == 0:
        return f.name, "pass", ""
    if re.search(r"Traceback|ImportError|ModuleNotFoundError|AttributeError|FileNotFoundError", out):
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
        wanted = ["unit", "db", "http"]
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
        # 6-병렬 판에선 error). 그래서 db/http는 직렬.
        workers = 6 if c == "unit" else 1
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
            results = list(ex.map(run_one, files))
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

"""브라우저 verify 그물 러너(스펙 438) — 씨앗 그물(run_suite, 스펙 353)의 브라우저판.

`tests/browser/verify-*.mjs`를 **순차** 실행한다(브라우저는 병렬 시 세션·화면·픽스처 경합 — vite·api·
라이브 DB 공유). 전제: vite(5173)·api(8000)·playwright(tests/e2e/node_modules) — 없으면 fail-fast.

격리(`KNOWN_DRIFT_BROWSER`): 지금 깨진 것(사유 필수)을 그물 밖으로 — 은폐가 아니라 부채 가시화
(run_suite KNOWN_DRIFT와 같은 계약). **목표는 이 집합을 줄이는 것.** 격리된 게 통과하면 해제 후보 알림.

상시 그물(make test)에 불포함 — 느림(수십 분)+실모델·vite 전제. 수동/스펙 마감용:
  uv run python tests/run_browser_suite.py            # 전수(격리 제외 판정)
  uv run python tests/run_browser_suite.py --only 193  # 부분(쉼표 구분 부분일치)
  uv run python tests/run_browser_suite.py --list      # 분류만
진행 노출(스펙 431): /tmp/suite-progress.json + [n/N] 스트리밍. 실행 중 저장소 편집·dev 서버 사용
금지(net-runs-are-exclusive — 거짓 실패의 뿌리).
"""

from __future__ import annotations

import pathlib
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))  # tests/ — _progress
from _progress import ProgressWriter

ROOT = pathlib.Path(__file__).resolve().parents[1]
BROWSER = ROOT / "tests" / "browser"
PLAYWRIGHT_DIR = ROOT / "tests" / "e2e" / "node_modules" / "playwright"
TIMEOUT_S = 300  # 실모델 다턴 스크립트(425 등) 여유 — 개별 스크립트가 자체 타임아웃도 가짐

# 격리 목록 — 사유 필수(은폐 금지). 고치면 지운다. run_suite.KNOWN_DRIFT와 같은 계약.
# 2026-08-04 전수 triage(스펙 438) — 군집별 사유. 목표는 이 집합을 줄이는 것(재활 캠페인 후보).
_R_ACCT = "픽스처 드리프트: 사라진 영속 계정/데이터 전제(7/28 초기화) — provisionSuper/자가픽스처로 재활"
_R_370 = "스펙 370 드리프트: 생성=초안(활성 버전 null) — activate 호출 추가로 재활"
_R_UI = "UI 개편 드리프트: 셀렉터/흐름 노후 — 개별 현행화 필요"
_R_ENV = "환경 전제: 실데이터 적재(movie-demo 스킬 등) 필요"
_R_CRASH = "스크립트 크래시(Node 오류 꼬리) — 개별 조사 필요"
_R_437 = "스펙 437 샘플 내용 차이: 옛 수동 샘플 문구 기대 — 질의/샘플 정합화로 재활"
_R_SUS = "실버그 의심(백로그 등재) — 개별 조사 전까지 격리"
KNOWN_DRIFT_BROWSER: dict[str, str] = {
    # A. 계정·픽스처 소실
    "verify-approval-history.mjs": _R_ACCT,
    "verify-inline-approval.mjs": _R_ACCT,
    "verify-self-approval.mjs": _R_ACCT,
    "verify-useagents-185b.mjs": _R_ACCT,
    "verify-approval-input-blocked.mjs": _R_ACCT,
    "verify-toolbox-recall-363.mjs": _R_ACCT + "(기억 픽스처 소실 memories=0)",
    # B. 스펙 370 버전 흐름
    "verify-318-node-agent-call-ui.mjs": _R_370,
    "verify-318-override-agent-picker.mjs": _R_370,
    "verify-320-tool-error-inspector.mjs": _R_370,
    # C. 437 샘플 정합
    "verify-pipeline-rag.mjs": _R_437,
    # D. 환경 전제
    "verify-310-rag-meta-assert.mjs": _R_ENV + "(movies-demo 컬렉션)",
    # E. 크래시/개별 조사
    "verify-346-checkpoint-ui.mjs": _R_CRASH,
    "verify-doc-edit-331.mjs": _R_CRASH,
    "verify-inspector-honesty-205.mjs": _R_CRASH,
    "verify-drawers-097.mjs": _R_CRASH,
    # F. 실버그 의심(백로그 조사 후보)
    "verify-312-reindex.mjs": _R_SUS + ": 재인덱싱 이력 0건(434/436 변경 접점 — 우선 조사)",
    "verify-344-audit-ui.mjs": _R_SUS + ": 감사 actor 표시 U1/U2",
    "verify-inspector-matrix.mjs": _R_SUS + ": 회상 trace 미표시(스펙 362 축)",
    # UI 개편 드리프트(개별 현행화 후보 — eval/artifact/agents 계열)
    "verify-269-memory-framing.mjs": _R_UI,
    "verify-273-override-shared-memory.mjs": _R_UI,
    "verify-275-node-collapse.mjs": _R_UI,
    "verify-287-node-override-drawer.mjs": _R_UI,
    "verify-309-runwithtoast.mjs": _R_UI,
    "verify-404-attach.mjs": _R_UI,
    "verify-405-knowledge.mjs": _R_UI,
    "verify-406-dragdrop.mjs": _R_UI,
    "verify-408-single-badge.mjs": _R_UI,
    "verify-409-model-form.mjs": _R_UI,
    "verify-410-thinking.mjs": _R_UI,
    "verify-425-thinking-live.mjs": _R_UI + "(플레이그라운드 진입 흐름)",
    "verify-427-budget-toast.mjs": _R_UI + "(플레이그라운드 진입 흐름 — 솔로는 통과했었음, 배치 상태 오염 의심)",
    "verify-artifact-188.mjs": _R_UI,
    "verify-assert-ux-194.mjs": _R_UI,
    "verify-case-reg-195.mjs": _R_UI,
    "verify-chunk-immutable-198.mjs": _R_UI,
    "verify-eval-shortcut-197.mjs": _R_UI,
    "verify-grant-ux-200.mjs": _R_UI,
    "verify-nocode-artifact-190.mjs": _R_UI,
    "verify-node-timeline-192.mjs": _R_UI,
    "verify-pipeline-form-ragscore.mjs": _R_UI,
    "verify-plan-demo-wiki.mjs": _R_UI,
    "verify-rag-threshold-191.mjs": _R_UI,
    "verify-webfetch-201.mjs": _R_UI,
}


def collect() -> list[pathlib.Path]:
    return sorted(BROWSER.glob("verify-*.mjs"))


def preflight() -> list[str]:
    """전제 검사 — 없으면 전 스크립트가 같은 이유로 붉어져 triage가 무의미해진다(fail-fast)."""
    problems = []
    if not PLAYWRIGHT_DIR.exists():
        problems.append(f"playwright 없음: {PLAYWRIGHT_DIR}")
    for name, url in (("api(8000)", "http://127.0.0.1:8000/docs"), ("vite(5173)", "http://127.0.0.1:5173/")):
        try:
            with urllib.request.urlopen(url, timeout=5) as r:
                if r.status >= 500:
                    problems.append(f"{name} 비정상 HTTP {r.status}")
        except Exception as exc:
            problems.append(f"{name} 미가동: {type(exc).__name__}")
    return problems


def run_one(f: pathlib.Path) -> tuple[str, str, str, float]:
    """(name, verdict pass|fail|timeout, detail, sec)."""
    t0 = time.perf_counter()
    env = {"PLAYWRIGHT_DIR": str(PLAYWRIGHT_DIR), "PATH": "/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin"}
    import os

    env = {**os.environ, **env}
    try:
        r = subprocess.run(
            ["node", str(f)], capture_output=True, text=True, timeout=TIMEOUT_S, env=env, cwd=ROOT
        )
    except subprocess.TimeoutExpired:
        return f.name, "timeout", f"timeout({TIMEOUT_S}s)", time.perf_counter() - t0
    sec = time.perf_counter() - t0
    if r.returncode == 0:
        return f.name, "pass", "", sec
    out = (r.stdout + r.stderr).strip()
    # 실패 전체 출력 보존(triage 재료 — 스펙 402 계측 결)
    fd = pathlib.Path("/tmp/browser_suite_fails")
    fd.mkdir(exist_ok=True)
    (fd / f"{f.name}.log").write_text(out[-20000:], errors="ignore")
    tail = next((ln for ln in reversed(out.splitlines()) if ln.strip() and "PROVISION" not in ln), "")
    return f.name, "fail", tail[:110], sec


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    only = None
    for a in sys.argv[1:]:
        if a.startswith("--only"):
            only = a.split("=", 1)[1] if "=" in a else None
    if only is None and args:
        only = args[0]
    files = collect()
    if only:
        toks = [t.strip() for t in only.split(",") if t.strip()]
        files = [f for f in files if any(t in f.name for t in toks)]

    if "--list" in flags:
        for f in files:
            mark = "격리" if f.name in KNOWN_DRIFT_BROWSER else " net"
            print(f"  {mark}  {f.name}")
        print(f"총 {len(files)}개 (격리 {sum(1 for f in files if f.name in KNOWN_DRIFT_BROWSER)})")
        return 0

    problems = preflight()
    if problems:
        print("PREFLIGHT FAIL —", " · ".join(problems))
        return 2

    prog = ProgressWriter("browser_suite", len(files))
    totals = {"pass": 0, "fail": 0, "timeout": 0}
    net_broken: list[tuple[str, str]] = []
    drift_passing: list[str] = []
    for i, f in enumerate(files, 1):
        prog.start(f.name)
        name, verdict, detail, sec = run_one(f)
        totals[verdict] += 1
        prog.finish(name, verdict == "pass")
        drift = name in KNOWN_DRIFT_BROWSER
        mark = "ok" if verdict == "pass" else verdict.upper()
        extra = f" — {detail}" if detail else ""
        print(f"  [{i}/{len(files)}] {'격리 ' if drift else ''}{name} {mark} ({sec:.0f}s){extra}", flush=True)
        if verdict == "pass" and drift:
            drift_passing.append(name)
        if verdict != "pass" and not drift:
            net_broken.append((name, detail))

    print("\n" + "=" * 60)
    print(f"통과 {totals['pass']} · 실패 {totals['fail']} · 타임아웃 {totals['timeout']}"
          f" · 격리 {sum(1 for f in files if f.name in KNOWN_DRIFT_BROWSER)}")
    if drift_passing:
        print("✅ 격리인데 통과(해제 후보):", ", ".join(drift_passing))
    if net_broken:
        print(f"🔴 그물 깨짐 {len(net_broken)}개:")
        for n, d in net_broken:
            print(f"   X {n}: {d}")
        return 1
    print("BROWSER_SUITE_OK — 그물(비격리) 전부 통과")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

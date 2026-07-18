"""스펙 373 검증 — 평가 게이트 이음매 e2e(실 파이프라인이 쓴 행 == 게이트가 읽는 행).

스펙 372 게이트의 존재 이유는 "평가한 것 == 배포한 것"이다. 그런데 그 이음매의 양 절반만
따로 초록이었다: verify_372는 EvalRun을 **SQL로 심어** 게이트의 read만 보고, verify_240은
**활성 버전만** 실제 평가한다. 이 파일은 그 사이 —
  **미오픈 스크래치를 body.agent_version으로 실제 지정 평가 → 그 실제 행을 게이트가 읽어 첫 오픈** —
을 실 파이프라인으로 닫는다(SQL 시드 없음). 지정 평가가 active를 태깅하거나 점수 스케일이
어긋나면 사용자는 스크래치를 아무리 평가해도 못 여는데, 240·372는 각자 초록이라 못 잡는다.

  D1  실 지정 평가가 **스크래치 버전으로 태깅**(active 아님)·status=ok·score∈[0,1](스케일 핀).
  D2  게이트 on(runs=1·score=0): 실적 없으면 스크래치 오픈 400 → 실 ok 런 1건 후 같은 요청 200.
  D3  버전별 귀속: 실적 있는 v2는 열렸어도, 실적 0인 다음 스크래치는 여전히 400(any-run 아님).

전제: 서버 8000(스펙 372 게이트 코드). 실행: .venv/bin/python tests/verify_373_eval_gate_e2e.py
"""

import os
import sys
import time
import uuid

import httpx

BASE = os.environ.get("VERIFY_BASE", "http://127.0.0.1:8000")  # 스펙 390: 격리 서버 주입
EMAIL = os.environ.get("ADMIN_EMAIL", "admin@example.com")
PASSWORD = os.environ.get("ADMIN_PASSWORD", "adminpass123")

_fails: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def main() -> None:
    tag = uuid.uuid4().hex[:6]
    cli = httpx.Client(base_url=BASE, timeout=120.0)
    cli.post("/auth/login", data={"username": EMAIL, "password": PASSWORD})

    def set_gate(runs: int, score: float) -> None:
        cli.put("/admin/settings/eval_gate_min_runs", json={"value": runs}).raise_for_status()
        cli.put("/admin/settings/eval_gate_min_score", json={"value": score}).raise_for_status()

    def scratch_ver(aid: str) -> str:
        vers = cli.get(f"/agents/{aid}").json()["versions"]
        return next(v["version"] for v in vers if not v["everOpened"])

    def run_eval(aid: str, ds: str, version: str) -> dict:
        """실 지정 평가 실행 + 완료까지 폴링(백그라운드 순차 실행)."""
        r = cli.post(f"/eval/datasets/{ds}/runs", json={"agent_id": aid, "agent_version": version})
        r.raise_for_status()
        run_id = r.json()["id"]
        for _ in range(120):
            got = cli.get(f"/eval/runs/{run_id}").json()
            if got.get("status") != "running":
                return got
            time.sleep(0.5)
        return got

    # UI 에이전트(source=ui 기본) + 실 평가용 데이터셋(케이스 no_error → 결정적 ok·score=1.0)
    a = cli.post(
        "/agents",
        json={
            "name": f"v373-{tag}",
            "config": {
                "model": "mock-llm",
                "prompt": "",
                "memories": [],
                "vectorTables": [],
                "mcps": [],
                "historyDepth": 10,
            },
        },
    ).json()
    aid = a["id"]
    ds = cli.post("/eval/datasets", json={"name": f"v373-ds-{tag}", "kind": "agent"}).json()
    ds_id = ds["id"]
    cli.post(
        f"/eval/datasets/{ds_id}/cases",
        json={"name": "인사", "input": "안녕", "asserts": [{"type": "no_error"}]},
    ).raise_for_status()

    try:
        # v1 오픈(게이트 끈 채) → 이후 게이트는 스크래치에만 걸린다.
        set_gate(0, 0)
        cli.post(f"/agents/{aid}/activate", json={"version": "v1"}).raise_for_status()

        # 편집 → v2 스크래치. 게이트 on(1회·점수 무관 — 결정적 통과 점수 불필요).
        cfg = a["versions"][0]["config"]
        cli.put(
            f"/agents/{aid}", json={"name": f"v373-{tag}", "config": {**cfg, "historyDepth": 12}}
        ).raise_for_status()
        v2 = scratch_ver(aid)
        set_gate(1, 0)

        # ── D2 전반 — 실적 0인 스크래치는 닫혀 있다(200-후를 유의미하게) ──────────────
        r = cli.post(f"/agents/{aid}/activate", json={"version": v2})
        check(r.status_code == 400, f"D2 실적 0 스크래치 오픈 400 (got {r.status_code})")

        # ── D1 — 미오픈 스크래치 v2를 **실제** 지정 평가 ───────────────────────────────
        got = run_eval(aid, ds_id, v2)
        check(
            got.get("status") == "ok", f"D1 실 지정 평가 완료(status=ok) (got {got.get('status')})"
        )
        check(
            got.get("agent_version") == v2,
            f"D1 실 런이 스크래치({v2})로 태깅 — active(v1) 아님 (got {got.get('agent_version')})",
        )
        sc = got.get("score")
        check(
            isinstance(sc, (int, float)) and 0.0 <= float(sc) <= 1.0,
            f"D1 score∈[0,1](스케일 핀 — 게이트 min_score와 동일 축) (got {sc})",
        )

        # ── D2 후반 — 실 행을 게이트가 읽어 오픈(money shot: SQL 시드 아님) ───────────
        r = cli.post(f"/agents/{aid}/activate", json={"version": v2})
        check(r.status_code == 200, f"D2 실 ok 런 1건 후 스크래치 오픈 200 (got {r.status_code})")

        # ── D3 — 버전별 귀속: 다음 스크래치는 실적 0이라 여전히 400 ──────────────────
        cli.put(
            f"/agents/{aid}", json={"name": f"v373-{tag}", "config": {**cfg, "historyDepth": 14}}
        ).raise_for_status()
        v3 = scratch_ver(aid)
        r = cli.post(f"/agents/{aid}/activate", json={"version": v3})
        check(
            r.status_code == 400,
            f"D3 실적 0인 다음 스크래치({v3})는 400 — 게이트는 버전별 실 행만 셈 (got {r.status_code})",
        )
    finally:
        set_gate(0, 0)  # 전역 설정 원복(다른 테스트 오염 방지)
        cli.delete(f"/eval/datasets/{ds_id}")
        cli.delete(f"/agents/{aid}")
        cli.close()

    print()
    if _fails:
        print(f"FAILED ({len(_fails)}):")
        for f in _fails:
            print("  - " + f)
        sys.exit(1)
    print("ALL PASS (verify_373)")


if __name__ == "__main__":
    main()

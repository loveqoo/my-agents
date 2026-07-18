"""스펙 372 검증 — 평가 게이트 배포(임계 통과해야 오픈) 실서버 통합 rung.

  C1  게이트 on(2회·80%): 미달 스크래치 오픈 → 400(사유에 현재/필요 수치) → 실적 충족 후 → 200.
  C2  기본(0/0) = 무게이트(오픈 자유 — 무회귀).
  C3  롤백 면제: 게이트 on·임계 미달이어도 ever_opened 재오픈 200.
  C4  에러 런 불산입: error 3회·ok 0회 → 400.
  C5  설정 왕복·즉시 발효(재시작 없이).

평가 실적은 EvalRun 행을 직접 적재(dataset 픽스처 포함, 정리 보장) — 평가 파이프라인 자체는
스펙 137/240 검증 소관, 여기선 게이트 판정 입력만 결정적으로 만든다.
전제: 서버 8000. 실행: .venv/bin/python tests/verify_372_eval_gate.py
"""

import os
import sys
import uuid

import httpx
from sqlalchemy import create_engine, text

BASE = os.environ.get("VERIFY_BASE", "http://127.0.0.1:8000")  # 스펙 390: 격리 서버 주입
EMAIL = os.environ.get("ADMIN_EMAIL", "admin@example.com")
PASSWORD = os.environ.get("ADMIN_PASSWORD", "adminpass123")
DB = os.environ.get(
    "DATABASE_URL", "postgresql+asyncpg://agent:agent@localhost:5432/agents"
).replace("+asyncpg", "+psycopg")

_fails: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def main() -> None:  # noqa: PLR0915
    tag = uuid.uuid4().hex[:6]
    cli = httpx.Client(base_url=BASE, timeout=60.0)
    cli.post("/auth/login", data={"username": EMAIL, "password": PASSWORD})
    eng = create_engine(DB)

    def set_gate(runs: int, score: float) -> None:
        cli.put("/admin/settings/eval_gate_min_runs", json={"value": runs}).raise_for_status()
        cli.put("/admin/settings/eval_gate_min_score", json={"value": score}).raise_for_status()

    def seed_runs(
        agent_pk: str, version: str, scores: list[float | None], status: str = "ok"
    ) -> None:
        with eng.begin() as c:
            for sc in scores:
                c.execute(
                    text(
                        "insert into eval_runs (id, dataset_id, agent_pk, agent_version, status, score, "
                        "created_at, updated_at, created_by, updated_by, started_at) "
                        "values (:id, :ds, :ap, :ver, :st, :sc, now(), now(), 'v372', 'v372', now())"
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "ds": ds_id,
                        "ap": agent_pk,
                        "ver": version,
                        "st": status,
                        "sc": sc,
                    },
                )

    # 픽스처: 최소 데이터셋(FK) — 스키마 필수 컬럼은 실측 후 적재.
    with eng.begin() as c:
        cols = {
            r[0]
            for r in c.execute(
                text(
                    "select column_name from information_schema.columns where table_name='eval_datasets'"
                )
            )
        }
    ds_id = str(uuid.uuid4())
    base_cols = {"id": ds_id, "name": f"v372-ds-{tag}"}
    extra = {}
    for col, val in (
        ("kind", "qa"),
        ("status", "ready"),
        ("created_by", "v372"),
        ("updated_by", "v372"),
    ):
        if col in cols:
            extra[col] = val
    with eng.begin() as c:
        names = ", ".join(list(base_cols) + list(extra) + ["created_at", "updated_at"])
        binds = ", ".join([f":{k}" for k in list(base_cols) + list(extra)] + ["now()", "now()"])
        c.execute(
            text(f"insert into eval_datasets ({names}) values ({binds})"), {**base_cols, **extra}
        )

    a = cli.post(
        "/agents",
        json={
            "name": f"v372-{tag}",
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
    aid, apk = a["id"], a["id"]

    try:
        # ── C2 기본(0/0) = 무게이트 ─────────────────────────────────────────────
        set_gate(0, 0)
        r = cli.post(f"/agents/{aid}/activate", json={"version": "v1"})
        check(r.status_code == 200, f"C2 게이트 꺼짐 → v1 오픈 200 (got {r.status_code})")

        # 편집 → v2 스크래치(게이트 대상)
        cfg = a["versions"][0]["config"]
        cli.put(
            f"/agents/{aid}", json={"name": f"v372-{tag}", "config": {**cfg, "historyDepth": 12}}
        ).raise_for_status()

        # ── C1 게이트 on: 미달 400 → 충족 200 ──────────────────────────────────
        set_gate(2, 0.8)
        r = cli.post(f"/agents/{aid}/activate", json={"version": "v2"})
        check(r.status_code == 400, f"C1 실적 0 → v2 오픈 400 (got {r.status_code})")
        detail = r.json().get("detail", "")
        check("2회" in detail and "80%" in detail, f"C1 사유에 필요 수치 명시 (got {detail[:80]})")

        seed_runs(apk, "v2", [0.9])  # 1회·90% — 회수 미달
        r = cli.post(f"/agents/{aid}/activate", json={"version": "v2"})
        check(r.status_code == 400, f"C1 1회(회수 미달) → 400 (got {r.status_code})")

        seed_runs(apk, "v2", [0.5])  # 2회·평균 70% — 점수 미달
        r = cli.post(f"/agents/{aid}/activate", json={"version": "v2"})
        check(r.status_code == 400, f"C1 평균 70%(점수 미달) → 400 (got {r.status_code})")

        seed_runs(apk, "v2", [1.0])  # 3회·평균 80% — 충족
        r = cli.post(f"/agents/{aid}/activate", json={"version": "v2"})
        check(r.status_code == 200, f"C1 3회·평균 80% → 오픈 200 (got {r.status_code})")

        # ── C3 롤백 면제: 임계 미달인 v1(실적 0)이어도 ever_opened → 재오픈 200 ──
        r = cli.post(f"/agents/{aid}/activate", json={"version": "v1"})
        check(r.status_code == 200, f"C3 롤백(v1 재오픈)은 게이트 면제 → 200 (got {r.status_code})")

        # ── C4 에러 런 불산입 ────────────────────────────────────────────────────
        cli.put(
            f"/agents/{aid}", json={"name": f"v372-{tag}", "config": {**cfg, "historyDepth": 14}}
        ).raise_for_status()
        vers = cli.get(f"/agents/{aid}").json()["versions"]
        scratch = next(v["version"] for v in vers if not v["everOpened"])
        seed_runs(apk, scratch, [0.9, 0.9, 0.9], status="error")
        r = cli.post(f"/agents/{aid}/activate", json={"version": scratch})
        check(r.status_code == 400, f"C4 error 3회는 실적 아님 → 400 (got {r.status_code})")

        # ── C5 설정 왕복·즉시 발효 ──────────────────────────────────────────────
        got = cli.get("/admin/settings").json()
        check(
            got.get("eval_gate_min_runs") == 2
            and abs(got.get("eval_gate_min_score", 0) - 0.8) < 1e-9,
            f"C5 설정 왕복 (got runs={got.get('eval_gate_min_runs')} score={got.get('eval_gate_min_score')})",
        )
        set_gate(0, 0)
        r = cli.post(f"/agents/{aid}/activate", json={"version": scratch})
        check(
            r.status_code == 200,
            f"C5 게이트 끄면 즉시 발효(재시작 없이 오픈 200) (got {r.status_code})",
        )
    finally:
        set_gate(0, 0)  # 전역 설정 원복(다른 테스트 오염 방지)
        cli.delete(f"/agents/{aid}")
        with eng.begin() as c:
            c.execute(text("delete from eval_runs where created_by='v372'"))
            c.execute(text("delete from eval_datasets where id=:i"), {"i": ds_id})
        cli.close()

    print()
    if _fails:
        print(f"FAILED ({len(_fails)}):")
        for f in _fails:
            print("  - " + f)
        sys.exit(1)
    print("ALL PASS (verify_372)")


if __name__ == "__main__":
    main()

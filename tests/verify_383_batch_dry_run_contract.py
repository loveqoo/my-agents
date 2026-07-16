"""verify_383 — 배치 트리거 dry_run 계약 경화(스펙 383).

배경: `POST /admin/batch/{job}/run`이 dry_run을 query에서만 읽어, body로 보내면 조용히 무시되고
기본값 false(진짜 실행)로 떨어졌다. 배치 잡은 전부 파괴적 삭제 잡이라 위험한 계약이었다.

경화: dry_run을 body에서도 읽고, 기본값을 안전쪽(dry-run)으로. 정밀도 body > query > true.

신호: 실제 삭제를 유발하지 않고 **계약 해석**만 단언한다 — run_job이 BatchRun(dry_run=resolved)로
박제하므로, POST 직후 GET /admin/batch/runs[0].dry_run이 해석된 값이다. 실행 경로가 필요한 칸
(dry_run=false 해석)은 NULL-config에서 no-op인 checkpoint-cleanup을 써 도그푸딩 데이터를 안 건드린다.

실행: cd packages/api && uv run python ../../tests/verify_383_batch_dry_run_contract.py
"""

from __future__ import annotations

import asyncio
import uuid

import httpx

from api.main import app
from api.users import current_active_user


class _SuperUser:
    # 배치 라우트는 authz.require → current_active_user(세션 유저) 전용(머신 토큰 401, verify_rbac_audit).
    # is_superuser 우회로 (batch,run) 통과. audit.actor_of가 읽는 필드까지 채운다.
    id = uuid.UUID("000000dd-0000-0000-0000-00000000038d")
    is_superuser = True
    is_active = True
    is_verified = True
    email = "verify-383-super@local"


app.dependency_overrides[current_active_user] = lambda: _SuperUser()

# NULL-config에서 실 삭제가 no-op인 잡(실행 경로 검증 칸에서 도그푸딩 데이터 보호).
SAFE_JOB = "checkpoint-cleanup"

PASS, FAIL = "PASS", "FAIL"
results: list[tuple[str, str, str]] = []


def check(name: str, ok: bool, detail: str) -> None:
    results.append((name, PASS if ok else FAIL, detail))


async def _trigger_and_read(
    c: httpx.AsyncClient, *, query: bool | None, body: bool | None
) -> bool:
    """POST 후 방금 만든 BatchRun의 dry_run 영속값을 돌려준다(해석 결과)."""
    url = f"/admin/batch/{SAFE_JOB}/run"
    if query is not None:
        url += f"?dry_run={str(query).lower()}"
    kwargs = {"json": {"dry_run": body}} if body is not None else {}
    r = await c.post(url, **kwargs)
    assert r.status_code == 200, f"POST {url} → {r.status_code} {r.text[:200]}"
    run_id = r.json()["run_id"]
    runs = (await c.get("/admin/batch/runs?limit=20")).json()
    row = next((x for x in runs if x["id"] == run_id), None)
    assert row is not None, f"run_id {run_id} 미발견"
    return bool(row["dry_run"])


async def main() -> int:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t", timeout=60) as c:
        # C1 기본값 안전: 어느 소스도 없음 → dry-run(True).
        c1 = await _trigger_and_read(c, query=None, body=None)
        check("C1 기본값 안전(무플래그→dry-run)", c1 is True, f"resolved dry_run={c1} (기대 True)")

        # C2 body 존중: body만 dry_run=true → dry-run(구 계약은 조용히 무시→진짜 실행이었다).
        c2 = await _trigger_and_read(c, query=None, body=True)
        check("C2 body 존중(body dry_run=true)", c2 is True, f"resolved dry_run={c2} (기대 True)")

        # C3 명시 실행: query dry_run=false → 진짜 실행(False). UI 실행 버튼 보존.
        c3 = await _trigger_and_read(c, query=False, body=None)
        check(
            "C3 명시 실행(query dry_run=false)", c3 is False, f"resolved dry_run={c3} (기대 False)"
        )

        # C4 정밀도: body=true + query=false → body 우선(dry-run True).
        c4 = await _trigger_and_read(c, query=False, body=True)
        check("C4 정밀도(body>query)", c4 is True, f"resolved dry_run={c4} (기대 True, body 우선)")

        # C5 UI dry-run 경로 보존: query dry_run=true → dry-run(True).
        c5 = await _trigger_and_read(c, query=True, body=None)
        check(
            "C5 UI dry-run 경로(query dry_run=true)",
            c5 is True,
            f"resolved dry_run={c5} (기대 True)",
        )

        # C6 StrictBool 거부(codex P1): body의 모호한 falsy 값은 조용히 False(진짜 실행)로 강제변환하지
        # 않고 422로 거부. {"dry_run":"off"}가 예전엔 False로 coerce돼 파괴적 실행으로 떨어졌다.
        for bad in ("off", 0, "no", "false"):
            r = await c.post(f"/admin/batch/{SAFE_JOB}/run", json={"dry_run": bad})
            check(
                f"C6 StrictBool 거부(body dry_run={bad!r}→422)",
                r.status_code == 422,
                f"status={r.status_code} (기대 422, 강제변환 금지)",
            )

        # C7 역 정밀도(의도된 위험 박기): body dry_run=false + query dry_run=true → body 우선 → 진짜 실행.
        # body>query 규칙의 위험쪽 방향을 회귀로 고정(스펙대로 body가 이긴다).
        c7 = await _trigger_and_read(c, query=True, body=False)
        check(
            "C7 역 정밀도(body false > query true → 실행)",
            c7 is False,
            f"resolved dry_run={c7} (기대 False, body 우선)",
        )

    npass = sum(1 for _, s, _ in results if s == PASS)
    for name, status, detail in results:
        print(f"  [{status:4}] {name} — {detail}")
    print(f"\n요약: {npass}/{len(results)} PASS")
    if npass == len(results):
        print("VERIFY383_OK")
        return 0
    print("VERIFY383_FAIL")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

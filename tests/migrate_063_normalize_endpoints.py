"""스펙 063 D3 — stale endpoint 일괄 정규화 마이그레이션 (비가역 — 기본 dry-run).

스펙 060(등록 시점 정규화) 이전에 만들어졌거나 정규화를 건너뛴 경로의 에이전트는 `endpoint`에
`http(s)://` 스킴이 없을 수 있다(스샷 버그: 채팅 시 "URL은 http(s) 절대 URL이어야 합니다").
호출 경계(D1)·빌더(D2)가 런타임을 자가치유하지만, 저장 데이터 자체를 청결히 해 표시·probe·
재조회까지 정합시키는 게 이 스크립트다.

선별 규칙(보수적 — 안전 행만):
  - source ∈ (code, external)  (ui=로컬 LangGraph는 endpoint 호출 안 함 → 제외)
  - endpoint NOT NULL/빈값 아님
  - endpoint가 `http://`·`https://`로 시작하지 **않음**(이미 절대면 건드리지 않음 — 멱등)
각 후보를 `normalize_http_url`로 절대화. 정규화 불가(비-http 스킴·base 필요 상대경로)는 **건드리지
않고 보고만** 한다(호출 경계 D1이 런타임에서 처리, 데이터는 그대로 둠 — 손실/추측 금지).

기본 **dry-run**(바뀔 행만 출력, 쓰기 없음). `--apply`로만 실제 UPDATE. 멱등: --apply 후 재실행하면
모든 후보가 이미 절대 → 선별 0건.

실행:
  uv run --project packages/api python tests/migrate_063_normalize_endpoints.py          # dry-run
  uv run --project packages/api python tests/migrate_063_normalize_endpoints.py --apply   # 실제 쓰기
"""

import asyncio
import os
import sys

import asyncpg

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "packages", "api", "src"))
from api.net_guard import normalize_http_url  # noqa: E402

DSN = os.environ.get("MIGRATE_DSN", "postgresql://agent:agent@localhost:5432/agents")


def _needs_norm(endpoint: str | None) -> bool:
    """절대 http(s)가 아니면 정규화 후보(빈값·NULL은 호출 경계 처리이라 후보 제외)."""
    if not endpoint or not endpoint.strip():
        return False
    return not endpoint.strip().lower().startswith(("http://", "https://"))


async def main(apply: bool) -> int:
    conn = await asyncpg.connect(DSN)
    rows = await conn.fetch(
        "SELECT agent_id, name, source, endpoint FROM agents "
        "WHERE source IN ('code', 'external') AND endpoint IS NOT NULL"
    )
    # 순수 선별/정규화(부수효과 없음) — 적대 검증이 이 로직만 떼어 본다.
    to_update: list[tuple[str, str, str, str]] = []  # (id, name, old, new)
    skipped: list[tuple[str, str, str]] = []  # (id, old, reason)
    for r in rows:
        ep = r["endpoint"]
        if not _needs_norm(ep):
            continue
        try:
            new = normalize_http_url(ep)
        except ValueError as exc:
            skipped.append((r["agent_id"], ep, str(exc)))
            continue
        if new != ep:  # 절대화로 실제 값이 바뀌는 경우만
            to_update.append((r["agent_id"], r["name"], ep, new))

    print(f"후보(스킴 누락 code/external): {len(to_update)}건, 정규화 불가(보고만): {len(skipped)}건\n")
    for aid, name, old, new in to_update:
        print(f"  [{aid}] {name!r}\n      {old!r}\n   -> {new!r}")
    if skipped:
        print("\n정규화 불가(데이터 보존, 호출 경계가 런타임 처리):")
        for aid, old, reason in skipped:
            print(f"  [{aid}] {old!r}  — {reason}")

    if not apply:
        print(f"\n[dry-run] 쓰기 없음. --apply 로 위 {len(to_update)}건 UPDATE.")
        await conn.close()
        return 0

    written = 0
    skipped_cas = 0
    try:
        async with conn.transaction():
            for aid, _name, old, new in to_update:
                # compare-and-set(적대 [P2]): WHERE에 읽은 시점 endpoint를 함께 건다. 조회~갱신
                # 사이 다른 경로가 endpoint를 바꿨다면(동시성) 이 행은 건드리지 않는다 — 오래된
                # old→new 계산값으로 최신 값을 되돌리는 lost-update를 막는다.
                res = await conn.execute(
                    "UPDATE agents SET endpoint = $1 WHERE agent_id = $2 AND endpoint = $3",
                    new, aid, old,
                )
                # asyncpg execute는 "UPDATE <n>" 태그 반환 — 0이면 그 사이 값이 바뀐 것.
                if res.endswith(" 0"):
                    skipped_cas += 1
                else:
                    written += 1
    finally:
        await conn.close()
    msg = f"\n[apply] {written}건 UPDATE 완료. 재실행 시 멱등(모두 절대 → 0건)."
    if skipped_cas:
        msg += f" (동시 변경 감지로 {skipped_cas}건 건너뜀 — 재실행 권장)"
    print(msg)
    return 0


if __name__ == "__main__":
    apply = "--apply" in sys.argv[1:]
    raise SystemExit(asyncio.run(main(apply)))

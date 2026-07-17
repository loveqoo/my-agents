"""도그푸딩 DB의 테스트-누수 에이전트 정리 — 반복 가능한 dev 유틸.

**왜**: e2e/verify 테스트가 공유 라이브 DB에 에이전트를 만들고(크래시·불완전 cleanup으로) 다 안
지운다. agents 테이블은 resource_policy상 "bounded(관리자 페이스)"인데 테스트가 그 전제를 깬다 —
prod에는 없는 문제라 앱 배치 스윕이 아니라 **dev 도구**로 봉합한다(이름 패턴 스윕은 prod엔 위험).

**안전**: 시드 데모(KEEP)는 절대 안 지운다. 삭제는 정식 API 관문(DELETE /agents/{id})으로 —
agent_versions cascade·블록 이력(delete_block_history)·세션 정합을 라우트가 처리(직접 DB 삭제 금지).

사용:
  uv run --package api python tests/clean_test_agents.py            # dry-run(기본, 안 지움)
  uv run --package api python tests/clean_test_agents.py --apply    # 실제 삭제
"""

import asyncio
import re
import sys
import uuid

import httpx
from sqlalchemy import select

from api.auth import _token, current_principal
from api.db import SessionLocal
from api.main import app
from api.models import Agent

# 시드 데모 — 절대 삭제 금지(seed.py가 만드는 고정 데모). 이름으로 고정.
KEEP = {
    "research-pipeline-demo",
    "acme-translate-a2a",
    "doc-translator",
    "personal-secretary",
    "research-assistant",
}

# 테스트-누수 이름 패턴(접두 매칭). 새 누수 패턴이 생기면 여기 추가.
LEAK_PATTERNS = [
    r"^e2e-agent-",  # e2e 스위트(admin/api spec)
    r"^_verify",  # verify_* 인프로세스 픽스처
    r"^v\d{3}-",  # 버전 테스트(v364-·v372- 등)
    r"^ui\d{3}-",  # UI 버전 테스트(ui370- 등)
    r"^mock-a2a-",  # A2A 협업 테스트 mock
    r"^mock-sdk-",  # SDK code 에이전트 테스트 mock
    r"^clone-src-",  # verify_120 클론 테스트
]


def is_leak(name: str | None) -> bool:
    n = name or ""
    if n in KEEP:
        return False
    return any(re.match(p, n) for p in LEAK_PATTERNS)


class _Super:
    id = uuid.UUID("000000dd-0000-0000-0000-0000000000dd")
    is_superuser = True
    is_active = True
    is_verified = True
    email = "clean-test-agents@local"


# 블록 누수 패턴(스펙 389 위생) — verify가 만드는 모델/프로바이더/컬렉션 잔재(크래시 시 잔존).
# agents와 동일 규율: KEEP은 실자산(시드+실모델), 패턴은 테스트 접두만.
BLOCK_LEAK_PATTERNS = [r"^_verify", r"^v\d{3}[-_]", r"^ui\d{3}-"]  # suite-kb는 상주 픽스처(KEEP)
BLOCK_KEEP = {
    "mock-llm",
    "mock-embed",
    "qwen3.6-35b",
    "e5-large-mlx",
    "Mock LLM",
    "MLX",
    "docs-kb",
    "product-titles",
    "team-notes",
}


def is_block_leak(name: str | None) -> bool:
    n = name or ""
    if n in BLOCK_KEEP:
        return False
    return any(re.match(p, n) for p in BLOCK_LEAK_PATTERNS)


async def sweep_blocks(c: "httpx.AsyncClient", apply: bool) -> None:
    """모델→프로바이더→컬렉션 순 스윕(모델이 provider를 참조하므로 순서 중요). 정식 라우트 경유
    (참조 가드가 있는 자원은 409로 스스로 보호 — 라우트가 안전핀)."""
    for path, label in (
        ("/models", "model"),
        ("/providers", "provider"),
        ("/collections", "collection"),
    ):
        rows = (await c.get(path)).json()
        rows = rows if isinstance(rows, list) else rows.get("items", [])
        for row in rows:
            if not is_block_leak(row.get("name")):
                continue
            if not apply:
                print(f"  would-DEL {label}  {row['name']}")
                continue
            r = await c.delete(f"{path}/{row['id']}")
            print(
                f"  {'DEL ' if r.status_code in (200, 204) else f'FAIL({r.status_code})'} {label}  {row['name']}"
            )


async def main(apply: bool) -> int:
    app.dependency_overrides[current_principal] = lambda: _Super()
    async with SessionLocal() as s:
        rows = (await s.execute(select(Agent.id, Agent.name))).all()
    targets = [(str(i), n) for i, n in rows if is_leak(n)]
    keep = [n for _, n in rows if not is_leak(n)]
    print(f"전체 {len(rows)}개 · 누수 {len(targets)}개 · 보존 {len(keep)}개")
    for n in sorted(keep):
        print(f"  KEEP  {n}")
    for _, n in sorted(targets, key=lambda t: t[1]):
        print(f"  {'DEL ' if apply else 'would-DEL'}  {n}")
    if not apply:
        auth = {"Authorization": f"Bearer {_token()}"}
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://t", headers=auth, timeout=60
        ) as c2:
            print("블록(모델/프로바이더/컬렉션) 누수 스윕(dry):")
            await sweep_blocks(c2, apply)
        print("\n(dry-run — 지우지 않음. 실제 삭제는 --apply)")
        return 0
    if not targets:
        print("\n정리할 누수 없음.")
        return 0
    auth = {"Authorization": f"Bearer {_token()}"}
    ok, fail = 0, []
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://t", headers=auth, timeout=60
    ) as c:
        for aid, name in targets:
            r = await c.delete(f"/agents/{aid}")
            if r.status_code in (200, 204):
                ok += 1
            else:
                fail.append((name, r.status_code))
    print(f"\n삭제 성공 {ok} · 실패 {len(fail)}")
    if fail:
        print("실패:", fail[:10])
        return 1
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t", headers=auth, timeout=60
    ) as c2:
        print("블록(모델/프로바이더/컬렉션) 누수 스윕:")
        await sweep_blocks(c2, apply)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main("--apply" in sys.argv)))

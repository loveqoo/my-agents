"""스펙 369 검증 — 블록 append-only 단조 불변 버전 (실서버 8000 HTTP+DB 통합 rung).

  C1  5종 각각 편집 → head.version 증가 + 이력 append + **이전 버전 payload 불변**.
  C2  이관 불변식: 이력 없는 블록 0 (블록 행 수 == 이력 보유 블록 수).
  C3  동시 PUT 8발 레이스 → 성공분 버전 연속·중복 0, 실패는 409.
  C4  운영 상태 변경(mcp publish 400 경로 대신 provider api_key 로테이션·model is_default)은 버전 무증가.

전제: 서버 8000(스펙 369 코드). 실행: .venv/bin/python tests/verify_369_block_versioning.py
"""

import asyncio
import json
import os
import sys
import uuid

import httpx
from sqlalchemy import create_engine, text

BASE = os.environ.get("API_BASE", "http://127.0.0.1:8000")
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


def hist(cli: httpx.Client, kind: str, pk: str) -> list[dict]:
    r = cli.get(f"/block-versions/{kind}/{pk}")
    r.raise_for_status()
    return r.json()


def main() -> None:
    tag = uuid.uuid4().hex[:6]
    cli = httpx.Client(base_url=BASE, timeout=60.0)
    r = cli.post("/auth/login", data={"username": EMAIL, "password": PASSWORD})
    check(r.status_code < 400 and "agentauth" in cli.cookies, f"로그인 ({r.status_code})")

    created: list[tuple[str, str]] = []  # (경로, id) 정리용

    try:
        # ── C1: prompt — 생성 v1 → 편집 v2 → 재편집 v3, v1/v2 payload 불변 ──────────
        p = cli.post("/prompts", json={"name": f"v369-p-{tag}", "tone": "t1", "body": "b1"}).json()
        created.append(("/prompts", p["id"]))
        check(p.get("version") == 1, f"C1 prompt 생성 = v1 (got {p.get('version')})")
        h1 = hist(cli, "prompt", p["id"])
        check(len(h1) == 1 and h1[0]["version"] == 1, "C1 prompt 이력 v1 존재")
        v1_payload_before = json.dumps(h1[0]["payload"], sort_keys=True)

        p2 = cli.put(
            f"/prompts/{p['id']}", json={"name": f"v369-p-{tag}", "tone": "t1", "body": "b2"}
        ).json()
        check(p2.get("version") == 2, f"C1 prompt 편집 → v2 (got {p2.get('version')})")
        p3 = cli.put(
            f"/prompts/{p['id']}", json={"name": f"v369-p-{tag}", "tone": "t2", "body": "b2"}
        ).json()
        check(p3.get("version") == 3, f"C1 prompt 재편집 → v3 (got {p3.get('version')})")
        h3 = hist(cli, "prompt", p["id"])
        check(
            [h["version"] for h in h3] == [3, 2, 1],
            f"C1 이력 3행 최신순 (got {[h['version'] for h in h3]})",
        )
        v1_payload_after = json.dumps(
            cli.get(f"/block-versions/prompt/{p['id']}/1").json()["payload"], sort_keys=True
        )
        check(
            v1_payload_before == v1_payload_after, "C1 v1 payload 불변(편집 2회 후에도 바이트 동일)"
        )
        check(
            h3[0]["payload"]["body"] == "b2" and h3[0]["payload"]["tone"] == "t2",
            "C1 v3 payload=최신 내용",
        )

        # 무변경 저장 = 버전 무증가
        p_same = cli.put(
            f"/prompts/{p['id']}", json={"name": f"v369-p-{tag}", "tone": "t2", "body": "b2"}
        ).json()
        check(
            p_same.get("version") == 3,
            f"C1 무변경 저장 → 버전 무증가 (got {p_same.get('version')})",
        )

        # ── C1 나머지 4종: 편집 1회 → v2 ─────────────────────────────────────────
        # memory-type은 스펙 387 후속으로 시스템 정의 봉인(생성 403) — 버전 관문 자체는 설명(body)
        # 수정 경로에 여전히 걸린다(record_block_version 유지). 여기선 봉인 계약만 확인.
        r_mt = cli.post(
            "/memory-types",
            json={"key": f"v369_mt_{tag}", "name": "타입", "scope": "agent", "body": "m1"},
        )
        check(r_mt.status_code == 403, f"C1 memory-type 생성 → 403 봉인 (got {r_mt.status_code})")

        mc = cli.post(
            "/mcp-servers",
            json={
                "name": f"v369-mcp-{tag}",
                "source": "local",
                "transport": "stdio",
                "tools": ["a"],
                "enabled_tools": ["a"],
            },
        ).json()
        created.append(("/mcp-servers", mc["id"]))
        mc_body = {k: mc[k] for k in ("name", "source", "transport", "tools")}
        mc2 = cli.put(
            f"/mcp-servers/{mc['id']}",
            json={**mc_body, "tools": ["a", "b"], "enabled_tools": ["a", "b"]},
        ).json()
        check(mc2.get("version") == 2, f"C1 mcp-server 편집 → v2 (got {mc2.get('version')})")

        prov = cli.post(
            "/providers",
            json={
                "name": f"v369-prov-{tag}",
                "protocol": "openai-compatible",
                "base_url": "http://x/v1",
                "api_key": "k1",
            },
        ).json()
        created.append(("/providers", prov["id"]))
        pv2 = cli.put(
            f"/providers/{prov['id']}",
            json={
                "name": f"v369-prov-{tag}",
                "protocol": "openai-compatible",
                "base_url": "http://y/v1",
                "api_key": None,
            },
        ).json()
        check(
            pv2.get("version") == 2, f"C1 provider 편집(base_url) → v2 (got {pv2.get('version')})"
        )

        mo = cli.post(
            "/models",
            json={
                "name": f"v369-m-{tag}",
                "provider_id": prov["id"],
                "model_id": "m1",
                "kind": "chat",
                "is_default": False,
                "params": {},
            },
        ).json()
        created.append(("/models", mo["id"]))
        mo2 = cli.put(
            f"/models/{mo['id']}",
            json={
                "name": f"v369-m-{tag}",
                "provider_id": prov["id"],
                "model_id": "m2",
                "kind": "chat",
                "is_default": False,
                "params": {},
            },
        ).json()
        check(mo2.get("version") == 2, f"C1 model 편집(model_id) → v2 (got {mo2.get('version')})")

        # ── C4: 운영-only 변경 = 버전 무증가 ─────────────────────────────────────
        pv3 = cli.put(
            f"/providers/{prov['id']}",
            json={
                "name": f"v369-prov-{tag}",
                "protocol": "openai-compatible",
                "base_url": "http://y/v1",
                "api_key": "rotated-key",
            },
        ).json()
        check(
            pv3.get("version") == 2,
            f"C4 provider 키 로테이션만 → 버전 무증가 (got {pv3.get('version')})",
        )
        mo3 = cli.put(
            f"/models/{mo['id']}",
            json={
                "name": f"v369-m-{tag}",
                "provider_id": prov["id"],
                "model_id": "m2",
                "kind": "chat",
                "is_default": True,
                "params": {},
            },
        ).json()
        check(
            mo3.get("version") == 2,
            f"C4 model is_default만 → 버전 무증가 (got {mo3.get('version')})",
        )
        # is_default 원복(시드 기본 모델 보존)
        cli.put(
            f"/models/{mo['id']}",
            json={
                "name": f"v369-m-{tag}",
                "provider_id": prov["id"],
                "model_id": "m2",
                "kind": "chat",
                "is_default": False,
                "params": {},
            },
        )
        seed_default = cli.get("/models").json()
        mock = next((m for m in seed_default if m["name"] == "mock-llm"), None)
        if mock and not mock["is_default"]:
            cli.put(f"/models/{mock['id']}/default", json={})

        # ── C3: 동시 PUT 8발 레이스 ─────────────────────────────────────────────
        async def race() -> list[int]:
            async with httpx.AsyncClient(base_url=BASE, timeout=60.0, cookies=cli.cookies) as ac:

                async def one(i: int) -> int:
                    r = await ac.put(
                        f"/prompts/{p['id']}",
                        json={"name": f"v369-p-{tag}", "tone": "t2", "body": f"race-{i}"},
                    )
                    return r.status_code

                return list(await asyncio.gather(*[one(i) for i in range(8)]))

        codes = asyncio.run(race())
        n409 = sum(1 for c in codes if c == 409)
        n200 = sum(1 for c in codes if c == 200)
        check(n200 + n409 == 8 and n200 >= 1, f"C3 레이스 결과 200={n200}·409={n409} (합 8)")
        hr = hist(cli, "prompt", p["id"])
        vers = sorted(h["version"] for h in hr)
        check(len(vers) == len(set(vers)), f"C3 버전 중복 0 (got {vers})")
        check(vers == list(range(1, len(vers) + 1)), f"C3 버전 연속(구멍 없음) (got {vers})")

        # ── C2: 이관 불변식(이력 없는 블록 0) — DB 실측 ──────────────────────────
        eng = create_engine(DB)
        kinds = {
            "prompt": "prompts",
            "memory-type": "memory_types",
            "mcp-server": "mcp_servers",
            "model": "models",
            "provider": "providers",
        }
        with eng.connect() as c:
            missing_total = 0
            orphans_total = 0
            for kind, table in kinds.items():
                # 양방향(스펙 371 교정): 이력 없는 블록 0 **그리고** head 없는 고아 이력 0.
                missing_total += (
                    c.execute(
                        text(
                            f"select count(*) from {table} h where not exists "
                            "(select 1 from block_versions bv where bv.kind=:k and bv.block_pk=h.id)"
                        ),
                        {"k": kind},
                    ).scalar()
                    or 0
                )
                orphans_total += (
                    c.execute(
                        text(
                            "select count(distinct bv.block_pk) from block_versions bv "
                            f"where bv.kind=:k and not exists (select 1 from {table} h where h.id=bv.block_pk)"
                        ),
                        {"k": kind},
                    ).scalar()
                    or 0
                )
            check(missing_total == 0, f"C2 이력 없는 블록 0 (missing={missing_total})")
            check(
                orphans_total == 0, f"C2b 고아 이력 0 (orphans={orphans_total}) — 부트 청소 후 기준"
            )
    finally:
        # 정리 — 생성 역순(모델→프로바이더 FK)
        for path, oid in reversed(created):
            cli.delete(f"{path}/{oid}")
        cli.close()

    print()
    if _fails:
        print(f"FAILED ({len(_fails)}):")
        for f in _fails:
            print("  - " + f)
        sys.exit(1)
    print("ALL PASS (verify_369)")


if __name__ == "__main__":
    main()

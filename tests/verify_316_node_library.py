"""스펙 316 검증 — 노드 라이브러리(등록 노드 + 버전 고정 참조).

검증 사다리(비겹침):
  [U] 단위 — 저장 스키마 ref 변형(수용·혼합 거부·버전 형식), 오버라이드 화이트리스트에 ref 없음.
  [H] 통합(in-process ASGI + 실 DB + mock-llm) —
      H1 발행: 새 노드 v1 → 같은 이름 v2(자동 증가)·목록 그룹·상세 최신 먼저.
      H2 참조 에이전트: ref 핀(v1) 해석 → resolvedNodes가 v1 config(뒤 버전 발행과 무관).
      H3 실행 왕복: 채팅 200 + 템플릿 노드 이름이 trace.graph에 + 템플릿 도구 호출 실측 + usedBy.
      H4 삭제 가드: 참조 버전 409(에이전트 이름 표면화)·미참조 버전 204.
      H5 미해결 참조: 저장 시 422(이른 실패)·직접 DB 삭제(가드 우회 시뮬) 후 채팅 422·
         GET resolvedNodes=None(조회 비잠금).
      H6 오버라이드: 해석→병합(ref 노드 위 세션 패치 applied — 인덱스 정렬 일치).
      H7 사본 격리: 해석 결과 변형이 등록 원본 비오염(재해석 불변).

실행: uv run --project packages/api python tests/verify_316_node_library.py
(사전: packages/api에서 alembic upgrade head — node_templates 테이블)
"""

import asyncio
import json
import os
import sys
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))
sys.path.insert(0, os.path.join(ROOT, "packages", "agent", "src"))

_fails: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


TPL = f"v316-node-{uuid.uuid4().hex[:6]}"
V1_PROMPT = "v1: 들어온 요청을 한 줄로 요약해라"
V2_PROMPT = "v2: 들어온 요청을 세 줄로 요약해라"


# ================================================================ [U] 단위
def unit_checks() -> None:
    print("[U] 단위 — 저장 스키마 ref 변형")
    from api.chat import _NODE_OVERRIDE_FIELDS
    from api.schemas import AgentConfig

    # U1 ref 변형 수용 — 정규화 결과는 ref만 남는다.
    out = AgentConfig._normalize_node({"ref": {"name": "a-node", "version": 3}})
    check(out == {"ref": {"name": "a-node", "version": 3}}, f"U1 ref 변형 수용·정규화 (got {out})")
    # U2 혼합 거부 — ref와 인라인 키 동시 금지(어느 쪽이 진실인지 모호한 반쪽 저장 차단).
    for bad, why in [
        ({"ref": {"name": "a", "version": 1}, "prompt": "p"}, "ref+인라인 혼합"),
        ({"ref": {"name": "a"}}, "version 누락"),
        ({"ref": {"name": "a", "version": 0}}, "version 0"),
        ({"ref": {"name": "a", "version": True}}, "version bool"),
        ({"ref": {"name": "", "version": 1}}, "빈 name"),
        ({"ref": "a@1"}, "ref 비객체"),
    ]:
        try:
            AgentConfig._normalize_node(bad)
            check(False, f"U2 거부돼야 함: {why}")
        except ValueError:
            check(True, f"U2 거부: {why}")
    # U3 인라인 노드는 기존 그대로(무회귀).
    out3 = AgentConfig._normalize_node({"prompt": "p", "model": "m", "tools": ["t"]})
    check(out3.get("prompt") == "p" and out3.get("tools") == ["t"], "U3 인라인 노드 무회귀")
    # U4 세션 오버라이드로 참조 교체 불가 — ref는 화이트리스트 밖(구조 변경 금지, 스펙 287 일관).
    check("ref" not in _NODE_OVERRIDE_FIELDS, "U4 _NODE_OVERRIDE_FIELDS에 ref 없음")

    # U5 변이 게이트(codex 316 P1) — member(비특권)는 403, 머신 토큰(특권)은 통과.
    import uuid as _uuid
    from types import SimpleNamespace

    from api.node_templates import require_node_manage, visible_used_by

    member = SimpleNamespace(is_superuser=False, id=_uuid.uuid4())
    try:
        asyncio.run(require_node_manage(member))  # type: ignore[arg-type]
        check(False, "U5 member 발행/삭제 403이어야 함")
    except Exception as e:
        check(getattr(e, "status_code", None) == 403, f"U5 member → 403 (got {e!r})")
    check(
        asyncio.run(require_node_manage("machine-token")) == "machine-token",  # type: ignore[arg-type]
        "U5 머신 토큰(특권) 통과",
    )

    # U6 usedBy 가시성 필터(codex 316 P1) — private(타인 소유) 이름은 숨기고 개수만.
    pub = SimpleNamespace(id=1, name="pub-agent", source="ui", owner_id=None)
    priv = SimpleNamespace(id=2, name="secret-agent", source="ui", owner_id="owner-x")
    names, hidden = visible_used_by([pub, priv], member)  # type: ignore[arg-type]
    check(
        names == ["pub-agent"] and hidden == 1,
        f"U6 member: private 이름 숨김+개수 (got {names}, {hidden})",
    )
    names2, hidden2 = visible_used_by([pub, priv], "machine")  # type: ignore[arg-type]
    check("secret-agent" in names2 and hidden2 == 0, "U6 특권: 전체 이름")


# ================================================================ [H] 통합
async def http_checks() -> None:
    print("[H] 통합 — 발행·핀 참조·실행·삭제 가드·미해결·오버라이드·사본 격리")
    import httpx
    from sqlalchemy import delete as sa_delete
    from sqlalchemy import select

    from api.auth import _token
    from api.db import SessionLocal
    from api.main import app
    from api.models import NodeTemplate
    from api.node_templates import resolve_node_refs

    auth = {"Authorization": f"Bearer {_token()}"}
    transport = httpx.ASGITransport(app=app)
    created_agents: list[str] = []

    async def _chat(client, aid: str, text: str, overrides: dict | None = None):
        acc: list[str] = []
        trace = None
        body: dict = {"messages": [{"role": "user", "content": text}]}
        if overrides is not None:
            body["overrides"] = overrides
        async with client.stream("POST", f"/agents/{aid}/chat", json=body) as resp:
            if resp.status_code != 200:
                return resp.status_code, "", None
            event = None
            async for line in resp.aiter_lines():
                if line.startswith("event:"):
                    event = line.split(":", 1)[1].strip()
                elif line.startswith("data:"):
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        continue
                    try:
                        obj = json.loads(payload)
                    except Exception:
                        continue
                    if event == "trace":
                        trace = obj
                    elif isinstance(obj, dict) and obj.get("text"):
                        acc.append(obj["text"])
        return 200, "".join(acc), trace

    async with httpx.AsyncClient(
        transport=transport, base_url="http://t", headers=auth, timeout=120
    ) as c:
        # ── H1 발행: v1 → 같은 이름 v2(자동 증가) ──
        r = await c.post(
            "/node-templates",
            json={
                "name": TPL,
                "description": "요약 노드",
                "config": {
                    "name": "요약",
                    "prompt": V1_PROMPT,
                    "model": "mock-llm",
                    "tools": ["local-tools__echo"],
                },
            },
        )
        check(
            r.status_code == 201 and r.json()["version"] == 1,
            f"H1 v1 발행 201 (got {r.status_code})",
        )
        r = await c.post(
            "/node-templates",
            json={
                "name": TPL,
                "config": {"name": "요약", "prompt": V2_PROMPT, "model": "mock-llm"},
            },
        )
        check(r.status_code == 201 and r.json()["version"] == 2, "H1 같은 이름 재발행 → v2 자동")
        groups = (await c.get("/node-templates")).json()
        g = next((x for x in groups if x["name"] == TPL), None)
        check(
            g is not None and g["latestVersion"] == 2 and g["versionCount"] == 2,
            f"H1 목록 그룹(latest=2, count=2) (got {g})",
        )
        detail = (await c.get(f"/node-templates/{TPL}")).json()
        check(
            [v["version"] for v in detail["versions"]] == [2, 1],
            "H1 상세 버전 히스토리 최신 먼저",
        )
        # 등록 config가 참조(ref)일 수는 없다(중첩 참조 금지).
        r = await c.post(
            "/node-templates",
            json={"name": f"{TPL}-x", "config": {"ref": {"name": TPL, "version": 1}}},
        )
        check(r.status_code == 422, f"H1 중첩 참조 등록 거부 422 (got {r.status_code})")

        # ── H2 참조 에이전트: v1 핀 — v2가 이미 있어도 v1 config로 해석 ──
        agent_name = f"v316-pipe-{uuid.uuid4().hex[:6]}"
        r = await c.post(
            "/agents",
            json={
                "name": agent_name,
                "config": {
                    "model": "mock-llm",
                    "prompt": "",
                    "impl": "pipeline",
                    "mcps": [],
                    "tools": [],
                    "nodes": [{"ref": {"name": TPL, "version": 1}}],
                },
            },
        )
        check(
            r.status_code == 201, f"H2 참조 에이전트 생성 201 (got {r.status_code}: {r.text[:200]})"
        )
        aid = r.json()["id"]
        created_agents.append(aid)
        out = (await c.get(f"/agents/{aid}")).json()
        rn = out.get("resolvedNodes")
        check(
            isinstance(rn, list) and rn and rn[0].get("prompt") == V1_PROMPT,
            f"H2 resolvedNodes=v1 config(핀 — v2 존재해도 v1) (got {rn and rn[0].get('prompt')})",
        )
        check(
            out.get("nodes") == [{"ref": {"name": TPL, "version": 1}}],
            "H2 저장본 nodes는 ref 유지(해석은 파생 필드만)",
        )
        # 풀 서버 파생(스펙 289)이 참조 노드의 도구를 봤는가 — mcps에 local-tools.
        check(
            "local-tools" in (out.get("mcps") or []),
            f"H2 풀 파생이 참조 도구 반영 (mcps={out.get('mcps')})",
        )

        # ── H3 실행 왕복: 템플릿 노드 이름이 trace에·템플릿 도구 호출 실측 ──
        status, text, tr = await _chat(c, aid, "echo 테스트를 해줘")
        check(status == 200 and bool(text), f"H3 채팅 200+답변 (status={status})")
        graph_nodes = [g0.get("node") or g0.get("name") for g0 in (tr or {}).get("graph", [])]
        check(
            any("요약" in str(n) for n in graph_nodes),
            f"H3 trace.graph에 템플릿 노드명 (got {graph_nodes})",
        )
        echo_calls = [
            x for x in (tr or {}).get("mcp", []) if str(x.get("tool", "")).endswith("echo")
        ]
        check(len(echo_calls) > 0, f"H3 템플릿 도구(echo) 호출 실측 (got {len(echo_calls)})")
        detail = (await c.get(f"/node-templates/{TPL}")).json()
        v1_used = next(v for v in detail["versions"] if v["version"] == 1)["usedBy"]
        check(agent_name in v1_used, f"H3 usedBy에 참조 에이전트 (got {v1_used})")

        # ── H4 삭제 가드: 참조 v1=409(이름 표면화)·미참조 v2=204 ──
        r = await c.delete(f"/node-templates/{TPL}/1")
        check(
            r.status_code == 409 and agent_name in r.json().get("detail", ""),
            f"H4 참조 버전 삭제 409+이름 (got {r.status_code})",
        )
        r = await c.delete(f"/node-templates/{TPL}/2")
        check(r.status_code == 204, f"H4 미참조 버전 삭제 204 (got {r.status_code})")

        # ── H5 미해결 참조: 저장 시 422(이른 실패) ──
        r = await c.post(
            "/agents",
            json={
                "name": f"v316-bad-{uuid.uuid4().hex[:6]}",
                "config": {
                    "model": "mock-llm",
                    "prompt": "",
                    "impl": "pipeline",
                    "nodes": [{"ref": {"name": TPL, "version": 99}}],
                },
            },
        )
        check(
            r.status_code == 422 and "미해결" in r.json().get("detail", ""),
            f"H5 없는 버전 저장 422 (got {r.status_code})",
        )
        if r.status_code == 201:
            created_agents.append(r.json()["id"])
        # H5b impl 비대칭 봉합(codex P1): impl 미선언(비노드형)이라도 ref 존재 검증은 저장 시 강제.
        r = await c.post(
            "/agents",
            json={
                "name": f"v316-noimpl-{uuid.uuid4().hex[:6]}",
                "config": {
                    "model": "mock-llm",
                    "prompt": "",
                    "nodes": [{"ref": {"name": TPL, "version": 99}}],
                },
            },
        )
        check(r.status_code == 422, f"H5b 비노드형도 없는 참조 저장 422 (got {r.status_code})")
        if r.status_code == 201:
            created_agents.append(r.json()["id"])
        # 직접 DB 삭제(삭제 가드 우회 시뮬 — TOCTOU 잔여 경로)에도 실행이 조용히 반쪽으로 돌지 않는다.
        async with SessionLocal() as s:
            await s.execute(sa_delete(NodeTemplate).where(NodeTemplate.name == TPL))
            await s.commit()
        status, _, _ = await _chat(c, aid, "안녕")
        check(status == 422, f"H5 참조 소실 후 채팅 422(마스킹 0) (got {status})")
        out = (await c.get(f"/agents/{aid}")).json()
        check(
            out.get("resolvedNodes") is None and isinstance(out.get("nodes"), list),
            "H5 조회는 비잠금(resolvedNodes=None·nodes 유지)",
        )

        # ── H6 오버라이드: 해석→병합(ref 노드 위 세션 패치) ──
        r = await c.post(
            "/node-templates",
            json={
                "name": TPL,
                "config": {"name": "요약", "prompt": V1_PROMPT, "model": "mock-llm"},
            },
        )
        check(r.status_code == 201, "H6 템플릿 재발행(v1 재생)")
        new_ver = r.json()["version"]
        # 에이전트 참조를 재생 버전으로 갱신(수정 입구도 ref 저장을 지나며 검증됨).
        r = await c.put(
            f"/agents/{aid}",
            json={
                "name": None,
                "description": None,
                "config": {
                    "model": "mock-llm",
                    "prompt": "",
                    "impl": "pipeline",
                    "nodes": [{"ref": {"name": TPL, "version": new_ver}}],
                },
            },
        )
        check(r.status_code == 200, f"H6 참조 갱신 저장 200 (got {r.status_code}: {r.text[:200]})")
        ov = {
            "nodes": [
                {
                    "prompt": "오버라이드: 무조건 '패치됨'이라고 답해라",
                    "model": "mock-llm",
                    "tools": [],
                }
            ]
        }
        status, _, tr = await _chat(c, aid, "아무거나", overrides=ov)
        check(
            status == 200
            and (tr or {}).get("overrides", {}).get("nodes", {}).get("status") == "applied",
            f"H6 ref 노드 오버라이드 applied(해석→병합·길이 일치) (got {(tr or {}).get('overrides')})",
        )

        # ── H7 사본 격리: 해석 결과 변형 → 재해석 불변(등록 원본 비오염) ──
        async with SessionLocal() as s:
            saved_nodes = [{"ref": {"name": TPL, "version": new_ver}}]
            first = await resolve_node_refs(s, saved_nodes)
            first[0]["prompt"] = "오염 시도"
            first[0]["tools"] = ["evil"]
            second = await resolve_node_refs(s, saved_nodes)
            check(
                second[0]["prompt"] == V1_PROMPT and "evil" not in (second[0].get("tools") or []),
                "H7 사본 격리(재해석 불변)",
            )
            row = (
                await s.execute(select(NodeTemplate).where(NodeTemplate.name == TPL))
            ).scalar_one()
            check(row.config.get("prompt") == V1_PROMPT, "H7 등록 원본 비오염(DB 확인)")

        # ── 정리 ──
        for a in created_agents:
            await c.delete(f"/agents/{a}")
        async with SessionLocal() as s:
            await s.execute(sa_delete(NodeTemplate).where(NodeTemplate.name.in_([TPL, f"{TPL}-x"])))
            await s.commit()


def main() -> None:
    unit_checks()
    asyncio.run(http_checks())
    print(f"\n{len(_fails)} failed")
    if _fails:
        for f in _fails:
            print("  FAILED:", f)
        sys.exit(1)
    print("VERIFY316_OK — 노드 라이브러리(등록·버전 핀 참조·삭제 가드·오버라이드) 정착")


if __name__ == "__main__":
    main()

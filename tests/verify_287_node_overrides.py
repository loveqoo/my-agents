"""스펙 287 검증 — 노드형 세션 오버라이드(구조 불변·필드만).

검증 사다리(비겹침):
  [U] 단위 — _merge_node_overrides(필드 화이트리스트·name 보존·길이/형식 불일치=mismatch),
      _overrides_trace nodes 요약({count,status} — 프롬프트 전문 미기록).
  [H] 통합(in-process ASGI + 실 DB + mock-llm) — 노드형 chat:
      효과 실측(노드 도구 오버라이드 → trace["mcp"] 호출 변화), trace.overrides.nodes 상태,
      구조 불일치=저장본 실행, name 오버라이드 시도=저장 이름 유지(trace.graph), 비노드형=mismatch.

실행: uv run --project packages/api python tests/verify_287_node_overrides.py
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


# ================================================================ [U] 단위
def unit_checks() -> None:
    print("[U] 단위 — merge 시맨틱·트레이스 요약")
    from api.chat import _merge_node_overrides, _overrides_trace

    saved = [
        {"name": "a", "prompt": "p1", "model": "m1", "tools": ["x"]},
        {"name": "b", "prompt": "p2", "model": "m2", "tools": []},
    ]
    # U1 필드 merge + name 보존 + 화이트리스트 밖 키 무시
    m, s = _merge_node_overrides(
        saved, [{"name": "HACK", "prompt": "P1", "model": "m9", "evil": 1}, {"tools": ["y"]}]
    )
    check(s == "applied", "U1 같은 길이 → applied")
    check(m[0]["name"] == "a" and m[1]["name"] == "b", "U1 name=구조 식별자 보존(HACK 무시)")
    check(m[0]["prompt"] == "P1" and m[0]["model"] == "m9", "U1 필드 덮음(prompt·model)")
    check("evil" not in m[0], "U1 화이트리스트 밖 키 무시")
    check(m[1]["tools"] == ["y"] and m[1]["prompt"] == "p2", "U1 미지정 필드=저장본 유지")
    check(saved[0]["prompt"] == "p1", "U1 저장본 원본 불변(사본 merge)")
    # U2 구조 불일치·형식 오류 → 저장본 그대로 + mismatch
    m2, s2 = _merge_node_overrides(saved, [{}])
    check(s2 == "mismatch" and m2 is saved, "U2 길이 불일치 → mismatch·저장본")
    _, s3 = _merge_node_overrides(saved, "x")
    check(s3 == "mismatch", "U2 리스트 아님 → mismatch")
    m4, s4 = _merge_node_overrides(saved, [{"prompt": "q"}, "notdict"])
    check(s4 == "mismatch" and m4 is saved, "U2 원소 형식 오류 → mismatch·저장본")
    # U3 트레이스 요약 — 개수+상태만(프롬프트 전문 미기록), 상태 없으면 nodes 미기록(무회귀)
    t = _overrides_trace({"nodes": [{"prompt": "비밀스러운 장문" * 50}]}, nodes_status="applied")
    check(
        t is not None and t.get("nodes") == {"count": 1, "status": "applied"},
        f"U3 nodes 요약 (got {t})",
    )
    check("비밀스러운" not in json.dumps(t, ensure_ascii=False), "U3 프롬프트 전문 미기록")
    t2 = _overrides_trace({"nodes": [{}]}, nodes_status=None)
    check(t2 is None, "U3 상태 없음(비적용 경로) → nodes 미기록")
    t3 = _overrides_trace({"nodes": [{}, {}]}, nodes_status="mismatch")
    check(
        t3 is not None and t3.get("nodes", {}).get("status") == "mismatch",
        "U3 mismatch도 기록(왜 안 먹었는지 표면화)",
    )
    # U4 vectorTables 트레이스 키(287 allowed 추가와 쌍)
    t4 = _overrides_trace({"vectorTables": ["docs_kb"]})
    check(t4 is not None and t4.get("vectorTables") == ["docs_kb"], "U4 vectorTables 트레이스 기록")


# ================================================================ [H] 통합
async def http_checks() -> None:
    print("[H] 통합 — 노드형 chat 오버라이드(효과 실측·트레이스·구조 게이트)")
    import httpx
    from api.auth import _token
    from api.main import app

    auth = {"Authorization": f"Bearer {_token()}"}
    transport = httpx.ASGITransport(app=app)
    created: list[str] = []

    async def _chat(client, aid: str, text: str, overrides: dict | None = None):
        acc: list[str] = []
        trace = None
        body: dict = {"messages": [{"role": "user", "content": text}]}
        if overrides is not None:
            body["overrides"] = overrides
        async with client.stream("POST", f"/agents/{aid}/chat", json=body) as resp:
            assert resp.status_code == 200, f"chat status {resp.status_code}"
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
        return "".join(acc), trace

    async with httpx.AsyncClient(
        transport=transport, base_url="http://t", headers=auth, timeout=120
    ) as c:
        # 노드형 픽스처 — 노드 1개, 도구=local-tools__echo(mock-llm은 바인딩된 도구 base 이름 언급 시 호출).
        r = await c.post(
            "/agents",
            json={
                "name": f"v287-pipe-{uuid.uuid4().hex[:6]}",
                "config": {
                    "model": "mock-llm",
                    "prompt": "",
                    "impl": "pipeline",
                    "mcps": ["local-tools"],
                    "tools": [],
                    "nodes": [
                        {
                            "name": "n1",
                            "prompt": "요청을 처리해라",
                            "model": "mock-llm",
                            "tools": ["local-tools__echo"],
                        }
                    ],
                },
            },
        )
        check(r.status_code == 201, f"H0 노드형 생성 201 (got {r.status_code})")
        pid = r.json()["id"]
        created.append(pid)

        # H1 기준선 — 오버라이드 없음: echo 언급 → 노드 도구 호출됨 + trace.overrides 없음.
        _, tr0 = await _chat(c, pid, "echo 테스트를 해줘")
        base_calls = [x for x in (tr0 or {}).get("mcp", []) if x.get("tool", "").endswith("echo")]
        check(
            len(base_calls) > 0,
            f"H1 기준선: echo 호출 실측 (mcp={[(x.get('server'), x.get('tool')) for x in (tr0 or {}).get('mcp', [])]})",
        )
        check("overrides" not in (tr0 or {}), "H1 오버라이드 없음 → trace.overrides 미기록")

        # H2 효과 실측 — 노드 도구를 빼는 오버라이드(같은 구조·필드만) → echo 호출 소멸 + applied.
        ov = {
            "nodes": [{"prompt": "요청을 처리해라", "model": "mock-llm", "tools": []}],
            "mcps": [],
            "vectorTables": [],
            "memories": [],
        }
        _, tr1 = await _chat(c, pid, "echo 테스트를 해줘", overrides=ov)
        ov_calls = [x for x in (tr1 or {}).get("mcp", []) if x.get("tool", "").endswith("echo")]
        check(
            len(ov_calls) == 0, f"H2 노드 도구 제거 오버라이드 → echo 호출 0 (got {len(ov_calls)})"
        )
        check(
            (tr1 or {}).get("overrides", {}).get("nodes") == {"count": 1, "status": "applied"},
            f"H2 trace.overrides.nodes=applied (got {(tr1 or {}).get('overrides', {}).get('nodes')})",
        )

        # H3 구조 불일치(노드 2개 — 저장본은 1개) → 저장 노드로 실행(echo 호출 유지) + mismatch 표면화.
        ov_bad = {
            "nodes": [{"tools": []}, {"prompt": "추가 노드", "model": "mock-llm", "tools": []}]
        }
        _, tr2 = await _chat(c, pid, "echo 테스트를 해줘", overrides=ov_bad)
        bad_calls = [x for x in (tr2 or {}).get("mcp", []) if x.get("tool", "").endswith("echo")]
        check(
            len(bad_calls) > 0,
            f"H3 구조 불일치 → 저장 노드로 실행(echo 호출 유지, got {len(bad_calls)})",
        )
        check(
            (tr2 or {}).get("overrides", {}).get("nodes", {}).get("status") == "mismatch",
            f"H3 trace mismatch 표면화 (got {(tr2 or {}).get('overrides', {}).get('nodes')})",
        )

        # H4 name 오버라이드 시도 → 실행 그래프의 노드 이름은 저장본 유지(구조 식별자 서버 강제).
        ov_name = {
            "nodes": [
                {"name": "HACK", "prompt": "요청을 처리해라", "model": "mock-llm", "tools": []}
            ]
        }
        _, tr3 = await _chat(c, pid, "안녕", overrides=ov_name)
        gnames = [g.get("node") for g in (tr3 or {}).get("graph", [])]
        check(
            "HACK" not in gnames and any("n1" in (g or "") for g in gnames),
            f"H4 name 오버라이드 무시 — 그래프 노드=저장 이름 (got {gnames})",
        )

        # H5 비노드형에 nodes를 보내면 mismatch(무해·표면화). 실행은 정상.
        r2 = await c.post(
            "/agents",
            json={
                "name": f"v287-direct-{uuid.uuid4().hex[:6]}",
                "config": {"model": "mock-llm", "prompt": "t"},
            },
        )
        did = r2.json()["id"]
        created.append(did)
        txt, tr4 = await _chat(c, did, "안녕", overrides={"nodes": [{"prompt": "x"}]})
        check(bool(txt), "H5 비노드형 + nodes 오버라이드 → 실행 정상")
        check(
            (tr4 or {}).get("overrides", {}).get("nodes", {}).get("status") == "mismatch",
            f"H5 비노드형 → mismatch 표면화 (got {(tr4 or {}).get('overrides', {}).get('nodes')})",
        )

        # H6 형 가드(codex 287 Low) — historyDepth 문자열 오버라이드가 500을 못 만든다(저장값 폴백).
        txt6, _ = await _chat(c, did, "안녕", overrides={"historyDepth": "abc"})
        check(bool(txt6), "H6 historyDepth 비정수 오버라이드 → 500 없이 실행(형 가드)")

        for aid in created:
            await c.delete(f"/agents/{aid}")


unit_checks()
asyncio.run(http_checks())

print()
print(f"{len(_fails)} FAIL" if _fails else "ALL PASS")
raise SystemExit(1 if _fails else 0)

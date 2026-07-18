"""스펙 317 검증 — 코드 노드(공통 노드 인터페이스 + 신뢰 레지스트리).

검증 사다리(비겹침):
  [U] 단위 — 레지스트리(등록/미등록/부적합), mask_pii_text 결정성, normalize_nodes impl 통과,
      미등록 impl 그래프 빌드=AgentConfigError(마스킹 0), 오버라이드 표면(_node_patch_fields·partial).
  [H] 통합(in-process ASGI + 실 DB) —
      H1 부팅 동기화: mask-pii@1 kind=code upsert·멱등·동일 버전 덮어쓰기(수정 후 재동기화=복원)·
         kind 혼합 스킵(설정 노드 이름과 겹치는 코드 노드는 미발행).
      H2 API 가드: 코드 노드 이름 발행 409·코드 노드 삭제 409.
      H3 실행 왕복: mask-pii 참조 에이전트 채팅 → 이메일·전화 마스킹된 답 + trace.graph에 노드명.
      H4 오버라이드: 코드 소유 필드 패치 → status=partial(조용한 무시 아님).
      H5 미등록 impl(고아 행): 채팅이 설정 오류 프레임으로 정직 거부(default 만회 0).

실행: uv run --project packages/api python tests/verify_317_code_node.py
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
    print("[U] 단위 — 레지스트리·마스킹·정규화·설정오류·오버라이드 표면")
    from agent.nodes import CustomNode, get_node_impl, mask_pii_text
    from agent.runtime import AgentBuildContext, AgentConfigError
    from agent.flows.pipeline import LinearPipelineAgent, normalize_nodes

    # U1 레지스트리 — 빌트인 해석·미등록 None
    impl = get_node_impl("mask_pii")
    check(
        impl is not None and isinstance(impl, CustomNode), "U1 빌트인 mask_pii 해석(Protocol 적합)"
    )
    check(get_node_impl("no-such-node") is None, "U1 미등록 키 → None")
    check(get_node_impl(None) is None and get_node_impl("") is None, "U1 빈 키 → None")
    mf = impl.describe()
    check(
        mf.name == "mask-pii" and mf.version == 1 and mf.overridable == (),
        f"U1 manifest (got {mf})",
    )

    # U2 마스킹 순수 함수 — 이메일·전화(하이픈/점/공백/+82) 결정적
    masked = mask_pii_text("문의: gunam.jung@gmail.com / 010-1234-5678 / +82 10 9876 5432")
    check(
        "gunam.jung@gmail.com" not in masked and "g***@gmail.com" in masked,
        f"U2 이메일 마스킹 (got {masked})",
    )
    check(
        "1234-5678" not in masked.replace("***-****-5678", "") and "***-****-5678" in masked,
        "U2 전화 마스킹(뒤 4자리)",
    )
    check("9876 5432" not in masked and "***-****-5432" in masked, "U2 +82 국제표기 마스킹")
    check(mask_pii_text("민감정보 없음") == "민감정보 없음", "U2 비민감 텍스트 불변")

    # U3 normalize_nodes — impl 노드는 prompt 없이 통과(이름 기본값), 인라인 규칙 무회귀
    out = normalize_nodes([{"impl": "mask_pii"}, {"prompt": "p"}])
    check(
        len(out) == 2 and out[0].get("impl") == "mask_pii" and out[0].get("name") == "노드1",
        f"U3 impl 노드 통과 (got {out[0]})",
    )
    check(normalize_nodes([{"impl": "  "}]) == [], "U3 공백 impl은 잡값(제거)")

    # U4 미등록 impl → 그래프 빌드 시 AgentConfigError(폴백 마스킹 0)
    ctx = AgentBuildContext(
        prompt="",
        model_cfg={"base_url": "http://x", "api_key": "k", "model_id": "m", "params": {}},
        tools=[],
        impl_config={"nodes": [{"impl": "ghost-impl", "name": "유령"}]},
    )
    try:
        LinearPipelineAgent().build_graph(ctx)
        check(False, "U4 미등록 impl은 AgentConfigError여야 함")
    except AgentConfigError as e:
        check(str(e) == "ghost-impl", f"U4 미등록 impl → AgentConfigError (got {e!r})")

    # U5 오버라이드 표면 — 설정 노드=전체, mask_pii=빈 표면, 미등록=빈 표면(fail-closed)
    from api.chat_context import _NODE_OVERRIDE_FIELDS, _merge_node_overrides, _node_patch_fields

    check(
        _node_patch_fields({"prompt": "p"}) == _NODE_OVERRIDE_FIELDS,
        "U5 설정 노드=화이트리스트 전체",
    )
    check(_node_patch_fields({"impl": "mask_pii"}) == set(), "U5 mask_pii=빈 표면(전부 코드 소유)")
    check(_node_patch_fields({"impl": "ghost"}) == set(), "U5 미등록 impl=빈 표면(fail-closed)")
    merged, status = _merge_node_overrides(
        [{"impl": "mask_pii", "name": "마스킹"}], [{"prompt": "덮기"}]
    )
    check(
        status == "partial" and "prompt" not in merged[0],
        f"U5 코드 소유 필드 패치 → partial+미병합 (got {status})",
    )
    merged2, status2 = _merge_node_overrides([{"prompt": "p", "model": "m"}], [{"prompt": "P2"}])
    check(status2 == "applied" and merged2[0]["prompt"] == "P2", "U5 설정 노드 applied 무회귀")


# ================================================================ [H] 통합
async def http_checks() -> None:
    print("[H] 통합 — 부팅 동기화·API 가드·실행 왕복·오버라이드 partial·고아 행 거부")
    import httpx
    from sqlalchemy import delete as sa_delete
    from sqlalchemy import select

    from agent.nodes import _NODES, NodeManifest, register_node
    from api.auth import _token
    from api.db import SessionLocal
    from api.main import app
    from api.models import NodeTemplate
    from api.node_templates import sync_code_nodes

    auth = {"Authorization": f"Bearer {_token()}"}
    transport = httpx.ASGITransport(app=app)
    created_agents: list[str] = []

    async def _row(name: str, version: int) -> NodeTemplate | None:
        async with SessionLocal() as s:
            return (
                await s.execute(
                    select(NodeTemplate).where(
                        NodeTemplate.name == name, NodeTemplate.version == version
                    )
                )
            ).scalar_one_or_none()

    async def _chat(client, aid: str, text: str, overrides: dict | None = None):
        acc: list[str] = []
        trace = None
        error = None
        body: dict = {"messages": [{"role": "user", "content": text}]}
        if overrides is not None:
            body["overrides"] = overrides
        async with client.stream("POST", f"/agents/{aid}/chat", json=body) as resp:
            if resp.status_code != 200:
                return resp.status_code, "", None, None
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
                    elif isinstance(obj, dict) and obj.get("error"):
                        error = obj["error"]
                    elif isinstance(obj, dict) and obj.get("text"):
                        acc.append(obj["text"])
        return 200, "".join(acc), trace, error

    async with httpx.AsyncClient(
        transport=transport, base_url="http://t", headers=auth, timeout=120
    ) as c:
        # ── H1 부팅 동기화 — upsert·멱등·동일 버전 덮어쓰기·kind 혼합 스킵 ──
        await sync_code_nodes()
        row = await _row("mask-pii", 1)
        check(
            row is not None and row.kind == "code" and (row.config or {}).get("impl") == "mask_pii",
            f"H1 mask-pii@1 kind=code 발행 (got {row and row.config})",
        )
        # 동일 버전 덮어쓰기 — 행을 오염시킨 뒤 재동기화하면 manifest 값으로 복원(전파 시맨틱).
        async with SessionLocal() as s:
            r = (
                await s.execute(
                    select(NodeTemplate).where(
                        NodeTemplate.name == "mask-pii", NodeTemplate.version == 1
                    )
                )
            ).scalar_one()
            r.config = {"impl": "tampered"}
            await s.commit()
        await sync_code_nodes()
        row = await _row("mask-pii", 1)
        check(
            (row.config or {}).get("impl") == "mask_pii",
            "H1 동일 버전 덮어쓰기(재동기화=코드 진실로 복원)",
        )
        # kind 혼합 스킵 — 기존 설정 노드와 같은 이름의 코드 노드는 발행되지 않는다.
        cfg_name = f"v317-cfg-{uuid.uuid4().hex[:6]}"
        r1 = await c.post(
            "/node-templates",
            json={"name": cfg_name, "config": {"prompt": "설정 노드", "model": "mock-llm"}},
        )
        check(r1.status_code == 201, "H1 설정 노드 발행(혼합 실험 준비)")

        class _Clash:
            def describe(self):
                return NodeManifest(name=cfg_name, version=1, description="충돌 실험")

            def build_step(self, node_cfg, ctx):
                async def _step(state):
                    return {"messages": []}

                return _step

        register_node("v317-clash", _Clash)
        try:
            await sync_code_nodes()
            clash = await _row(cfg_name, 1)
            check(
                clash is not None and clash.kind == "config",
                "H1 kind 혼합 스킵(설정 노드 보존·코드 미발행)",
            )
        finally:
            _NODES.pop("v317-clash", None)

        # ── H2 API 가드 — 코드 노드 이름 발행 409·삭제 409 ──
        r = await c.post(
            "/node-templates",
            json={"name": "mask-pii", "config": {"prompt": "x", "model": "mock-llm"}},
        )
        check(
            r.status_code == 409 and "코드" in r.json().get("detail", ""),
            f"H2 코드 이름 발행 409 (got {r.status_code})",
        )
        r = await c.delete("/node-templates/mask-pii/1")
        check(
            r.status_code == 409 and "코드" in r.json().get("detail", ""),
            f"H2 코드 노드 삭제 409 (got {r.status_code})",
        )

        # ── H3 실행 왕복 — mask-pii 참조 에이전트: 입력의 이메일·전화가 답에서 마스킹 ──
        agent_name = f"v317-pipe-{uuid.uuid4().hex[:6]}"
        r = await c.post(
            "/agents",
            json={
                "name": agent_name,
                "config": {
                    "model": "mock-llm",
                    "prompt": "",
                    "impl": "pipeline",
                    "nodes": [{"ref": {"name": "mask-pii", "version": 1}}],
                },
            },
        )
        check(
            r.status_code == 201,
            f"H3 코드 노드 참조 에이전트 생성 201 (got {r.status_code}: {r.text[:200]})",
        )
        aid = r.json()["id"]
        created_agents.append(aid)
        out = (await c.get(f"/agents/{aid}")).json()  # resolvedNodes는 조회 파생(생성 응답엔 없음)
        rn = (out.get("resolvedNodes") or [{}])[0]
        check(
            rn.get("impl") == "mask_pii" and rn.get("overridable") == [],
            f"H3 resolvedNodes에 impl+표면 (got {rn})",
        )
        status, text, tr, _err = await _chat(
            c,
            aid,
            "제 이메일은 gunam.jung@gmail.com 이고 전화는 010-1234-5678 입니다. 기억해 주세요.",
        )
        check(status == 200 and bool(text), f"H3 채팅 200+답변 (status={status})")
        check(
            "gunam.jung@gmail.com" not in text and "g***@gmail.com" in text,
            f"H3 이메일 마스킹 실측 (got {text[:80]})",
        )
        check("010-1234-5678" not in text and "***-****-5678" in text, "H3 전화 마스킹 실측")
        graph_nodes = [g.get("node") or g.get("name") for g in (tr or {}).get("graph", [])]
        check(
            any("mask-pii" in str(n) for n in graph_nodes),
            f"H3 trace.graph에 코드 노드명 (got {graph_nodes})",
        )

        # ── H4 오버라이드 — 코드 소유 필드 패치 → partial 표면화 ──
        status, _t, tr4, _e = await _chat(
            c, aid, "테스트", overrides={"nodes": [{"prompt": "덮어쓰기 시도"}]}
        )
        got4 = (tr4 or {}).get("overrides", {}).get("nodes", {})
        check(
            status == 200 and got4.get("status") == "partial",
            f"H4 코드 소유 필드 → partial (got {got4})",
        )

        # ── H5 고아 행(레지스트리에 없는 impl) — 실행이 설정 오류로 정직 거부 ──
        ghost = f"v317-ghost-{uuid.uuid4().hex[:6]}"
        async with SessionLocal() as s:
            s.add(
                NodeTemplate(
                    name=ghost,
                    version=1,
                    kind="code",
                    config={"impl": "ghost-impl"},
                    description=None,
                )
            )
            await s.commit()
        r = await c.post(
            "/agents",
            json={
                "name": f"v317-ghost-a-{uuid.uuid4().hex[:6]}",
                "config": {
                    "model": "mock-llm",
                    "prompt": "",
                    "impl": "pipeline",
                    "nodes": [{"ref": {"name": ghost, "version": 1}}],
                },
            },
        )
        check(r.status_code == 201, "H5 고아 행 참조 저장(행은 존재 — 코드만 부재)")
        gid = r.json()["id"]
        created_agents.append(gid)
        status, _t, _tr, err = await _chat(c, gid, "안녕")
        check(
            status == 200 and err is not None and "설정 오류" in err,
            f"H5 채팅=설정 오류 프레임(마스킹 0) (got {err})",
        )

        # ── H6 eval 입구(codex P1) — 평가도 실제 파이프라인(코드 노드)을 태운다(기본 노드 퇴화 금지) ──
        from api.eval_runner import eval_run_agent

        obs = await eval_run_agent(
            uuid.UUID(aid), "이메일 gunam.jung@gmail.com 을 기억해", principal="machine"
        )
        check(
            not obs.get("error") and "g***@gmail.com" in obs.get("output", ""),
            f"H6 eval이 코드 노드를 실행(마스킹 실측) (got {obs.get('output', '')[:60]!r})",
        )
        obs_ghost = await eval_run_agent(uuid.UUID(gid), "안녕", principal="machine")
        check(
            obs_ghost.get("error") is True and "조립 실패" in (obs_ghost.get("detail") or ""),
            f"H6 eval 고아 impl=error obs(조용한 폴백 채점 금지) (got {obs_ghost.get('detail')})",
        )

        # ── 정리 ──
        for a in created_agents:
            await c.delete(f"/agents/{a}")
        await c.delete(f"/node-templates/{cfg_name}/1")
        async with SessionLocal() as s:
            await s.execute(sa_delete(NodeTemplate).where(NodeTemplate.name.in_([ghost, cfg_name])))
            await s.commit()


def main() -> None:
    unit_checks()
    asyncio.run(http_checks())
    print(f"\n{len(_fails)} failed")
    if _fails:
        for f in _fails:
            print("  FAILED:", f)
        sys.exit(1)
    print("VERIFY317_OK — 코드 노드(인터페이스·레지스트리·동기화·가드·오버라이드 표면) 정착")


if __name__ == "__main__":
    main()

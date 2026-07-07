"""verify_233 — 능력(capability kind) × impl 타입 조합 전수 발동 매트릭스(스펙 233).

배경(스펙 201 후속2, 회고 188): 능력을 **배선했는데 실제 저장된 에이전트가 대화 중 발동을 안 하는**
버그 클래스를 잡는다. 부품 단위테스트(도구 함수 직접 호출)는 이 틈을 못 본다 — 필요한 건 "실 저장
config로 채팅을 관통했을 때 능력이 진짜 발동하는가"의 조합 전수다.

verify_110 패턴 확장(오버라이드 금지·실 저장 경로): httpx.ASGITransport(app) 인프로세스, 슈퍼principal
override, POST /agents(실 저장) → POST /agents/{id}/chat 1턴 → 최종 trace JSON 단언 → finally 삭제.

핵심 매트릭스 = impl 8종 × 능력 6종 = 48칸. 각 칸은 impl의 `consumes`(스펙 206, /agent-impls)가 그 능력을
나르는 **설정 표면**을 포함하느냐로 발동(FIRE)/무시(IGNORE)가 갈린다:
  - default·plan_execute : mcp·rag·memory  발동 (consumes=mcps,vectorTables,memories)
  - route                : memory 발동      (consumes=memories)
  - orchestrate·ranked   : 6종 전부 발동     (consumes=capabilities,memories — 브로커 위임)
  - artifact_* 3종        : 0종 발동          (consumes=artifactSpec)
=> 발동 19칸 / 무시 29칸.

발동 신호(최종 SSE trace):
  - 브로커 위임(orchestrate)의 읽기 cap(agent·rag·memory) : graph 노드에 `broker_invoke:{kind}`.
  - 브로커 위임의 부수효과 cap(mcp·memwrite·memedit)        : 전송 이전 HIL interrupt → 승인대기(approval).
  - 직접 ReAct(default·plan_execute)의 mcp(delete_record)   : HIL interrupt → 승인대기(approval).
  - 직접 ReAct의 rag                                        : `mcp`(calls_sink)에 (rag, search_documents).
  - 직접 memory 회상                                        : `memories` 필드 hit(플랫폼 회상).
결정성: 브로커 위임=LLM 독립(discover=lexical). ReAct 도구=mock-llm `_TOOL_TRIGGERS`(rag→"검색",
mcp delete_record→"삭제"). 모델은 전 config에서 `mock-llm`.

메모리 백엔드: 이 하네스는 **MEMORY_BACKEND=inmemory**(스펙 040 레퍼런스 백엔드)를 강제해 직접-memory
회상을 결정적으로 만든다(시드=프라이밍 턴 1회 → 같은 세션 회상). mem_cfg가 해석 안 되면(기본 chat/
embedding 모델 부재) 직접-memory 발동칸을 **SKIP**(silent 금지) — 브로커-memory 발동칸은 백엔드 무관
(노드가 error에도 기록됨)이라 항상 검증한다.

실행: cd packages/api && uv run python ../../tests/verify_233_capability_matrix.py
"""

from __future__ import annotations

import os

# 반드시 app import 이전에 — inmemory 레퍼런스 백엔드로 직접-memory 회상을 결정적으로.
os.environ.setdefault("MEMORY_BACKEND", "inmemory")

import asyncio  # noqa: E402
import json  # noqa: E402
import uuid  # noqa: E402

import httpx  # noqa: E402

from agent.runtime import DefaultUiAgent  # noqa: E402
from api.auth import _token, current_principal  # noqa: E402
from api.main import app  # noqa: E402
from api.memory import LONG_TERM_MEMORY  # noqa: E402

# ------------------------------------------------------------------ principal override
# verify_110과 동일 — 채팅 능력 오케스트레이션은 유저 세션 RBAC를 통과해야 한다(머신 토큰=deny).
# is_superuser 우회로 capability:* 허용. Session.user_id는 String이라 스텁 UUID 무해.
class _SuperPrincipal:
    id = uuid.UUID("000000bb-0000-0000-0000-0000000000bb")
    is_superuser = True
    is_active = True
    is_verified = True
    email = "e2e-233-super@local"


app.dependency_overrides[current_principal] = lambda: _SuperPrincipal()

# ------------------------------------------------------------------ 축 상수
IMPLS = [
    "default",
    "plan_execute",
    "route",
    "orchestrate",
    "orchestrate_ranked",
    "artifact_slotfill",
    "artifact_targeting",
    "artifact_form",
]
KINDS = ["agent", "mcp", "rag", "memory", "memwrite", "memedit"]

BROKER_IMPLS = {"orchestrate", "orchestrate_ranked"}
DIRECT_MEM_IMPLS = {"default", "plan_execute", "route"}  # consumes "memories"(직접 회상)
ARTIFACT_IMPLS = {"artifact_slotfill", "artifact_targeting", "artifact_form"}
REACT_IMPLS = {"default", "plan_execute"}  # ctx.tools(mcp+rag) 소비

# 결과 마커
PASS, FAIL, IGNORE_OK, SKIP = "PASS", "FAIL", "IGNORE-OK", "SKIP"


# ------------------------------------------------------------------ SSE 파서
def _parse(txt: str):
    """SSE 본문 → (traces, frames). trace = event:trace 데이터, frame = 일반 data 프레임."""
    traces: list[dict] = []
    frames: list[dict] = []
    for block in txt.split("\n\n"):
        ev = None
        data = None
        for line in block.splitlines():
            if line.startswith("event:"):
                ev = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data = line[len("data:"):].strip()
        if not data or data == "[DONE]":
            continue
        try:
            j = json.loads(data)
        except json.JSONDecodeError:
            continue
        (traces if ev == "trace" else frames).append(j)
    return traces, frames


def _signals(txt: str) -> dict:
    """최종 trace/frame에서 발동 신호를 추출한다."""
    traces, frames = _parse(txt)
    broker_nodes: list[str] = []
    broker_calls: list[dict] = []  # brokerCalls: cap별 {cap_id, error?, hits?, resultPreview?} — 성공/실패 구분
    memories: list = []
    mcp_calls: list = []
    for t in traces:
        for n in t.get("graph", []) or []:
            node = n.get("node") if isinstance(n, dict) else n
            if node and "broker_invoke" in node:
                broker_nodes.append(node)
        if t.get("brokerCalls"):
            broker_calls = t["brokerCalls"]
        if t.get("memories"):
            memories = t["memories"]
        if t.get("mcp"):
            mcp_calls = t["mcp"]
    # 승인대기(HIL interrupt) — frame의 approval 키 또는 trace approval, + wait 텍스트.
    approval_texts = [str(f.get("text", "")) for f in frames if "approval" in f]
    approval = bool(approval_texts) or any(t.get("approval") for t in traces)
    errors = [f["error"] for f in frames if isinstance(f, dict) and "error" in f]
    return {
        "broker": broker_nodes,
        "brokerCalls": broker_calls,
        "mcp": [(m.get("server"), m.get("tool")) for m in mcp_calls],
        "memories": len(memories),
        "approval": approval,
        "approval_texts": approval_texts,
        "errors": errors,
    }


def _any_fire(sig: dict) -> bool:
    """어떤 발동 신호라도 있으면 True(무시칸/대조군 검증용)."""
    return bool(sig["broker"]) or bool(sig["mcp"]) or sig["memories"] > 0 or sig["approval"]


# ------------------------------------------------------------------ 셀 배선 규칙
def wiring_surface(impl: str, kind: str) -> str:
    """이 (impl,kind) 셀을 실을 설정 표면. consumes 계약 단언 대상이기도 하다."""
    if kind == "mcp":
        return "capabilities" if impl in BROKER_IMPLS else "mcps"
    if kind == "rag":
        return "capabilities" if impl in BROKER_IMPLS else "vectorTables"
    if kind == "memory":
        # memory의 실제 표면은 config.memories(플랫폼 회상). 브로커 impl만 capabilities(broker memory
        # 위임)로 검증. artifact 무시칸도 **실 표면(config.memories)**으로 실어 정직하게 — 회상 0을 관측
        # (codex 지적1: 브로커 표면 우회 금지). 실측: artifact_form+config.memories 회상 hit=0(probe A).
        return "capabilities" if impl in BROKER_IMPLS else "memories"
    # agent / memwrite / memedit 는 직접 표면이 없다 → 항상 capabilities(브로커).
    return "capabilities"


_CAP_ID = {
    "agent": None,  # 런타임에 doc-translator agent_id로 채움(bare)
    "mcp": "mcp:{mcp_server}/{mcp_tool}",
    "rag": "rag:{collection}",
    "memory": "memory:user",
    "memwrite": "memwrite:user",
    "memedit": "memedit:user",
}


def cell_config(impl: str, kind: str, res: dict) -> dict:
    """이 셀의 실 저장 config(오버라이드 아님)."""
    cfg: dict = {"model": "mock-llm", "persona": "매트릭스 테스트", "historyDepth": 6}
    if impl != "default":
        cfg["impl"] = impl
    if impl in ARTIFACT_IMPLS:
        cfg["artifactSpec"] = {"fields": [{"key": "x", "label": "X"}]}
    surface = wiring_surface(impl, kind)
    if surface == "mcps":
        cfg["mcps"] = [res["mcp_server"]]
    elif surface == "vectorTables":
        cfg["vectorTables"] = [res["collection"]]
    elif surface == "memories":
        cfg["memories"] = [LONG_TERM_MEMORY]
    else:  # capabilities(브로커)
        if kind == "agent":
            cap = res["agent_id"]
        else:
            cap = _CAP_ID[kind].format(**res)
        cfg["capabilities"] = [cap]
    return cfg


def cell_prompt(impl: str, kind: str, res: dict) -> str:
    """이 셀의 채팅 프롬프트(발동을 유도하는 결정적 트리거)."""
    surface = wiring_surface(impl, kind)
    if surface == "mcps":  # 직접 mcp delete_record → "삭제" 트리거
        return "레코드 rec-001 삭제해줘"
    if surface == "vectorTables":  # 직접 rag search_documents → "검색" 트리거
        return f"{res['collection']} 문서 검색해줘"
    if surface == "memories":  # 직접 회상 — 2턴(프라이밍→회상)은 호출측이 처리
        return "등산"
    # 브로커: discover(lexical) — 단일 cap이라 항상 표면화되나 자원명으로 유도.
    return {
        "agent": "doc-translator 번역",
        "mcp": "delete_record 삭제",
        "rag": f"{res['collection']}",
        "memory": "장기 기억 회상",
        "memwrite": "저장",
        "memedit": "수정 삭제",
    }[kind]


def expected_fire(impl: str, kind: str) -> bool:
    if impl in BROKER_IMPLS:
        return True  # 브로커: capabilities 표면으로 6종 전부 위임
    if kind == "memory":
        # 실측 발견(스펙 233 §finding): memory 회상(config.memories)은 **플랫폼 레벨** — impl의 consumes와
        # 무관하게 발동한다(artifact도 회상함). spec 206상 consumes는 폼 힌트지 런타임 게이트가 아님.
        # 따라서 memory는 브로커 포함 전 impl에서 발동(회상 콘텐츠가 있을 때).
        return True
    if impl in {"default", "plan_execute"} and kind in {"mcp", "rag"}:
        return True  # ReAct: mcps(도구)·vectorTables(rag) 직접 소비
    return False


# ------------------------------------------------------------------ HTTP 헬퍼
async def _mk(c: httpx.AsyncClient, impl: str, kind: str, cfg: dict) -> str:
    # 이름 규칙(스펙 148)은 밑줄을 거부한다 — impl 키(plan_execute 등)의 `_`를 `-`로 정규화.
    slug = f"m233-{impl}-{kind}".replace("_", "-")
    r = await c.post("/agents", json={"name": f"{slug}-{uuid.uuid4().hex[:5]}", "config": cfg})
    r.raise_for_status()
    return r.json()["id"]


async def _chat(c: httpx.AsyncClient, aid: str, text: str, session: str | None = None) -> str:
    body: dict = {"messages": [{"role": "user", "content": text}]}
    if session:
        body["sessionId"] = session
    r = await c.post(f"/agents/{aid}/chat", json=body)
    return r.text


async def _chat_direct_memory(c: httpx.AsyncClient, aid: str) -> str:
    """직접-memory 회상 — 프라이밍 턴(자동 add) → 같은 세션 회상 턴. 회상 턴 SSE 반환."""
    r1 = await c.post(
        f"/agents/{aid}/chat",
        json={"messages": [{"role": "user", "content": "제 취미는 등산입니다 기억해주세요"}]},
    )
    _, frames = _parse(r1.text)
    session = next((f["session"] for f in frames if isinstance(f, dict) and "session" in f), None)
    r2 = await c.post(
        f"/agents/{aid}/chat",
        json={"messages": [{"role": "user", "content": "등산"}], "sessionId": session},
    )
    return r2.text


# ------------------------------------------------------------------ 발동칸 단언
def assert_fire(impl: str, kind: str, sig: dict, res: dict) -> tuple[str, str]:
    """발동칸 검증 → (marker, detail). PASS/FAIL."""
    surface = wiring_surface(impl, kind)
    if impl in BROKER_IMPLS:
        if kind in ("agent", "rag", "memory"):  # 읽기 cap → broker_invoke 노드 + brokerCall 성공(무error)
            if not any(n.startswith(f"broker_invoke:{kind}") for n in sig["broker"]):
                return FAIL, f"broker_invoke:{kind} 노드 부재 (broker={sig['broker']}, err={sig['errors']})"
            node = next(n for n in sig["broker"] if n.startswith(f"broker_invoke:{kind}"))
            # codex 지적2: 노드 존재≠성공. brokerCall이 error가 아니어야(+ rag는 hits 필드 관측).
            cap_prefix = {"rag": "rag:", "memory": "memory:", "agent": "agt_"}[kind]
            bc = next((x for x in sig["brokerCalls"] if str(x.get("cap_id", "")).startswith(cap_prefix)), None)
            if bc is None:
                return FAIL, f"위임 노드 {node} 있으나 brokerCall 레코드 부재(성공 확인 불가) calls={sig['brokerCalls']}"
            if bc.get("error"):
                return FAIL, f"위임 발동했으나 실패(error) {node} bc={bc}"
            if kind == "rag" and "hits" not in bc:
                return FAIL, f"rag 위임 성공 신호(hits) 부재 bc={bc}"
            success = f"hits={bc.get('hits')}" if kind == "rag" else ("resultPreview" if bc.get("resultPreview") else "무error")
            return PASS, f"위임 성공 {node} ({success})"
        # mcp / memwrite / memedit → 부수효과 HIL 승인대기
        action = {"mcp": f"{res['mcp_server']}.{res['mcp_tool']}", "memwrite": "memory.write", "memedit": "memory.edit"}[kind]
        if sig["approval"] and any(action in t for t in sig["approval_texts"]):
            return PASS, f"승인대기(action~={action})"
        if sig["approval"]:
            return FAIL, f"승인대기 발생했으나 action 불일치({action}) texts={sig['approval_texts']}"
        return FAIL, f"승인대기 부재(부수효과 cap 미발동) broker={sig['broker']} err={sig['errors']}"
    # 직접 ReAct / 회상
    if surface == "mcps":  # delete_record HIL
        if sig["approval"] and any(f"{res['mcp_server']}.{res['mcp_tool']}" in t for t in sig["approval_texts"]):
            return PASS, "직접 MCP 승인대기(delete_record)"
        return FAIL, f"직접 MCP 미발동 approval={sig['approval']} texts={sig['approval_texts']}"
    if surface == "vectorTables":  # RAG calls_sink
        if ("rag", "search_documents") in sig["mcp"]:
            return PASS, "직접 RAG search_documents 실행"
        return FAIL, f"직접 RAG 미발동 calls_sink={sig['mcp']}"
    if surface == "memories":  # 회상 hit
        if sig["memories"] > 0:
            return PASS, f"회상 hit={sig['memories']}"
        return FAIL, f"회상 0건(직접 memory 미발동) errors={sig['errors']}"
    return FAIL, "미분류 발동칸"


def assert_ignore(impl: str, kind: str, sig: dict, consumes: dict) -> tuple[str, str]:
    """무시칸 검증 → (marker, detail). IGNORE-OK/FAIL.
    조건 둘: (1) 발동 신호 전부 부재, (2) RuntimeMeta.consumes가 배선 표면 제외(무시의 근거)."""
    surface = wiring_surface(impl, kind)
    cons = consumes.get(impl)
    contract_ok = cons is not None and surface not in cons
    if _any_fire(sig):
        return FAIL, (
            f"무시칸인데 발동 신호 존재: broker={sig['broker']} mcp={sig['mcp']} "
            f"mems={sig['memories']} approval={sig['approval']}"
        )
    if not contract_ok:
        return FAIL, f"consumes 계약 위반: consumes({impl})={cons} 가 표면 '{surface}' 를 제외하지 않음"
    return IGNORE_OK, f"무시(신호 0) + consumes({impl})={cons} ∌ {surface}"


# ------------------------------------------------------------------ 메인
async def run() -> int:
    checks: list[tuple[str, str, str, str]] = []  # (impl, kind, marker, detail)

    t = httpx.ASGITransport(app=app)
    headers = {"Authorization": f"Bearer {_token()}"}
    async with httpx.AsyncClient(transport=t, base_url="http://t", headers=headers, timeout=120) as c:
        # --- 시드 자원 확인(하드코딩 금지 — DB에서 조회) ---
        cols = (await c.get("/collections")).json()
        col = next((x["name"] for x in cols if x["name"] == "docs-kb"), cols[0]["name"] if cols else None)
        servers = (await c.get("/mcp-servers")).json()
        mcp_srv = next(
            (s for s in servers if s["name"] == "local-tools" and "delete_record" in (s.get("enabled_tools") or [])),
            None,
        )
        agents = (await c.get("/agents")).json()
        agents = agents if isinstance(agents, list) else agents.get("items", agents)
        remote = next(
            (a for a in agents if a.get("source") in ("code", "external")
             and a.get("endpoint") and "127.0.0.1" in a.get("endpoint", "")),
            None,
        )
        impls_meta = (await c.get("/agent-impls")).json()
        consumes: dict[str, list | None] = {m["key"]: m.get("consumes") for m in impls_meta}
        # default는 레지스트리에 없다(impl 미선언) — 레퍼런스 구현에서 직접.
        consumes["default"] = list(DefaultUiAgent().describe().consumes or [])

        if not col or not mcp_srv or not remote:
            print(f"FATAL: 시드 자원 부족 col={col} mcp={bool(mcp_srv)} remote={bool(remote)}")
            return 2

        res = {
            "collection": col,
            "mcp_server": mcp_srv["name"],
            "mcp_tool": "delete_record",
            "agent_id": remote["agentId"],
            "agent_name": remote["name"],
        }
        print(f"[setup] collection={col} mcp={mcp_srv['name']}/delete_record "
              f"remote_agent={remote['name']}({remote['agentId']}) backend={os.environ['MEMORY_BACKEND']}")
        print(f"[setup] consumes={json.dumps(consumes, ensure_ascii=False)}")

        # --- 직접-memory 백엔드 가용성 프로브(SKIP 판정) ---
        direct_mem_ok = False
        probe_id = None
        try:
            probe_id = await _mk(c, "default", "memprobe", {
                "model": "mock-llm", "persona": "probe", "historyDepth": 6, "memories": [LONG_TERM_MEMORY],
            })
            sig = _signals(await _chat_direct_memory(c, probe_id))
            direct_mem_ok = sig["memories"] > 0
        finally:
            if probe_id:
                await c.delete(f"/agents/{probe_id}")
        print(f"[setup] 직접-memory 회상 가용={direct_mem_ok} "
              f"(불가 시 default/plan_execute/route + memory 발동칸 SKIP)")

        # --- 48칸 순회 ---
        for impl in IMPLS:
            for kind in KINDS:
                fire = expected_fire(impl, kind)
                surface = wiring_surface(impl, kind)
                # 인프라 게이트: 직접-memory 발동칸은 백엔드 필요.
                if fire and surface == "memories" and not direct_mem_ok:
                    checks.append((impl, kind, SKIP, "memory 백엔드/기본모델 미가용(mem_cfg None) — 직접 회상 불가"))
                    continue
                cfg = cell_config(impl, kind, res)
                prompt = cell_prompt(impl, kind, res)
                aid = None
                try:
                    aid = await _mk(c, impl, kind, cfg)
                    if surface == "memories":
                        txt = await _chat_direct_memory(c, aid)
                    else:
                        txt = await _chat(c, aid, prompt)
                    sig = _signals(txt)
                    if fire:
                        marker, detail = assert_fire(impl, kind, sig, res)
                    else:
                        marker, detail = assert_ignore(impl, kind, sig, consumes)
                except Exception as exc:  # noqa: BLE001 — 셀 예외는 FAIL로 표면화(하네스 견고)
                    marker, detail = FAIL, f"예외 {type(exc).__name__}: {exc}"
                finally:
                    if aid:
                        await c.delete(f"/agents/{aid}")
                checks.append((impl, kind, marker, detail))
                print(f"  [{impl:>18} × {kind:<8}] {marker:<9} {detail}")

        # --- 위양성 대조군: 능력 0개 에이전트는 어떤 발동 신호도 없어야(false-green 방어) ---
        # 전 impl(artifact 포함)에 대해 돈다 — 특히 **memory 인과 대조**: 메모리 스토어에 콘텐츠가
        # 있어도(앞 셀 프라이밍) config.memories가 없으면 회상 0이어야(codex 2차 지적3 — 회상 발동은
        # 공유 콘텐츠 누수가 아니라 config.memories 배선이 원인임을 증명). recall은 memory_enabled(
        # config.memories) 게이트라 무배선=무회상.
        print("\n[negative controls — 능력 0개 에이전트는 발동 신호 0(memory 인과 대조 포함)]")
        neg_prompt = "레코드 rec-001 삭제 검색 등산 장기 기억 저장 doc-translator"
        for impl in IMPLS:
            cfg = {"model": "mock-llm", "persona": "대조군", "historyDepth": 6}
            if impl != "default":
                cfg["impl"] = impl
            if impl in ARTIFACT_IMPLS:
                cfg["artifactSpec"] = {"fields": [{"key": "x", "label": "X"}]}
            aid = None
            try:
                aid = await _mk(c, impl, "none", cfg)
                sig = _signals(await _chat(c, aid, neg_prompt))
                if _any_fire(sig):
                    marker, detail = FAIL, f"능력 0개인데 발동 신호! {sig}"
                else:
                    marker, detail = PASS, "발동 신호 0(위양성 없음)"
            except Exception as exc:  # noqa: BLE001
                marker, detail = FAIL, f"예외 {type(exc).__name__}: {exc}"
            finally:
                if aid:
                    await c.delete(f"/agents/{aid}")
            checks.append((f"[ctl]{impl}", "—", marker, detail))
            print(f"  [{impl:>18} × control ] {marker:<9} {detail}")

    # ------------------------------------------------------------------ 결과 그리드
    print("\n" + "=" * 78)
    print("결과 그리드 (impl 행 × 능력 열)")
    grid = {(i, k): m for (i, k, m, _) in checks if not i.startswith("[ctl]")}
    head = "impl \\ kind".ljust(20) + "".join(k.ljust(11) for k in KINDS)
    print(head)
    print("-" * len(head))
    for impl in IMPLS:
        row = impl.ljust(20)
        for kind in KINDS:
            row += (grid.get((impl, kind), "?")).ljust(11)
        print(row)

    # ------------------------------------------------------------------ 요약
    from collections import Counter

    tally = Counter(m for (_, _, m, _) in checks)
    print("\n요약: " + " | ".join(f"{k}={v}" for k, v in sorted(tally.items())))
    fails = [(i, k, d) for (i, k, m, d) in checks if m == FAIL]
    skips = [(i, k, d) for (i, k, m, d) in checks if m == SKIP]
    if skips:
        print("\nSKIP 상세:")
        for i, k, d in skips:
            print(f"  - {i} × {k}: {d}")
    if fails:
        print("\nFAIL 상세(발동 기대≠관측 — 제품 결함 후보 또는 하네스 버그):")
        for i, k, d in fails:
            print(f"  - {i} × {k}: {d}")

    ok = not fails
    print("\n" + ("VERIFY233_OK" if ok else f"VERIFY233_FAIL({len(fails)})"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))

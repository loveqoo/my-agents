"""suite- 픽스처 멱등 부트스트랩 (스펙 288).

원칙:
- **이름 기준 get-or-update**: 픽스처 정의(config)의 해시를 description에 박아, 같으면 재사용·
  다르면 삭제 후 재생성. 필드별 비교 대신 해시 비교 — API 응답 필드 매핑 drift에 안 흔들린다.
- **seed 비결합**(learning 045): seed 데이터(local-tools, docs-kb)는 읽기만, 변경하지 않는다.
  suite가 소유하는 것은 suite- 접두 에이전트·suite-kb 컬렉션·SUITE- 토큰 기억뿐.
- 반환 counts(created/reused/recreated)로 멱등성을 측정한다(2회차 created+recreated=0이 완료 기준 3).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

import httpx

# 고유 토큰 — 실모델 비결정성 속에서 기록·회상 단언의 앵커.
KB_NAME = "suite-kb"
FACT_TOKEN = "SUITE-FACT-ALPHA-7743"
FACT_DOC = (
    f"회사 표준 배포 코드네임은 {FACT_TOKEN} 입니다. "
    "이 문서는 조합 시나리오 스위트(스펙 288)의 검색 픽스처로, 위 코드네임은 이 문서에만 존재합니다.\n"
    "보조 사실: 스위트의 기본 리트라이 횟수는 1회이며, 단언은 기록 기반으로만 수행합니다."
)
PREF_TOKEN = "SUITE-PREF-LATTE-9182"
PREF_MEMORY = f"사용자의 커피 취향은 {PREF_TOKEN} (오트 라떼)이다."

# 스위트 principal — 세션 소유권·기억 스코프(user_id)가 이 id로 흐른다.
SUITE_USER = uuid.UUID("00000288-0000-0000-0000-000000000288")

MEM_LONG = "장기 기억 (mem0)"  # seed MemoryType 이름(단일 출처: api/seed.py)
TOOL_ECHO = "local-tools__echo"
TOOL_SEARCH = "local-tools__web_search"
TOOL_DELETE = "local-tools__delete_record"  # 승인 필요(HIL)

PROMPT = (
    "당신은 기능 테스트 도우미입니다. 간결한 한국어로 답하세요. "
    "도구 사용을 지시받으면 반드시 그 도구를 호출한 뒤 결과를 요약하세요."
)


def _hash(cfg: dict) -> str:
    return hashlib.sha256(json.dumps(cfg, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]


def doc_tool(collection: str) -> str:
    """노드 문서 도구 이름 — admin safeToolName('search_documents', name)과 동일 규칙."""
    return f"search_documents__{collection}"


def pick_from(ms: list[dict]) -> tuple[dict, dict]:
    """실모델(chat, embedding) 선택 — 순수 함수(프리플라이트 단위 검증 대상, 시나리오 #31).
    provider_kind != mock, 기본값 우선. SUITE_CHAT_MODEL/SUITE_EMBED_MODEL 환경변수로 고정.
    없으면 RuntimeError(프리플라이트가 exit 2로 번역)."""
    import os

    real = [m for m in ms if m.get("provider_kind") != "mock"]

    def _pick(kind: str, env: str) -> dict:
        want = os.environ.get(env)
        pool = [m for m in real if m["kind"] == kind]
        if want:
            hit = [m for m in pool if m["name"] == want]
            if not hit:
                raise RuntimeError(f"{env}={want} 모델이 등록돼 있지 않습니다(kind={kind}).")
            return hit[0]
        pool.sort(key=lambda m: not m["is_default"])  # 기본값 우선
        if not pool:
            raise RuntimeError(f"실모델(kind={kind}, provider_kind != mock)이 없습니다 — 모델을 등록하세요.")
        return pool[0]

    return _pick("chat", "SUITE_CHAT_MODEL"), _pick("embedding", "SUITE_EMBED_MODEL")


async def pick_models(c: httpx.AsyncClient) -> tuple[dict, dict]:
    return pick_from((await c.get("/models")).json())


async def ensure_collection(c: httpx.AsyncClient, embed_model: dict, _retry: bool = True) -> dict:
    """suite-kb 컬렉션 get-or-create + 고유 토큰 문서 인제스트 + **검색 실증**.

    codex 288 #5: chunk_count>0만 믿으면 낡은 컬렉션(다른 임베더·다른 문서)이 초록을 위장한다.
    실제 검색으로 FACT_TOKEN 히트를 확인하고, 임베더 불일치·검색 미스면 삭제 후 1회 재생성.
    이 검색이 실 임베딩 추론 1회를 겸한다(codex #9 — 임베딩 딥 핑)."""
    cols = (await c.get("/collections")).json()
    col = next((x for x in cols if x["name"] == KB_NAME), None)
    if col is not None and str(col.get("embedding_model_id") or "") not in ("", str(embed_model["id"])):
        await c.delete(f"/collections/{col['id']}")
        col = None
    if col is None:
        r = await c.post("/collections", json={
            "name": KB_NAME,
            "description": "스펙 288 조합 스위트 검색 픽스처 (자동 생성 — 삭제해도 부트스트랩이 복원)",
            "embedding_model_id": str(embed_model["id"]),
        })
        r.raise_for_status()
        col = r.json()
    if not col.get("chunk_count"):
        r = await c.post(
            f"/collections/{col['id']}/documents",
            files={"file": ("suite-facts.txt", FACT_DOC.encode(), "text/plain")},
        )
        r.raise_for_status()
        col = (await c.get(f"/collections/{col['id']}")).json()
    sr = await c.post(f"/collections/{col['id']}/search", json={"query": "회사 표준 배포 코드네임"})
    hits = (sr.json() or {}).get("results") if sr.status_code == 200 else None
    if not any(FACT_TOKEN in (h.get("text") or "") for h in (hits or [])):
        if not _retry:
            raise RuntimeError(f"suite-kb 검색 실증 실패(재생성 후에도) — hits={hits!r}")
        await c.delete(f"/collections/{col['id']}")
        return await ensure_collection(c, embed_model, _retry=False)
    return col


async def ensure_memory_seed() -> str:
    """suite 유저 스코프에 고유 토큰 기억을 심는다(이미 있으면 스킵) — in-process 공유 코어 사용.
    반환: 'seeded' | 'reused'."""
    from api import memory
    from api.db import SessionLocal
    from api.memory_routes import _user_mem_cfg

    scope = {"user_id": str(SUITE_USER)}
    async with SessionLocal() as db:
        mem_cfg = await _user_mem_cfg(db)
    existing = memory.list_memories(scope, mem_cfg)
    # 오염 정리(codex 288 #8): 채팅 자동 추출(infer)이 회차마다 suite 유저 기억을 불린다 —
    # 시드 토큰 외 기억을 지워 회차 간 독립 기준선을 복원(suite 전용 user 스코프라 안전).
    for m in existing:
        if PREF_TOKEN not in (m.get("text") or "") and m.get("id"):
            memory.delete_memory(m["id"], mem_cfg)
    if any(PREF_TOKEN in (m.get("text") or "") for m in existing):
        return "reused"
    # infer=False — 이미 정제된 한 줄 사실(스펙 029 저작 경로와 동일). 실패는 조용히 무시되므로
    # 심은 뒤 재조회로 실제 저장을 확인한다(빈 초록 방지).
    memory.add(scope, [{"role": "user", "content": PREF_MEMORY}], mem_cfg, infer=False)
    after = memory.list_memories(scope, mem_cfg)
    if not any(PREF_TOKEN in (m.get("text") or "") for m in after):
        raise RuntimeError("기억 픽스처 저장 실패 — mem0 백엔드가 준비되지 않았습니다(프리플라이트 확인).")
    return "seeded"


async def _ensure_agent(c: httpx.AsyncClient, name: str, cfg: dict, counts: dict, *, serve: bool = False) -> dict:
    """이름으로 찾고 config 해시가 같으면 재사용, 다르면 삭제 후 재생성.

    serve=True면 v1을 활성화해 서빙 상태로 만든다 — 로컬 위임(브로커) 후보는 활성 버전 보유가
    조건(broker.py 스펙 256: 초안-only는 후보 아님. 실측 — 이 게이트에 걸려 위임 0이던 함정)."""
    h = _hash(cfg)
    marker = f"suite fixture(스펙 288) — 자동 생성, cfg={h}"
    agents = (await c.get("/agents")).json()
    hit = next((a for a in agents if a.get("name") == name), None)
    if hit is not None:
        # 해시 마커 + 핵심 필드 실측(codex 288 #6) — 마커만 믿으면 마커를 보존한 채 config가
        # 바뀐 경우(수동 편집 등)를 재사용한다. 완전 방어(전 필드 대조)는 개인 환경 과투자라
        # model/impl 두 축만 실측(불일치=재생성).
        fresh = (
            hit.get("description") == marker
            and hit.get("model") == cfg.get("model")
            and (hit.get("impl") or "") == (cfg.get("impl") or "")
        )
        if fresh:
            if serve and not hit.get("activeVersion"):
                await c.post(f"/agents/{hit['id']}/activate", json={"version": "v1"})
                hit = (await c.get(f"/agents/{hit['id']}")).json()
            counts["reused"] += 1
            return hit
        await c.delete(f"/agents/{hit['id']}")
        counts["recreated"] += 1
    else:
        counts["created"] += 1
    r = await c.post("/agents", json={"name": name, "description": marker, "config": cfg})
    r.raise_for_status()
    made = r.json()
    if serve:
        rr = await c.post(f"/agents/{made['id']}/activate", json={"version": "v1"})
        rr.raise_for_status()
        made = rr.json()
    return made


async def ensure_all(c: httpx.AsyncClient) -> dict[str, Any]:
    """픽스처 전부 보장. 반환: {agents: {별칭: AgentOut}, chat_model, embed_model, collection, counts}."""
    counts = {"created": 0, "reused": 0, "recreated": 0}
    chat_m, embed_m = await pick_models(c)
    col = await ensure_collection(c, embed_m)
    mem_state = await ensure_memory_seed()

    model = chat_m["name"]
    base = {"model": model, "prompt": PROMPT, "historyDepth": 20}
    agents: dict[str, dict] = {}

    # serve=True: 조율형 위임 대상은 활성 버전 보유(서빙 중)가 조건(스펙 256).
    agents["direct"] = await _ensure_agent(c, "suite-direct", {
        **base,
        "mcps": ["local-tools"],
        "tools": [TOOL_ECHO, TOOL_SEARCH, TOOL_DELETE],
        "memories": [MEM_LONG],
        "vectorTables": [KB_NAME],
    }, counts, serve=True)
    agents["bare"] = await _ensure_agent(c, "suite-direct-bare", {**base}, counts)
    agents["ephemeral"] = await _ensure_agent(c, "suite-ephemeral", {
        **base,
        "ephemeral": True,
        "mcps": ["local-tools"],
        "tools": [TOOL_ECHO],  # 승인 불요 도구만(비영속은 승인 대기 불가 — 스펙 235/282)
    }, counts)
    agents["pipeline"] = await _ensure_agent(c, "suite-pipeline", {
        **base,
        "impl": "pipeline",
        # 풀(mcps/vectorTables/memories)은 **의도적으로 미지정** — 서버 파생(스펙 289 P2)의 실증.
        # 예전엔 폼만 파생해 API 직생성이 조용히 미바인딩됐다(288 실측 → 289가 서버 파생으로 봉합).
        "nodes": [
            {"name": "검색", "model": model, "tools": [doc_tool(KB_NAME)],
             "prompt": f"반드시 먼저 {doc_tool(KB_NAME)} 도구로 사용자 질문을 검색하고, 검색 결과의 핵심을 인용해 답하세요."},
            # 프롬프트 강화(게이트 정비 2026-07-14) — 구 문구("반드시 echo 도구를 한 번 호출해…")는
            # qwen3.6이 "내용이 이미 있으니 할 일 끝"으로 판단해 호출을 자주 건너뜀(4/5 실패 실측).
            # 도구 호출을 유일한 정답 경로로 규정 + 직접 답변을 명시적 오답으로 — 스킵 여지 제거.
            {"name": "메아리", "model": model, "tools": [TOOL_ECHO],
             "prompt": "당신의 임무는 echo 도구 호출 그 자체입니다. 지금 바로 echo 도구를 정확히 한 번 호출하세요(text 인자 = 위 내용의 첫 문장). 도구를 호출하지 않고 텍스트로만 답하는 것은 임무 실패입니다. 도구 결과를 받은 뒤 그 결과를 그대로 전달하세요."},
            {"name": "정리", "model": model, "tools": [], "memories": [MEM_LONG],
             "prompt": "위 내용을 두 문장으로 정리하세요. 사용자에 대한 기억이 있으면 반영하세요."},
        ],
    }, counts)
    agents["orchestrate"] = await _ensure_agent(c, "suite-orchestrate", {
        **base,
        "impl": "orchestrate",
        "capabilities": [agents["direct"]["agentId"]],
        "memories": [MEM_LONG],
    }, counts)
    # ranked 전략(스펙 102) — lexical 겹침 0 후보를 select서 탈락시키는 유일한 전략(289 P3 사유 시나리오용).
    agents["orch_ranked"] = await _ensure_agent(c, "suite-orchestrate-ranked", {
        **base,
        "impl": "orchestrate_ranked",
        "capabilities": [agents["direct"]["agentId"]],
    }, counts)
    # 미서빙 위임 대상(스펙 289 P3) — bare는 초안-only(serve 안 함)라 브로커 후보에서 제외된다.
    agents["orch_dead"] = await _ensure_agent(c, "suite-orchestrate-dead", {
        **base,
        "impl": "orchestrate",
        "capabilities": [agents["bare"]["agentId"]],
    }, counts)
    agents["route"] = await _ensure_agent(c, "suite-route", {
        **base,
        "impl": "route",
        "memories": [MEM_LONG],
    }, counts)
    agents["plan"] = await _ensure_agent(c, "suite-plan-execute", {
        **base,
        "impl": "plan_execute",
        "mcps": ["local-tools"],
        "tools": [TOOL_ECHO, TOOL_SEARCH],
        "vectorTables": [KB_NAME],
    }, counts)

    return {
        "agents": agents,
        "chat_model": chat_m,
        "embed_model": embed_m,
        "collection": col,
        "memory": mem_state,
        "counts": counts,
    }

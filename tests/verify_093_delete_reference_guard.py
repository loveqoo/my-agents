"""verify_093 — 연결된 에이전트가 있으면 MCP 서버·RAG 컬렉션 삭제/rename 차단 (스펙 093).

검증 ①(단위 시맨틱): references.config_names(가드·런타임 단일 normalizer)·_config_has(멤버십)·
  referenced_message(string detail·where 라벨·action·길이상한).
검증 ②(실 DB 통합, 자기 픽스처 learning 045): 실 SessionLocal로 에이전트/서버/컬렉션을 만들고
  엔드포인트 함수를 직접 호출 —
    - 활성(Agent.config) 참조 → 409 where=active (T1·T5)
    - 비-서빙 버전(draft) 참조 → 409 where=version (T2)
    - archived 버전 참조 → 409 (T3) — codex 교정: activate_version이 archived 롤백 허용(agents.py:225)
      이므로 archived도 롤백 가능한 live 참조, 삭제 시 부활 방지 차단
    - 미참조 → 삭제 성공(T4·T6), 참조 해제 후 삭제 성공(T7) — 자가-잠금 대칭 핀
    - 참조중 rename → 409 (T8, operation-symmetry 형제 입구), name 동일 update는 허용(T9, 과잉차단 아님)
  MCP·컬렉션 둘 다(operation-symmetry, learning 050). 픽스처는 _TAG로 정리.

전제: DB 마이그레이션 적용됨(SessionLocal 연결 가능). API 서버 실행 불요(엔드포인트 함수 직접 호출).
실행: uv run python tests/verify_093_delete_reference_guard.py
(적대는 codex — 5건 적발분 반영 완료. 단위 술어 + 실 DB 통합 비겹침.)
"""

import asyncio
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))

from fastapi import HTTPException  # noqa: E402

from api import blocks, crypto, rag, references  # noqa: E402
from api.db import SessionLocal  # noqa: E402
from api.models import (  # noqa: E402
    Agent,
    AgentVersion,
    Collection,
    McpServer,
    ModelConfig,
    Provider,
)

_fails: list[str] = []
_TAG = "_verify093"  # 픽스처 식별 접두사(정리용)

passed = 0


def check(cond: bool, msg: str) -> None:
    global passed
    print(("  ok  " if cond else " FAIL ") + msg)
    if cond:
        passed += 1
    else:
        _fails.append(msg)


# ─────────────────────────── ① 단위: config_names / _config_has ───────────────────────────
def unit_config_has() -> None:
    print("① 단위 — references.config_names (가드·런타임 단일 normalizer, codex P2)")
    cn = references.config_names
    check(cn({"mcps": ["a", "b"]}, "mcps") == ["a", "b"], "list[str] 그대로")
    check(cn({"mcps": {"a": True}}, "mcps") == [], "dict field → [](런타임도 참조 아님으로 접음)")
    check(cn({"mcps": "a"}, "mcps") == [], "스칼라 field → []")
    check(cn(None, "mcps") == [], "config None → []")
    check(cn({"mcps": ["a", 1, None, "b"]}, "mcps") == ["a", "b"], "비-str 원소 걸러냄")

    print("① 단위 — references._config_has")
    ch = references._config_has
    check(ch({"mcps": ["a", "b"]}, "mcps", "b") is True, "배열에 있으면 True")
    check(ch({"mcps": ["a", "b"]}, "mcps", "c") is False, "배열에 없으면 False")
    check(ch({"mcps": []}, "mcps", "a") is False, "빈 배열 False")
    check(ch({}, "mcps", "a") is False, "필드 없음 False")
    check(ch(None, "mcps", "a") is False, "config None fail-safe False")
    check(ch({"mcps": "a"}, "mcps", "a") is False, "스칼라(리스트 아님) False — 부분매칭 방지")
    check(ch({"mcps": ["ab"]}, "mcps", "a") is False, "부분문자열 매칭 안 함(정확 멤버십)")

    print("① 단위 — references.referenced_message (string detail, 062 계약)")
    rm = references.referenced_message
    msg = rm([{"agent": "Weather Bot", "where": "active"},
              {"agent": "Old Bot", "where": "version"}], "MCP 서버")
    check(isinstance(msg, str), "detail은 dict 아닌 string(httpError는 string만 노출)")
    check("Weather Bot(활성)" in msg, "active → '이름(활성)'")
    check("Old Bot(버전)" in msg, "version → '이름(버전)' (usedBy 배지와 어긋나는 차단 설명)")
    check("2개 에이전트" in msg, "참조 개수 포함")
    check("MCP 서버" in msg, "자원 명사 포함")
    check("삭제할 수 없습니다" in msg, "기본 action=삭제")
    rmsg = rm([{"agent": "X", "where": "active"}], "MCP 서버", action="이름 변경")
    check("이름 변경할 수 없습니다" in rmsg, "action=이름 변경(rename 가드 공용)")

    # 메시지 길이 상한(codex P2): 25개 참조 → 20개 나열 + "외 5개"
    many = [{"agent": f"A{i}", "where": "active"} for i in range(25)]
    mmsg = rm(many, "MCP 서버")
    check("외 5개" in mmsg, "20개 초과 시 '외 M개'로 축약")
    check("25개 에이전트" in mmsg, "총 개수는 실제값 유지")
    check(mmsg.count("(활성)") == 20, "나열은 최대 20개")


# ─────────────────────── 픽스처 정리 ───────────────────────
async def _cleanup(s) -> None:
    from sqlalchemy import delete, select

    # 에이전트(+버전 cascade), 컬렉션, 서버, 모델, 프로바이더 — _TAG 접두사만.
    for agent in (await s.execute(select(Agent).where(Agent.name.like(f"{_TAG}%")))).scalars():
        await s.delete(agent)
    for col in (await s.execute(select(Collection).where(Collection.name.like(f"{_TAG}%")))).scalars():
        await s.delete(col)
    for mc in (await s.execute(select(McpServer).where(McpServer.name.like(f"{_TAG}%")))).scalars():
        await s.delete(mc)
    await s.commit()
    for m in (await s.execute(select(ModelConfig).where(ModelConfig.name.like(f"{_TAG}%")))).scalars():
        await s.delete(m)
    await s.commit()
    for p in (await s.execute(select(Provider).where(Provider.name.like(f"{_TAG}%")))).scalars():
        await s.delete(p)
    await s.commit()


async def _expect_409(coro, label: str):
    """엔드포인트 호출이 409를 던지는지. detail *문자열* 반환. 실패 시 None."""
    try:
        await coro
        check(False, f"{label} — 409 기대했으나 통과함(삭제됨!)")
        return None
    except HTTPException as e:
        check(e.status_code == 409, f"{label} — 409 (got {e.status_code})")
        check(isinstance(e.detail, str), f"{label} — detail은 string(062 계약, httpError 노출)")
        return e.detail if isinstance(e.detail, str) else None


# ─────────────────────── ② 실 DB 통합 ───────────────────────
async def integration() -> None:
    print("② 실 DB 통합 — 삭제 가드")
    async with SessionLocal() as s:
        await _cleanup(s)

        # 픽스처: MCP 서버 3(active참조/draft참조/archived참조), 컬렉션 1(active참조),
        #        embedding 모델 체인, 에이전트 3.
        srv_active = McpServer(name=f"{_TAG}_srv_active", source="local", transport="http",
                               url="http://127.0.0.1:9/mcp")
        srv_draft = McpServer(name=f"{_TAG}_srv_draft", source="local", transport="http",
                              url="http://127.0.0.1:9/mcp")
        srv_arch = McpServer(name=f"{_TAG}_srv_arch", source="local", transport="http",
                             url="http://127.0.0.1:9/mcp")
        srv_free = McpServer(name=f"{_TAG}_srv_free", source="local", transport="http",
                             url="http://127.0.0.1:9/mcp")
        s.add_all([srv_active, srv_draft, srv_arch, srv_free])

        prov = Provider(name=f"{_TAG}_prov", protocol="openai-compatible",
                        base_url="http://127.0.0.1:8000/_remote/v1",
                        api_key=crypto.encrypt("sk-noauth"), kind="mock")
        s.add(prov)
        await s.commit()
        await s.refresh(prov)
        emb = ModelConfig(name=f"{_TAG}_emb", provider_id=prov.id, model_id="mock-embed",
                          kind="embedding")
        s.add(emb)
        await s.commit()
        await s.refresh(emb)
        col_ref = Collection(name=f"{_TAG}_col_ref", description="", embedding_model_id=emb.id,
                             dims=8, status="empty")
        col_free = Collection(name=f"{_TAG}_col_free", description="", embedding_model_id=emb.id,
                              dims=8, status="empty")
        s.add_all([col_ref, col_free])
        await s.commit()
        for o in (srv_active, srv_draft, srv_arch, srv_free, col_ref, col_free):
            await s.refresh(o)

        # 에이전트 A: 활성 config가 srv_active + col_ref 참조.
        agent_a = Agent(agent_id=f"agt_{_TAG}_a", name=f"{_TAG}_agent_active",
                        config={"mcps": [srv_active.name], "vectorTables": [col_ref.name]},
                        active_version="v1")
        agent_a.versions.append(AgentVersion(version="v1", status="active",
                                             config={"mcps": [srv_active.name],
                                                     "vectorTables": [col_ref.name]}))
        # 에이전트 B: 활성 config는 비었고 *draft* 버전만 srv_draft 참조(활성화 전 잠복).
        agent_b = Agent(agent_id=f"agt_{_TAG}_b", name=f"{_TAG}_agent_draft",
                        config={"mcps": [], "vectorTables": []}, active_version="v1")
        agent_b.versions.append(AgentVersion(version="v1", status="active", config={"mcps": []}))
        agent_b.versions.append(AgentVersion(version="v2", status="draft",
                                             config={"mcps": [srv_draft.name]}))
        # 에이전트 C: archived 버전만 srv_arch 참조 → 삭제 막으면 안 됨(음성).
        agent_c = Agent(agent_id=f"agt_{_TAG}_c", name=f"{_TAG}_agent_arch",
                        config={"mcps": []}, active_version="v2")
        agent_c.versions.append(AgentVersion(version="v1", status="archived",
                                             config={"mcps": [srv_arch.name]}))
        agent_c.versions.append(AgentVersion(version="v2", status="active", config={"mcps": []}))
        s.add_all([agent_a, agent_b, agent_c])
        await s.commit()
        for o in (srv_active, srv_draft, srv_arch, srv_free, col_ref, col_free):
            await s.refresh(o)

        # ── T1. 활성 참조 MCP 삭제 → 409, where=active ──
        d = await _expect_409(blocks.delete_mcp_server(srv_active.id, s), "T1 활성참조 MCP 삭제")
        if d is not None:
            check(f"{agent_a.name}(활성)" in d,
                  f"T1 메시지에 active 참조 에이전트(활성) 정확(got {d!r})")

        # ── T2. draft-only(비-서빙 버전) 참조 MCP 삭제 → 409, where=version ──
        d = await _expect_409(blocks.delete_mcp_server(srv_draft.id, s), "T2 draft참조 MCP 삭제")
        if d is not None:
            check(f"{agent_b.name}(버전)" in d,
                  f"T2 메시지에 버전 참조 에이전트(버전) 정확(got {d!r})")

        # ── T3. archived-only 참조 MCP 삭제 → 409(차단) ──
        # codex 적대리뷰로 교정: activate_version이 archived 롤백을 허용(agents.py:225)하므로
        # archived 참조도 삭제하면 롤백 순간 dead ref가 된다 → live 참조로 취급, 삭제 차단.
        d = await _expect_409(blocks.delete_mcp_server(srv_arch.id, s), "T3 archived참조 MCP 삭제")
        if d is not None:
            check(f"{agent_c.name}(버전)" in d,
                  f"T3 archived 참조도 차단(롤백 가능 → live), where=version(got {d!r})")

        # ── T4. 미참조 MCP 삭제 → 성공(자가-잠금 대칭 핀) ──
        try:
            await blocks.delete_mcp_server(srv_free.id, s)
            check(await s.get(McpServer, srv_free.id) is None, "T4 미참조 서버 삭제 성공(가드 과잉 아님)")
        except HTTPException as e:
            check(False, f"T4 미참조 서버 삭제가 막힘(과잉차단!) status={e.status_code}")

        # ── T5. 활성 참조 컬렉션 삭제 → 409 (operation-symmetry: RAG도 동일) ──
        d = await _expect_409(rag.delete_collection(col_ref.id, s), "T5 활성참조 컬렉션 삭제")
        if d is not None:
            check(f"{agent_a.name}(활성)" in d and "RAG 컬렉션" in d,
                  f"T5 컬렉션 메시지 정확(got {d!r})")

        # ── T6. 미참조 컬렉션 삭제 → 성공 ──
        try:
            await rag.delete_collection(col_free.id, s)
            check(await s.get(Collection, col_free.id) is None, "T6 미참조 컬렉션 삭제 성공")
        except HTTPException as e:
            check(False, f"T6 미참조 컬렉션 삭제가 막힘(과잉차단!) status={e.status_code}")

        # ── T7. 참조 해제 후 삭제 성공 (해제→삭제 경로) ──
        agent_a.config = {"mcps": [], "vectorTables": []}
        # active 버전도 갱신(그대로 두면 여전히 참조 — 실제 해제는 config+활성버전 동시)
        for v in agent_a.versions:
            if v.status == "active":
                v.config = {"mcps": [], "vectorTables": []}
        await s.commit()
        try:
            await blocks.delete_mcp_server(srv_active.id, s)
            check(await s.get(McpServer, srv_active.id) is None, "T7 참조 해제 후 MCP 삭제 성공")
        except HTTPException as e:
            check(False, f"T7 해제 후에도 삭제 막힘 status={e.status_code}")

        # ── T8. 참조 중인 MCP rename → 409 (operation-symmetry: 삭제와 형제 입구) ──
        # srv_draft는 agent_b의 v2 draft가 여전히 참조(T2에서 삭제 차단됨). name을 바꾸면 옛 name이
        # config에 dangling으로 남아 런타임이 조용히 도구를 잃는다 → rename도 409로 차단.
        from sqlalchemy import select as _sel

        from api.schemas import McpServerIn

        # rollback이 ORM 객체를 expire시키므로 id/name을 plain 값으로 먼저 캡처(재로드 방지).
        draft_id = srv_draft.id
        draft_name = srv_draft.name
        rename_body = McpServerIn(name=f"{_TAG}_srv_draft_RENAMED", source="local",
                                  transport="http", url="http://127.0.0.1:9/mcp")
        try:
            await blocks.update_mcp_server(draft_id, rename_body, s)
            check(False, "T8 참조중 MCP rename이 통과함(가드 누락!)")
        except HTTPException as e:
            check(e.status_code == 409, f"T8 참조중 MCP rename → 409 (got {e.status_code})")
            check(isinstance(e.detail, str) and "이름 변경할 수 없습니다" in e.detail,
                  f"T8 rename 차단 메시지(이름 변경) 정확(got {e.detail!r})")
        await s.rollback()  # 실패한 rename 트랜잭션 정리

        # ── T9. 같은 name으로 update(rename 아님) → 가드 통과(과잉차단 아님) ──
        # srv_draft를 원래 name 그대로 두고 다른 필드만 갱신 → new_name==obj.name이라 가드 스킵.
        same_body = McpServerIn(name=draft_name, source="local", transport="http",
                                url="http://127.0.0.1:9/mcp/v2")
        try:
            await blocks.update_mcp_server(draft_id, same_body, s)
            new_url = (
                await s.execute(_sel(McpServer.url).where(McpServer.id == draft_id))
            ).scalar_one()
            check(new_url.endswith("/v2"),
                  "T9 name 동일 update는 참조 있어도 허용(rename만 차단)")
        except HTTPException as e:
            check(False, f"T9 name 동일 update가 막힘(과잉차단!) status={e.status_code}")

        await _cleanup(s)


async def main() -> None:
    unit_config_has()
    await integration()
    print(f"\n{passed} passed, {len(_fails)} failed")
    if _fails:
        for f in _fails:
            print("  ✗", f)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

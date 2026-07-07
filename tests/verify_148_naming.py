"""verify_148 — 네이밍 규칙 + 식별 이름/별명 분리 (스펙 148).

  V1 검증기/slugify 순수 함수 표본(허용/거부/변환).
  V2 에이전트: 생성 위반 400 · 정상+별명 201 · 중복 409 · rename 위반 400 · description 비우기.
  V3 복제: 식별 이름 자동(-copy, 규칙 준수·유니크, 스펙 217) + 설명 "(복사본)".
  V4 코드 등록(원격 유래): 거부 대신 자동 변환 + 원문 별명 보존.
  V5 컬렉션/페르소나/권한/MCP: 생성 위반 400 · 정상+별명 저장 · (페르소나) rename 위반 400.
  V6 마이그레이션 후 불변식: 5테이블 전량 규칙 준수 + config 참조(신규 dangling 0).
  V7 참조 가드(codex 148 High/Medium): 페르소나·권한 rename/삭제 409 + 조율형 capabilities로만
     참조된 MCP rename 409.
실행: uv run --project packages/api --env-file .env python tests/verify_148_naming.py
"""
import asyncio
import json
import os
import re
import sys
import uuid as _uuid

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "packages", "api", "src"))

from fastapi import HTTPException  # noqa: E402
from sqlalchemy import select, text  # noqa: E402

from api.db import SessionLocal as async_session  # noqa: E402
from api import agents as AG  # noqa: E402
from api import blocks as BL  # noqa: E402
from api import rag as RG  # noqa: E402
from api.models import Agent, Collection, McpServer, Persona  # noqa: E402
from api.naming import NAME_RE, slugify_name, validate_resource_name  # noqa: E402
from api.schemas import AgentCreate, AgentConfig, AgentUpdate, CollectionIn, McpServerIn, PersonaIn, RegisterCodeAgentIn  # noqa: E402

_fails = []
passed = 0


def check(cond, msg):
    global passed
    print(("  ok  " if cond else " FAIL ") + msg)
    if cond:
        passed += 1
    else:
        _fails.append(msg)


class _P:
    def __init__(self, uid, superuser=True):
        self.id = uid
        self.is_superuser = superuser


async def main():
    from api.authz import init_authz
    await init_authz()
    admin = _P(_uuid.uuid4())
    tag = f"v148-{_uuid.uuid4().hex[:6]}"
    made = {"agents": [], "personas": [], "collections": [], "mcp": []}

    # ---- V1 순수 함수 ----
    check(validate_resource_name("obsidian-manager") is None, "V1a 영소문자+대시 허용")
    check(validate_resource_name("rag-docs-01") is None, "V1b 영소문자+숫자+대시 허용")
    # 스펙 217(사용자 지시): 한글·마침표 거부. 이전 규칙(한글·마침표 허용)에서 좁힘.
    check(validate_resource_name("옵시디언-매니저") is not None, "V1c 한글 거부(스펙 217)")
    for bad in ("My Agent", "doc_translator", "Docs", "옵시디언 매니저", "a.b-c1", "rag.docs", "", "  "):
        check(validate_resource_name(bad) is not None, f"V1d 거부: {bad!r}")
    check(slugify_name("Doc Translator") == "doc-translator", "V1e slugify 공백·대문자")
    check(slugify_name("옵시디언 매니저") == "unnamed", "V1f slugify 한글 전탈락→영문 fallback(스펙 217)")
    check(slugify_name("docs_kb") == "docs-kb", "V1g slugify 밑줄")
    check(slugify_name("Acme Translate (A2A)") == "acme-translate-a2a", "V1h slugify 특수문자 제거")
    check(NAME_RE.match(slugify_name("!!!")) is not None, "V1i 전탈락도 규칙 준수 fallback")

    try:
        # ---- V2 에이전트 ----
        async with async_session() as s:
            try:
                await AG.create_agent(AgentCreate(name=f"{tag} bad name", config=AgentConfig()), session=s, principal=admin)
                check(False, "V2a 위반 이름 생성 → 400이어야")
            except HTTPException as e:
                check(e.status_code == 400, f"V2a 위반 이름 생성 400 (got {e.status_code})")
        async with async_session() as s:
            out = await AG.create_agent(
                AgentCreate(name=f"{tag}-agent", description="검증용 에이전트", config=AgentConfig()),
                session=s, principal=admin)
            made["agents"].append(out.id)
            check(out.name == f"{tag}-agent" and out.description == "검증용 에이전트", "V2b 정상 생성 + 별명 저장")
        async with async_session() as s:
            try:
                await AG.create_agent(AgentCreate(name=f"{tag}-agent", config=AgentConfig()), session=s, principal=admin)
                check(False, "V2c 중복 식별 이름 → 409이어야")
            except HTTPException as e:
                check(e.status_code == 409, f"V2c 중복 이름 409 (got {e.status_code})")
        async with async_session() as s:
            try:
                await AG.update_agent(made["agents"][0], AgentUpdate(name="Bad Rename", config=AgentConfig()),
                                      session=s, principal=admin)
                check(False, "V2d rename 위반 → 400이어야")
            except HTTPException as e:
                check(e.status_code == 400, f"V2d rename 위반 400 (got {e.status_code})")
        async with async_session() as s:
            out = await AG.update_agent(made["agents"][0], AgentUpdate(name=None, description="", config=AgentConfig()),
                                        session=s, principal=admin)
            check(out.description is None, "V2e description=''로 별명 비우기")

        # ---- V3 복제 ----
        async with async_session() as s:
            out = await AG.update_agent(made["agents"][0], AgentUpdate(name=None, description="원본 별명", config=AgentConfig()),
                                        session=s, principal=admin)
        async with async_session() as s:
            clone = await AG.clone_agent(made["agents"][0], session=s, principal=admin)
            made["agents"].append(clone.id)
            check(NAME_RE.match(clone.name) is not None and clone.name.startswith(f"{tag}-agent-copy"),
                  f"V3a 복제 식별 이름 규칙 준수(스펙 217: 영문 '-copy' 접미): {clone.name!r}")
            check(clone.description == "원본 별명 (복사본)", f"V3b 복제 별명: {clone.description!r}")
        async with async_session() as s:
            clone2 = await AG.clone_agent(made["agents"][0], session=s, principal=admin)
            made["agents"].append(clone2.id)
            check(clone2.name != clone.name, f"V3c 복제 이름 유니크 dedupe: {clone2.name!r}")

        # ---- V4 코드 등록(원격 유래 자동 변환) ----
        async with async_session() as s:
            out = await AG.register_code_agent(
                RegisterCodeAgentIn(name=f"{tag.upper()} SDK Agent", endpoint="http://127.0.0.1:9",
                                    token="tk", model="", persona="", memories=[], mcps=[],
                                    historyDepth=10, runtime="", repo="", commit=""),
                session=s, principal=admin)
            made["agents"].append(out.id)
            check(NAME_RE.match(out.name) is not None, f"V4a 원격 유래 자동 변환: {out.name!r}")
            check(out.description == f"{tag.upper()} SDK Agent", "V4b 원문은 별명 보존")

        # ---- V5 나머지 4종 ----
        async with async_session() as s:
            try:
                await RG.create_collection(CollectionIn(name="Bad Col", embedding_model_id=_uuid.uuid4()),
                                           session=s, principal=admin)
                check(False, "V5a 컬렉션 위반 → 400이어야")
            except HTTPException as e:
                check(e.status_code == 400 and "규칙" in str(e.detail), f"V5a 컬렉션 위반 400 (got {e.status_code})")
        async with async_session() as s:
            try:
                await BL.create_persona(PersonaIn(name="Bad Persona"), session=s)
                check(False, "V5b 페르소나 위반 → 400이어야")
            except HTTPException as e:
                check(e.status_code == 400, f"V5b 페르소나 위반 400 (got {e.status_code})")
        async with async_session() as s:
            p = await BL.create_persona(PersonaIn(name=f"{tag}-persona", description="검증 페르소나"), session=s)
            made["personas"].append(p.id)
            check(p.name == f"{tag}-persona" and p.description == "검증 페르소나", "V5c 페르소나 정상+별명")
        async with async_session() as s:
            try:
                await BL.update_persona(made["personas"][0], PersonaIn(name="Renamed Bad"), session=s)
                check(False, "V5d 페르소나 rename 위반 → 400이어야")
            except HTTPException as e:
                check(e.status_code == 400, f"V5d 페르소나 rename 위반 400 (got {e.status_code})")
        async with async_session() as s:
            # 이름 유지 + 본문만 수정은 grandfather(규칙 검사 없음) — 기존 위반 이름도 편집 가능해야 한다
            p2 = await BL.update_persona(made["personas"][0], PersonaIn(name=f"{tag}-persona", body="b2"), session=s)
            check(p2.body == "b2", "V5e 이름 유지 편집은 통과(grandfather)")
        async with async_session() as s:
            try:
                await BL.create_mcp_server(McpServerIn(name="Bad MCP"), session=s, principal=admin)
                check(False, "V5h MCP 위반 → 400이어야")
            except HTTPException as e:
                check(e.status_code == 400, f"V5h MCP 위반 400 (got {e.status_code})")
        async with async_session() as s:
            m = await BL.create_mcp_server(McpServerIn(name=f"{tag}-mcp", description="검증 MCP"), session=s, principal=admin)
            made["mcp"].append(_uuid.UUID(str(m.id)))
            check(m.description == "검증 MCP", "V5i MCP 정상+별명")

        # ---- V7 참조 가드(codex 148) — 참조 에이전트를 만들어 rename/삭제 409 확인 ----
        async with async_session() as s:
            ref_agent = Agent(
                agent_id=f"{tag}-ref", name=f"{tag}-ref",
                config={"persona": f"{tag}-persona",
                        "mcps": [], "vectorTables": [], "capabilities": [f"mcp:{tag}-mcp/some-tool"]},
            )
            s.add(ref_agent)
            await s.commit()
            made["agents"].append(ref_agent.id)
        async with async_session() as s:
            try:
                await BL.update_persona(made["personas"][0], PersonaIn(name=f"{tag}-persona2"), session=s)
                check(False, "V7a 참조 중 페르소나 rename → 409이어야")
            except HTTPException as e:
                check(e.status_code == 409, f"V7a 참조 중 페르소나 rename 409 (got {e.status_code})")
        async with async_session() as s:
            try:
                await BL.delete_persona(made["personas"][0], session=s)
                check(False, "V7b 참조 중 페르소나 삭제 → 409이어야")
            except HTTPException as e:
                check(e.status_code == 409, f"V7b 참조 중 페르소나 삭제 409 (got {e.status_code})")
        async with async_session() as s:
            # mcps는 비고 capabilities("mcp:{서버}/{툴}")로만 참조 — 가드가 이 축도 봐야 한다
            try:
                await BL.update_mcp_server(made["mcp"][0], McpServerIn(name=f"{tag}-mcp2"),
                                           session=s, principal=admin)
                check(False, "V7e capabilities 참조 MCP rename → 409이어야")
            except HTTPException as e:
                check(e.status_code == 409, f"V7e capabilities 참조 MCP rename 409 (got {e.status_code})")
        # 참조 에이전트 제거 후 rename은 통과해야(가드가 과차단이 아님을 핀)
        async with async_session() as s:
            a = await s.get(Agent, made["agents"][-1])
            await s.delete(a)
            await s.commit()
            made["agents"].pop()
        async with async_session() as s:
            p2 = await BL.update_persona(made["personas"][0], PersonaIn(name=f"{tag}-persona2"), session=s)
            check(p2.name == f"{tag}-persona2", "V7f 참조 해제 후 rename 통과(자가-잠금 아님)")

        # ---- V6 마이그레이션 후 불변식(실 DB 전량) ----
        async with async_session() as s:
            for model, label in ((Persona, "personas"), (Collection, "collections"),
                                 (McpServer, "mcp_servers"), (Agent, "agents")):
                names = (await s.execute(select(model.name))).scalars().all()
                bad = [n for n in names if not NAME_RE.match(n or "")]
                check(not bad, f"V6 {label} 전량 규칙 준수 (위반 {bad[:3]})")
            # 신규 dangling 0: 마이그레이션 이전부터의 잔재(team_notes·product_titles)만 허용
            cols = set((await s.execute(select(Collection.name))).scalars().all())
            mcps = set((await s.execute(select(McpServer.name))).scalars().all())
            legacy_ok = {"team_notes", "product_titles"}
            dangling = []
            for name, cfg in (await s.execute(select(Agent.name, Agent.config))).all():
                cfg = cfg if isinstance(cfg, dict) else json.loads(cfg or "{}")
                for x in cfg.get("vectorTables") or []:
                    if x not in cols and x not in legacy_ok:
                        dangling.append((name, x))
                for x in cfg.get("mcps") or []:
                    if x not in mcps:
                        dangling.append((name, x))
                for c in cfg.get("capabilities") or []:
                    if isinstance(c, str) and c.startswith("rag:") and c[4:] not in cols:
                        dangling.append((name, c))
            check(not dangling, f"V6 config 참조 무결(신규 dangling 0) {dangling[:3]}")
    finally:
        # 청소 — 검증 생성물 제거
        async with async_session() as s:
            for aid in made["agents"]:
                a = await s.get(Agent, aid)
                if a is not None:
                    await s.delete(a)
            for pid in made["personas"]:
                p = await s.get(Persona, pid)
                if p is not None:
                    await s.delete(p)
            for mid in made["mcp"]:
                m = await s.get(McpServer, mid)
                if m is not None:
                    await s.delete(m)
            await s.commit()

    print(f"\n{passed} passed, {len(_fails)} failed")
    if _fails:
        sys.exit(1)


asyncio.run(main())

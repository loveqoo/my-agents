"""초기 시드 — 어드민 UI mock 데이터를 실 DB에 적재 (테이블이 비어있을 때만).

admin/src/admin/mockData.ts 와 동일한 도메인 데이터. 실서비스 첫 기동 시 화면이
빈 상태가 아니라 의미있는 데이터로 채워지도록 한다.
"""

import os

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from . import crypto

from .models import (
    RAG_EMBED_DIMS,
    Agent,
    AgentVersion,
    Approval,
    BatchConfig,
    Collection,
    McpServer,
    MemoryType,
    ModelConfig,
    Permission,
    Persona,
    Provider,
    Session,
)

# 등록되는 기본 chat 모델명 — ModelConfig와 에이전트 참조를 단일 소스로 묶어
# 둘이 어긋나지 않게 한다(스펙 023). 가상 모델명(claude-*/gpt-*) 금지.
CHAT_MODEL_NAME = "qwen3.6-35b"

PERSONAS = [
    ("Methodical Researcher", "전문적, 차분함", "Rigorous, source-driven, neutral. Prefer primary sources. Always cite. Lead with a one-line answer."),
    ("Strict Senior Engineer", "단호함, 공감적", "Direct, specific, kind. Flag correctness and security first, style last. Cite exact line numbers."),
    ("Calm SRE", "차분함", "Unflappable. Quantify before acting. Smallest safe step first. Confirm blast radius."),
    ("Warm Secretary", "친근함, 열정적", "Friendly, concise, proactive. Protect the user's time and focus. Confirm before sending."),
]

# 카탈로그는 실제 동작과 1:1로 맞춘다(스펙 020). 인지과학 분류(의미/일화/절차)는 mem0 기능이 아니라
# 데모 카탈로그였고, 백엔드는 단 두 메커니즘만 구현한다: 인-컨텍스트 윈도우(mem0 아님)와 mem0 장기 메모리.
# mem0 장기 메모리의 스코프(유저/세션)는 요청 userId 유무로 자동 결정되므로 별도 토글로 두지 않는다.
MEMORY_TYPES = [
    ("단기(세션)", "단기(세션)", "In-context · mem0 아님",
     "현재 세션의 인-컨텍스트 윈도우(historyDepth) — 최근 N턴만 모델에 전달하는 컨텍스트 절단입니다. "
     "mem0 저장소가 아니며 세션이 끝나면 사라집니다."),
    ("장기 기억 (mem0)", "장기 기억 (mem0)", "Auto · userId 유무로 결정",
     "mem0 장기 메모리. 켜면 대화에서 사실을 추출·저장하고 매 턴 의미적으로 유사한 top-k를 회상합니다. "
     "스코프는 요청 userId로 자동 결정 — userId가 있으면 유저 단위(세션 가로지름)와 세션에 함께 저장하고, "
     "없으면 현재 세션에만 저장합니다."),
]

# RAG 컬렉션 시드(스펙 036) — 이름은 AGENTS의 vectorTables 참조와 일치(usedBy 집계용).
# 차원은 임베딩 모델에 맞춰 RAG_EMBED_DIMS로 고정. 빈(empty) 상태로 생성 — 문서는 업로드로 채운다.
# (name, description, embed_model_name) — embed_model_name이 있으면 그 모델에 바인딩,
# None이면 기본 임베딩 모델(MLX). docs_kb만 mock-embed에 묶어 라이브 MLX 없이 결정적으로 샘플을
# 적재·검색하는 *대표 데모* 컬렉션으로 쓴다(스펙 048 #9). 나머지 3개는 실데이터 대기 플레이스홀더.
COLLECTIONS = [
    ("docs_kb", "헬프센터 문서 본문 지식베이스 — RAG 답변에 사용(샘플 적재됨, 스펙 048).", "mock-embed"),
    ("product_titles", "상품 title 임베딩 — 상품 의미 검색·추천. 문서를 업로드해 채웁니다.", None),
    ("support_tickets", "과거 지원 티켓 요약 — 유사 사례 검색. 문서를 업로드해 채웁니다.", None),
    ("team_notes", "팀 노션 노트 — 내부 지식 의미 검색. 문서를 업로드해 채웁니다.", None),
]


def _collection_seed_specs(embs, collections=COLLECTIONS):
    """게이트(스펙 048): 컬렉션 시드 스펙 (name, description, embedding_model_id) 목록.

    embedding 모델이 하나도 없으면 빈 리스트 → 컬렉션 시드 자체를 스킵한다("임베딩 모델 설정이
    있는 경우만"). 있으면 각 컬렉션의 embed_model_name으로 매칭하고, 못 찾으면 기본 모델
    (is_default 우선, 없으면 첫 번째)에 바인딩한다. embs 원소는 .name/.is_default/.id를 갖는
    ModelConfig(또는 동형 객체) — 그래서 DB 없이도 게이트를 단위 검증할 수 있다.
    """
    # 방어(적대 리뷰 048): 호출자가 kind 필터를 빼먹어도 컬렉션이 chat 모델에 바인딩되지 않게
    # 헬퍼 안에서도 embedding만 남긴다. .kind가 없는 동형 객체는 통과(단위 테스트 편의).
    embs = [m for m in embs if getattr(m, "kind", "embedding") == "embedding"]
    if not embs:
        return []
    by_name = {m.name: m for m in embs}
    default_emb = next((m for m in embs if m.is_default), embs[0])
    return [(n, d, (by_name.get(em) or default_emb).id) for n, d, em in collections]

# 순수 웹 에이전트 플랫폼 — 파일/터미널/repo/k8s 권한은 쓰지 않으므로 카탈로그에서 제외(스펙 046).
# 코드 에이전트가 아니라 웹에서 동작하는 에이전트이기 때문(UI 피드백 #4).
PERMISSIONS = [
    ("web.search", "Network", "user", "Outbound web search via the configured provider."),
    ("calendar.rw", "Productivity", "user", "Read & write calendar events. Writes are confirmed inline by the user."),
    ("mail.send", "Productivity", "user", "Send email on the user's behalf. Each send is confirmed inline by the user."),
]

# name, source, transport, url, endpoint, tools, status, published, auth
# 코드/인프라 MCP(filesystem·github·prometheus·kubernetes)는 아직 미구현이고 웹 에이전트에
# 불필요하므로 카탈로그에서 제외(스펙 046, UI 피드백 #5). HIL 게이트 메커니즘(스펙 041
# runtime._APPROVAL_ACTIONS)은 정책으로 보존 — 카탈로그에 트리거 도구가 없을 뿐.
MCP_SERVERS = [
    ("tavily", "local", "stdio", None, "mcp://my-agents.local/tavily", ["search"], "connected", True, None),
    ("gcal", "local", "http", None, "mcp://my-agents.local/gcal", ["list", "create"], "connected", False, None),
    ("gmail", "local", "http", None, "mcp://my-agents.local/gmail", ["search"], "disconnected", False, None),
    ("notion", "local", "http", None, "mcp://my-agents.local/notion", ["append"], "connected", True, None),
    ("acme-weather", "external", "http", "mcp://acme.io/weather", None, ["forecast", "current"], "connected", False, "Bearer ****"),
    ("partner-crm", "external", "http", "mcp://partner.example.com/crm", None, ["lookup", "create_lead"], "degraded", False, "OAuth"),
]

# agent_id, name, source, model, persona, memories, historyDepth, vectorTables, permissions, mcps, a2a, status, activeVersion, versions[(version,status,createdAt,note)]
AGENTS = [
    # 코드/인프라 권한·MCP 제거(스펙 046)에 맞춰 web.search/tavily만 유지.
    ("agt_rsch_7f3a91", "Research Assistant", "ui", CHAT_MODEL_NAME, "Methodical Researcher",
     ["단기(세션)", "장기 기억 (mem0)"], 20, ["docs_kb", "product_titles"], ["web.search"], ["tavily"],
     True, "online", "v3",
     [("v3", "active", "2026-06-12", "Tightened citation rules"), ("v2", "archived", "2026-06-04", "Web search tuning"), ("v1", "archived", "2026-05-30", "Initial")]),
    # Code Reviewer·Ops Copilot(코드/인프라 권한 전용 데모)는 에이전트째 제거(스펙 046, UI 피드백 #4).
    ("agt_sec_9d4417", "Personal Secretary", "ui", CHAT_MODEL_NAME, "Warm Secretary",
     ["단기(세션)", "장기 기억 (mem0)"], 40, ["team_notes"], ["calendar.rw", "mail.send"], ["gcal", "gmail", "notion"],
     False, "online", "v2",
     [("v2", "active", "2026-06-16", "Warmer tone"), ("v1", "archived", "2026-06-15", "Initial")]),
]

# sessions: session_id, agent_id(agt_), agent_name, channel, status, turns, tokens
# sess-6c93(Code Reviewer)은 에이전트 제거(스펙 046)와 함께 삭제 — 유지 에이전트 세션만 남긴다.
SESSIONS = [
    ("sess-8f21", "agt_rsch_7f3a91", "Research Assistant", "debug-console", "active", 6, 18420),
    ("sess-7a05", "agt_rsch_7f3a91", "Research Assistant", "A2A · partner-x", "idle", 14, 52110),
    ("sess-5d77", "agt_sec_9d4417", "Personal Secretary", "web-chat", "error", 2, 3110),
    ("sess-4b10", "agt_rsch_7f3a91", "Research Assistant", "web-chat", "completed", 21, 74300),
]

# 시드 승인 데모는 repo.merge·k8s.write(제거 권한) + Code Reviewer·Ops Copilot(제거 에이전트)에
# 묶여 있었으므로 제거(스펙 046). HIL 게이트 메커니즘(041)은 runtime 정책으로 보존 — 카탈로그에
# 트리거 도구가 없어 발화하지 않을 뿐. 미래 웹 액션이 추가되면 게이트가 그대로 재사용된다.
APPROVALS: list = []


async def _empty(session: AsyncSession, model) -> bool:
    count = await session.scalar(select(func.count()).select_from(model))
    return (count or 0) == 0


async def seed_if_empty(session: AsyncSession) -> None:
    """각 카탈로그가 비어있으면 시드. 부분 시드 가능(독립적)."""
    persona_body = {name: body for name, _tone, body in PERSONAS}

    if await _empty(session, Persona):
        session.add_all([Persona(name=n, tone=t, body=b) for n, t, b in PERSONAS])
    if await _empty(session, MemoryType):
        session.add_all([MemoryType(key=k, name=n, scope=s, body=b) for k, n, s, b in MEMORY_TYPES])
    if await _empty(session, Permission):
        session.add_all([Permission(name=n, scope=sc, approver=ap, body=b) for n, sc, ap, b in PERMISSIONS])
    if await _empty(session, McpServer):
        session.add_all([
            McpServer(name=n, source=src, transport=tr, url=url, endpoint=ep,
                      tools=list(tools), enabled_tools=list(tools), status=st, published=pub, auth=auth)
            for n, src, tr, url, ep, tools, st, pub, auth in MCP_SERVERS
        ])

    if await _empty(session, Provider):
        base_url = os.environ.get("MLX_BASE_URL", "http://localhost:8045/v1")
        api_key = os.environ.get("MLX_API_KEY")
        chat_id = os.environ.get("MLX_MODEL", "mlx-community/Qwen3.6-35B-A3B-mxfp8")
        embed_id = os.environ.get("MLX_EMBED_MODEL", "mlx-community/multilingual-e5-large-mlx")
        # mock chat provider — 라이브 MLX 없이 결정적 실행용(스펙 024). base_url은 **이 API 자신의**
        # OpenAI 호환 mock 엔드포인트(self-call). API를 다른 호스트/포트로 옮기면 MOCK_LLM_BASE_URL로
        # 그 자기주소를 맞춰준다. REMOTE_AGENT_BASE(코드 에이전트 배포)와는 의미가 다른 별개 env다.
        mock_base = os.environ.get("MOCK_LLM_BASE_URL", "http://127.0.0.1:8000/_remote/v1")
        # provider 1회 등록 → 하위 모델이 base_url/api_key 상속(스펙 035).
        mlx_provider = Provider(
            name="MLX (local)", protocol="openai-compatible", base_url=base_url,
            api_key=crypto.encrypt(api_key),
            kind="local", description="실제 로컬 MLX 서버",
        )
        mock_provider = Provider(
            name="Mock LLM", protocol="openai-compatible", base_url=mock_base,
            api_key=crypto.encrypt("sk-noauth"),
            kind="mock", description="라이브 없이 결정적 테스트용 내장 목(스펙 024)",
        )
        session.add_all([mlx_provider, mock_provider])
        await session.flush()  # provider id 확보(모델 FK용)
        session.add_all([
            ModelConfig(
                name=CHAT_MODEL_NAME, provider_id=mlx_provider.id, model_id=chat_id,
                kind="chat", is_default=True,
                params={"temperature": 0.7, "enable_thinking": False},
            ),
            ModelConfig(
                name="multilingual-e5-large", provider_id=mlx_provider.id, model_id=embed_id,
                kind="embedding", is_default=True, params={},
            ),
            ModelConfig(
                name="mock-llm", provider_id=mock_provider.id, model_id="mock-chat",
                kind="chat", is_default=False, params={},
            ),
            # mock 임베딩 모델(스펙 024 철학) — `/_remote/v1/embeddings`가 RAG_EMBED_DIMS 차원
            # 벡터를 입력 1건당 1개 반환 → 라이브 MLX 없이 RAG 인제스트가 결정적으로 통과한다.
            ModelConfig(
                name="mock-embed", provider_id=mock_provider.id, model_id="mock-embed",
                kind="embedding", is_default=False, params={},
            ),
        ])

    if await _empty(session, Collection):
        # 임베딩 모델에 맞춰 컬렉션 생성(차원 고정). 같은 트랜잭션의 시드 모델을 flush로 가시화.
        await session.flush()
        embs = (
            await session.execute(
                select(ModelConfig).where(ModelConfig.kind == "embedding")
            )
        ).scalars().all()
        # 게이트(스펙 048)는 _collection_seed_specs로 분리 — DB 없이 단위 테스트 가능.
        session.add_all([
            Collection(name=n, description=d, embedding_model_id=mid, dims=RAG_EMBED_DIMS, status="empty")
            for n, d, mid in _collection_seed_specs(embs)
        ])

    if await _empty(session, Agent):
        for (aid, name, source, model, persona, mems, hist, vts, perms, mcps, a2a, status, active, versions) in AGENTS:
            cfg = {
                "model": model, "persona": persona, "memories": list(mems),
                "vectorTables": list(vts), "permissions": list(perms), "mcps": list(mcps),
                "historyDepth": hist,
            }
            agent = Agent(
                agent_id=aid, name=name, source=source, model=model,
                persona=persona_body.get(persona, persona), history_depth=hist,
                config=cfg, exposed={"a2a": a2a}, status=status, active_version=active,
            )
            for (ver, vstatus, created, note) in versions:
                agent.versions.append(
                    AgentVersion(version=ver, status=vstatus, note=note, config=dict(cfg))
                )
            session.add(agent)

        # 코드 정의(SDK 배포) 에이전트 — UI mock과 동일하게 1개 시드.
        code_cfg = {
            "model": CHAT_MODEL_NAME, "persona": "코드 정의 (SDK)", "memories": ["단기(세션)"],
            "vectorTables": [], "permissions": ["web.search"], "mcps": ["tavily"],
            "historyDepth": 10,
        }
        translator = Agent(
            agent_id="agt_xlt_a17c33", name="Doc Translator", source="code", model=CHAT_MODEL_NAME,
            persona="코드 정의 (SDK)", history_depth=10, config=code_cfg, exposed={"a2a": True},
            status="online", active_version="f3a91c2",
            # 개발용 mock 원격 에이전트로 연결 → 코드 에이전트 원격 실행이 바로 동작.
            # 실제 배포는 자기 URL을 쓴다(REMOTE_AGENT_BASE로 오버라이드 가능).
            endpoint=os.environ.get("REMOTE_AGENT_BASE", "http://127.0.0.1:8000/_remote/agent"),
            token=crypto.encrypt("sk_live_demo_doc_translator_a17c33"),
            runtime="my-agents-sdk · Python 2.4.1", repo="acme/doc-translator", commit="f3a91c2",
            registered_at="2026-06-18", last_sync="12분 전",
        )
        translator.versions.append(
            AgentVersion(version="f3a91c2", status="active", note="Deploy · 용어집 조회 추가", config=dict(code_cfg))
        )
        translator.versions.append(
            AgentVersion(version="9b22d01", status="archived", note="Deploy · 초기 배포", config=dict(code_cfg))
        )
        session.add(translator)

        # 외부(A2A) 에이전트 시드 — 카드 스냅샷 하드코딩(네트워크 self-call 없이 어드민에서
        # 3분기 source 배지/카드 패널을 바로 시연). 실제 등록은 POST /agents/external 경유(026).
        ext_card = {
            "name": "Acme Translate (A2A)",
            "description": "외부 조직이 A2A로 공개한 번역 에이전트(시드 스냅샷).",
            "url": "https://agents.acme.example/translate/a2a",
            "version": "2.1.0",
            "provider": {"organization": "Acme", "url": "https://acme.example"},
            "capabilities": {"streaming": True, "pushNotifications": False},
            "defaultInputModes": ["text/plain"],
            "defaultOutputModes": ["text/plain"],
            "skills": [
                {"id": "translate", "name": "문서 번역", "description": "문서를 대상 언어로 번역",
                 "tags": ["translation", "i18n"]},
            ],
        }
        external = Agent(
            agent_id="agt_ext_ac2e01", name=ext_card["name"], source="external", model="",
            persona="", history_depth=10,
            config={"model": "", "persona": "", "memories": [], "vectorTables": [],
                    "permissions": [], "mcps": [], "historyDepth": 10, "card": ext_card},
            exposed={"a2a": False}, status="online",
            endpoint=ext_card["url"], token=None,
            registered_at="2026-06-26", last_sync="방금",
        )
        session.add(external)

    if await _empty(session, Session):
        # agent_pk 연결을 위해 먼저 flush 필요 — 시드 에이전트가 같은 트랜잭션에 있을 수 있음
        await session.flush()
        agents_by_aid = {
            a.agent_id: a for a in (await session.execute(select(Agent))).scalars().all()
        }
        for (sid, aid, aname, channel, status, turns, tokens) in SESSIONS:
            a = agents_by_aid.get(aid)
            if a is None:
                continue
            session.add(Session(
                session_id=sid, agent_pk=a.id, agent_name=aname,
                channel=channel, status=status, turns=turns, tokens=tokens,
            ))

    if await _empty(session, BatchConfig):
        # 배치 설정 싱글톤 1행(스펙 038) — 값은 NULL(보존창·cron 비활성). 운영자가 명시 설정 전엔
        # 아무 것도 자동 삭제·발화하지 않는다(보수적 기본값).
        session.add(BatchConfig())

    if await _empty(session, Approval):
        await session.flush()
        agents_by_aid = {
            a.agent_id: a for a in (await session.execute(select(Agent))).scalars().all()
        }
        for (apid, sid, aid, aname, perm, action, args, summary, ckpt) in APPROVALS:
            a = agents_by_aid.get(aid)
            session.add(Approval(
                approval_id=apid, session_id=sid, agent_pk=a.id if a else None,
                agent_name=aname, permission=perm, action=action, args=args,
                summary=summary, checkpoint=ckpt, status="pending",
            ))

    await session.commit()

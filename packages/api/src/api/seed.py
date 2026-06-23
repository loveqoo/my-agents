"""초기 시드 — 어드민 UI mock 데이터를 실 DB에 적재 (테이블이 비어있을 때만).

admin/src/admin/mockData.ts 와 동일한 도메인 데이터. 실서비스 첫 기동 시 화면이
빈 상태가 아니라 의미있는 데이터로 채워지도록 한다.
"""

import os

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
    Agent,
    AgentVersion,
    Approval,
    McpServer,
    MemoryType,
    ModelConfig,
    Permission,
    Persona,
    Session,
    VectorTable,
)

PERSONAS = [
    ("Methodical Researcher", "Rigorous · neutral", "Rigorous, source-driven, neutral. Prefer primary sources. Always cite. Lead with a one-line answer."),
    ("Strict Senior Engineer", "Direct · kind", "Direct, specific, kind. Flag correctness and security first, style last. Cite exact line numbers."),
    ("Calm SRE", "Unflappable", "Unflappable. Quantify before acting. Smallest safe step first. Confirm blast radius."),
    ("Warm Secretary", "Friendly · proactive", "Friendly, concise, proactive. Protect the user's time and focus. Confirm before sending."),
]

MEMORY_TYPES = [
    ("단기(세션)", "단기(세션)", "Single session", "현재 세션의 인-컨텍스트 윈도우. 세션이 끝나면 비워집니다. 영속성 없음."),
    ("장기·의미론적", "장기·의미론적", "Cross-session", "벡터 스토어. 매 턴 전에 의미적으로 유사한 메모리 top-k를 검색합니다. TTL 없음."),
    ("장기·일화적", "장기·일화적", "Rolling window", "상호작용 이벤트 로그를 일 단위로 요약. 과거 대화·사건을 회상합니다."),
    ("절차적", "절차적", "Cross-session", "학습된 절차·선호·규칙을 누적. 반복 작업의 방법을 기억합니다."),
]

VECTOR_TABLES = [
    ("product_titles", "text-embedding-3-large", "products.title", 3072, 12840, "synced", "상품 테이블의 title 컬럼을 임베딩. 상품 의미 검색·추천에 사용."),
    ("docs_kb", "text-embedding-3-small", "help_articles.body", 1536, 3204, "synced", "헬프센터 문서 본문을 청크 단위로 임베딩한 지식베이스. RAG 답변에 사용."),
    ("support_tickets", "voyage-3", "tickets.summary", 1024, 58210, "indexing", "과거 지원 티켓 요약을 임베딩. 유사 사례 검색용. 현재 재색인 중."),
    ("team_notes", "nomic-embed-text", "notion.pages", 768, 941, "stale", "팀 노션 노트를 로컬 임베딩. 원본 변경분 미반영(stale) — 재동기화 필요."),
]

PERMISSIONS = [
    ("web.search", "Network", "user", "Outbound web search via the configured provider."),
    ("files.read", "Filesystem", "user", "Read-only access to whitelisted local paths."),
    ("repo.read", "Code", "user", "Read pull requests, files and diffs from connected repos."),
    ("k8s.read", "Infra", "user", "Read-only cluster + workload inspection."),
    ("calendar.rw", "Productivity", "user", "Read & write calendar events. Writes are confirmed inline by the user."),
    ("mail.send", "Productivity", "user", "Send email on the user's behalf. Each send is confirmed inline by the user."),
    ("repo.merge", "Code", "admin", "Merge pull requests. Routed to an admin for approval before execution."),
    ("k8s.write", "Infra", "admin", "Mutate cluster state (scale, restart, apply). Requires admin approval."),
]

# name, source, transport, url, endpoint, tools, status, published, auth
MCP_SERVERS = [
    ("tavily", "local", "stdio", None, "mcp://my-agents.local/tavily", ["search"], "connected", True, None),
    ("filesystem", "local", "stdio", None, "mcp://my-agents.local/filesystem", ["read", "list"], "connected", False, None),
    ("github", "local", "http", None, "mcp://my-agents.local/github", ["get_pr", "get_file"], "connected", True, None),
    ("prometheus", "local", "http", None, "mcp://my-agents.local/prometheus", ["query"], "connected", False, None),
    ("kubernetes", "local", "http", None, "mcp://my-agents.local/kubernetes", ["get"], "degraded", False, None),
    ("gcal", "local", "http", None, "mcp://my-agents.local/gcal", ["list", "create"], "connected", False, None),
    ("gmail", "local", "http", None, "mcp://my-agents.local/gmail", ["search"], "disconnected", False, None),
    ("notion", "local", "http", None, "mcp://my-agents.local/notion", ["append"], "connected", True, None),
    ("acme-weather", "external", "http", "mcp://acme.io/weather", None, ["forecast", "current"], "connected", False, "Bearer ****"),
    ("partner-crm", "external", "http", "mcp://partner.example.com/crm", None, ["lookup", "create_lead"], "degraded", False, "OAuth"),
]

# agent_id, name, source, model, persona, memories, historyDepth, vectorTables, permissions, mcps, a2a, status, activeVersion, versions[(version,status,createdAt,note)]
AGENTS = [
    ("agt_rsch_7f3a91", "Research Assistant", "ui", "claude-sonnet-4", "Methodical Researcher",
     ["단기(세션)", "장기·의미론적"], 20, ["docs_kb", "product_titles"], ["web.search", "files.read"], ["tavily", "filesystem"],
     True, "online", "v3",
     [("v3", "active", "2026-06-12", "Tightened citation rules"), ("v2", "archived", "2026-06-04", "Added filesystem MCP"), ("v1", "archived", "2026-05-30", "Initial")]),
    ("agt_rvw_2b91c4", "Code Reviewer", "ui", "gpt-4o", "Strict Senior Engineer",
     ["단기(세션)"], 10, [], ["repo.read", "repo.merge"], ["github", "filesystem"],
     True, "online", "v2",
     [("v3", "draft", "2026-06-19", "Trial: auto-merge on green CI"), ("v2", "active", "2026-06-09", "Added repo.merge (admin-gated)"), ("v1", "archived", "2026-06-02", "Initial")]),
    ("agt_ops_5c0833", "Ops Copilot", "ui", "claude-haiku-4", "Calm SRE",
     [], 6, [], ["k8s.read", "k8s.write"], ["prometheus", "kubernetes"],
     False, "idle", "v1",
     [("v1", "active", "2026-06-10", "Initial")]),
    ("agt_sec_9d4417", "Personal Secretary", "ui", "claude-sonnet-4", "Warm Secretary",
     ["단기(세션)", "장기·일화적", "절차적"], 40, ["team_notes"], ["calendar.rw", "mail.send"], ["gcal", "gmail", "notion"],
     False, "online", "v2",
     [("v2", "active", "2026-06-16", "Warmer tone"), ("v1", "archived", "2026-06-15", "Initial")]),
]

# sessions: session_id, agent_id(agt_), agent_name, channel, status, turns, tokens
SESSIONS = [
    ("sess-8f21", "agt_rsch_7f3a91", "Research Assistant", "debug-console", "active", 6, 18420),
    ("sess-7a05", "agt_rsch_7f3a91", "Research Assistant", "A2A · partner-x", "idle", 14, 52110),
    ("sess-6c93", "agt_rvw_2b91c4", "Code Reviewer", "github-webhook", "awaiting", 3, 9240),
    ("sess-5d77", "agt_sec_9d4417", "Personal Secretary", "web-chat", "error", 2, 3110),
    ("sess-4b10", "agt_rsch_7f3a91", "Research Assistant", "web-chat", "completed", 21, 74300),
]

APPROVALS = [
    ("apr-3391", "sess-6c93", "agt_rvw_2b91c4", "Code Reviewer", "repo.merge", "github.merge_pr",
     {"pr": 482, "repo": "my-agents", "strategy": "squash"}, "Merge PR #482 “Fix token refresh race” into main", "ckpt_6c93_07"),
    ("apr-3388", "sess-9d22", "agt_ops_5c0833", "Ops Copilot", "k8s.write", "kubernetes.scale",
     {"deployment": "api", "replicas": 8, "namespace": "prod"}, "Scale prod/api from 5 → 8 replicas", "ckpt_9d22_03"),
]


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
    if await _empty(session, VectorTable):
        session.add_all([
            VectorTable(name=n, model=m, source=src, dims=d, rows=r, status=st, body=b)
            for n, m, src, d, r, st, b in VECTOR_TABLES
        ])
    if await _empty(session, Permission):
        session.add_all([Permission(name=n, scope=sc, approver=ap, body=b) for n, sc, ap, b in PERMISSIONS])
    if await _empty(session, McpServer):
        session.add_all([
            McpServer(name=n, source=src, transport=tr, url=url, endpoint=ep,
                      tools=list(tools), enabled_tools=list(tools), status=st, published=pub, auth=auth)
            for n, src, tr, url, ep, tools, st, pub, auth in MCP_SERVERS
        ])

    if await _empty(session, ModelConfig):
        base_url = os.environ.get("MLX_BASE_URL", "http://localhost:8045/v1")
        api_key = os.environ.get("MLX_API_KEY")
        chat_id = os.environ.get("MLX_MODEL", "mlx-community/Qwen3.6-35B-A3B-mxfp8")
        embed_id = os.environ.get("MLX_EMBED_MODEL", "mlx-community/multilingual-e5-large-mlx")
        session.add_all([
            ModelConfig(
                name="qwen3.6-35b", provider="openai-compatible", base_url=base_url,
                api_key=api_key, model_id=chat_id, kind="chat", is_default=True,
                params={"temperature": 0.7, "enable_thinking": False},
            ),
            ModelConfig(
                name="multilingual-e5-large", provider="openai-compatible", base_url=base_url,
                api_key=api_key, model_id=embed_id, kind="embedding", is_default=True, params={},
            ),
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
            "model": "claude-sonnet-4", "persona": "코드 정의 (SDK)", "memories": ["단기(세션)"],
            "vectorTables": [], "permissions": ["web.search", "files.read"], "mcps": ["tavily"],
            "historyDepth": 10,
        }
        translator = Agent(
            agent_id="agt_xlt_a17c33", name="Doc Translator", source="code", model="claude-sonnet-4",
            persona="코드 정의 (SDK)", history_depth=10, config=code_cfg, exposed={"a2a": True},
            status="online", active_version="f3a91c2",
            endpoint="https://agents.acme.dev/doc-translator", token="sk_live_a3f••••••••91c2",
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

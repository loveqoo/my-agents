"""초기 시드 — 어드민 UI mock 데이터를 실 DB에 적재 (테이블이 비어있을 때만).

admin/src/admin/mockData.ts 와 동일한 도메인 데이터. 실서비스 첫 기동 시 화면이
빈 상태가 아니라 의미있는 데이터로 채워지도록 한다.
"""

import os

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from . import crypto
from .mock_mcp import MOCK_MCP_SERVER_NAME, MOCK_MCP_TOOLS, MOCK_MCP_TOOLS_META, MOCK_MCP_URL
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
    Persona,
    Provider,
    Session,
)
from .served_mcp import SERVED_MCP_TOOLS, SERVED_MCP_TOOLS_META, served_url

# 등록되는 기본 chat 모델명 — ModelConfig와 에이전트 참조를 단일 소스로 묶어
# 둘이 어긋나지 않게 한다(스펙 023). 기본은 Mock LLM(무외부 동작, 스펙 059) — 실 모델은
# admin Provider UI에서 추가하고 기본 전환한다. 가상 모델명(claude-*/gpt-*) 금지.
CHAT_MODEL_NAME = "mock-llm"

# (name=식별 이름·규칙 준수, description=설명, tone, body) — 스펙 148, 210. name은 config.persona 참조 키.
PERSONAS = [
    (
        "methodical-researcher",
        "Methodical Researcher",
        "전문적, 차분함",
        "Rigorous, source-driven, neutral. Prefer primary sources. Always cite. Lead with a one-line answer.",
    ),
    (
        "strict-senior-engineer",
        "Strict Senior Engineer",
        "단호함, 공감적",
        "Direct, specific, kind. Flag correctness and security first, style last. Cite exact line numbers.",
    ),
    (
        "calm-sre",
        "Calm SRE",
        "차분함",
        "Unflappable. Quantify before acting. Smallest safe step first. Confirm blast radius.",
    ),
    (
        "warm-secretary",
        "Warm Secretary",
        "친근함, 열정적",
        "Friendly, concise, proactive. Protect the user's time and focus. Confirm before sending.",
    ),
]

# 카탈로그는 실제 동작과 1:1로 맞춘다(스펙 020). 인지과학 분류(의미/일화/절차)는 mem0 기능이 아니라
# 데모 카탈로그였고, 백엔드는 단 두 메커니즘만 구현한다: 인-컨텍스트 윈도우(mem0 아님)와 mem0 장기 메모리.
# mem0 장기 메모리의 스코프(유저/세션)는 요청 userId 유무로 자동 결정되므로 별도 토글로 두지 않는다.
MEMORY_TYPES = [
    (
        "단기(세션)",
        "단기(세션)",
        "In-context · mem0 아님",
        "현재 세션의 인-컨텍스트 윈도우(historyDepth) — 최근 N턴만 모델에 전달하는 컨텍스트 절단입니다. "
        "mem0 저장소가 아니며 세션이 끝나면 사라집니다.",
    ),
    (
        "장기 기억 (mem0)",
        "장기 기억 (mem0)",
        "Auto · userId 유무로 결정",
        "mem0 장기 메모리. 켜면 대화에서 사실을 추출·저장하고 매 턴 의미적으로 유사한 top-k를 회상합니다. "
        "스코프는 요청 userId로 자동 결정 — userId가 있으면 유저 단위(세션 가로지름)와 세션에 함께 저장하고, "
        "없으면 현재 세션에만 저장합니다.",
    ),
]

# RAG 컬렉션 시드(스펙 036) — 이름은 AGENTS의 vectorTables 참조와 일치(usedBy 집계용).
# 차원은 임베딩 모델에 맞춰 RAG_EMBED_DIMS로 고정. 빈(empty) 상태로 생성 — 문서는 업로드로 채운다.
# (name, description, embed_model_name) — embed_model_name이 있으면 그 모델에 바인딩,
# None이면 기본 임베딩 모델(mock-embed, 스펙 059). docs_kb를 mock-embed에 묶어 라이브 모델 없이
# 결정적으로 샘플을 적재·검색하는 *대표 데모* 컬렉션으로 쓴다(스펙 048 #9). 나머지 3개는 실데이터 대기.
COLLECTIONS = [
    # 이름은 규칙 준수(스펙 148 — `_` 금지→`-`). AGENTS vectorTables 참조와 일치 유지.
    (
        "docs-kb",
        "헬프센터 문서 본문 지식베이스 — RAG 답변에 사용(샘플 적재됨, 스펙 048).",
        "mock-embed",
    ),
    ("product-titles", "상품 title 임베딩 — 상품 의미 검색·추천. 문서를 업로드해 채웁니다.", None),
    ("support-tickets", "과거 지원 티켓 요약 — 유사 사례 검색. 문서를 업로드해 채웁니다.", None),
    ("team-notes", "팀 노션 노트 — 내부 지식 의미 검색. 문서를 업로드해 채웁니다.", None),
]


def _collection_seed_specs(
    embs: list[ModelConfig],
    collections: list[tuple[str, str, str | None]] = COLLECTIONS,
) -> list[tuple]:
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
# name, source, transport, url, endpoint, tools, status, published, auth
# 이전엔 mcp:// 가짜 6행(tavily/gcal/gmail/notion/acme-weather/partner-crm)을 시드했는데, 그 URL은
# 연결 대상이 없어 런타임이 실제로 붙지 못했다(스펙 054 — 하드코딩/가짜 제거). 지금은 self-host
# 실 mock MCP 서버(mock_mcp.py, /_remote/mcp) 1행으로 대체 — 라이브 연결로 실제 도구를 노출한다.
# delete_record는 HIL 게이트(스펙 041 runtime._APPROVAL_ACTIONS, 키 (local-tools, delete_record))로
# 보호되어 카탈로그에 둬도 안전하다. 이름/URL은 mock_mcp 상수가 단일 출처(드리프트 방지, learning 025).
MCP_SERVERS = [
    (
        MOCK_MCP_SERVER_NAME,
        "local",
        "http",
        MOCK_MCP_URL,
        None,
        list(MOCK_MCP_TOOLS),
        "connected",
        True,
        None,
    ),
    # 커스텀(SDK) MCP(스펙 156, 실사용 #4) — 우리가 코드로 정의·호스팅해 서빙 가능한 MCP. 시드는
    # published=False(관리자가 드로어에서 켜면 /_served/mcp/calc-tools/로 외부 공개). source=custom이라
    # 서빙 게이트 통과 대상이고 external 봉인(152)과 구분된다. plan-execute-demo가 커스텀 에이전트
    # 실증인 것과 동형(커스텀 MCP 실증 시드 1행).
    (
        "calc-tools",
        "custom",
        "http",
        served_url("calc-tools"),
        None,
        list(SERVED_MCP_TOOLS["calc-tools"]),
        "connected",
        False,
        None,
    ),
]

# agent_id, name(식별·규칙), description(설명), source, model, persona, memories, historyDepth, vectorTables, mcps, a2a, status, activeVersion, versions[(version,status,createdAt,note)]
AGENTS = [
    # 코드/인프라 권한·MCP 제거(스펙 046)에 맞춰 web.search/tavily만 유지.
    (
        "agt_rsch_7f3a91",
        "research-assistant",
        "Research Assistant",
        "ui",
        CHAT_MODEL_NAME,
        "methodical-researcher",
        ["단기(세션)", "장기 기억 (mem0)"],
        20,
        ["docs-kb", "product-titles"],
        [MOCK_MCP_SERVER_NAME],
        True,
        "online",
        "v3",
        [
            ("v3", "active", "2026-06-12", "Tightened citation rules"),
            ("v2", "archived", "2026-06-04", "Web search tuning"),
            ("v1", "archived", "2026-05-30", "Initial"),
        ],
    ),
    # Code Reviewer·Ops Copilot(코드/인프라 권한 전용 데모)는 에이전트째 제거(스펙 046, UI 피드백 #4).
    (
        "agt_sec_9d4417",
        "personal-secretary",
        "Personal Secretary",
        "ui",
        CHAT_MODEL_NAME,
        "warm-secretary",
        ["단기(세션)", "장기 기억 (mem0)"],
        40,
        ["team-notes"],
        [MOCK_MCP_SERVER_NAME],
        False,
        "online",
        "v2",
        [
            ("v2", "active", "2026-06-16", "Warmer tone"),
            ("v1", "archived", "2026-06-15", "Initial"),
        ],
    ),
]

# sessions: session_id, agent_id(agt_), agent_name, channel, status, turns, tokens
# sess-6c93(Code Reviewer)은 에이전트 제거(스펙 046)와 함께 삭제 — 유지 에이전트 세션만 남긴다.
# turns/tokens는 0으로 진실화(스펙 056, learning 058): 이 데모 세션들은 Message 행을 심지 않으므로
# 실제 턴=0이다. 부풀린 카운터(turns=14 등)는 정리 배치가 빈 세션을 고턴으로 오인해 보존하게 만들었다.
# status·channel로 데모 다양성은 유지하되 카운터는 실제 행과 일치시킨다(빈 세션은 정직하게 0턴·정리대상).
SESSIONS = [
    ("sess-8f21", "agt_rsch_7f3a91", "research-assistant", "debug-console", "active", 0, 0),
    ("sess-7a05", "agt_rsch_7f3a91", "research-assistant", "A2A · partner-x", "idle", 0, 0),
    ("sess-5d77", "agt_sec_9d4417", "personal-secretary", "web-chat", "error", 0, 0),
    ("sess-4b10", "agt_rsch_7f3a91", "research-assistant", "web-chat", "completed", 0, 0),
]

# 시드 승인 데모는 repo.merge·k8s.write(제거 권한) + Code Reviewer·Ops Copilot(제거 에이전트)에
# 묶여 있었으므로 제거(스펙 046). HIL 게이트 메커니즘(041)은 runtime 정책으로 보존 — 카탈로그에
# 트리거 도구가 없어 발화하지 않을 뿐. 미래 웹 액션이 추가되면 게이트가 그대로 재사용된다.
APPROVALS: list = []


async def _empty(session: AsyncSession, model: type) -> bool:
    count = await session.scalar(select(func.count()).select_from(model))
    return (count or 0) == 0


def _seed_personas(session: AsyncSession) -> None:
    """PERSONAS 카탈로그를 행으로 적재."""
    session.add_all([Persona(name=n, description=d, tone=t, body=b) for n, d, t, b in PERSONAS])


def _seed_memory_types(session: AsyncSession) -> None:
    """MEMORY_TYPES 카탈로그를 행으로 적재."""
    session.add_all([MemoryType(key=k, name=n, scope=s, body=b) for k, n, s, b in MEMORY_TYPES])


def _seed_mcp_servers(session: AsyncSession) -> None:
    """MCP_SERVERS 카탈로그를 행으로 적재."""
    session.add_all(
        [
            McpServer(
                name=n,
                source=src,
                transport=tr,
                url=url,
                endpoint=ep,
                tools=list(tools),
                enabled_tools=list(tools),
                status=st,
                published=pub,
                auth=auth,
                # 도구 메타(스펙 151·156) — local-tools + 서빙 커스텀 MCP(calc-tools)가 정의 보유.
                tools_meta=(
                    MOCK_MCP_TOOLS_META
                    if n == MOCK_MCP_SERVER_NAME
                    else SERVED_MCP_TOOLS_META.get(n)
                ),
            )
            for n, src, tr, url, ep, tools, st, pub, auth in MCP_SERVERS
        ]
    )


async def _seed_mock_provider_models(session: AsyncSession) -> None:
    """기본 provider(Mock LLM 하나, 스펙 059)와 기본 chat/embedding 모델을 적재.

    외부 의존 0으로 첫 채팅/RAG가 바로 동작한다. 실 모델(MLX·OpenAI 호환 등)은 env가 아니라
    admin Provider UI에서 추가하고 기본 전환한다(Provider는 1급 엔티티 — 스펙 035). base_url은
    **이 API 자신의** OpenAI 호환 mock 엔드포인트(self-call) — API를 다른 호스트/포트로 옮기면
    MOCK_LLM_BASE_URL로 자기주소를 맞춘다. (이 경로는 create_all 폴백에서만 도달 — 정상 alembic
    경로는 f4a5+a1b2c3가 provider를 먼저 만들어 _empty가 False라 스킵되고, 그 경로의 기본값은
    마이그레이션이 세운다. 스펙 059.)
    """
    mock_base = os.environ.get("MOCK_LLM_BASE_URL", "http://127.0.0.1:8000/_remote/v1")
    mock_provider = Provider(
        name="Mock LLM",
        protocol="openai-compatible",
        base_url=mock_base,
        api_key=crypto.encrypt("sk-noauth"),
        kind="mock",
        description="라이브 없이 결정적 동작용 내장 목(스펙 024) — 기본 provider(059)",
    )
    session.add(mock_provider)
    await session.flush()  # provider id 확보(모델 FK용)
    session.add_all(
        [
            # 기본 chat — Mock(무외부, canned). CHAT_MODEL_NAME으로 에이전트 참조와 단일 소스.
            ModelConfig(
                name=CHAT_MODEL_NAME,
                provider_id=mock_provider.id,
                model_id="mock-chat",
                kind="chat",
                is_default=True,
                params={},
            ),
            # 기본 embedding — mock-embed. `/_remote/v1/embeddings`가 RAG_EMBED_DIMS 차원 벡터를
            # 입력 1건당 1개 반환 → 라이브 모델 없이 RAG 인제스트/검색이 결정적으로 통과한다(스펙 048).
            ModelConfig(
                name="mock-embed",
                provider_id=mock_provider.id,
                model_id="mock-embed",
                kind="embedding",
                is_default=True,
                params={},
            ),
        ]
    )


async def _seed_collections(session: AsyncSession) -> None:
    """임베딩 모델에 맞춰 RAG 컬렉션 생성(차원 고정, 스펙 048)."""
    # 같은 트랜잭션의 시드 모델을 flush로 가시화.
    await session.flush()
    embs = (
        (await session.execute(select(ModelConfig).where(ModelConfig.kind == "embedding")))
        .scalars()
        .all()
    )
    # 게이트(스펙 048)는 _collection_seed_specs로 분리 — DB 없이 단위 테스트 가능.
    session.add_all(
        [
            Collection(
                name=n,
                description=d,
                embedding_model_id=mid,
                dims=RAG_EMBED_DIMS,
                status="empty",
            )
            for n, d, mid in _collection_seed_specs(embs)
        ]
    )


def _seed_ui_agents(session: AsyncSession, persona_body: dict[str, str]) -> None:
    """AGENTS 카탈로그(ui 소스)를 버전 이력과 함께 적재."""
    for (
        aid,
        name,
        description,
        source,
        model,
        persona,
        mems,
        hist,
        vts,
        mcps,
        a2a,
        status,
        active,
        versions,
    ) in AGENTS:
        cfg = {
            "model": model,
            "persona": persona,
            "memories": list(mems),
            "vectorTables": list(vts),
            "mcps": list(mcps),
            "historyDepth": hist,
        }
        agent = Agent(
            agent_id=aid,
            name=name,
            description=description,
            source=source,
            model=model,
            persona=persona_body.get(persona, persona),
            history_depth=hist,
            config=cfg,
            exposed={"a2a": a2a},
            status=status,
            active_version=active,
        )
        for ver, vstatus, _created, note in versions:
            agent.versions.append(
                AgentVersion(version=ver, status=vstatus, note=note, config=dict(cfg))
            )
        session.add(agent)


def _seed_plan_execute_agent(session: AsyncSession, persona_body: dict[str, str]) -> None:
    """in-process 커스텀 에이전트 시드(스펙 085) — source=ui(로컬 실행)이되 config.impl로 신뢰
    레지스트리의 plan→execute 그래프를 가리킨다. DefaultUiAgent(create_agent)와 *구조가 다른*
    다노드 그래프라, 플레이그라운드 추적에 실 노드열([plan, execute])이 뜨고 오버라이드 주입도
    동일하게 받는다(인터페이스가 create_agent에 과적합되지 않았음을 화면으로 증명)."""
    pe_cfg = {
        "model": CHAT_MODEL_NAME,
        "persona": "methodical-researcher",
        "memories": ["단기(세션)"],
        "vectorTables": [],
        "mcps": [],
        "historyDepth": 20,
        "impl": "plan_execute",
    }
    plan_execute = Agent(
        agent_id="agt_plex_b5e207",
        name="plan-execute-demo",
        description="Plan-Execute Demo",
        source="ui",
        model=CHAT_MODEL_NAME,
        persona=persona_body.get("methodical-researcher", "methodical-researcher"),
        history_depth=20,
        config=pe_cfg,
        exposed={"a2a": False},
        status="online",
        active_version="v1",
    )
    plan_execute.versions.append(
        AgentVersion(
            version="v1",
            status="active",
            note="plan→execute 커스텀 SDK 데모(스펙 085)",
            config=dict(pe_cfg),
        )
    )
    session.add(plan_execute)


def _seed_code_agent(session: AsyncSession) -> None:
    """코드 정의(SDK 배포) 에이전트 시드 — UI mock과 동일하게 1개.

    스펙 057(A2A 단일화): code도 A2A로 호출한다. endpoint는 mock A2A JSON-RPC 서비스,
    config["card"]는 connect가 빌드하는 것과 동형(x-my-agents 확장 포함)으로 스냅샷한다.
    실 배포는 자기 A2A url을 쓴다(REMOTE_AGENT_BASE로 오버라이드 가능).
    """
    code_endpoint = os.environ.get("REMOTE_AGENT_BASE", "http://127.0.0.1:8000/_remote/a2a")
    code_card = {
        "name": "Doc Translator",
        "description": "my-agents-sdk로 배포한 번역 에이전트(시드 스냅샷).",
        "url": code_endpoint,
        "version": "1.0.0",
        "provider": {"organization": "acme", "url": "https://acme.example"},
        "capabilities": {"streaming": True, "pushNotifications": False},
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain"],
        "skills": [
            {
                "id": "translate",
                "name": "문서 번역",
                "description": "문서를 대상 언어로 번역",
                "tags": ["translation", "i18n"],
            },
        ],
        "x-my-agents": {
            "manifest": {
                "model": CHAT_MODEL_NAME,
                "persona": "코드 정의 (SDK)",
                "memories": ["단기(세션)"],
                "mcps": [MOCK_MCP_SERVER_NAME],
                "historyDepth": 10,
            },
            "deploy": {
                "repo": "acme/doc-translator",
                "commit": "f3a91c2",
                "runtime": "my-agents-sdk · Python 2.4.1",
                "versions": [
                    {
                        "version": "f3a91c2",
                        "status": "active",
                        "note": "Deploy · 용어집 조회 추가",
                    },
                    {"version": "9b22d01", "status": "archived", "note": "Deploy · 초기 배포"},
                ],
            },
        },
    }
    code_cfg = {
        "model": CHAT_MODEL_NAME,
        "persona": "코드 정의 (SDK)",
        "memories": ["단기(세션)"],
        "vectorTables": [],
        "mcps": [MOCK_MCP_SERVER_NAME],
        "historyDepth": 10,
        "card": code_card,
    }
    translator = Agent(
        agent_id="agt_xlt_a17c33",
        name="doc-translator",
        description="Doc Translator",
        source="code",
        model=CHAT_MODEL_NAME,
        persona="코드 정의 (SDK)",
        history_depth=10,
        config=code_cfg,
        exposed={"a2a": False},
        status="online",
        active_version="f3a91c2",
        endpoint=code_endpoint,
        token=crypto.encrypt("sk_live_demo_doc_translator_a17c33"),
        runtime="my-agents-sdk · Python 2.4.1",
        repo="acme/doc-translator",
        commit="f3a91c2",
        registered_at="2026-06-18",
        last_sync="12분 전",
    )
    translator.versions.append(
        AgentVersion(
            version="f3a91c2",
            status="active",
            note="Deploy · 용어집 조회 추가",
            config=dict(code_cfg),
        )
    )
    translator.versions.append(
        AgentVersion(
            version="9b22d01",
            status="archived",
            note="Deploy · 초기 배포",
            config=dict(code_cfg),
        )
    )
    session.add(translator)


def _seed_external_agent(session: AsyncSession) -> None:
    """외부(A2A) 에이전트 시드 — 카드 스냅샷 하드코딩(네트워크 self-call 없이 어드민에서 source
    배지/카드 패널을 바로 시연). 실제 등록은 POST /agents/connect 경유(057, x-my-agents 확장이
    없으니 external로 분류된다)."""
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
            {
                "id": "translate",
                "name": "문서 번역",
                "description": "문서를 대상 언어로 번역",
                "tags": ["translation", "i18n"],
            },
        ],
    }
    external = Agent(
        # 원격 유래 카드명은 자동 변환 + 원문을 설명으로 보존(스펙 148, 210 — connect 경로와 동형)
        agent_id="agt_ext_ac2e01",
        name="acme-translate-a2a",
        description=ext_card["name"],
        source="external",
        model="",
        persona="",
        history_depth=10,
        config={
            "model": "",
            "persona": "",
            "memories": [],
            "vectorTables": [],
            "mcps": [],
            "historyDepth": 10,
            "card": ext_card,
        },
        exposed={"a2a": False},
        status="online",
        endpoint=ext_card["url"],
        token=None,
        registered_at="2026-06-26",
        last_sync="방금",
    )
    session.add(external)


def _seed_agents(session: AsyncSession) -> None:
    """에이전트 카탈로그 시드 — ui 2종 + plan-execute(085) + code(SDK, 057) + external(A2A)."""
    persona_body = {name: body for name, _description, _tone, body in PERSONAS}
    _seed_ui_agents(session, persona_body)
    _seed_plan_execute_agent(session, persona_body)
    _seed_code_agent(session)
    _seed_external_agent(session)


async def _seed_sessions(session: AsyncSession) -> None:
    """SESSIONS 데모 세션을 시드 에이전트의 agent_pk에 연결해 적재."""
    # agent_pk 연결을 위해 먼저 flush 필요 — 시드 에이전트가 같은 트랜잭션에 있을 수 있음
    await session.flush()
    agents_by_aid = {a.agent_id: a for a in (await session.execute(select(Agent))).scalars().all()}
    for sid, aid, aname, channel, status, turns, tokens in SESSIONS:
        a = agents_by_aid.get(aid)
        if a is None:
            continue
        session.add(
            Session(
                session_id=sid,
                agent_pk=a.id,
                agent_name=aname,
                channel=channel,
                status=status,
                turns=turns,
                tokens=tokens,
            )
        )


async def _seed_approvals(session: AsyncSession) -> None:
    """APPROVALS 데모 승인 적재(현재 빈 카탈로그 — 스펙 046으로 트리거 도구 제거, 상단 주석 참고)."""
    await session.flush()
    agents_by_aid = {a.agent_id: a for a in (await session.execute(select(Agent))).scalars().all()}
    for apid, sid, aid, aname, perm, action, args, summary, ckpt in APPROVALS:
        a = agents_by_aid.get(aid)
        session.add(
            Approval(
                approval_id=apid,
                session_id=sid,
                agent_pk=a.id if a else None,
                agent_name=aname,
                permission=perm,
                action=action,
                args=args,
                summary=summary,
                checkpoint=ckpt,
                status="pending",
            )
        )


async def _reconcile_served_mcp(session: AsyncSession) -> None:
    """서빙 커스텀 MCP 행 멱등 reconcile(스펙 156, codex Medium/High) — _empty 게이트와 무관하게 매
    부팅 실행. 이유 둘: (1) 기존 설치(테이블 비지 않음)에도 기능이 나타나게 한다(Medium), (2) custom
    행은 오직 여기서만(owner_id=None, 시스템 소유) 생성 → create 라우트의 source=custom 차단(High)과
    합쳐 "사용자가 custom을 자가선언해 선점·공개"하는 우회를 원천 봉인."""
    have = set((await session.execute(select(McpServer.name))).scalars().all())
    for sname, stools in SERVED_MCP_TOOLS.items():
        if sname not in have:
            session.add(
                McpServer(
                    name=sname,
                    source="custom",
                    transport="http",
                    url=served_url(sname),
                    tools=list(stools),
                    enabled_tools=list(stools),
                    status="connected",
                    published=False,
                    tools_meta=SERVED_MCP_TOOLS_META.get(sname),
                    owner_id=None,
                )
            )
            continue
        # 기존 행은 **코드 소유 필드만** 동기화(스펙 201 후속) — 도구 정의·설명(=모델 라우팅 재료이자
        # 드로어 안내)이 레지스트리에서 바뀌면 화면과 모델이 같은 문서를 보게. 관리자 소유 필드
        # (published·description·enabled_tools)는 보존 — 통째 교체는 관리자 저작을 지우는 함정
        # (learning: sync-wholesale-replace). source=custom 행만(같은 이름의 사용자 local 행이면 불변 —
        # custom 자가선언 봉인과 일관).
        row = (await session.execute(select(McpServer).where(McpServer.name == sname))).scalar_one()
        if row.source == "custom":
            row.tools = list(stools)
            row.tools_meta = SERVED_MCP_TOOLS_META.get(sname)
            row.url = served_url(sname)


async def seed_if_empty(session: AsyncSession) -> None:
    """각 카탈로그가 비어있으면 시드. 부분 시드 가능(독립적)."""
    if await _empty(session, Persona):
        _seed_personas(session)
    if await _empty(session, MemoryType):
        _seed_memory_types(session)
    if await _empty(session, McpServer):
        _seed_mcp_servers(session)
    if await _empty(session, Provider):
        await _seed_mock_provider_models(session)
    if await _empty(session, Collection):
        await _seed_collections(session)
    if await _empty(session, Agent):
        _seed_agents(session)
    if await _empty(session, Session):
        await _seed_sessions(session)
    if await _empty(session, BatchConfig):
        # 배치 설정 싱글톤 1행(스펙 038) — 값은 NULL(보존창·cron 비활성). 운영자가 명시 설정 전엔
        # 아무 것도 자동 삭제·발화하지 않는다(보수적 기본값).
        session.add(BatchConfig())
    if await _empty(session, Approval):
        await _seed_approvals(session)

    await _reconcile_served_mcp(session)
    await session.commit()

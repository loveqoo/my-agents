"""참조 무결성 — 에이전트 config가 MCP 서버·RAG 컬렉션을 name으로 참조하는지 스캔(스펙 093).

에이전트 config는 자원을 **name 문자열**로 참조한다(FK 아님):
  config["mcps"]         → McpServer.name  (런타임 해석 chat.py: McpServer.name.in_)
  config["vectorTables"] → Collection.name (런타임 해석 chat.py: Collection.name.in_)

삭제 엔드포인트(blocks.py mcp-servers, rag.py collections)가 이 헬퍼로 참조 에이전트를 세어,
있으면 삭제를 409로 막는다 — 삭제 후 config에 dangling name만 남아 런타임이 조용히 도구/RAG 없이
동작(chat.py 미해석 warning)하는 실수를 방지.

참조 범위(스펙 093 §2.1, codex 적대리뷰로 교정) = **활성 서빙 config ∪ 모든 버전 config**:
  - Agent.config      : 활성(발행) 버전 config(activate_version이 agent.config=cfg로 덮음). 런타임이 로드.
  - AgentVersion(전 상태): draft/active/**archived 포함**. 어떤 상태의 버전이든 `activate_version`으로
    활성화 가능하다(agents.py:225 "archived=롤백은 허용", :232 active 승격 → :235 agent.config 부활).
    즉 archived도 *죽은 이력이 아니라 롤백 가능한 live 참조*다 — 여기 name을 지우면 롤백 순간 dead ref.
    (초안 스펙은 "archived는 활성화 불가"로 잘못 가정해 제외했었다 — codex가 반증, 측정으로 교정.)
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .models import Agent

# config에서 name 배열을 담는 필드(닫힌 집합). 삭제 자원별 field 매핑은 호출측이 고정.
_FIELDS = ("mcps", "vectorTables")


def config_names(config: object, field: str) -> list[str]:
    """config[field]의 name 리스트를 정규화 반환 — **list[str]만 인정**, 그 외 모양은 [](fail-safe).

    가드(`_config_has`)와 런타임(`chat.py`가 이 결과를 `name.in_(...)`에 사용)이 **이 단일 normalizer를
    공유**해 판정 드리프트 0(codex P2: dict config를 런타임은 키로 해석·가드는 무시하던 어긋남 차단).
    dict/None/스칼라 config·비-list field·리스트 내 비-str 원소는 모두 참조 아님으로 접는다."""
    if not isinstance(config, dict):
        return []
    value = config.get(field)
    if not isinstance(value, list):
        return []
    return [x for x in value if isinstance(x, str)]


def _config_has(config: object, field: str, name: str) -> bool:
    """config[field](name 배열)에 name이 있나. 비정상 모양엔 fail-safe False(config_names 경유)."""
    return name in config_names(config, field)


async def agents_referencing(
    session: AsyncSession, field: str, name: str
) -> list[dict[str, str]]:
    """config[field]에 name을 담은 참조 목록.

    반환: [{"agent": <에이전트 이름>, "where": "active"|"version"}] — where=active는 서빙
    config(Agent.config), version은 서빙은 아니지만 *활성화 가능한* 버전(draft/archived 포함)에 있는
    잠복 참조. 같은 에이전트가 양쪽이면 active 우선 1건(dedupe). field는 _FIELDS 중 하나(오타 방지)."""
    if field not in _FIELDS:
        raise ValueError(f"unknown reference field: {field!r} (expected one of {_FIELDS})")
    if not name:
        return []  # 빈 name은 참조 대상이 될 수 없음(자원 name은 non-empty·unique)

    agents = list(
        (
            await session.execute(select(Agent).options(selectinload(Agent.versions)))
        ).scalars().all()
    )

    refs: list[dict[str, str]] = []
    for agent in agents:
        if _config_has(agent.config, field, name):
            refs.append({"agent": agent.name, "where": "active"})
            continue  # active로 이미 잡힘 — 버전 중복 계상 안 함
        # archived 포함 전 버전: 어떤 상태든 activate_version으로 롤백/발행 가능 → live 참조.
        if any(_config_has(v.config, field, name) for v in agent.versions):
            refs.append({"agent": agent.name, "where": "version"})
    return refs


# where 코드 → 사람이 읽는 위치말. active=서빙 config, version=활성화 가능한 비-서빙 버전.
_WHERE_LABEL = {"active": "활성", "version": "버전"}
_MSG_MAX_NAMES = 20  # 409 메시지에 나열할 최대 에이전트 수(무제한 연결 방지, codex P2).


def referenced_message(refs: list[dict[str, str]], resource: str, action: str = "삭제") -> str:
    """409 detail *문자열* — 참조 에이전트 목록을 사람이 읽는 한 문장으로.

    dict 아닌 string으로 반환하는 이유: 중앙 error 헬퍼(spec 062 `httpError.ts`)와 이 뷰들의
    기존 409 관례(`CollectionsView`: "서버 메시지를 그대로 노출")가 **string detail만** 노출한다.
    dict를 주면 프런트가 일반 폴백만 보여 참조 목록이 안 뜬다. where(active/version) 구분은
    "이름(활성/버전)"으로 문자열 안에 보존해 usedBy 배지(활성만)와 어긋나는 버전 차단도 정직히 설명.

    나열은 최대 _MSG_MAX_NAMES개 + "외 M개"로 상한(codex P2: 수백 참조 시 무제한 연결 방지).
    resource: 대상 명사('MCP 서버' | 'RAG 컬렉션'). action: 막는 동작('삭제' | '이름 변경') —
    삭제·rename 둘 다 참조 name 링크를 깨므로 같은 포매터 공유(operation-symmetry, learning 050)."""
    shown = refs[:_MSG_MAX_NAMES]
    names = ", ".join(
        f"{r['agent']}({_WHERE_LABEL.get(r['where'], r['where'])})" for r in shown
    )
    if len(refs) > _MSG_MAX_NAMES:
        names += f" 외 {len(refs) - _MSG_MAX_NAMES}개"
    return (
        f"이 {resource}을(를) {len(refs)}개 에이전트가 사용 중이라 {action}할 수 없습니다: "
        f"{names}. 먼저 각 에이전트에서 해제한 뒤 {action}하세요."
    )

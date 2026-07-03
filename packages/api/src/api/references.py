"""참조 무결성 — 에이전트 config가 MCP 서버·RAG 컬렉션을 name으로 참조하는지 스캔(스펙 093).

에이전트 config는 자원을 **name 문자열**로 참조한다(FK 아님):
  config["mcps"]         → McpServer.name  (런타임 해석 chat.py: McpServer.name.in_)
  config["vectorTables"] → Collection.name (런타임 해석 chat.py: Collection.name.in_)

삭제 엔드포인트(blocks.py mcp-servers, rag.py collections)가 이 헬퍼로 참조 에이전트를 세어,
있으면 삭제를 409로 막는다 — 삭제 후 config에 dangling name만 남아 런타임이 조용히 도구/RAG 없이
동작(chat.py 미해석 warning)하는 실수를 방지.

참조 범위(스펙 121로 완화) = **활성 서빙 config만**(`Agent.config`):
  - 스펙 093은 모든 버전(draft/archived 포함)까지 훑어 "롤백 시 dead ref"를 막았으나, 실사용에서
    과거 버전에 남은 참조 하나가 자원을 영구히 못 지우게 해 과도하게 엄격했다(사용자 버그1).
  - **활성 config만 검사**로 완화 — 과거 버전은 무시한다. 트레이드오프: 삭제된 자원을 참조하는 오래된
    버전으로 롤백하면 그 자원 없이 동작하나, 런타임이 dangling name을 **경고 후 우아하게 degrade**한다
    (chat.py 미해석 warning — 도구/RAG 없이 진행). 이 완화는 **usedBy 배지(활성만)와 삭제 가드를 일치**
    시킨다(093에선 배지는 활성만·삭제만 버전까지 세던 어긋남을 스스로 지적했었다).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Agent

# config에서 name을 담는 필드(닫힌 집합). 삭제 자원별 field 매핑은 호출측이 고정.
# persona는 스칼라(config["persona"] == name), 나머지는 name 배열(codex 148 High — 페르소나·권한
# rename/삭제도 참조를 깨므로 같은 가드 아래 둔다).
_FIELDS = ("mcps", "vectorTables", "permissions", "persona")

# 배열 필드 외에 조율형 capabilities(`{kind}:{name}` 또는 `{kind}:{name}/{tool}`)로도 참조된다
# (codex 148 Medium — mcps가 비고 capabilities만 있는 조율형이 가드를 우회하던 구멍).
_CAP_KIND = {"mcps": "mcp", "vectorTables": "rag"}


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
    """config[field]가 name을 참조하나. 비정상 모양엔 fail-safe False(config_names 경유).
    persona=스칼라 비교, mcps/vectorTables는 배열 + capabilities(`kind:name[/tool]`)도 본다(스펙 148)."""
    if field == "persona":
        return isinstance(config, dict) and config.get("persona") == name
    if name in config_names(config, field):
        return True
    kind = _CAP_KIND.get(field)
    if kind and isinstance(config, dict):
        prefix = f"{kind}:{name}"
        caps = config.get("capabilities")
        if isinstance(caps, list):
            return any(
                isinstance(c, str) and (c == prefix or c.startswith(prefix + "/")) for c in caps
            )
    return False


async def agents_referencing(
    session: AsyncSession, field: str, name: str
) -> list[dict[str, str]]:
    """config[field]에 name을 담은 참조 목록 — **활성 서빙 config만**(스펙 121, 과거 버전 무시).

    반환: [{"agent": <에이전트 이름>, "where": "active"}]. 활성 `Agent.config`만 검사해 usedBy 배지와
    일치시킨다. 과거 버전(draft/archived)은 세지 않는다 — 그 참조가 자원을 영구 잠그던 과엄격을 완화
    (롤백 시엔 런타임이 dangling name을 경고·degrade). field는 _FIELDS 중 하나(오타 방지)."""
    if field not in _FIELDS:
        raise ValueError(f"unknown reference field: {field!r} (expected one of {_FIELDS})")
    if not name:
        return []  # 빈 name은 참조 대상이 될 수 없음(자원 name은 non-empty·unique)

    agents = list((await session.execute(select(Agent))).scalars().all())
    return [
        {"agent": agent.name, "where": "active"}
        for agent in agents
        if _config_has(agent.config, field, name)
    ]


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

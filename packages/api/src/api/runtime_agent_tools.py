"""에이전트-호출 위임 도구(스펙 318) — runtime.py에서 분할(스펙 397 P3, 순수 이동).

실행은 broker.invoke 경유(재귀 가드·HIL·격리 승계 전부 브로커 소유). 파사드는 runtime.py.
"""

from typing import Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import StructuredTool

from .runtime_mcp import _safe_name


def _wrap_agent_tool(broker: Any, cap: Any) -> StructuredTool:
    """에이전트-호출 도구(스펙 318) — 노드가 다른 에이전트에 위임하는 도구. 실행은 `broker.invoke`
    경유라 **재귀 가드**(방문 집합=체인 내 재방문 금지·깊이·너비 예산)·HIL 승인 게이트(interrupt)·
    위임 결과의 데이터 채널 격리가 전부 브로커에서 그대로 적용된다(스펙 100~256, 새 코드 0). 도구
    이름 `agent__{agent_id}`(MCP `_safe_name` 관례) — 노드 `tools` 목록의 이름과 일치해 `_resolve_tool`
    이 여느 도구처럼 바인딩. 트레이스는 broker.invocations(brokerCalls)가 담당(calls_sink 불요).
    결과는 InvokeResult.text로 접고, 실패는 graceful 문자열(에이전트를 죽이지 않음).

    broker 이중 모드(스펙 421 P3) — **config 우선**(`configurable.broker`, 캐시 그래프: 이번 턴
    principal의 브로커가 매 호출 주입 → 인가가 라이브), 없으면 클로저 폴백(직접 빌드: eval·resume —
    종전 동작). 캐시 관문에 넣는 빌드는 broker=None 스텁으로 만들어 **클로저 폴백이 turn-A broker가
    되는 길 자체가 없다**(주입 없이 호출되면 정직한 실패 — fail-closed, 누출 불가)."""
    cap_id = cap.id
    label = cap.name or cap_id

    async def _delegate(text: str = "", config: RunnableConfig = None) -> str:
        br = ((config or {}).get("configurable") or {}).get("broker") or broker
        if br is None:
            return f"에이전트 '{label}' 호출 불가: 위임 브로커가 이 실행 경로에 연결되지 않았습니다."
        res = await br.invoke(cap_id, {"text": text})
        if getattr(res, "error", None):
            return f"에이전트 '{label}' 호출 실패: {res.error}"
        return getattr(res, "text", "") or ""

    hook = (cap.hook or "").strip()
    desc = f"에이전트 '{label}'에게 하위 작업을 위임한다"
    if hook:
        desc += f" — {hook}"
    desc += ". 입력: text(위임할 질문/지시). 이 에이전트가 답을 만들어 돌려준다."
    return StructuredTool.from_function(
        coroutine=_delegate,
        name=_safe_name("agent", cap_id),
        description=desc,
    )


def build_agent_tools(broker: Any, agent_caps: list) -> list[StructuredTool]:
    """허가된 kind=agent 능력마다 위임 도구 하나(스펙 318). 후보=broker가 이미 스코프한 것
    (allowlist∩RBAC) — 이 빌더는 권한을 새로 열지 않는다(브로커가 유일한 정책 게이트, confused-deputy
    0). 노드는 자기 `tools`에서 `agent__{id}`를 골라 바인딩(build_mcp_tools·build_rag_tool과 같은
    풀 합류 패턴). broker=None이면 config-주입 전용 스텁(스펙 421 P3 — 캐시 빌드용, 위 이중 모드)."""
    return [_wrap_agent_tool(broker, cap) for cap in agent_caps]

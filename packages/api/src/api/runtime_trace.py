"""트레이스 요약·타임라인·조립 — runtime.py에서 분할(스펙 397 P2).

노드 델타 요약(스펙 086 — 값-allowlist polarity)·타임라인 3원(관측/노드열/합성)·트레이스 조립.
_summarize_messages_delta(구 CC 11)는 메시지 프리뷰(_message_preview) 추출로,
_summarize_node_update(구 CC 11)는 키 dispatch(_summarize_delta_entry) 추출로 분해.
파사드는 runtime.py(재수출 계약).
"""

from typing import Any

from langchain_core.messages import ToolMessage

from .runtime_trace_safety import (
    _FIELD_CAP,
    _MSG_PREVIEW_CAP,
    _MSG_PREVIEW_N,
    _REDACTED,
    _SENSITIVE_KEY,
    _VALUE_SAFE_KEYS,
    _cap,
    _content_text,
)


def is_tool_message(msg: Any) -> bool:
    """도구 노드가 낸 ToolMessage(도구 원본 응답)인가 — 채팅 본문 sink에서 제외하는 단일 판정(스펙 092).

    ReAct 그래프의 stream_mode="messages"는 모델 노드의 AIMessage(Chunk)뿐 아니라 tools 노드의 ToolMessage
    (도구 실행 원본)도 청크로 흘린다(`.dev/probe_092_tool_message_stream.py`로 실측). 본문에는 모델의
    추론만 남기고 도구 원본은 빼야 하며, 도구 호출 자체는 인스펙터 trace(calls_sink)에 독립 보존된다.
    판별은 **isinstance(ToolMessage)** — `.type` 문자열은 청크/비청크 간 불안정하다(ToolMessage.type=='tool'
    이지만 ToolMessageChunk.type=='ToolMessageChunk', AIMessageChunk.type=='AIMessageChunk'로 측정됨).
    ToolMessageChunk는 ToolMessage의 서브클래스라 isinstance가 둘 다 잡고 AI 메시지는 제외한다(verify_092로 확정)."""
    return isinstance(msg, ToolMessage)


def _msg_role(m: Any) -> str:
    """메시지(LangChain 객체/dict)의 역할을 사용자 친화 라벨로. 청크형 type명(AIMessageChunk 등)도
    소문자 접두 매칭으로 방어(스펙 086 노트: .type은 청크/비청크 간 불안정)."""
    r = str(
        (m.get("role") or m.get("type") or "")
        if isinstance(m, dict)
        else getattr(m, "type", "") or ""
    )
    low = r.lower()
    for k, v in (("ai", "assistant"), ("human", "user"), ("tool", "tool"), ("system", "system")):
        if low.startswith(k):
            return v
    return r or "msg"


def _message_preview(msg: Any) -> str:
    """메시지 1건 → role+본문 프리뷰(스펙 397 분해) — 마스킹은 캡 이전 큰 cap으로(무절단),
    잘림은 _cap이 정직 표기(086 U2 불변식)."""
    from .memory import _sanitize as _mask

    raw = msg.get("content") if isinstance(msg, dict) else getattr(msg, "content", None)
    text = _cap(_mask(_content_text(raw), cap=1_000_000), _MSG_PREVIEW_CAP)
    return f"{_msg_role(msg)}: «{text}»" if text else _msg_role(msg)


def _summarize_messages_delta(val: list) -> str:
    """messages 델타를 role+본문 프리뷰 한 줄로 요약해 반환(스펙 192 후속).

    채팅 스트림과 일부 중복이라 프리뷰는 짧게 캡. 맥락 격리(스펙 260/262) — clean 노드가 낸
    RemoveMessage(role=="remove", 상태 삭제 지시)는 내부어라 사람 말로 접는다: "이전 맥락 N개 정리
    (격리)". 앞 _MSG_PREVIEW_N건만 펼치고 나머지는 카운트(거대 리스트 방어)."""
    if not val:
        return "메시지 0건"
    removes = sum(1 for m in val if _msg_role(m) == "remove")
    rest = [m for m in val if _msg_role(m) != "remove"]
    previews: list[str] = []
    if removes:
        previews.append(f"이전 맥락 {removes}개 정리 (격리)")
    previews.extend(_message_preview(msg) for msg in rest[:_MSG_PREVIEW_N])
    extra = max(0, len(rest) - _MSG_PREVIEW_N)
    return " / ".join(previews) + (f" (+{extra}건)" if extra > 0 else "")


def _summarize_delta_value(key: str, val: Any) -> str:
    """단일 델타 값의 안전 요약 문자열을 반환(값-비밀 fail-closed, budgeted 캡)."""
    if isinstance(val, str):
        # 안전 키(plan)만 값 원문(budgeted 캡); 그 외 임의 키는 길이만(F2 값-비밀 fail-closed).
        if key in _VALUE_SAFE_KEYS:
            # 키 접두로 어떤 값인지 명시(131 — 안전 키가 4개로 늘어 구분 필요).
            # delegated는 위임 결과(untrusted 본문) fold라 **비밀 마스킹 백스톱 필수**
            # (codex 131 #1 — 캡은 크기 방어일 뿐). 마스킹은 캡 **이전에**(cap 크게 줘 무절단),
            # 잘림은 기존 _cap이 담당 — "…N자 생략" 정직 표기 보존(086 U2 불변식).
            from .memory import _sanitize as _mask

            return f"{key}: {_cap(_mask(val, cap=1_000_000), _FIELD_CAP)}"
        return f"{key}: <{len(val)}자>"
    if isinstance(val, (list, tuple)):
        return f"{key}[{len(val)}]"
    if isinstance(val, dict):
        # 중첩 dict도 키만(중첩 안의 비밀 누출 차단 — 값 펼치지 않음). 키 목록도 캡(거대 dict 방어).
        inner = _cap(
            ", ".join(_REDACTED if _SENSITIVE_KEY.search(str(k)) else str(k) for k in val),
            80,
        )
        return f"{key}{{{inner}}}"
    if val is None or isinstance(val, (bool, int, float)):
        return f"{key}={val}"  # 스칼라(유한 길이, 비밀 위험 낮음)
    return f"{key}=<{type(val).__name__}>"  # 미지 타입은 타입명만(fail-closed)


def _summarize_delta_entry(key: str, val: Any) -> str:
    """델타 항목 1개 dispatch(스펙 397 분해) — 민감 키 마스킹 → messages 특례 → 일반 값 요약."""
    if _SENSITIVE_KEY.search(key):
        return f"{key}={_REDACTED}"
    # messages: 그 단계가 낸 발화를 타임라인에서 보이게(plan처럼 execute 등도, 스펙 192 후속).
    if key == "messages" and isinstance(val, list):
        return _summarize_messages_delta(val)
    return _summarize_delta_value(key, val)


def _summarize_node_update(_node: str, delta: Any) -> str | None:
    """노드가 발화하며 바꾼 상태 델타를 사람이 읽을 짧은 문자열로 요약(스펙 086).

    불변식(codex 적대 리뷰 F2·F3·F5 반영):
    (1) **비밀 누출 0(fail-closed)** — 민감 *키*(_SENSITIVE_KEY)는 값 마스킹하고, 그 외 임의 키의
        문자열 값은 *원문 미표시*(길이만). 값 원문은 _VALUE_SAFE_KEYS(우리가 심은 안전 필드)만.
        키 이름이 평범/비영문이라 키-패턴이 못 잡아도 값-비밀이 안 샌다.
    (2) **budgeted 캡** — 각 값을 append 전에 _cap에 통과(거대 값을 join으로 통째 만들지 않음 —
        learning: .content 위 카운트는 막은 척, raw에서 캡).
    (3) **fail-closed 예외** — 비문자 키 등으로 요약이 실패해도 None 반환(chat loop 안 깸, F5).
    빈/무의미 델타는 None(요약 행 미표시)."""
    if not isinstance(delta, dict) or not delta:
        return None
    try:
        parts = [_summarize_delta_entry(str(raw_key), val) for raw_key, val in delta.items()]
        text = _cap(" · ".join(p for p in parts if p))
        return text or None
    except Exception:
        return None


def build_graph_path(used_memory: bool, used_tools: bool, total_ms: int) -> list[dict]:
    """관측된 실행으로 LangGraph 경로 트레이스를 합성. 인스펙터 표시용."""
    nodes = ["__start__"]
    if used_memory:
        nodes.append("retrieve_memory")
    if used_tools:
        nodes.append("tools")
    nodes.append("call_model")
    nodes.append("__end__")
    # total_ms를 노드에 대략 분배 (start/end는 0/소량).
    inner = [n for n in nodes if not n.startswith("__")]
    per = int(total_ms / max(1, len(inner)))
    path: list[dict] = []
    for node in nodes:
        if node == "__start__":
            path.append({"node": node, "ms": 0})
        elif node == "__end__":
            path.append({"node": node, "ms": 15})
        else:
            path.append({"node": node, "ms": per})
    return path


def _timeline_from_observations(observed: list[dict]) -> list[dict]:
    """관측 레코드(`{node, ms, summary}`, 스펙 086)를 인스펙터 타임라인으로. ms는 실측(균등분할
    아님), summary는 안전 요약. __start__/__end__ 센티넬로 감싸 표시 일관성 유지. 중복(재진입) 보존."""
    path: list[dict] = [{"node": "__start__", "ms": 0}]
    for rec in observed:
        item = {"node": rec["node"], "ms": int(rec.get("ms", 0))}
        if rec.get("summary"):
            item["summary"] = rec["summary"]
        # 병렬 superstep(한 update 청크에 노드 2+)이면 ms는 *공유 청크 경과*지 노드별 실측이 아니다 —
        # 순차 누적으로 과장 표시되지 않게 플래그를 싣는다(codex F4: ms 정직성).
        if rec.get("parallel"):
            item["parallel"] = True
        path.append(item)
    path.append({"node": "__end__", "ms": 15})
    return path


def _timeline_from_nodes(nodes: list[str], total_ms: int) -> list[dict]:
    """`updates` 스트림서 **관측한 노드 발화 순서**로 타임라인을 구성(스펙 085).

    하드코딩 합성(build_graph_path)과 달리 어떤 적합 그래프든 자기 실 노드를 그대로 싣는다 —
    create_agent(단일 노드)든 plan→execute(다노드)든. 중복은 보존(같은 노드 반복 발화=실 재진입).
    __start__/__end__ 센티넬로 감싸 인스펙터 표시 일관성 유지.

    경계(codex 적대 리뷰 F3): 이건 **관측된 update 순서**지 엄밀한 호출 스택 순서가 아니다.
    *직렬* 그래프(현 출하 2종: create_agent ReAct, plan→execute)에선 update가 노드별 순차
    도착이라 실행 순서와 일치한다. 하지만 *병렬 superstep* 그래프라면 한 update 청크가 여러
    분기 노드를 동시에 실어와 dict 키 순서로 평탄화되므로 — 실행에 전순서가 없을 수 있고 — 이
    타임라인은 근사다. ms도 total을 노드 수로 **균등 분할**한 표시용 추정치지 노드별 실측이
    아니다. 병렬 그래프를 1급 추적하려면 superstep 그룹핑·노드별 실측 타이밍을 싣는 스트림
    소스로 승급해야 한다(후속 스펙)."""
    seq = [n for n in nodes if not n.startswith("__")]
    per = int(total_ms / max(1, len(seq)))
    path: list[dict] = [{"node": "__start__", "ms": 0}]
    for node in seq:
        path.append({"node": node, "ms": per})
    path.append({"node": "__end__", "ms": 15})
    return path


def estimate_tokens(prompt_chars: int, output_chars: int) -> dict[str, int]:
    """대략적 토큰 추정 (≈4 chars/token). usage가 없을 때 폴백."""
    return {"in": max(1, prompt_chars // 4), "out": max(1, output_chars // 4)}


def assemble_trace(
    *,
    agent_id: str,
    memories: list[dict],
    mcp_calls: list[dict],
    used_memory: bool,
    total_ms: int,
    tokens: dict[str, int],
    graph_nodes: list[str] | None = None,
    graph_observations: list[dict] | None = None,
) -> dict[str, Any]:
    """Playground 인스펙터가 기대하는 트레이스 형태로 조립.

    타임라인 우선순위(무회귀 — 셋 다 보존):
      1. graph_observations(`{node, ms, summary}` 실측·요약, 스펙 086) — 풀디테일.
      2. graph_nodes(실 노드열 순서만, 스펙 085) — 요약/실측 없는 경로(현 폴백 호출부 호환).
      3. build_graph_path(합성) — 원격 재개 등 노드 관측 불가 시."""
    if graph_observations:
        graph = _timeline_from_observations(graph_observations)
    elif graph_nodes:
        graph = _timeline_from_nodes(graph_nodes, total_ms)
    else:
        graph = build_graph_path(used_memory, bool(mcp_calls), total_ms)
    return {
        "latencyMs": total_ms,
        "tokens": tokens,
        "promptRef": agent_id,
        "memories": memories,
        "mcp": mcp_calls,
        "graph": graph,
    }

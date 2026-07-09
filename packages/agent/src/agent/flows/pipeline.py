"""노드형 에이전트 — 일렬 파이프라인 (스펙 259, 노코드).

사용자가 UI에서 **노드를 N개 추가**하고 노드마다 프롬프트·모델·도구를 고른다. 각 노드는 **작은
에이전트**(자기 시스템 프롬프트+자기 모델+자기 도구 부분집합)이고, 노드들은 **선언 순서대로 일렬**로
실행된다(node_0 → node_1 → … → END). 각 노드가 응답을 메시지에 append하고 다음 노드가 누적 맥락을 본다.
마지막 노드 출력이 에이전트 응답. 추적 타임라인엔 노드 이름별 실 호출이 뜬다.

**설정 주도(스펙 190 패턴)**: 로직을 박지 않고 `ctx.impl_config["nodes"]`(데이터)를 읽어 그래프를
조립한다 — 노드는 데이터(프롬프트 글자·모델 cfg·도구 이름)이고 이 엔진은 고정 신뢰 코드다. eval 없음
(085 §보안경계). **주입만 읽는다**(085 U2): 노드 모델은 플랫폼이 미리 해석해 `node["model_cfg"]`로 주입,
도구는 `ctx.tools`(이미 RBAC·브로커 스코프)에서 이름으로 필터 — 노드가 에이전트 권한을 넘을 수 없다.
"""

from __future__ import annotations

import json
import logging
from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from ..runtime import AgentBuildContext, AgentManifest

log = logging.getLogger(__name__)


class _State(TypedDict):
    messages: Annotated[list, add_messages]


def _coerce_json(text: object, fields: list) -> dict | None:
    """관대 JSON 추출·파싱·필수키 검사(스펙 261, 순수 — 단위 검증 가능). 코드펜스·전후 산문에 감싸여도
    첫 `{`~마지막 `}` 슬라이스로 시도하고, 안 되면 전체 문자열로 재시도. dict 아님·파싱 실패·필수키
    누락이면 None(형식 위반을 조용히 통과시키지 않음)."""
    if not isinstance(text, str) or not text.strip():
        return None
    candidates = []
    s, e = text.find("{"), text.rfind("}")
    if s != -1 and e != -1 and e > s:
        candidates.append(text[s:e + 1])
    candidates.append(text.strip())
    for c in candidates:
        try:
            obj = json.loads(c)
        except (ValueError, TypeError):
            continue
        if not isinstance(obj, dict):
            continue
        if fields and any(k not in obj for k in fields):
            continue
        return obj
    return None


def _text_of(m: object) -> str:
    """메시지의 텍스트 내용 추출(clean 모드가 앞 결과를 새 입력으로 심을 때). content가 문자열이면
    그대로, 멀티모달 리스트면 text 파트만 이어붙임."""
    c = getattr(m, "content", "")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "\n".join(str(p.get("text", "")) if isinstance(p, dict) else str(p) for p in c)
    return str(c)


def _model_from_node(node: dict, ctx: AgentBuildContext) -> ChatOpenAI:
    """노드별 모델 — 플랫폼이 미리 해석해 심은 `node["model_cfg"]`를 쓰고, 없으면 에이전트 기본
    `ctx.model_cfg`로 폴백(주입 단일 출처 — env·DB 미접촉). base_url/model_id 없으면 명확히 실패."""
    cfg = node.get("model_cfg") or ctx.model_cfg or {}
    base_url = cfg.get("base_url") or ""
    model_id = cfg.get("model_id") or ""
    if not base_url or not model_id:
        raise RuntimeError("노드 모델 설정이 필요합니다 (base_url/model_id) — 모델을 등록하세요.")
    cfg_params = cfg.get("params") or {}
    temperature = ctx.params.get("temperature", cfg_params.get("temperature", 0.7))
    enable_thinking = cfg_params.get("enable_thinking", False)
    return ChatOpenAI(
        base_url=base_url,
        api_key=cfg.get("api_key") or "sk-noauth",
        model=model_id,
        temperature=temperature,
        extra_body={"chat_template_kwargs": {"enable_thinking": enable_thinking}},
    )


def normalize_nodes(raw: object) -> list[dict]:
    """impl_config의 노드 리스트를 방어적으로 정규화(순수 — 단위 검증 가능). dict 리스트만, prompt
    문자열 필수(빈 노드 제거), name/model/tools는 선택. 순서 보존. 잡값은 조용히 걸러 빈 리스트로."""
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for i, n in enumerate(raw):
        if not isinstance(n, dict):
            continue
        prompt = n.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            continue  # 프롬프트 없는 노드는 실행 의미 없음 — 정직하게 제외
        name = n.get("name")
        name = name.strip() if isinstance(name, str) and name.strip() else f"노드{i + 1}"
        tools = n.get("tools")
        tools = [t for t in tools if isinstance(t, str)] if isinstance(tools, list) else []
        # 맥락 모드(스펙 260): carry=누적 대화 이어받기(기본), clean=앞 결과만 격리 입력. 잡값→carry.
        context = n.get("context")
        context = context if context in ("carry", "clean") else "carry"
        # 출력 형식(스펙 261): text=자유(기본), json=유효 JSON 강제. fields=필수 키(선택). 잡값→text.
        fmt = n.get("format")
        fmt = fmt if fmt in ("text", "json") else "text"
        raw_fields = n.get("fields")
        node_fields = [f for f in raw_fields if isinstance(f, str) and f.strip()] if isinstance(raw_fields, list) else []
        # 노드별 기억(스펙 268 P2): memories=선택한 기억 블록(비면 회상 안 받음), memoryQuery=회상
        # 키워드 모드(user=사용자 입력[캐시 공유], input=이 노드의 입력[개별 키워드]). 잡값→user.
        raw_mem = n.get("memories")
        node_mem = [m for m in raw_mem if isinstance(m, str) and m.strip()] if isinstance(raw_mem, list) else []
        mem_q = n.get("memoryQuery")
        mem_q = mem_q if mem_q in ("user", "input") else "user"
        # 노드별 단기 기억 창(스펙 270): int면 그 값, 아니면 None=에이전트-레벨 상속. bool은 int
        # 하위형이라 배제(True/False가 1/0으로 새는 것 방지). 상한 1000 캡을 여기서도 강제(codex 270 —
        # 스키마가 쓰기 시 캡하나 엔진=최종 신뢰경계라 legacy/직접DB 우회 대비 미러). 음수=전체(유지).
        hd = n.get("historyDepth")
        node_hd = min(hd, 1000) if (isinstance(hd, int) and not isinstance(hd, bool)) else None
        out.append({
            "name": name,
            "prompt": prompt,
            "model_cfg": n.get("model_cfg") if isinstance(n.get("model_cfg"), dict) else None,
            "tools": tools,
            "context": context,
            "format": fmt,
            "fields": node_fields,
            "memories": node_mem,
            "memoryQuery": mem_q,
            "historyDepth": node_hd,
        })
    return out


def _unique_node_ids(nodes: list[dict]) -> list[str]:
    """그래프 노드 id(이름 충돌 시 접미 — LangGraph 노드명 유일 요구). 표시 이름은 별개 보존.

    `__tools` 접미는 예약(codex 268 P2): 도구 노드 id가 `<id>__tools`로 생성되므로, 사용자가 노드를
    문자 그대로 "A__tools"로 지으면 (a) 노드 "A"의 도구 노드와 id 충돌(그래프 빌드 크래시),
    (b) 인스펙터가 도구 노드로 오귀속. 예약 접미로 끝나는 이름은 '_'를 덧붙여 회피(정직 표기 —
    id에만, 저장된 이름은 불변)."""
    seen: dict[str, int] = {}
    ids: list[str] = []
    for n in nodes:
        base = n["name"]
        while base.endswith("__tools"):
            base += "_"
        if base in seen:
            seen[base] += 1
            ids.append(f"{base}#{seen[base]}")
        else:
            seen[base] = 0
            ids.append(base)
    return ids


class LinearPipelineAgent:
    """노드형(일렬 파이프라인) 커스텀 에이전트 — describe()/build_graph(ctx). NAME=`pipeline`."""

    NAME = "pipeline"

    def describe(self) -> AgentManifest:
        # 노드가 도구를 고르므로 mcps/vectorTables(도구 풀)·memories(회상)를 소비. 노드 자체 설정은
        # nodes 표면. supports_hil=True: 노드가 승인 도구를 바인딩하면 브로커/도구 HIL이 발화(정직).
        return AgentManifest(
            name="pipeline",
            consumes=("nodes", "mcps", "vectorTables", "memories"),
            description="노드를 순서대로 실행하는 파이프라인 에이전트(노코드, 스펙 259)",
            supports_hil=True,
        )

    def build_graph(self, ctx: AgentBuildContext):
        nodes = normalize_nodes((ctx.impl_config or {}).get("nodes"))
        if not nodes:
            # 노드 없음 — 조용한 빈 그래프 대신 단일 패스스루로 정직하게(입력을 그대로 모델에 태워
            # 최소 동작). 기본 모델도 없으면 build 시점에 명확히 실패(_model_from_node).
            nodes = [{"name": "노드1", "prompt": "사용자 입력에 답하세요.", "model_cfg": None, "tools": [], "context": "carry"}]

        # 노드 도구 해석(스펙 265) — 정확 일치 우선. MCP 도구의 런타임 이름은 `서버__도구`(_safe_name)라
        # UI/설정이 민이름("wiki_search")으로 저장한 경우 정확 일치가 0이 되고, 도구가 조용히 미바인딩돼
        # 모델이 "호출한 척" 환각하는 버그가 났다(스펙 264 후속 실측). 접미가 유일하면 매칭(자가치유),
        # 두 서버에 동명 도구면 모호 → 스킵(정직 — 아무거나 바인딩 금지). 후보는 전부 ctx.tools(이미
        # RBAC 스코프) 안이라 권한 영향 0.
        by_name = {t.name: t for t in (ctx.tools or [])}
        by_suffix: dict[str, list] = {}
        for t in ctx.tools or []:
            if "__" in t.name:
                by_suffix.setdefault(t.name.split("__", 1)[1], []).append(t)

        def _resolve_tool(name: str):
            if name in by_name:
                return by_name[name]
            cands = by_suffix.get(name) or []
            return cands[0] if len(cands) == 1 else None
        ids = _unique_node_ids(nodes)
        g = StateGraph(_State)

        def _make_step(nid: str, node: dict):
            model = _model_from_node(node, ctx)
            node_tools = [t for t in (_resolve_tool(name) for name in node["tools"]) if t is not None]
            bound = model.bind_tools(node_tools) if node_tools else model
            prompt = node["prompt"]
            clean = node.get("context") == "clean"
            fmt = node.get("format") or "text"
            fields = node.get("fields") or []
            node_mem = node.get("memories") or []
            mem_mode = node.get("memoryQuery") or "user"
            node_hd = node.get("historyDepth")  # 단기 기억 창(스펙 270) — None=에이전트 상속(프록시 기본값)

            async def _history_block(reentry: bool) -> list:
                # 단기 기억(스펙 270) — 이전 대화 슬라이스를 프롬프트 앞에 주입. clean은 대화 격리(결정 가),
                # 프록시 없으면(비노드형) 빈 리스트. 재진입(도구 루프)에도 주입해 대화가 루프 내내 보이게
                # (무회귀 — 오늘은 시드된 대화가 도구 루프 내내 보임), 단 기록은 첫 진입만(트레이스 스팸 방지).
                if clean or ctx.history_window is None:
                    return []
                try:
                    return await ctx.history_window(node_hd, node=nid, record=not reentry)
                except Exception:  # noqa: BLE001 — 창 장애는 대화 없이 진행(graceful, 회상과 동결)
                    log.warning("노드 단기 기억 실패(node=%s) — 대화 없이 진행", nid)
                    return []

            async def _recall_block(msgs: list, reentry: bool) -> str:
                # 노드별 회상(스펙 268 P2) — 첫 진입에만(재진입=도구 루프 중간, 자체 문맥 보유).
                # 프록시(플랫폼 주입·스코프 고정)를 키워드로 호출 — user=사용자 입력(캐시 공유),
                # input=이 노드가 받은 마지막 메시지(개별 키워드). 실패는 노드를 죽이지 않음(graceful).
                if reentry or not node_mem or ctx.memory_recall is None:
                    return ""
                q = None if mem_mode == "user" else (_text_of(msgs[-1]) if msgs else None)
                try:
                    text = await ctx.memory_recall(q, node=nid)
                except Exception:  # noqa: BLE001 — 회상 장애는 회상 없이 진행(기존 graceful 결)
                    log.warning("노드 회상 실패(node=%s) — 회상 없이 진행", nid)
                    return ""
                return f"\n\n# 관련 기억(회상됨)\n{text}" if text else ""
            # 출력 형식 강제(스펙 261): JSON이면 시스템 프롬프트에 지시를 덧붙여 첫 시도부터 JSON 지향.
            sys_content = prompt
            if fmt == "json":
                key_req = f" 반드시 다음 키를 포함하세요: {', '.join(fields)}." if fields else ""
                sys_content = (
                    f"{prompt}\n\n[출력 형식] 최종 답변은 유효한 JSON 객체 하나로만 출력하세요"
                    f"(도구 호출은 예외). 코드블록·설명·주석 없이 JSON만.{key_req}"
                )

            async def _finalize(resp):
                # JSON 강제는 노드의 최종 응답(tool_calls 없음)에만. 도구 루프 중간은 건드리지 않음.
                if fmt != "json" or getattr(resp, "tool_calls", None):
                    return resp
                obj = _coerce_json(_text_of(resp), fields)
                if obj is None:
                    # 1회 보정 — unbound 모델(도구 없이)에 형식 변환만 요청.
                    repair = await model.ainvoke([
                        SystemMessage(content=sys_content),
                        HumanMessage(content="다음 내용을 위 형식의 유효한 JSON 객체 하나로 변환해 JSON만 출력하세요:\n\n" + _text_of(resp)),
                    ])
                    obj = _coerce_json(_text_of(repair), fields)
                if obj is not None:
                    return AIMessage(content=json.dumps(obj, ensure_ascii=False))
                # 강제 실패 — 원문 통과(크래시 0·거짓 JSON 조작 안 함). codex P3: "조용한 퇴화"를
                # 관측 가능하게 로그(소비층이 format=json을 신뢰하다 실패하는 계약 위험을 운영이 인지).
                log.warning("노드형 JSON 강제 실패 — 원문 통과(형식 미충족). fields=%s", fields)
                return resp

            async def _step(state: _State) -> dict:
                msgs = state["messages"]
                # clean 첫 진입(스펙 260): 쌓인 대화를 걷어내고 앞 결과만 새 입력으로 격리. 재진입
                # (도구 루프 뒤 = 마지막이 ToolMessage)은 격리 buffer 위에서 정상 누적(carry 경로).
                reentry = bool(msgs) and isinstance(msgs[-1], ToolMessage)
                # 노드별 회상 블록(스펙 268 P2) — 첫 진입에만 시스템 프롬프트에 덧붙임.
                sys = SystemMessage(content=sys_content + await _recall_block(msgs, reentry))
                if clean and not reentry:
                    prev_text = _text_of(msgs[-1]) if msgs else ""
                    human = HumanMessage(content=prev_text)
                    resp = await _finalize(await bound.ainvoke([sys, human]))
                    # 이전 메시지 전부 제거 + [앞 결과 입력, 응답]만 남김(격리 경계 — 하류도 여기부터 봄).
                    removals = [RemoveMessage(id=m.id) for m in msgs if getattr(m, "id", None)]
                    return {"messages": [*removals, human, resp]}
                # 단기 기억(스펙 270) — 이전 대화 슬라이스를 sys와 누적 msgs 사이에 주입([sys, 대화, 입력…]).
                # 슬라이스는 상태에 누적 안 함(노드마다 자기 depth로 새로 주입) — carry/clean은 턴내 흐름만 관장.
                history = await _history_block(reentry)
                resp = await _finalize(await bound.ainvoke([sys, *history, *msgs]))
                return {"messages": [resp]}

            return _step, node_tools

        # 노드 등록 + 노드별 도구 루프(도구 있으면 <id>__tools ToolNode 자기 루프).
        steps: list[tuple] = []
        for nid, node in zip(ids, nodes):
            step, node_tools = _make_step(nid, node)
            g.add_node(nid, step)
            steps.append((nid, node_tools))

        g.add_edge(START, ids[0])
        for i, (nid, node_tools) in enumerate(steps):
            nxt = ids[i + 1] if i + 1 < len(ids) else END
            if node_tools:
                tools_id = f"{nid}__tools"
                g.add_node(tools_id, ToolNode(node_tools))

                def _route(state: _State, _nxt=nxt, _tools_id=tools_id) -> str:
                    last = state["messages"][-1]
                    return _tools_id if getattr(last, "tool_calls", None) else _nxt

                g.add_conditional_edges(nid, _route, {tools_id: tools_id, nxt: nxt})
                g.add_edge(tools_id, nid)  # 도구 실행 후 같은 노드 재진입(표준 루프)
            else:
                g.add_edge(nid, nxt)
        return g.compile(checkpointer=ctx.checkpointer)

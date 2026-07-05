"""산출물형 에이전트 뼈대(스펙 188) — produce(로직 실행) → Artifact(산출물) → sink(처리).

스펙 102(OrchestrationAgentBase) 패턴의 재적용: **조상이 골격과 불변식을 소유**하고 자식은 유일한
구멍 `produce(ctx)`만 채운다. 구체 로직(타겟팅 등)은 자식이며, 뼈대는 다목적이다(사용자 교정 —
"이런 기능을 추상적으로 제공하고 알맹이를 유저가 정의").

골격이 소유하는 것:
- 수명주기: produce 실행 → Artifact 구조 검증 → state 커밋(+최종 요약 메시지). sink 1호는 frame
  (chat.py가 state.artifact를 프레임으로 노출 — P4).
- 멀티턴 기계: `ctx.ask`/`ctx.form`은 LangGraph `interrupt()`로 그래프를 멈추고, 다음 사용자 입력이
  `Command(resume={"type":"text"|"form", ...})`로 재개한다(승인 흐름과 같은 체크포인트 기계).
  **재실행 시맨틱**: 재개 시 produce 노드는 처음부터 다시 실행되고 interrupt()는 기록된 답을 순서대로
  반환한다(LangGraph 계약). 그래서 —
- **스텝 캐시(리플레이 결정성)**: extract/rag/tool 같은 비-interrupt 프리미티브는 호출 순서 인덱스로
  결과를 스레드별 캐시에 기록하고, 재실행에서는 재호출 없이 기록을 반환한다(조율형이 스펙 116에서
  state 커밋으로 푼 문제의 produce판 — 중복 부수효과·비용 차단 + 비결정 LLM 재추출로 인한 리플레이
  드리프트 차단). 캐시는 프로세스 메모리(재시작 시 소실 → read-only 프리미티브 재실행으로 폴백,
  P1 경계 — 영속화는 후속).
- **결정성 계약(문서화)**: produce는 프리미티브 반환값 외의 비결정 입력(시계·난수)에 분기하면 안 된다
  — 리플레이가 같은 경로를 밟아야 기록된 답이 올바른 interrupt에 매칭된다(Temporal류 워크플로와 동일
  규율).
- 보안 경계: 프리미티브는 **닫힌 집합**(ask·form·rag·tool·extract). rag/tool은 정책 스코프된
  `ctx.broker`를 경유하므로(스펙 100 deny-by-default) 이 뼈대가 여는 새 권한이 없다.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import OrderedDict
from dataclasses import dataclass
from typing import Annotated, Any, TypedDict, final

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import interrupt

from ..runtime import AgentBuildContext, AgentManifest


class _State(TypedDict):
    messages: Annotated[list, add_messages]
    artifact: dict | None  # 완성 산출물({kind,data,raw}) — sink(frame)가 소비


@dataclass
class Artifact:
    """produce의 반환 — 뼈대는 구조(kind 비어있지 않음·data dict)만 검증한다.
    의미 검증(값 조합의 타당성)은 produce 책임(자기 도메인이므로)."""

    kind: str
    data: dict
    raw: str | None = None


# ----------------------------- 스텝 캐시 (리플레이 결정성) -----------------------------
# thread_id → 프리미티브 결과 로그(호출 순서). produce 노드가 재실행돼도(interrupt 재개 시맨틱)
# 이미 실행된 extract/rag/tool은 재호출 없이 기록을 반환한다. LRU 상한으로 무한 성장 방지.
_STEP_CACHE: OrderedDict[str, list] = OrderedDict()
_STEP_CACHE_MAX = 256


def _step_log(thread_id: str) -> list:
    log = _STEP_CACHE.get(thread_id)
    if log is None:
        log = []
        _STEP_CACHE[thread_id] = log
        while len(_STEP_CACHE) > _STEP_CACHE_MAX:
            _STEP_CACHE.popitem(last=False)
    else:
        _STEP_CACHE.move_to_end(thread_id)
    return log


def _drop_step_log(thread_id: str) -> None:
    _STEP_CACHE.pop(thread_id, None)


def _resume_text(envelope: Any) -> str:
    """재개 봉투(union — 스펙 188 이중 입력)에서 텍스트를 꺼낸다. 뼈대가 봉투 해석을 소유해
    produce는 분기를 모른다. 문자열이 직접 오면(레거시/테스트) 그대로 수용."""
    if isinstance(envelope, dict):
        return str(envelope.get("message") or envelope.get("text") or "")
    return str(envelope or "")


class ProduceContext:
    """produce()에 주입되는 프리미티브 핸들(닫힌 집합 — 뼈대가 보안 경계 소유).

    - `text`: 이 실행을 시작한 사용자 발화(마지막 user 메시지).
    - `ask(question)`: 질문을 던지고 사용자의 다음 입력을 받는다(턴 넘김 — interrupt).
    - `extract(instruction, text)`: LLM 구조화 추출(JSON dict 반환). 스텝 캐시 경유.
    - `rag(collection, query)` / `tool(cap_id, args)`: 정책 스코프된 broker 경유. 스텝 캐시 경유.
    - `form(...)`: P2(스펙 188)에서 승인 프레임 일반화로 추가 — 지금은 NotImplementedError.
    """

    def __init__(self, *, text: str, model: Any, broker: Any, step_log: list):
        self.text = text
        self._model = model
        self._broker = broker
        self._log = step_log
        self._idx = 0  # 이번 (재)실행의 스텝 커서 — 로그보다 앞이면 리플레이, 끝이면 실호출

    # -- interrupt 프리미티브(캐시 불필요 — LangGraph가 기록된 답을 순서 매칭으로 반환) --
    def ask(self, question: str) -> str:
        envelope = interrupt({"kind": "ask", "text": question})
        return _resume_text(envelope).strip()

    def form(self, fields: list[dict], prefill: dict | None = None) -> dict:
        raise NotImplementedError("ctx.form은 스펙 188 P2에서 제공됩니다")

    # -- 비-interrupt 프리미티브(스텝 캐시 경유 — 리플레이 시 재호출 금지) --
    async def _cached(self, call):
        if self._idx < len(self._log):
            result = self._log[self._idx]
        else:
            result = await call()
            self._log.append(result)
        self._idx += 1
        return result

    async def extract(self, instruction: str, text: str) -> dict:
        """LLM 구조화 추출 — instruction이 원하는 JSON 형태를 지시하고, 응답에서 첫 JSON 객체를
        파싱한다. 실패 시 빈 dict(호출측이 되물음 등으로 처리 — 조용히 죽지 않게 로그는 값으로 남음)."""

        async def call():
            if self._model is None:
                return {}
            msgs = [
                SystemMessage(
                    content=(
                        "다음 지시에 따라 텍스트에서 정보를 추출해 JSON 객체 **하나만** 출력하세요."
                        " 설명·마크다운 없이 JSON만.\n\n# 지시\n" + instruction
                    )
                ),
                HumanMessage(content=text),
            ]
            resp = await self._model.ainvoke(msgs)
            return _first_json_obj(getattr(resp, "content", "") or "")

        return await self._cached(call)

    async def rag(self, collection: str, query: str):
        """컬렉션 검색 — broker의 rag 능력 경유(may_use_collection 등 기존 게이트 그대로)."""

        async def call():
            if self._broker is None:
                return None  # deny-by-default(브로커 미주입 = 발견 공집합)
            return await self._broker.invoke(f"rag:{collection}", {"text": query})

        return await self._cached(call)

    async def tool(self, cap_id: str, args: dict):
        """MCP 도구 호출 — broker 경유(배선 권한 113·승인 정책 그대로)."""

        async def call():
            if self._broker is None:
                return None
            return await self._broker.invoke(cap_id, args)

        return await self._cached(call)


def _first_json_obj(text: str) -> dict:
    """응답 텍스트에서 첫 최상위 JSON 객체를 찾아 파싱(순수함수 — 단위 검증). 실패 시 {}."""
    import json

    depth = 0
    start = -1
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start >= 0:
                    try:
                        obj = json.loads(text[start : i + 1])
                        return obj if isinstance(obj, dict) else {}
                    except ValueError:
                        start = -1  # 파싱 실패 — 다음 후보 계속 탐색
    return {}


def _last_user_text(state: _State) -> str:
    for msg in reversed(state["messages"]):
        content = getattr(msg, "content", None)
        if content is None and isinstance(msg, dict):
            content = msg.get("content")
        role = getattr(msg, "type", None) or (msg.get("role") if isinstance(msg, dict) else None)
        if content and role in ("human", "user", None):
            return content if isinstance(content, str) else str(content)
    return ""


def summarize_artifact(art: Artifact) -> str:
    """완성 산출물의 사용자용 요약(순수함수). data가 평면 dict면 `키=값` 나열, 아니면 JSON."""
    import json

    parts = []
    for k, v in art.data.items():
        if isinstance(v, (str, int, float, bool)) or v is None:
            parts.append(f"{k}={v}")
        else:
            parts.append(f"{k}={json.dumps(v, ensure_ascii=False)}")
    body = " · ".join(parts) if parts else "(빈 산출물)"
    return f"✅ 산출물 완성 — {art.kind}: {body}"


class ArtifactAgentBase(ABC):
    """산출물형 에이전트의 **공통 조상**(스펙 188). 골격(produce→검증→커밋)과 불변식(멀티턴
    interrupt 기계·스텝 캐시 리플레이·프리미티브 닫힌 집합)을 소유한다. 자식의 유일한 구멍은
    `produce(ctx)` — `describe`/`build_graph`는 @final(재정의 = 불변식 우회, 스펙 102 규율)."""

    #: 레지스트리/매니페스트 표시 이름(자식이 설정).
    NAME: str = "artifact"
    #: 매니페스트 설명(자식이 설정).
    DESCRIPTION: str = "산출물(구조화 데이터)을 만들기 위해 노력하는 에이전트"

    @final
    def describe(self) -> AgentManifest:
        # ask/form의 interrupt 재개가 곧 HIL 계약 — supports_hil=True 정직 표기(조상 소유).
        return AgentManifest(name=self.NAME, description=self.DESCRIPTION, supports_hil=True)

    @abstractmethod
    async def produce(self, ctx: ProduceContext) -> Artifact:
        """산출물을 만드는 유저 정의 로직 — 프리미티브(ctx.*)만으로 조립한다.
        **결정성 계약**: 프리미티브 반환값 외의 비결정 입력(시계·난수)에 분기 금지(리플레이 매칭)."""
        ...

    @final
    def build_graph(self, ctx: AgentBuildContext):
        model = _make_model(ctx)  # 모델 미설정이어도 ask-only produce는 동작(extract 시 {})
        broker = ctx.broker

        async def produce_node(state: _State, config) -> dict:
            thread_id = (config or {}).get("configurable", {}).get("thread_id", "")
            pctx = ProduceContext(
                text=_last_user_text(state),
                model=model,
                broker=broker,
                step_log=_step_log(thread_id) if thread_id else [],
            )
            art = await self.produce(pctx)
            # 구조 검증(뼈대 소유) — produce가 무엇을 반환하든 여기서 걸러진다.
            if not isinstance(art, Artifact) or not art.kind or not isinstance(art.data, dict):
                raise RuntimeError("produce는 Artifact(kind, data:dict)를 반환해야 합니다")
            if thread_id:
                _drop_step_log(thread_id)  # 완주 — 리플레이 캐시 정리
            return {
                "messages": [AIMessage(content=summarize_artifact(art))],
                "artifact": {"kind": art.kind, "data": art.data, "raw": art.raw},
            }

        g = StateGraph(_State)
        g.add_node("produce", produce_node)
        g.add_edge(START, "produce")
        g.add_edge("produce", END)
        # checkpointer 주입 보존 — ask/form interrupt 재개(HIL 계약)의 전제.
        return g.compile(checkpointer=ctx.checkpointer)


def _make_model(ctx: AgentBuildContext):
    """model_cfg가 온전할 때만 ChatOpenAI 구성 — ask-only produce는 모델 없이도 돌아야 해서
    (조율형 _model_from_cfg처럼) 즉시 raise하지 않고 None을 허용한다(extract가 {} 반환)."""
    cfg = ctx.model_cfg or {}
    base_url = cfg.get("base_url") or ""
    model_id = cfg.get("model_id") or ""
    if not base_url or not model_id:
        return None
    from langchain_openai import ChatOpenAI

    cfg_params = cfg.get("params") or {}
    temperature = ctx.params.get("temperature", cfg_params.get("temperature", 0.2))
    return ChatOpenAI(
        base_url=base_url,
        api_key=cfg.get("api_key") or "sk-noauth",
        model=model_id,
        temperature=temperature,
        extra_body={"chat_template_kwargs": {"enable_thinking": cfg_params.get("enable_thinking", False)}},
    )


# ----------------------------- 데모 1: slot-fill (대조 구현) -----------------------------
@dataclass(frozen=True)
class SlotField:
    key: str
    label: str
    hint: str = ""


class SlotFillDemoAgent(ArtifactAgentBase):
    """고정 필드 목록을 대화로 채우는 최단 경로 데모(스펙 188 §E-2). 동적 합성(타겟팅, P3)의
    대조 구현 — 두 produce가 같은 뼈대에서 갈라져야 추상이 안 샌 것(둘째 구현 규율)."""

    NAME = "artifact_slotfill"
    DESCRIPTION = "고정 필드(출장 신청)를 대화로 채워 산출물을 만드는 데모(스펙 188)"

    FIELDS: tuple[SlotField, ...] = (
        SlotField("destination", "목적지", "예: 서울, 부산"),
        SlotField("period", "기간", "예: 3월 2일부터 3일간"),
        SlotField("budget", "예산", "예: 50만원"),
    )

    async def produce(self, ctx: ProduceContext) -> Artifact:
        values: dict[str, str] = {}
        for f in self.FIELDS:
            # 빈 답이면 같은 필드를 되묻는다(무한루프 방지 상한 3회 — 그 뒤 "(미입력)" 기록).
            for attempt in range(3):
                suffix = f" ({f.hint})" if f.hint and attempt == 0 else ""
                ans = ctx.ask(f"{f.label}을(를) 알려주세요{suffix}")
                if ans:
                    values[f.key] = ans
                    break
            else:
                values[f.key] = "(미입력)"
        return Artifact(kind="travel-request", data=values, raw=ctx.text)

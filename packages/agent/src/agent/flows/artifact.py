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
#
# **멱등성 계약(경계 — 적대 검증 P1-4)**: 이 로그는 **인메모리**다. 프로세스 재시작이나 동시
# interrupt 스레드가 256개를 넘어 evict되면 로그가 사라져, 재개 시 이미 실행된 프리미티브가
# **재호출**된다. 따라서 produce가 부르는 프리미티브(특히 ctx.tool/ctx.rag)는 **멱등(부수효과
# 없음)** 이어야 한다 — 재실행돼도 안전(같은 입력→같은/최신 데이터). 서빙 MCP는 이 불변식을
# `_SIDE_EFFECT_FREE_TOOLS` 게이트로 강제하고, produce의 결정성 계약(아래 produce docstring)도
# 같은 요구다. 스텝로그를 체크포인트에 영속화(재시작 넘어 정확 재개)는 향후 과제(스펙 188 §빚).
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


# ----------------------------- 폼 순수함수 (P2 — 단위 검증 대상) -----------------------------
def validate_form_values(fields: list[dict], values: dict | None) -> dict:
    """제출/프리필 값 검증(순수) — **알려진 key만**, candidates가 있으면 그 안의 값만, 빈 값 제외.
    서버(chat.py)와 뼈대(ctx.form)가 같은 함수를 쓴다(이중 게이트·drift 0)."""
    ok: dict = {}
    by_key = {f["key"]: f for f in fields if f.get("key")}
    for k, v in (values or {}).items():
        f = by_key.get(k)
        if f is None or v in (None, ""):
            continue
        cands = f.get("candidates")
        # candidates는 **리스트형 enum**일 때만 멤버십 게이트한다 — 문자열이면 `v in "문자열"`이
        # substring 오판정("a"∈"abc")이라 후보 밖 값이 새어든다(적대 검증 P2-1 하드닝).
        if isinstance(cands, (list, tuple, set)) and cands and v not in cands:
            continue
        ok[k] = v
    return ok


def missing_required(fields: list[dict], values: dict) -> list[str]:
    """미충족 필수 필드 key 목록(순수) — required 기본 True."""
    return [f["key"] for f in fields if f.get("required", True) and not values.get(f.get("key"))]


def merge_text_into_fields(fields: list[dict], values: dict, text: str) -> dict:
    """폼 대기 중 **텍스트 입력**의 결정적 1차 병합(순수함수) — 후보(enum) 필드에 한해 후보 문자열이
    텍스트에 등장하면 채운다(모델 불요·리플레이 결정적). 이미 찬 필드는 덮지 않는다.
    (자유 텍스트 필드의 2차 병합은 ctx.form이 extract(LLM)로 시도 — 모델 없으면 생략.)"""
    out = dict(values)
    for f in fields:
        key = f.get("key")
        if not key or out.get(key):
            continue
        # 긴 후보 우선 — "최근 한 달"이 "최근"의 접두를 공유할 때 더 구체적인 쪽을 채운다(결정적).
        for c in sorted(f.get("candidates") or [], key=len, reverse=True):
            if c and c in (text or ""):
                out[key] = c
                break
    return out


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

    async def form(self, fields: list[dict], prefill: dict | None = None, *, confirm: bool = False) -> dict:
        """폼 프레임을 띄우고 값을 받는다(P2) — **이중 입력 일급**(스펙 188 설계 기둥). 재개 봉투:
        - {"type":"form","values":{...}}: 제출값(서버가 이미 필드 명세로 1차 검증 — 여기서 재검증,
          이중 게이트).
        - {"type":"text","message":...}: 폼 대기 중 채팅 텍스트 → 결정적 후보 매칭(1차) + LLM
          extract(2차, 모델 있을 때)로 병합 후 **갱신된 프리필로 폼 재제시**.
        활성 필수가 전부 찰 때까지 반복 — produce는 최종 values만 본다(분기 소유=뼈대)."""
        values = validate_form_values(fields, dict(prefill or {}))
        note = ""
        presented = False  # confirm=True면 프리필이 완전해도 최소 1회 폼을 보여 확인받는다.
        reconfirm = False  # confirm 계약에서 **텍스트 병합으로 값이 바뀌면** 확정 전 재제시(P2-2).
        while missing_required(fields, values) or (confirm and not presented) or reconfirm:
            presented = True
            reconfirm = False
            payload: dict = {"kind": "form", "fields": fields, "prefill": values}
            if note:
                payload["note"] = note
            note = ""
            envelope = interrupt(payload)
            if isinstance(envelope, dict) and envelope.get("type") == "form":
                values.update(validate_form_values(fields, envelope.get("values")))
                if missing_required(fields, values):
                    note = "필수 항목이 남아 있어요 — 마저 채워 주세요."
            else:
                text = _resume_text(envelope)
                before = dict(values)
                values = merge_text_into_fields(fields, values, text)
                still = missing_required(fields, values)
                if still and self._model is not None and text:
                    # 2차: 남은 필드만 LLM 추출(스텝 캐시 경유 — 리플레이 결정적).
                    remain = [f for f in fields if f.get("key") in still]
                    spec = ", ".join(
                        f'"{f["key"]}"({f.get("label") or f["key"]})' for f in remain
                    )
                    got = await self.extract(
                        f"다음 필드의 값을 찾아 {{키: 값}} JSON으로: {spec}. 없는 필드는 생략.",
                        text,
                    )
                    values.update(validate_form_values(fields, got))
                if values == before:
                    note = "입력에서 채울 값을 찾지 못했어요 — 폼으로 선택하거나 다시 말씀해 주세요."
                elif confirm:
                    # 텍스트(결정적 substring/LLM 추출)는 **오후보·부정어**를 잘못 채울 수 있다
                    # ("서울 말고 부산"이 '서울'을 채우는 등). confirm 계약이면 병합값을 곧장 확정하지
                    # 않고 **갱신된 프리필을 재제시**해 사용자가 검토·제출(폼)로 확정하게 한다
                    # (무확인 확정 봉인 — 적대 검증 P2-2). 폼 제출만이 최종 확정 경로.
                    note = "말씀하신 내용으로 채웠어요 — 확인 후 제출해 주세요."
                    reconfirm = True
        return values

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
    `produce(ctx)` — `describe`/`build_graph`는 @final(재정의 = 불변식 우회, 스펙 102 규율).

    **신뢰 모델(경계 — 적대 검증 P1-5)**: produce는 `register_agent`로 코드에 등록되는 **신뢰
    1급 구현**(source=code — 리뷰 대상, in-process)이지 사용자가 런타임에 넘기는 미신뢰 입력이
    아니다. 따라서 "프리미티브 닫힌 집합"은 미신뢰 코드를 가두는 **샌드박스가 아니라**, 저작자가
    안전한 조립 블록(정책 스코프 broker·리플레이 결정 캐시·interrupt HIL)만으로 짜도록 하는
    **저작 규율**이다. 미신뢰 produce 본문을 외부에서 받아 실행하려면 별도 프로세스/샌드박스
    경계가 필요하다(그 경우 ctx._model/_broker 접근을 막아야 함) — 현 설계 범위 밖."""

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


# ----------------------------- 데모 2: targeting (동적 폼 합성 — 사용자 시나리오) -----------------------------
def match_entities(utterance: str, entities: list[dict]) -> list[dict]:
    """발화에서 카탈로그 엔티티를 결정적으로 매칭(순수함수) — label/synonyms 부분 문자열.
    카탈로그 순서 보존(안정) — 모델 불요·리플레이 결정적. 실 임베딩 환경에선 ctx.rag 결과가
    이 매칭에 합류한다(produce 참고)."""
    hits = []
    for e in entities:
        keys = [e.get("label") or "", *(e.get("synonyms") or [])]
        if any(k and k in (utterance or "") for k in keys):
            hits.append(e)
    return hits


_RAG_ENTITY_RE = None  # lazy compile


def entity_ids_from_rag_text(text: str) -> list[str]:
    """RAG 히트 텍스트에서 엔티티 id 마커(`[entity:<id>]`)를 추출(순수) — 카탈로그 문서가 이 마커를
    본문에 심는 규약. 순서 보존·중복 제거."""
    global _RAG_ENTITY_RE
    if _RAG_ENTITY_RE is None:
        import re

        _RAG_ENTITY_RE = re.compile(r"\[entity:([a-z0-9_]+)\]")
    seen: list[str] = []
    for m in _RAG_ENTITY_RE.findall(text or ""):
        if m not in seen:
            seen.append(m)
    return seen


class TargetingDemoAgent(ArtifactAgentBase):
    """타겟팅 조건 수집 데모(스펙 188 §E-1 — 사용자 시나리오 그대로): 발화→요소 매칭(RAG+카탈로그)→
    엔티티별 성격 조회(도구)→**폼 동적 합성**(후보 SelectBox+발화 프리필)→확인→conditions JSON.

    slot-fill(정적 필드)과 같은 뼈대에서 갈라지는 **둘째 구현**(추상 무누수 측정, 스펙 102 규율).
    매칭은 ① ctx.rag(실 임베딩 환경 — 히트 본문의 [entity:id] 마커) ② 카탈로그 동의어(결정적 폴백)의
    합집합 — mock 임베딩 환경에서도 데모가 결정적으로 돈다(rag 오류/미배선은 조용히 폴백,
    카탈로그 0건은 조용히 넘어가지 않고 되묻는다 — 스펙 125 원칙)."""

    NAME = "artifact_targeting"
    DESCRIPTION = "타겟팅 조건을 대화+동적 폼으로 수집하는 데모(스펙 188)"
    CATALOG_MCP = "targeting-catalog"
    RAG_COLLECTION = "targeting-entities"

    async def produce(self, ctx: ProduceContext) -> Artifact:
        utter = ctx.text or ctx.ask("어떤 유저를 타겟팅할까요? 조건을 문장으로 말씀해 주세요.")
        # ① 카탈로그 목록(도구) — 없으면 정직하게 종료(빈 폼을 조용히 띄우지 않는다).
        listing = await ctx.tool(f"mcp:{self.CATALOG_MCP}/list_entities", {})
        catalog = _first_json_obj(getattr(listing, "text", "") or "").get("entities") or []
        if not catalog:
            return Artifact(
                kind="targeting",
                data={"conditions": [], "error": "타겟팅 카탈로그를 찾을 수 없습니다(도구 미배선?)"},
                raw=utter,
            )
        # ② 매칭 = rag 마커 ∪ 동의어(결정적) — rag는 실 임베딩 환경의 1차 경로, 오류는 무시(폴백).
        rag_res = await ctx.rag(self.RAG_COLLECTION, utter)
        rag_ids = entity_ids_from_rag_text(getattr(rag_res, "text", "") or "")
        matched = match_entities(utter, catalog)
        matched_ids = [e["id"] for e in matched]
        for rid in rag_ids:
            if rid not in matched_ids:
                ent = next((e for e in catalog if e.get("id") == rid), None)
                if ent:
                    matched.append(ent)
                    matched_ids.append(rid)
        for _ in range(2):
            if matched:
                break
            utter = ctx.ask("말씀하신 조건에서 타겟팅 항목을 찾지 못했어요 — 다르게 말씀해 주시겠어요?")
            matched = match_entities(utter, catalog)
        if not matched:
            return Artifact(kind="targeting", data={"conditions": []}, raw=utter)
        # ③ 엔티티별 성격 조회(도구) → 폼 필드 합성(후보 SelectBox).
        fields: list[dict] = []
        for e in matched:
            detail_res = await ctx.tool(
                f"mcp:{self.CATALOG_MCP}/get_entity", {"entity_id": e["id"]}
            )
            detail = _first_json_obj(getattr(detail_res, "text", "") or "")
            fields.append(
                {
                    "key": e["id"],
                    "label": detail.get("label") or e.get("label") or e["id"],
                    "candidates": detail.get("candidates") or [],
                    "required": True,
                }
            )
        # ④ 발화 프리필(결정적 후보 매칭) → 폼 제시(confirm=True: 프리필 완전해도 확인 1회).
        prefill = merge_text_into_fields(fields, {}, utter)
        values = await ctx.form(fields, prefill, confirm=True)
        conditions = [
            {"entity_id": f["key"], "label": f["label"], "value": values.get(f["key"])}
            for f in fields
        ]
        return Artifact(kind="targeting", data={"conditions": conditions}, raw=utter)

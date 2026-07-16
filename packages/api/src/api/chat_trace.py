"""트레이스 조립(오버라이드·브로커 호출 투영·종결 트레이스) — chat.py에서 분할(스펙 291 3b·386).

파사드는 chat.py(재수출 계약) — 인스펙터가 소비하는 trace 필드의 정화·화이트리스트 단일 출처.
"""

import uuid

from agent.runtime import CustomAgent

from . import memory, runtime, trace_capture
from .chat_context import ChatContext
from .chat_history import _format_sent_measured
from .db import SessionLocal
from .models import Message

# 트레이스에 기록할 오버라이드 허용 키(스펙 134) — _load_context 병합 allowlist + systemPrompt.
_OVERRIDE_TRACE_KEYS = (
    "model",
    "temperature",
    "historyDepth",
    "mcps",
    "memories",
    "capabilities",
    "tools",
    "vectorTables",
    "systemPrompt",
)


def _trace_override_value(key: str, v: object) -> str | int | float | bool | list[str] | None:
    """오버라이드 값 1개를 트레이스 표시용으로 정화(131 프레임 재사용) — 기록 제외면 None.

    문자열=비밀 마스킹+캡 300, 리스트=항목별 캡 100·개수 20, 숫자 통과. systemPrompt는
    _load_context가 **비어있지 않을 때만 적용**(빈/공백은 무시) — 트레이스도 같은 가드를 미러
    (적용 안 된 값을 "적용됨"으로 기록 금지, codex 134 #1)."""
    from .memory import _sanitize

    if isinstance(v, str):
        if key == "systemPrompt" and not v.strip():
            return None
        return _sanitize(v, cap=300)
    if isinstance(v, (int, float, bool)):
        return v
    if isinstance(v, list):
        return [_sanitize(str(it), cap=100) for it in v[:20]]
    return None


def _overrides_trace(overrides: dict | None, nodes_status: str | None = None) -> dict | None:
    """이 턴에 적용된 오버라이드를 트레이스 표시용으로 정화(스펙 134) — 한 세션에 설정이 다른 턴이
    섞여도 턴별로 구분 가능하게 영구 기록. 실제 온 허용 키만 — 없으면 None(필드 미기록=무회귀)."""
    if not isinstance(overrides, dict):
        return None
    out: dict = {}
    for key in _OVERRIDE_TRACE_KEYS:
        if key not in overrides or overrides[key] is None:
            continue
        v = _trace_override_value(key, overrides[key])
        if v is not None:
            out[key] = v
    # 노드 오버라이드(스펙 287) — 프롬프트 전문 대신 요약(개수+적용 상태). mismatch도 기록해
    # "왜 안 먹었는지"를 표면화(스펙 125 계열 — 조용한 드롭 금지).
    if nodes_status is not None and isinstance(overrides.get("nodes"), list):
        out["nodes"] = {"count": len(overrides["nodes"]), "status": nodes_status}
    return out or None


def _broker_calls_trace(invocations: list[dict]) -> list[dict]:
    """브로커 호출 이력 → 트레이스 표시용 투영(스펙 130) — **키 화이트리스트 단일 출처**(메인/승인대기/
    재개 세 경로 공유, drift 0). 본문·args 불포함(087/092 원문 누출 0 유지)."""
    return [
        {
            k: v
            for k, v in inv.items()
            if k
            in (
                "node",
                "cap_id",
                "ms",
                "hits",
                "topScore",
                "error",
                "resultPreview",
                "hitsDetail",
                "minScore",
                "query",
                "local",
                "subTraceNodes",
            )
        }
        for inv in invocations
    ]


# ---------------------------------------------------------------- 종결 트레이스 조립(스펙 386 이동)
# chat.py에서 이동 — 트레이스 주석·조립 가족은 이 모듈이 정주지(파사드는 chat.py 재수출 계약 유지).

_MEMORY_SAVE_ITEM_CAP = 20  # 트레일링 이벤트/트레이스에 실을 기억 항목 상한
_MEMORY_SAVE_TEXT_CAP = 300  # 항목 본문 표시 상한(마스킹 후, 131/191 프레임 재사용)


def _annotate_execution(
    trace: dict,
    ctx: ChatContext,
    turn: dict,
    *,
    capture: trace_capture.TraceCaptureHandler,
    sent_messages: list[dict],
    impl: CustomAgent,
) -> None:
    """실행 메타 주석 — 버전(242)·도구 무발동 진단(236)·전송 전문 출처(205/131)."""
    if ctx.exec_version:
        # 실행 버전(스펙 242) — 이 턴이 어느 버전 config였나(지정 버전 미리보기 포함, 240 평가 귀속과 대칭).
        trace["agentVersion"] = ctx.exec_version
        if ctx.pinned_version:
            trace["versionPinned"] = True  # 미리보기 턴 표식(활성 아님)
    # 도구 무발동 진단(스펙 236) — 도구가 바인딩된 턴의 호출 수를 항상 기록. called=0이면 UI가
    # "왜 안 되는지" 후보(모델이 도구 호출 미지원(mock 등)·질문이 도구와 무관)를 표면화한다
    # (158 회상·125 검색 진단의 결 — 조용한 무발동 금지). impl이 도구 표면(mcps/vectorTables)을
    # 안 읽는 타입(route·artifact류)은 제외 — 그건 무발동이 아니라 설계상 무소비(폼이 이미 경고).
    consumes = impl.describe().consumes
    reads_tools = consumes is None or bool({"mcps", "vectorTables"} & set(consumes))
    if turn["tools"] and reads_tools:
        trace["toolDiag"] = {
            "bound": [getattr(tl, "name", "?") for tl in turn["tools"]][:20],
            "called": len(turn["calls_sink"]),
        }
    # 전송 프롬프트(스펙 205): 콜백 실측(마지막 모델 호출 — 커스텀 impl의 계획·도구 안내 포함)
    # 우선, 콜백 미발화면 기존 재구성(131) 폴백. 출처를 표기해 UI가 정직하게 라벨링.
    if capture.calls:
        trace["sentMessages"] = _format_sent_measured(capture.calls[-1])
        trace["modelCalls"] = len(capture.calls)
        trace["sentMessagesSource"] = "measured"
    else:
        trace["sentMessages"] = sent_messages  # 전송 프롬프트 전문(스펙 131, 메시지당 2000자 캡)
        trace["sentMessagesSource"] = "reconstructed"


def _annotate_context_sources(
    trace: dict, ctx: ChatContext, turn: dict, *, user_text: str, history_restore: dict | None
) -> None:
    """맥락 출처 주석 — 오버라이드(134)·재구성 실측(289)·브로커(130)·RAG(037)·메모리(079/268/270)."""
    ov_trace = _overrides_trace(ctx.overrides, ctx.overrides_nodes_status)
    if ov_trace:
        # 이 턴에 적용된 오버라이드(스펙 134) — 세션에 설정 다른 턴이 섞여도 턴별 구분 가능.
        trace["overrides"] = ov_trace
    if history_restore:
        # 히스토리 서버 재구성 실측(스펙 289 P1) — 몇 개를 몇 ms에 이어붙였나(캐시 재론의 근거 데이터).
        trace["historyRestore"] = history_restore
    if turn["broker"].invocations:
        # 브로커 호출 상세(스펙 130) — 조율형의 RAG 검색이 인스펙터에 "N건·최고 유사도"로 보이게.
        # 위임 없던 턴은 필드 자체가 없음(무회귀).
        trace["brokerCalls"] = _broker_calls_trace(turn["broker"].invocations)
    if ctx.rag_collections:
        # 구성된 RAG 컬렉션 — 호출 안 해도 인스펙터에 노출(실제 호출은 trace["mcp"]의 server="rag").
        trace["ragCollections"] = [c["name"] for c in ctx.rag_collections]
    if ctx.rag_unresolved:
        # 요청됐으나 해석 실패한 이름 — 도구가 조용히 비는 footgun을 인스펙터에 드러냄(타자검증 F).
        trace["ragUnresolved"] = ctx.rag_unresolved
    _annotate_memory_observations(trace, turn, user_text=user_text)


def _annotate_memory_observations(trace: dict, turn: dict, *, user_text: str) -> None:
    """메모리 관측 주석 — 회상 스코프/쿼리(079)·노드별 회상(268 P2)·단기 기억 창(270)."""
    if turn["used_memory"]:
        # None이 아닌 회상 축만 — {"user_id","run_id","agent_id"} 부분집합 (Inspector가 축별 렌더).
        trace["memoryScope"] = {k: v for k, v in turn["recall_scope"].items() if v}
        # 회상에 쓴 쿼리(=user_text)를 에코 — 0건 회상이어도 "조회 행위"를 인스펙터에 남긴다(스펙 079).
        # 표시 전용·길이상한(방금 그 유저가 보낸 텍스트라 경계 이동 없음).
        trace["memoryQuery"] = user_text[:300]
    if turn["memory_recalls"]:
        # 노드별 회상 기록(스펙 268 P2) — (node, query, hits, cached). 프록시가 조회마다 남김
        # (082 조회 행위 계측). 인스펙터가 노드 행에 귀속 렌더.
        trace["memoryRecalls"] = turn["memory_recalls"]
    if turn["history_windows"]:
        # 노드별 단기 기억 창 기록(스펙 270) — (node, depth, count). 프록시가 첫 진입에 남김
        # (082 조회 계측). 내용 아닌 건수만(누출 0). 인스펙터가 노드 행에 귀속 렌더.
        trace["historyWindows"] = turn["history_windows"]


def _final_trace(
    ctx: ChatContext,
    turn: dict,
    *,
    capture: trace_capture.TraceCaptureHandler,
    full: str,
    total_ms: int,
    messages: list[dict],
    sent_messages: list[dict],
    observed: list,
    impl: CustomAgent,
    user_text: str,
    history_restore: dict | None,
) -> tuple[dict, dict]:
    """정상/오류 종결 턴의 trace·tokens 조립 — 반환 (trace, tokens)."""
    prompt_chars = sum(len(m["content"]) for m in messages)
    # 토큰(스펙 205): 모델 usage 실측 우선, 부재 시 추정 폴백(estimated로 정직 표기).
    if capture.usage_seen:
        tokens = {"in": capture.tokens_in, "out": capture.tokens_out, "estimated": False}
    else:
        tokens = {**runtime.estimate_tokens(prompt_chars, len(full)), "estimated": True}
    trace = runtime.assemble_trace(
        agent_id=ctx.ext_agent_id,
        memories=turn["mem_hits"],
        mcp_calls=turn["calls_sink"],
        used_memory=turn["used_memory"],
        total_ms=total_ms,
        tokens=tokens,
        graph_observations=observed,
    )
    trace["contextMessages"] = len(messages)  # 모델에 넣은 메시지 수(historyDepth 적용 결과)
    if turn.get("build_ms"):
        trace["buildMs"] = turn[
            "build_ms"
        ]  # 매턴 그래프 재구성 비용 분해(스펙 368 — 캐시 367-D 잣대)
    _annotate_execution(trace, ctx, turn, capture=capture, sent_messages=sent_messages, impl=impl)
    _annotate_context_sources(
        trace, ctx, turn, user_text=user_text, history_restore=history_restore
    )
    return trace, tokens


def _summarize_saved(saved: list[dict]) -> dict:
    """백그라운드 기억 저장 결과를 인스펙터 표시용으로 정화(스펙 314) — 비밀 마스킹+캡. status:
    ok(1건+)/none(0건). count=원 건수(상한 전). items=[{event, text(마스킹)}]. event도 마스킹
    (codex P2: 백엔드 계약상 event는 '원문'이라 custom 백엔드가 secret-like 값을 넣을 수 있음)."""
    items: list[dict] = []
    for row in (saved or [])[:_MEMORY_SAVE_ITEM_CAP]:
        text = memory._sanitize(row.get("text", ""), cap=_MEMORY_SAVE_TEXT_CAP)
        if not text:
            continue
        items.append(
            {"event": memory._sanitize(str(row.get("event") or "ADD"), cap=16), "text": text}
        )
    return {"status": "ok" if items else "none", "count": len(saved or []), "items": items}


async def _finalize_memory_trace(mid: str, summary: dict) -> None:
    """저장 완료 후 그 assistant 메시지의 영속 trace에 memorySaved 병합(스펙 314) — 새로고침 시
    인스펙터가 결과를 다시 불러오게 한다. 잘못된/사라진/비-assistant mid는 no-op(codex P2 — 함수
    자체가 '남의 메시지 클로버 금지'를 보장하도록 role까지 확인)."""
    try:
        pk = uuid.UUID(mid)
    except (ValueError, TypeError):
        return
    async with SessionLocal() as db:
        msg = await db.get(Message, pk)
        if msg is None or msg.role != "assistant" or not isinstance(msg.trace, dict):
            return
        trace = dict(
            msg.trace
        )  # 새 dict 대입으로 JSON 컬럼 dirty 플래그 확실히(in-place 변형 아님)
        trace["memorySaved"] = summary
        msg.trace = trace
        await db.commit()

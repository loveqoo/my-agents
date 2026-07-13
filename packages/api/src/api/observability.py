"""관측·측정 계층(스펙 118→328) — LangGraph 실행 trace를 **OTEL(OTLP)로 내보내되 설정될 때만** 켜진다.

설계 원칙(스펙 118 계약 유지):
- **inert-until-configured**: `OTEL_EXPORTER_OTLP_ENDPOINT` 환경변수가 있을 때만 콜백을 붙이고,
  없으면 조용히 무동작(no-op). 패키지 미설치·초기화 실패도 예외 없이 빈 콜백으로 접는다
  (핵심 채팅 경로가 관측 때문에 깨지지 않게 — 관측은 부가물이지 하중이 아니다).
- **백엔드 중립**(스펙 328): 구 Langfuse SDK 직결을 제거하고 OTLP 표준으로 방출 — 수신은 회사
  Grafana 스택이든 Jaeger 컨테이너든 Langfuse(OTLP 수신)든 endpoint 주소만 바꿔 꽂는다.
- **전송 표면 최소화**: span에는 이름·모델·토큰 수·지연·에러 타입만 싣는다. 프롬프트·도구 인자·
  응답 본문은 싣지 않는다(외부 전송이므로 — 상세는 내부 trace/인스펙터가 소유).

기존 관측(스펙 085/086/100 — trace 이벤트·broker_invoke 노드)은 그대로. OTEL은 그 위에 얹는
**외부 집계/측정** 계층으로, 수치 기반 자율(목표 주고 반복)의 토대가 된다.
"""

from __future__ import annotations

import contextlib
import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable


def is_configured() -> bool:
    """OTEL 활성 조건 — OTLP endpoint가 env에 있을 때만(값은 exporter가 직접 읽음, 로그 미노출)."""
    return bool(os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"))


_TRACER: Any = None


def _tracer() -> Any:
    """TracerProvider 싱글턴 lazy 초기화 — BatchSpanProcessor(OTLP http/protobuf).

    exporter는 표준 env(`OTEL_EXPORTER_OTLP_ENDPOINT`·`OTEL_SERVICE_NAME`)를 스스로 소비한다.
    실패하면 None(graceful) — 호출측이 빈 콜백으로 접는다."""
    global _TRACER
    if _TRACER is not None:
        return _TRACER
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        provider = TracerProvider(
            resource=Resource.create(
                {"service.name": os.environ.get("OTEL_SERVICE_NAME", "my-agents-api")}
            )
        )
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        trace.set_tracer_provider(provider)
        _TRACER = trace.get_tracer("my-agents")
    except Exception:
        return None
    return _TRACER


def shutdown() -> None:
    """프로세스 종료 시 미전송 span flush(BatchSpanProcessor 큐) — lifespan 종료 훅이 부른다."""
    try:
        from opentelemetry import trace

        provider = trace.get_tracer_provider()
        force_flush = getattr(provider, "force_flush", None)
        if callable(force_flush):
            force_flush(timeout_millis=3000)
    except Exception:
        pass  # 종료 경로 — 관측 때문에 셧다운을 막지 않는다


def _make_handler() -> Any | None:
    """OTEL LangChain 콜백 핸들러 생성 — 미설치/실패 시 None(graceful)."""
    try:
        tracer = _tracer()
        if tracer is None:
            return None
        return _OtelCallbackHandler(tracer)
    except Exception:
        return None


def _safe(fn: Any) -> Any:
    """콜백 메서드 가드 — 관측 실패가 실행을 깨지 않게 전 구간 예외 삼킴."""

    def wrapper(*args: Any, **kwargs: Any) -> None:
        with contextlib.suppress(Exception):
            fn(*args, **kwargs)

    return wrapper


class _OtelCallbackHandler:
    """자작 thin LangChain→OTEL 변환기(스펙 328) — 서드파티 계측 라이브러리 불채택(의존 무게 대비
    이득 없음). 우리가 내는 span은 셋뿐: 루트(run) · llm · tool.

    LangChain 콜백의 run_id/parent_run_id 트리를 OTEL span 부모 관계로 옮긴다. 중간 chain은 span을
    만들지 않되(LangGraph 노드 체인은 소음) `_parents`에 링크만 기록해, llm/tool이 조상을 거슬러
    가장 가까운 실제 span에 붙게 한다. BaseCallbackHandler 상속 대신 duck-typing으로 필요한 메서드만
    구현(콜백 매니저는 존재하는 메서드만 부르고, raise_error=False 경로가 예외를 접는다)."""

    raise_error = False  # LangChain 콜백 계약 — 핸들러 예외를 실행으로 전파하지 않는다
    ignore_chain = False
    ignore_llm = False
    # 주의(역사적 기벽): on_tool_start는 ignore_agent 플래그에 게이트된다(langchain_core
    # callbacks/manager — 도구가 "agent" 콜백군 소속이던 시절 잔재). True면 tool span이 소리 없이
    # 빠진다 — 라이브 Jaeger 측정으로 발견(스펙 328).
    ignore_agent = False
    ignore_retriever = True
    ignore_chat_model = False
    run_inline = True  # 스레드 넘김 없이 현재 컨텍스트에서 실행(span 부모 추적 단순화)

    def __init__(self, tracer: Any) -> None:
        self._tracer = tracer
        self._spans: dict[Any, Any] = {}  # run_id → 살아있는 span(루트·llm·tool만)
        self._parents: dict[Any, Any] = {}  # run_id → parent_run_id(모든 이벤트 — 조상 탐색용)

    # -- 내부 헬퍼 --
    def _parent_span(self, parent_run_id: Any) -> Any | None:
        """가장 가까운 조상 span — 중간 chain(스팬 없음)은 건너뛴다. 순환 방어 상한 64."""
        cur = parent_run_id
        for _ in range(64):
            if cur is None:
                return None
            span = self._spans.get(cur)
            if span is not None:
                return span
            cur = self._parents.get(cur)
        return None

    def _start(self, name: str, run_id: Any, parent_run_id: Any, attrs: dict) -> None:
        from opentelemetry import trace as _t

        parent = self._parent_span(parent_run_id)
        ctx = _t.set_span_in_context(parent) if parent is not None else None
        span = self._tracer.start_span(name, context=ctx)
        for k, v in attrs.items():
            if v is not None:
                span.set_attribute(k, v)
        self._spans[run_id] = span

    def _end(self, run_id: Any, error: BaseException | None = None) -> None:
        span = self._spans.pop(run_id, None)
        self._parents.pop(run_id, None)
        if span is None:
            return
        if error is not None:
            from opentelemetry.trace import Status, StatusCode

            span.set_attribute("error.type", type(error).__name__.lstrip("_"))
            span.set_status(Status(StatusCode.ERROR))
        span.end()

    # -- chain: 루트만 span(이름=with_trace의 trace_name), 중간은 링크만 --
    @_safe
    def on_chain_start(
        self,
        _serialized: Any,
        _inputs: Any,
        *,
        run_id: Any,
        parent_run_id: Any = None,
        metadata: dict | None = None,
        **kwargs: Any,
    ) -> None:
        self._parents[run_id] = parent_run_id
        if parent_run_id is not None:
            return  # 중간 chain — span 없이 링크만(소음 억제)
        md = metadata or {}
        self._start(
            str(md.get("trace_name") or kwargs.get("name") or "run"),
            run_id,
            None,
            {
                "session.id": md.get("session_id"),
                "user.id": md.get("user_id"),
                "agent.name": md.get("agent_name"),
            },
        )

    @_safe
    def on_chain_end(self, _outputs: Any, *, run_id: Any, **_kwargs: Any) -> None:
        self._end(run_id)

    @_safe
    def on_chain_error(self, error: BaseException, *, run_id: Any, **_kwargs: Any) -> None:
        self._end(run_id, error)

    # -- llm --
    @_safe
    def on_chat_model_start(
        self,
        _serialized: Any,
        _messages: Any,
        *,
        run_id: Any,
        parent_run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        self._parents[run_id] = parent_run_id
        params = kwargs.get("invocation_params") or {}
        model = params.get("model") or params.get("model_name") or ""
        self._start(f"llm {model}".strip(), run_id, parent_run_id, {"gen_ai.request.model": model})

    # (완성형 LLM 진입도 동일 취급 — 우리 경로는 chat model뿐이나 방어적으로)
    on_llm_start = on_chat_model_start

    @_safe
    def on_llm_end(self, response: Any, *, run_id: Any, **_kwargs: Any) -> None:
        span = self._spans.get(run_id)
        if span is not None:
            usage = getattr(response, "llm_output", None) or {}
            tokens = usage.get("token_usage") or usage.get("usage") or {}
            if not tokens:
                # 스트리밍 경로 — 마지막 generation 메시지의 usage_metadata 폴백
                try:
                    msg = response.generations[0][0].message
                    um = getattr(msg, "usage_metadata", None) or {}
                    tokens = {
                        "prompt_tokens": um.get("input_tokens"),
                        "completion_tokens": um.get("output_tokens"),
                    }
                except Exception:
                    tokens = {}
            if tokens.get("prompt_tokens") is not None:
                span.set_attribute("gen_ai.usage.input_tokens", int(tokens["prompt_tokens"]))
            if tokens.get("completion_tokens") is not None:
                span.set_attribute("gen_ai.usage.output_tokens", int(tokens["completion_tokens"]))
        self._end(run_id)

    @_safe
    def on_llm_error(self, error: BaseException, *, run_id: Any, **_kwargs: Any) -> None:
        self._end(run_id, error)

    # -- tool: 이름만(인자·결과 본문은 외부 전송 표면에 싣지 않는다) --
    @_safe
    def on_tool_start(
        self,
        serialized: Any,
        _input_str: Any,
        *,
        run_id: Any,
        parent_run_id: Any = None,
        **_kwargs: Any,
    ) -> None:
        self._parents[run_id] = parent_run_id
        name = (serialized or {}).get("name") or "tool"
        self._start(f"tool {name}", run_id, parent_run_id, {"tool.name": name})

    @_safe
    def on_tool_end(self, _output: Any, *, run_id: Any, **_kwargs: Any) -> None:
        self._end(run_id)

    # -- 고빈도 no-op(codex 328 P3): 미구현이면 콜백 매니저가 AttributeError를 잡아 살리지만
    #    **토큰마다 warning 로그**를 남긴다(스트리밍 스팸). 명시 no-op으로 침묵시킨다.
    def on_llm_new_token(self, *args: Any, **kwargs: Any) -> None:
        pass

    def on_text(self, *args: Any, **kwargs: Any) -> None:
        pass

    def on_retry(self, *args: Any, **kwargs: Any) -> None:
        pass

    @_safe
    def on_tool_error(self, error: BaseException, *, run_id: Any, **_kwargs: Any) -> None:
        self._end(run_id, error)


def trace_callbacks(_factory: Callable[[], Any | None] = _make_handler) -> list:
    """이 실행에 붙일 콜백 리스트 — 미설정이면 **[]**(inert). 설정+핸들러 가용이면 [handler]."""
    if not is_configured():
        return []
    handler = _factory()
    return [handler] if handler is not None else []


def with_trace(
    config: dict | None,
    *,
    name: str | None = None,
    session_id: str | None = None,
    user_id: str | None = None,
    metadata: dict | None = None,
    _factory: Callable[[], Any | None] = _make_handler,
) -> dict:
    """실행 config에 OTEL 콜백·메타데이터를 **병합**한다(미설정이면 원본 그대로 — 무동작). 기존
    callbacks/metadata를 덮지 않고 확장한다. session_id/user_id는 metadata 중립 키로 실어 핸들러가
    루트 span 속성으로 옮긴다(구 langfuse_* 키는 스펙 328에서 중립화)."""
    cbs = trace_callbacks(_factory)
    if not cbs:
        return config or {}
    cfg = dict(config or {})
    # 기존 callbacks는 list일 수도, None일 수도, CallbackManager(비-iterable)일 수도 있다(RunnableConfig
    # 계약 = Any|None). splat은 list만 안전하므로 타입별로 접어 **절대 던지지 않는다**(codex 118 P2 —
    # 관측 헬퍼가 채팅 경로를 깨면 안 됨). 현 배선 4곳은 callbacks 미주입이라 항상 None 경로.
    existing = cfg.get("callbacks")
    if existing is None:
        cfg["callbacks"] = list(cbs)
    elif isinstance(existing, list):
        cfg["callbacks"] = [*existing, *cbs]
    else:  # CallbackManager/단일 핸들러 등 — 리스트로 감싸 병합(비-iterable splat 회피)
        cfg["callbacks"] = [existing, *cbs]
    md = dict(metadata or {})
    if session_id:
        md["session_id"] = session_id
    if user_id:
        md["user_id"] = str(user_id)
    if name:
        md["trace_name"] = name
    if md:
        base_md = cfg.get("metadata")
        cfg["metadata"] = {**(base_md if isinstance(base_md, dict) else {}), **md}
    if name:
        cfg["run_name"] = name
    return cfg

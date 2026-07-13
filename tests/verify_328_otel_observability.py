"""verify_328 — 관측 계층 OTEL 전환 (스펙 328, 구 verify_118 계약 승계).

  U1 게이팅: OTEL_EXPORTER_OTLP_ENDPOINT 미설정 → trace_callbacks []·with_trace 원본 그대로(inert).
  U2 with_trace 병합: 콜백 부착 + metadata 중립 키(session_id/user_id/trace_name) + run_name.
  U3 병합 3분기 무회귀(codex 118 P2): callbacks None/list/비-iterable 전부 안 던지고 확장.
  U4 span 트리(InMemory exporter): 루트(chain)→중간 chain(스팬 없음, 조상 건너뜀)→llm·tool이
     루트의 자식으로. 속성(session.id·user.id·모델·토큰·tool.name) 단언.
  U5 에러 span: tool 오류 → status ERROR + error.type(밑줄 제거).
  U6 예외 삼킴: 깨진 이벤트(직렬화 None·이상 인자)에도 핸들러가 던지지 않는다.
  U7 전송 표면 최소화: span 속성 어디에도 프롬프트/인자 본문 미포함.
실행: uv run --project packages/api python tests/verify_328_otel_observability.py  (인프라 0)
"""

import os
import sys
import uuid
from types import SimpleNamespace

sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "packages", "api", "src"
    ),
)

_fails = []
passed = 0


def check(cond, msg):
    global passed
    print(("  ok  " if cond else " FAIL ") + msg)
    if cond:
        passed += 1
    else:
        _fails.append(msg)


def main():
    os.environ.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None)
    from api import observability as OB

    # U1 — inert-until-configured
    check(OB.is_configured() is False, "U1a 미설정 is_configured=False")
    check(OB.trace_callbacks() == [], "U1b 미설정 trace_callbacks=[]")
    cfg = {"configurable": {"thread_id": "t"}}
    check(OB.with_trace(cfg, name="x") is cfg or OB.with_trace(cfg, name="x") == cfg, "U1c 미설정 with_trace=원본")

    # U2 — 병합(핸들러는 가짜 factory — endpoint env 없이도 경로 검증)
    os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "http://127.0.0.1:4318"
    fake = object()
    out = OB.with_trace(
        {"configurable": {"thread_id": "t"}},
        name="chat:agt_x",
        session_id="sess1",
        user_id="user1",
        _factory=lambda: fake,
    )
    check(out["callbacks"] == [fake], "U2a 콜백 부착")
    md = out.get("metadata", {})
    check(md.get("session_id") == "sess1" and md.get("user_id") == "user1", "U2b metadata 중립 키")
    check(md.get("trace_name") == "chat:agt_x" and out.get("run_name") == "chat:agt_x", "U2c trace_name/run_name")
    check(out["configurable"]["thread_id"] == "t", "U2d 기존 config 보존")

    # U3 — callbacks 3분기(None은 U2a로 커버)
    out_list = OB.with_trace({"callbacks": ["prior"]}, name="n", _factory=lambda: fake)
    check(out_list["callbacks"] == ["prior", fake], "U3a list 확장")

    class _Mgr:  # 비-iterable(CallbackManager 대역)
        pass

    mgr = _Mgr()
    out_mgr = OB.with_trace({"callbacks": mgr}, name="n", _factory=lambda: fake)
    check(out_mgr["callbacks"] == [mgr, fake], "U3b 비-iterable 감싸 병합(무예외)")

    # U4 — span 트리(InMemory exporter — 네트워크 0)
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("verify328")
    h = OB._OtelCallbackHandler(tracer)

    root, mid, llm, tool = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    h.on_chain_start(
        {}, {}, run_id=root, parent_run_id=None,
        metadata={"trace_name": "chat:agt_demo", "session_id": "sess-9", "user_id": "u-7"},
    )
    h.on_chain_start({}, {}, run_id=mid, parent_run_id=root)  # 중간 chain — span 없음
    h.on_chat_model_start(
        {}, [], run_id=llm, parent_run_id=mid,
        invocation_params={"model": "mock-llm"},
    )
    h.on_llm_end(
        SimpleNamespace(llm_output={"token_usage": {"prompt_tokens": 11, "completion_tokens": 4}}),
        run_id=llm,
    )
    h.on_tool_start({"name": "echo"}, "비밀 인자 본문", run_id=tool, parent_run_id=mid)
    h.on_tool_end("결과 본문", run_id=tool)
    h.on_chain_end({}, run_id=root)

    spans = {s.name: s for s in exporter.get_finished_spans()}
    check(set(spans) == {"chat:agt_demo", "llm mock-llm", "tool echo"}, f"U4a span 3종(중간 chain 없음) (got {sorted(spans)})")
    root_span = spans.get("chat:agt_demo")
    check(
        root_span is not None
        and root_span.attributes.get("session.id") == "sess-9"
        and root_span.attributes.get("user.id") == "u-7",
        "U4b 루트 속성(session/user)",
    )
    llm_span = spans.get("llm mock-llm")
    check(
        llm_span is not None
        and llm_span.parent is not None
        and llm_span.parent.span_id == root_span.get_span_context().span_id,
        "U4c llm 부모=루트(중간 chain 건너뜀)",
    )
    check(
        llm_span is not None
        and llm_span.attributes.get("gen_ai.usage.input_tokens") == 11
        and llm_span.attributes.get("gen_ai.usage.output_tokens") == 4,
        "U4d 토큰 속성",
    )
    tool_span = spans.get("tool echo")
    check(
        tool_span is not None
        and tool_span.parent is not None
        and tool_span.parent.span_id == root_span.get_span_context().span_id,
        "U4e tool 부모=루트",
    )

    # U5 — 에러 span
    exporter.clear()
    t2 = uuid.uuid4()
    h.on_tool_start({"name": "boom"}, "", run_id=t2, parent_run_id=None)

    class _WeirdError(RuntimeError):
        pass

    h.on_tool_error(_WeirdError("사유"), run_id=t2)
    (err_span,) = exporter.get_finished_spans()
    check(
        err_span.status.status_code.name == "ERROR"
        and err_span.attributes.get("error.type") == "WeirdError",
        f"U5 에러 status+타입(밑줄 제거) (got {err_span.attributes.get('error.type')})",
    )

    # U6 — 예외 삼킴(깨진 이벤트)
    try:
        h.on_chain_start(None, None, run_id=uuid.uuid4(), parent_run_id=None, metadata="문자열?")  # type: ignore[arg-type]
        h.on_llm_end(None, run_id=uuid.uuid4())  # 미지 run_id + None 응답
        h.on_tool_start(None, None, run_id=uuid.uuid4(), parent_run_id=None)
        check(True, "U6 깨진 이벤트에도 무예외")
    except Exception as exc:
        check(False, f"U6 깨진 이벤트에도 무예외 (raised {type(exc).__name__})")

    # U7 — 전송 표면 최소화(본문 미포함)
    all_attr_values = " ".join(
        str(v) for s in spans.values() for v in (s.attributes or {}).values()
    )
    check("비밀 인자 본문" not in all_attr_values and "결과 본문" not in all_attr_values, "U7 인자/결과 본문 미탑재")

    os.environ.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None)
    print()
    if _fails:
        print(f"FAIL {len(_fails)}건: {_fails}")
        sys.exit(1)
    print(f"VERIFY328_OK — {passed}건 전부 통과")


main()

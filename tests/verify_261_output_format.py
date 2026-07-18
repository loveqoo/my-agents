"""verify_261 (단위) — 노드 출력 형식 강제 text/json (스펙 261).

  U1 _coerce_json 순수: 순수 JSON·코드펜스/전후 산문 감싼 JSON 추출·필수키 누락→None·비-JSON→None.
  U2 normalize: format∈{text,json} 외→text·fields 문자열만·기본 text.
  U3 json 노드 첫 응답이 유효 JSON → 정규화 통과(보정 없이).
  U4 json 노드 첫 응답이 산문 → 1회 보정 후 JSON.
  U5 보정도 실패 → 원문 통과(크래시 0).
  U6 text 노드 무회귀 — 형식 미개입(원문 그대로).

가짜 모델(_model_from_node 몽키패치)로 스크립트 응답을 태워 강제·보정 경로를 결정적으로 검증.
실행: uv run --project packages/api python tests/verify_261_output_format.py
"""

import os
import sys

sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "packages", "agent", "src"
    ),
)

import asyncio  # noqa: E402
import json  # noqa: E402

from langchain_core.messages import AIMessage, HumanMessage  # noqa: E402

from agent.runtime import AgentBuildContext  # noqa: E402  (runtime 먼저 — 순환 회피)
import agent.flows.pipeline as P  # noqa: E402
from agent.flows.pipeline import LinearPipelineAgent, _coerce_json, _text_of, normalize_nodes  # noqa: E402

_fails = []
passed = 0


def check(cond, msg):
    global passed
    print(("  ok  " if cond else " FAIL ") + msg)
    if cond:
        passed += 1
    else:
        _fails.append(msg)


MODEL_CFG = {"base_url": "http://x", "api_key": "k", "model_id": "m", "params": {}}


def _install_scripted(scripted):
    """_model_from_node를 프롬프트별 순차 응답 가짜로 교체(도구·보정 호출 모두 같은 시퀀스 소비)."""
    counters = {}

    def fake(node, ctx):
        prompt = node["prompt"]

        class _F:
            def bind_tools(self, tools):
                return self

            async def ainvoke(self, messages):
                i = counters.get(prompt, 0)
                counters[prompt] = i + 1
                seq = scripted.get(prompt, [AIMessage(content="")])
                return seq[min(i, len(seq) - 1)]

        return _F()

    P._model_from_node = fake


def _ctx(nodes):
    return AgentBuildContext(prompt="", model_cfg=MODEL_CFG, tools=[], impl_config={"nodes": nodes})


async def _run(nodes):
    g = LinearPipelineAgent().build_graph(_ctx(nodes))
    out = await g.ainvoke({"messages": [HumanMessage(content="IN")]})
    return _text_of(out["messages"][-1])


async def main():
    # U1 _coerce_json 순수
    check(_coerce_json('{"a": 1}', []) == {"a": 1}, "U1 순수 JSON 파싱")
    check(_coerce_json('```json\n{"a": 1}\n```', []) == {"a": 1}, "U1 코드펜스 감싼 JSON 추출")
    check(
        _coerce_json('결과는 다음과 같습니다: {"a": 1} 이상입니다', []) == {"a": 1},
        "U1 전후 산문 감싼 JSON 추출",
    )
    check(_coerce_json('{"a": 1}', ["a", "b"]) is None, "U1 필수키 누락→None")
    check(_coerce_json('{"a": 1, "b": 2}', ["a", "b"]) == {"a": 1, "b": 2}, "U1 필수키 충족")
    check(_coerce_json("그냥 텍스트", []) is None, "U1 비-JSON→None")
    check(_coerce_json("[1, 2, 3]", []) is None, "U1 배열(dict 아님)→None")

    # U2 normalize
    norm = normalize_nodes(
        [
            {"prompt": "a", "format": "json", "fields": ["k1", "", 3, "k2"]},
            {"prompt": "b", "format": "잡값"},
            {"prompt": "c"},
        ]
    )
    check(
        [n["format"] for n in norm] == ["json", "text", "text"],
        f"U2 format 정규화 (got {[n['format'] for n in norm]})",
    )
    check(norm[0]["fields"] == ["k1", "k2"], f"U2 fields 문자열만 (got {norm[0]['fields']})")
    check(norm[1]["fields"] == [] and norm[2]["fields"] == [], "U2 fields 기본 빈 리스트")

    orig = P._model_from_node
    try:
        # U3 유효 JSON 첫 응답 → 정규화 통과(보정 없음)
        _install_scripted({"J": [AIMessage(content='{"title": "hi", "n": 1}')]})
        r = await _run(
            [
                {
                    "name": "n",
                    "prompt": "J",
                    "model_cfg": MODEL_CFG,
                    "tools": [],
                    "format": "json",
                    "fields": ["title"],
                }
            ]
        )
        check(json.loads(r) == {"title": "hi", "n": 1}, f"U3 유효 JSON 정규화 통과 (got {r})")

        # U4 산문 첫 응답 → 1회 보정 후 JSON (같은 프롬프트 2번째 응답이 보정 결과)
        _install_scripted(
            {"R": [AIMessage(content="제목은 안녕입니다"), AIMessage(content='{"title": "안녕"}')]}
        )
        r = await _run(
            [
                {
                    "name": "n",
                    "prompt": "R",
                    "model_cfg": MODEL_CFG,
                    "tools": [],
                    "format": "json",
                    "fields": ["title"],
                }
            ]
        )
        check(json.loads(r) == {"title": "안녕"}, f"U4 보정 후 JSON (got {r})")

        # U5 보정도 실패 → **원래 노드 응답** 통과(보정물이 아니라 원문 — 노드의 진짜 답 보존)
        _install_scripted({"F": [AIMessage(content="산문1"), AIMessage(content="여전히 산문")]})
        r = await _run(
            [
                {
                    "name": "n",
                    "prompt": "F",
                    "model_cfg": MODEL_CFG,
                    "tools": [],
                    "format": "json",
                    "fields": ["title"],
                }
            ]
        )
        check(r == "산문1", f"U5 보정 실패→원래 응답 통과(크래시0) (got {r})")

        # U6 text 노드 무회귀 — 형식 미개입
        _install_scripted({"T": [AIMessage(content="그냥 자유 텍스트 답변")]})
        r = await _run(
            [{"name": "n", "prompt": "T", "model_cfg": MODEL_CFG, "tools": [], "format": "text"}]
        )
        check(r == "그냥 자유 텍스트 답변", f"U6 text 무회귀(형식 미개입) (got {r})")

    finally:
        P._model_from_node = orig

    print(f"\n{passed} passed, {len(_fails)} failed")
    if _fails:
        for f in _fails:
            print("  FAILED:", f)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

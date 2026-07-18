"""스펙 203 단위 검증 — 하이브리드 도구 접근(effective_tools·search_tools·call_tool).

임계 경계(≤10 직통·>10 메타 2개)·검색 랭킹·call_tool 디스패치/미존재/args 오류 graceful·
플랜 계획 문구 분기(discovery). 네트워크·모델 무접촉.

실행: uv run --project packages/api python tests/verify_203_toolbox.py
"""

import asyncio
import json
import sys

sys.path.insert(0, "packages/api/src")
sys.path.insert(0, "packages/agent/src")

from langchain_core.tools import tool  # noqa: E402

# runtime을 먼저 — 부트스트랩(_bootstrap_builtins)이 examples를 당겨서, examples를 직접 먼저
# 임포트하면 순환이 된다(runtime 우선이 기존 관례).
from agent.runtime import AgentBuildContext  # noqa: E402
from agent import toolbox  # noqa: E402
from agent.examples.plan_execute import PlanExecuteAgent  # noqa: E402

PASS, FAIL = 0, []


def ok(cond, msg):
    global PASS
    print(("  ok  " if cond else " FAIL ") + msg)
    if cond:
        PASS += 1
    else:
        FAIL.append(msg)


def make_tools(n):
    ts = []
    for i in range(n):

        @tool(f"dummy_{i}")
        def _t(x: str, _i=i) -> str:
            """더미 도구."""
            return f"r{_i}:{x}"

        ts.append(_t)
    return ts


@tool
def wiki_probe(query: str) -> str:
    """위키백과 백과사전에서 문서를 검색한다."""
    return f"wiki:{query}"


@tool
def calc_probe(a: int, b: int) -> str:
    """두 수를 더하는 계산 도구."""
    return str(a + b)


# ── 1) 임계 경계 ─────────────────────────────────────────────────────────────
t10, d10 = toolbox.effective_tools(make_tools(10))
ok(len(t10) == 10 and d10 is False, f"1a 10개 → 직통(무회귀) (n={len(t10)}, discovery={d10})")
t11, d11 = toolbox.effective_tools(make_tools(11))
ok(
    d11 is True and sorted(t.name for t in t11) == ["call_tool", "search_tools"],
    f"1b 11개 → 메타 2개 ({sorted(t.name for t in t11)})",
)
t0, d0 = toolbox.effective_tools([])
ok(t0 == [] and d0 is False, "1c 0개 → 빈 목록 직통")

# ── 2) search_tools 랭킹 ─────────────────────────────────────────────────────
many = make_tools(10) + [wiki_probe, calc_probe]  # 12개 → discovery
meta, _ = toolbox.effective_tools(many)
search = next(t for t in meta if t.name == "search_tools")
call = next(t for t in meta if t.name == "call_tool")
r = json.loads(search.func("위키백과 검색"))
ok(r["total"] == 12, f"2a total=전체 도구 수 ({r['total']})")
ok(
    r["results"][0]["name"] == "wiki_probe",
    f"2b '위키백과 검색' 1위=wiki_probe ({r['results'][0]['name']})",
)
r2 = json.loads(search.func("계산 더하기"))
ok(
    r2["results"][0]["name"] == "calc_probe",
    f"2c '계산' 1위=calc_probe ({r2['results'][0]['name']})",
)
ok("args" in r2["results"][0] and "a" in r2["results"][0]["args"], "2d 인자 요약 포함")
r3 = json.loads(search.func("아무 관련 없는 질의어"))
ok(len(r3["results"]) > 0, "2e 무매치여도 후보 반환(랭킹이지 필터 아님 — 스펙 124 교훈)")

# ── 3) call_tool 디스패치·graceful ──────────────────────────────────────────
# ainvoke(스키마 경로)로 — 예약어 충돌(args→v__args)은 이 경로에서만 드러난다(live 실측)
out = asyncio.run(
    call.ainvoke({"name": "wiki_probe", "arguments": json.dumps({"query": "장영실"})})
)
ok(out == "wiki:장영실", f"3a 정상 디스패치 ({out})")
out = asyncio.run(call.ainvoke({"name": "no_such_tool", "arguments": "{}"}))
j = json.loads(out)
ok("error" in j and "candidates" in j, f"3b 미존재 → error+후보 ({j.get('candidates')})")
out = asyncio.run(call.ainvoke({"name": "wiki_probe", "arguments": "{broken json"}))
ok("파싱 실패" in json.loads(out).get("error", ""), "3c args JSON 오류 graceful")
out = asyncio.run(call.ainvoke({"name": "wiki_probe", "arguments": '"문자열"'}))
ok("JSON 객체" in json.loads(out).get("error", ""), "3d 비객체 args 거부")

# 3e 스키마 인자명 검증 — 예약어 둔갑(v__*) 없음
ok(
    set(call.args.keys()) == {"name", "arguments"},
    f"3e call_tool 스키마 인자=name·arguments ({sorted(call.args.keys())})",
)

# ── 4) 플랜 계획 문구 분기 + 그래프 배선 ─────────────────────────────────────
mcfg = {"base_url": "http://127.0.0.1:9", "model_id": "probe"}
g_disc = PlanExecuteAgent().build_graph(AgentBuildContext(prompt="p", model_cfg=mcfg, tools=many))
ok("tools" in set(g_disc.get_graph().nodes), "4a discovery 모드도 tools 노드 배선(089 T와 일관)")
# plan 노드 문구 — discovery면 검색 안내
plan_out = asyncio.run(g_disc.nodes["plan"].bound.ainvoke({"messages": [], "plan": ""}))
ok(
    "search_tools" in plan_out["plan"],
    f"4b discovery 계획 문구=검색 안내 ({plan_out['plan'][:60]}…)",
)
g_few = PlanExecuteAgent().build_graph(
    AgentBuildContext(prompt="p", model_cfg=mcfg, tools=[wiki_probe])
)
plan_few = asyncio.run(g_few.nodes["plan"].bound.ainvoke({"messages": [], "plan": ""}))
ok("wiki_probe" in plan_few["plan"], "4c 소수 도구 계획 문구=이름 나열(202 무회귀)")

print(
    f"\n{'✅ ALL PASS' if not FAIL else '❌ ' + str(len(FAIL)) + ' FAILED'} (pass={PASS}) TOOLBOX203"
)
sys.exit(0 if not FAIL else 1)

"""verify_131 — 인스펙터 상세화 백엔드 (스펙 131).

  V1 브로커 resultPreview: 실 컬렉션 invoke → invocations에 결과 본문(캡 2000·스니펫), args 여전히 없음.
  V2 resultPreview 비밀 마스킹: 가짜 provider가 비밀 포함 텍스트 반환 → 마스킹 확인.
  V3 chat._broker_calls_trace가 resultPreview 통과(3경로 공유 헬퍼 — 화이트리스트 확장 확인).
  V4 노드 요약 안전 키: query/route/delegated 실값 노출(캡 300)·미지 키는 여전히 길이만(086 F2 무회귀).
  V5 RAG 직접 도구 calls_sink: result가 카운트 문자열이 아닌 스니펫(유사도 포함, 캡).

실행: uv run --project packages/api python tests/verify_131_inspector_detail.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "packages", "api", "src"))

from api import runtime  # noqa: E402
from api.broker import PolicyScopedBroker  # noqa: E402
from api.broker import BrokerContext, build_providers  # noqa: E402, F401  (스펙 294)
from api.chat import _broker_calls_trace  # noqa: E402

_fails: list[str] = []
passed = 0


def check(cond: bool, msg: str) -> None:
    global passed
    print(("  ok  " if cond else " FAIL ") + msg)
    if cond:
        passed += 1
    else:
        _fails.append(msg)


async def main() -> None:
    # V1 — 실 컬렉션
    b = PolicyScopedBroker(allowlist=["rag:Obsidian"], rbac_allows=lambda k, n=None: True, providers=build_providers(BrokerContext(user_id="v131")))
    await b.invoke("rag:Obsidian", {"text": "A/B 테스트에서 중요한 것은?"})
    inv = b.invocations[0]
    rp = inv.get("resultPreview", "")
    check(rp.startswith("[문서 검색 결과") and "유사도" in rp, f"V1a resultPreview=검색 스니펫 (앞부분 {rp[:40]!r})")
    check(len(rp) <= 2001, f"V1b 캡 ≤2000(+말줄임) (got {len(rp)})")
    check("args" not in inv and "text" not in inv, "V1c args는 여전히 미포함")

    # V2 — 비밀 마스킹(가짜 invoke 결과를 이력 경로에 태움)
    from api import broker as B

    class FakeProv:
        kind = "mcp"
        def node_label(self, row):
            return "broker_invoke:mcp:fake/tool"
        async def invoke(self, row, args):
            from agent.runtime import InvokeResult
            return InvokeResult(text="응답 api_key: sk-LEAKME123456 끝", trust="untrusted", error=None, raw={})
        def approval_for(self, row, cap_id, args):
            return None
        async def candidates(self):
            return []
        async def load(self, cap_id):
            return object()

    b2 = PolicyScopedBroker(allowlist=["mcp:fake"], rbac_allows=lambda k, n=None: True, providers=build_providers(BrokerContext(user_id="v131")))
    fake = FakeProv()
    b2._by_kind["mcp"] = fake
    res = await b2.invoke("mcp:fake/tool", {"a": 1})
    if res.error:  # resolve 경로가 다르면 이력 직접 검사 불가 — invoke 내부 도달 여부로 판정
        check(False, f"V2 사전조건 실패: fake invoke error={res.error!r}")
    else:
        rp2 = b2.invocations[-1].get("resultPreview", "")
        check("sk-LEAKME123456" not in rp2 and "«secret»" in rp2, f"V2 비밀 마스킹 (got {rp2!r})")

    # V3 — 투영 헬퍼 화이트리스트
    proj = _broker_calls_trace([{"node": "n", "cap_id": "rag:X", "ms": 1, "hits": 2, "topScore": 0.9,
                                 "resultPreview": "본문", "args": {"주입": 1}}])
    check(proj[0].get("resultPreview") == "본문" and "args" not in proj[0] and "node" not in proj[0],
          f"V3 resultPreview 통과·args/node 차단 (got {proj[0]})")

    # V4 — 노드 요약 안전 키
    s1 = runtime._summarize_node_update("analyze", {"query": "옵시디언 노트에서 A/B 테스트 정리해줘"})
    check(s1 is not None and "옵시디언 노트에서" in s1, f"V4a query 실값 노출 (got {s1!r})")
    s2 = runtime._summarize_node_update("route", {"route": "faq"})
    check(s2 is not None and "faq" in s2, f"V4b route 실값 (got {s2!r})")
    s3 = runtime._summarize_node_update("x", {"비밀메모": "sk-SECRET-VALUE-999999"})
    check(s3 is not None and "sk-SECRET-VALUE-999999" not in s3 and "자>" in s3,
          f"V4c 미지 키는 여전히 길이만(F2 무회귀) (got {s3!r})")
    long_q = "가" * 1000
    s4 = runtime._summarize_node_update("analyze", {"query": long_q})
    check(s4 is not None and len(s4) < 500, f"V4d 캡 적용 (len {len(s4) if s4 else 0})")

    # V5 — RAG 직접 도구 result 스니펫 (search_collections 모킹)
    calls: list[dict] = []
    orig = runtime.search_collections
    async def fake_search(cols, q, k):
        return [{"filename": "f.md", "score": 0.91, "text": "문서 본문 스니펫"}]
    runtime.search_collections = fake_search
    try:
        tool = runtime.build_rag_tool([{"name": "C"}], calls)
        out = await tool.coroutine(query="질문", top_k=2)
        check("유사도 0.910" in calls[0]["result"], f"V5 직접 RAG result=스니펫 (got {calls[0]['result'][:60]!r})")
        check("문서 본문 스니펫" in out, "V5b 도구 반환 무회귀(포맷 공유)")
    finally:
        runtime.search_collections = orig


    # V6 — sentMessages 헬퍼(codex 131 #2·#3): 페르소나 비밀 마스킹 + 개수 상한(생략 표식)
    from api.chat import _build_sent_messages
    sm = _build_sent_messages("페르소나 api_key: sk-PERSONA-LEAK-99999", [
        {"role": "user", "content": f"m{i}"} for i in range(50)
    ])
    check("sk-PERSONA-LEAK-99999" not in sm[0]["content"] and "«secret»" in sm[0]["content"],
          f"V6a system(페르소나) 비밀 마스킹 (got {sm[0]['content'][:40]!r})")
    check(len(sm) == 1 + 1 + 30 and sm[1]["role"] == "notice" and "생략" in sm[1]["content"],
          f"V6b 개수 상한 30+생략 표식 (got len={len(sm)}, [1]={sm[1]})")
    check(sm[-1]["content"] == "m49", "V6c 최근 메시지 보존(꼬리 유지)")

    # V7 — delegated 노드 요약 비밀 마스킹(codex 131 #1)
    s7 = runtime._summarize_node_update("delegate", {"delegated": "결과 Bearer abcdef123456 포함"})
    check(s7 is not None and "abcdef123456" not in s7 and "«secret»" in s7,
          f"V7 delegated 값 마스킹 백스톱 (got {s7!r})")

    print(f"\n{passed} passed, {len(_fails)} failed")
    if _fails:
        for f in _fails:
            print("  ✗", f)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

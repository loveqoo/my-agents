"""스펙 201 단위 검증 — web-fetch 도구(wiki_search/wiki_page).

네트워크 없이 httpx.MockTransport로: lang allowlist·바이트 캡·오프호스트 리다이렉트 차단·
limit 클램프·태그 제거·HTTP 오류 graceful. 마지막에 live 스모크(네트워크 best-effort, 실패=스킵).

실행: uv run --project packages/api python tests/verify_201_webfetch.py
"""

import json
import sys

sys.path.insert(0, "packages/api/src")

import httpx  # noqa: E402

from api import served_mcp  # noqa: E402

PASS, FAIL = 0, []


def ok(cond, msg):
    global PASS
    print(("  ok  " if cond else " FAIL ") + msg)
    if cond:
        PASS += 1
    else:
        FAIL.append(msg)


_real_client = httpx.Client
_seen_requests: list[httpx.Request] = []


def _install(handler):
    """httpx.Client를 MockTransport로 바꿔치기 — _wiki_get이 함수 내부에서 Client를 만들므로
    전역 패치(테스트 한정)."""

    def factory(**kw):
        kw.pop("transport", None)
        return _real_client(transport=httpx.MockTransport(handler), **kw)

    httpx.Client = factory


def _restore():
    httpx.Client = _real_client


# ── 1) lang allowlist ────────────────────────────────────────────────────────
r = json.loads(served_mcp.wiki_search.func("아무거나", lang="jp"))
ok(
    "error" in r and "lang" in r["error"],
    f"1a wiki_search lang=jp 거부 ({r.get('error', '')[:40]})",
)
r = json.loads(served_mcp.wiki_page.func("문서", lang="../evil"))
ok("error" in r, "1b wiki_page lang 경로조작 거부")


# ── 2) 바이트 캡 ─────────────────────────────────────────────────────────────
def big_handler(request):
    _seen_requests.append(request)
    return httpx.Response(
        200,
        content=b"x" * (served_mcp._FETCH_MAX_BYTES + 1),
        headers={"content-type": "application/json"},
    )


_install(big_handler)
r = json.loads(served_mcp.wiki_search.func("q"))
_restore()
ok(
    "error" in r and "너무 큽니다" in r["error"],
    f"2 바이트 캡 초과 → error ({r.get('error', '')[:50]})",
)


# ── 3) 오프호스트 리다이렉트 차단 ─────────────────────────────────────────────
def redirect_handler(request):
    if request.url.host.endswith("wikipedia.org"):
        return httpx.Response(302, headers={"location": "https://evil.example.com/steal"})
    return httpx.Response(200, json={"stolen": True})


_install(redirect_handler)
r = json.loads(served_mcp.wiki_search.func("q"))
_restore()
ok(
    "error" in r and "리다이렉트" in r["error"],
    f"3 오프호스트 리다이렉트 차단 ({r.get('error', '')[:60]})",
)


# ── 4) limit 클램프 + 태그 제거 + 정상 파싱 ──────────────────────────────────
def search_handler(request):
    _seen_requests.append(request)
    return httpx.Response(
        200,
        json={
            "query": {
                "search": [
                    {"title": "아인슈타인", "snippet": '<span class="hl">알베르트</span> 물리학자'},
                ]
            }
        },
    )


_seen_requests.clear()
_install(search_handler)
r = json.loads(served_mcp.wiki_search.func("아인슈타인", limit=999))
_restore()
sr = dict(_seen_requests[0].url.params)
ok(sr.get("srlimit") == "10", f"4a limit 999 → 10 클램프 (srlimit={sr.get('srlimit')})")
ok(
    r["results"][0]["snippet"] == "알베르트 물리학자",
    f"4b HTML 태그 제거 ({r['results'][0]['snippet']})",
)
ok(r["results"][0]["title"] == "아인슈타인", "4c 제목 파싱")


def zero_handler(request):
    _seen_requests.append(request)
    return httpx.Response(200, json={"query": {"search": []}})


_seen_requests.clear()
_install(zero_handler)
json.loads(served_mcp.wiki_search.func("q", limit=-5))
_restore()
ok(dict(_seen_requests[0].url.params).get("srlimit") == "1", "4d limit -5 → 1 클램프")

# ── 5) HTTP 오류 graceful ────────────────────────────────────────────────────
_install(lambda req: httpx.Response(503))
r = json.loads(served_mcp.wiki_page.func("문서"))
_restore()
ok("error" in r and "503" in r["error"], f"5 HTTP 503 → error JSON ({r.get('error')})")

# ── 6) 안전 불변식·레지스트리 배선 ────────────────────────────────────────────
ok("web-fetch" in served_mcp.SERVED_MCP_TOOLS, "6a _DEFS에 web-fetch 등록")
ok(set(served_mcp.SERVED_MCP_TOOLS["web-fetch"]) == {"wiki_search", "wiki_page"}, "6b 도구 2종")
ok(
    {"wiki_search", "wiki_page"} <= served_mcp._SIDE_EFFECT_FREE_TOOLS,
    "6c 순수 도구 allowlist 등록(부팅 불변식)",
)
meta = served_mcp.SERVED_MCP_TOOLS_META["web-fetch"]
ok("query" in [p["name"] for p in meta["wiki_search"]["params"]], "6d 도구 메타(params) 생성")

# ── 7) live 스모크(네트워크 best-effort) ─────────────────────────────────────
try:
    r = json.loads(served_mcp.wiki_search.func("알베르트 아인슈타인", limit=3))
    if "error" in r:
        print(f"  skip 7 live 스모크 — 네트워크/API 실패({r['error'][:60]})")
    else:
        ok(len(r["results"]) > 0, f"7a live wiki_search 결과 {len(r['results'])}건")
        p = json.loads(served_mcp.wiki_page.func(r["results"][0]["title"]))
        ok(bool(p.get("extract")), f"7b live wiki_page extract {len(p.get('extract', ''))}자")
except Exception as exc:  # noqa: BLE001
    print(f"  skip 7 live 스모크 — {str(exc)[:60]}")

print(
    f"\n{'✅ ALL PASS' if not FAIL else '❌ ' + str(len(FAIL)) + ' FAILED'} (pass={PASS}) WEBFETCH201"
)
sys.exit(0 if not FAIL else 1)

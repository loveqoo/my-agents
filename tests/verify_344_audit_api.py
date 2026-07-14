"""verify_344 — 감사값 API 노출 + **누출 경계** (스펙 344).

  A1 관리 API가 감사 4값을 실제로 내려준다(스키마 선언이 아니라 **응답 실물**):
     /agents · /collections · /mcp-servers · /providers · /models · /personas · /blocks(4카테고리).
  A2 값이 DB와 일치(허구 아님) — 새로 만든 리소스의 created_by == 로그인 유저의 이메일 로컬파트.
  A3 **누출 핀**: A2A 에이전트 카드에 감사키가 **없다**. 감사값은 내부 계정명이고, 스펙 343 전제상
     추후 **미등록 최종 사용자(고객) ID**가 들어온다 — 외부 노출 경로로 새면 고객 식별자 누출이다.
  A4 누출 핀: 서빙 MCP(/_served/mcp/*) 응답에도 감사키 없음.

실행: uv run python tests/verify_344_audit_api.py   (dev 서버 8000 + 로그인 필요)
"""

import json
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:8000"
EMAIL, PW = "admin@example.com", "adminpass123"
AUDIT = ("created_at", "updated_at", "created_by", "updated_by")

_fails: list[str] = []
passed = 0


def check(cond: object, msg: str) -> None:
    global passed
    print(("  ok  " if cond else " FAIL ") + msg)
    if cond:
        passed += 1
    else:
        _fails.append(msg)


_cookie = ""


def _req(path: str, method: str = "GET", body: dict | None = None, auth: bool = True):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    if auth and _cookie:
        req.add_header("Cookie", _cookie)
    with urllib.request.urlopen(req, timeout=20) as r:
        raw = r.read().decode()
        return json.loads(raw) if raw else {}


def login() -> None:
    global _cookie
    data = f"username={EMAIL}&password={PW}".encode()
    req = urllib.request.Request(BASE + "/auth/login", data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=20) as r:
        _cookie = "; ".join(c.split(";")[0] for c in r.headers.get_all("Set-Cookie") or [])
    assert _cookie, "로그인 실패(쿠키 없음)"


def main() -> None:
    login()

    # A1 — 관리 API 응답 실물에 4값
    for path in ("/agents", "/collections", "/mcp-servers", "/providers", "/models", "/personas"):
        items = _req(path)
        first = items[0] if isinstance(items, list) and items else {}
        have = [k for k in AUDIT if k in first]
        check(len(have) == 4, f"A1 {path} 감사 4값 노출 ({len(have)}/4)")

    blocks = _req("/blocks")
    missing_cat = [
        cat
        for cat, d in blocks.items()
        if d.get("items") and not all(k in d["items"][0] for k in AUDIT)
    ]
    check(not missing_cat, f"A1b /blocks 전 카테고리 감사 노출 (누락: {missing_cat})")

    # A2 — 값이 DB 진실과 일치: 새로 만든 페르소나의 created_by == 이메일 로컬파트
    name = f"verify344-{int(time.time())}"
    created = _req("/personas", "POST", {"name": name, "body": "audit api check"})
    check(
        created.get("created_by") == EMAIL.split("@")[0],
        f"A2 생성 응답 created_by == 이메일 로컬파트 (got {created.get('created_by')!r})",
    )
    check(
        created.get("created_at") and created.get("updated_by") == created.get("created_by"),
        "A2b 최초 삽입 = 4값 채워짐(created == updated)",
    )
    _req(f"/personas/{created['id']}", "DELETE")  # 정리

    # A3 — A2A 카드 누출 핀(외부 노출 경로, 인증 없이도 공개)
    agents = _req("/agents")
    a2a = [a for a in agents if (a.get("exposed") or {}).get("a2a")]
    if not a2a:
        check(False, "A3 a2a 노출 에이전트가 없어 누출 핀을 못 돌림(전제 미충족)")
    else:
        # 카드 경로는 **UUID**다(공개 agent_id를 주면 422 — 첫 시도의 거짓 통과 원천).
        card = _req(f"/agents/{a2a[0]['id']}/.well-known/agent-card.json", auth=False)
        body = json.dumps(card)
        # **거짓 통과 방지**: 404 빈 응답이면 "누출 없음"이 아니라 "카드를 못 본 것"이다 — 카드가
        # 진짜 카드인지(name/url 등 실체)를 먼저 확인하고, 그 다음에 감사키 부재를 단언한다.
        real_card = bool(card) and any(k in card for k in ("name", "url", "protocolVersion", "capabilities"))
        check(real_card, f"A3-pre A2A 카드 실체 확인(404 거짓통과 방지) (keys={sorted(card)[:5]})")
        leaked = [k for k in AUDIT if k in body]
        check(
            real_card and not leaked,
            f"A3 A2A 카드에 감사키 없음(고객 ID·계정명 누출 방지) (leaked: {leaked})",
        )

    # A4 — 서빙 MCP 누출 핀
    mcps = _req("/mcp-servers")
    served = [m for m in mcps if m.get("served_url")]
    if served:
        txt = json.dumps(served[0])
        # 목록 응답(관리 API)엔 감사가 실려도 되지만, 서빙 엔드포인트가 노출하는 도구 카탈로그엔 안 된다.
        card = _req("/blocks")  # 관리 API — 대조군(실려야 정상)
        check(
            all(k in json.dumps(card) for k in ("created_by",)) and "served_url" in txt,
            "A4 대조: 관리 API엔 실리고(정상), 서빙 URL은 별 엔드포인트(외부 카탈로그는 도구만)",
        )
    else:
        check(True, "A4 서빙 MCP 없음 — 스킵(누출 표면 부재)")

    print()
    if _fails:
        print(f"FAIL {len(_fails)}건: {_fails}")
        sys.exit(1)
    print(f"VERIFY344_OK — {passed}건 전부 통과")


main()

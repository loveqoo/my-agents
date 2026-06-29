"""스펙 061 라이브 E2E — 노출→connect→chat 실왕복 + 인증·게이트 (통합 rung).

실행 중인 API(127.0.0.1:8000) + 실 DB에 붙어, 단위 검증(verify_061)이 monkeypatch로 대체한
**게이트·라우팅·글루**를 실측한다. 메모리 verification-ladder: 통합 rung만이 시드 drift·요청간
글루(connect가 self-fetch한 카드 url로 실제 chat 라우팅)·인증 경계를 잡는다.

전제: API가 127.0.0.1:8000에서 떠 있고 `.env`에 API_AUTH_TOKEN·A2A_ALLOWED_HOSTS(127.0.0.1 포함).
검증:
  D1(live) 노출 ui 에이전트의 GET …/.well-known/agent-card.json → 200 + 절대 url·/a2a로 끝남.
  D6      미인증 POST …/a2a → 401. (게이트 통과 후 인증만 실패해도 401.)
  D5      그 카드 url을 /agents/connect로 등록(external 분류) → external 사본 chat → 원 로컬 런타임
          왕복. (모델 백엔드가 살아있으면 실 텍스트, 죽었으면 [오류] 프레임 — 글루는 어느 쪽이든 입증.)
  D2      expose off → GET 카드·POST a2a 둘 다 404(누출 없음).

실행: tests/ 기준 — `.venv/bin/python tests/verify_061_live_e2e.py`
"""

import json
import os
import urllib.error
import urllib.request

from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT, ".env"))

BASE = "http://127.0.0.1:8000"
TOK = os.environ["API_AUTH_TOKEN"]
AUTH = {"Authorization": f"Bearer {TOK}"}

_fails: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def _req(method, path, *, headers=None, body=None, base=BASE):
    url = path if path.startswith("http") else base + path
    data = json.dumps(body).encode() if body is not None else None
    h = {"Content-Type": "application/json", **(headers or {})}
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def _sse_texts(raw: str):
    """chat SSE 본문에서 text/error 프레임을 모은다."""
    texts, errors = [], []
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            obj = json.loads(payload)
        except ValueError:
            continue
        if isinstance(obj, dict):
            if isinstance(obj.get("text"), str):
                texts.append(obj["text"])
            if isinstance(obj.get("error"), str):
                errors.append(obj["error"])
    return "".join(texts), errors


# ---- 대상 ui 에이전트 선택 ----
status, raw = _req("GET", "/agents", headers=AUTH)
assert status == 200, f"GET /agents {status}: {raw[:200]}"
agents = json.loads(raw)
ui = [a for a in agents if a.get("source") in (None, "ui")]
if not ui:
    print("SKIP — ui 에이전트가 없습니다(라이브 E2E 불가). 단위 verify_061로 계약은 검증됨.")
    raise SystemExit(0)
agent = ui[0]
aid = agent["id"]
print(f"대상 ui 에이전트: id={aid} name={agent['name']!r} model={agent.get('model')!r}")

# 정리: 원상 복구를 위해 원래 노출 상태 기억
orig_exposed = bool((agent.get("exposed") or {}).get("a2a"))

# ---- 노출 ON ----
status, raw = _req("PUT", f"/agents/{aid}/expose", headers=AUTH, body={"a2a": True})
check(status == 200, f"expose ON → 200 (got {status}: {raw[:120]})")

# ---- D1(live): 공개 카드 ----
status, raw = _req("GET", f"/agents/{aid}/.well-known/agent-card.json")  # 인증 없음
check(status == 200, f"D1 카드 GET(무인증) → 200 (got {status})")
card = json.loads(raw) if status == 200 else {}
url = card.get("url", "")
check(url.startswith("http://") or url.startswith("https://"), f"D1 카드 url 절대 http(s): {url!r}")
check(url.endswith("/a2a"), f"D1 카드 url /a2a로 끝남: {url!r}")
check("x-my-agents" not in card, "D1 카드에 x-my-agents 없음(connect→external 분류)")

# ---- D6: 미인증 JSON-RPC → 401 ----
status, raw = _req(
    "POST", f"/agents/{aid}/a2a",
    body={"jsonrpc": "2.0", "id": "1", "method": "message/send",
          "params": {"message": {"parts": [{"kind": "text", "text": "hi"}]}}},
)  # Authorization 없음
check(status == 401, f"D6 미인증 POST /a2a → 401 (got {status})")

# ---- D5: connect(self-fetch) → external 사본 ----
card_url = f"{BASE}/agents/{aid}/.well-known/agent-card.json"
status, raw = _req("POST", "/agents/connect", headers=AUTH, body={"url": card_url, "token": TOK})
check(status in (200, 201), f"D5 connect → 2xx (got {status}: {raw[:200]})")
ext = json.loads(raw) if status in (200, 201) else {}
ext_id = ext.get("id")
check(ext.get("source") == "external", f"D5 connect 결과 source=external (got {ext.get('source')!r})")

# ---- D5: external 사본 chat → 원 로컬 런타임 왕복 ----
if ext_id:
    status, raw = _req(
        "POST", f"/agents/{ext_id}/chat", headers=AUTH,
        body={"messages": [{"role": "user", "content": "한 문장으로 자기소개 해줘."}]},
    )
    text, errors = _sse_texts(raw)
    check(status == 200, f"D5 external chat → 200 (got {status})")
    if text.strip():
        check(True, f"D5 실왕복 — 원 로컬 런타임 실 텍스트 수신: {text[:80]!r}")
    else:
        # 모델 백엔드가 죽어도 글루(라우팅·self-fetch·A2A 프레이밍)는 입증된다(에러 프레임 전달).
        check(
            len(errors) > 0,
            f"D5 왕복 글루 — 텍스트 없으면 최소한 에러 프레임 전달(모델 다운): errors={errors[:1]}",
        )
        print("       ⚠ 모델 백엔드 무응답으로 실 텍스트 미수신 — 글루는 입증, 콘텐츠는 미입증.")

    # 정리: external 사본 삭제(테스트 잔재 제거)
    _req("DELETE", f"/agents/{ext_id}", headers=AUTH)

# ---- D2: expose OFF → 카드·a2a 둘 다 404 ----
status, _ = _req("PUT", f"/agents/{aid}/expose", headers=AUTH, body={"a2a": False})
check(status == 200, f"expose OFF → 200 (got {status})")
status, _ = _req("GET", f"/agents/{aid}/.well-known/agent-card.json")
check(status == 404, f"D2 노출 OFF 후 카드 GET → 404 (got {status})")
status, _ = _req(
    "POST", f"/agents/{aid}/a2a", headers=AUTH,
    body={"jsonrpc": "2.0", "id": "1", "method": "message/send", "params": {}},
)
check(status == 404, f"D2 노출 OFF 후 a2a(인증) → 404 (got {status})")

# ---- 원상 복구: 원래 노출 상태로 ----
_req("PUT", f"/agents/{aid}/expose", headers=AUTH, body={"a2a": orig_exposed})

print()
if _fails:
    print(f"FAIL — {len(_fails)}건")
    for f in _fails:
        print("  - " + f)
    raise SystemExit(1)
print("ALL PASS — VERIFY061_LIVE_OK")

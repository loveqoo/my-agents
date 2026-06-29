"""스펙 061 검증 — 로컬(ui) 에이전트 A2A 노출의 카드·JSON-RPC 계약(단위, 라이브 런타임 미필요).

노출 라우트의 *형태·게이트·프레이밍*을 단언한다. 게이트(_load_exposed_ui_agent)와 로컬 런타임
(chat.stream_local_reply)은 monkeypatch로 대체해, DB·실 LLM 없이 카드 스키마·JSON-RPC send/stream
프레임·미지원 메서드·에러 비에코를 결정적으로 검증한다. **실왕복(D5)·인증(D6)·실 DB 게이트(D2)는
라이브 E2E**(verification 단계, 이 호스트 부팅)로 — 3-rung 분담(메모리 verification-ladder).

검증(완료조건 표면):
  D1. 노출 카드 → validate_card 통과, url 절대 http(s)·`/a2a`로 끝남, x-my-agents 없음(external 분류).
  D3. message/send → JSONRPCResponse.result Message, a2a_client.extract_text가 런타임 텍스트 복원.
  D4. message/stream → status-update 청크들 + final + [DONE], a2a_client 파서가 텍스트 복원.
  -32601. 미지원 메서드 → JSON-RPC error 코드 -32601.
  비에코. 런타임 예외 → error -32000, 메시지에 예외 *타입만*(내부값·자격증명 누출 없음).

실행: uv run python tests/verify_061_a2a_exposure.py   (or: .venv/bin/python)
"""

import asyncio
import json
import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))

os.environ.pop("A2A_SELF_BASE_URL", None)  # request.base_url 폴백을 단언

from api import a2a_client, a2a_server, agent_card, chat  # noqa: E402

_fails: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


FAKE_AGENT = types.SimpleNamespace(
    id="agt-fake-pk", name="테스트 로컬 에이전트", source="ui",
    exposed={"a2a": True}, active_version="v3",
)
FAKE_REQUEST = types.SimpleNamespace(base_url="http://127.0.0.1:8000/")
RUNTIME_REPLY_CHUNKS = ["안녕하세요, ", "로컬 ", "에이전트 ", "응답입니다."]
RUNTIME_REPLY = "".join(RUNTIME_REPLY_CHUNKS)


async def _fake_load(agent_id):
    return FAKE_AGENT


async def _fake_stream(agent_id, user_text):
    # 입력 의존(결정적) — user_text를 머리에 붙여 mock 고정문구가 아님을 보인다.
    yield f"[{user_text}] "
    for c in RUNTIME_REPLY_CHUNKS:
        yield c


async def _fake_stream_raises(agent_id, user_text):
    raise RuntimeError("secret-internal-detail-XYZ")
    yield  # pragma: no cover — async generator로 만들기 위함


# monkeypatch
a2a_server._load_exposed_ui_agent = _fake_load
chat.stream_local_reply = _fake_stream


def _collect_sse(text: str) -> list[dict]:
    """SSE 본문에서 data: JSON 라인을 파싱(‘[DONE]’ 제외)."""
    out = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            payload = line[5:].strip()
            if payload and payload != "[DONE]":
                out.append(json.loads(payload))
    return out


async def main():
    # ---- D1: 카드 ----
    card = await a2a_server.exposed_agent_card("agt-x", FAKE_REQUEST)
    try:
        agent_card.validate_card(card)
        check(True, "D1 카드가 validate_card 통과")
    except ValueError as exc:
        check(False, f"D1 카드 validate_card 실패: {exc}")
    url = card.get("url", "")
    check(url.startswith("http://") or url.startswith("https://"), f"D1 카드 url 절대 http(s): {url}")
    check(url.endswith("/a2a"), f"D1 카드 url이 /a2a로 끝남: {url}")
    check(url == "http://127.0.0.1:8000/agents/agt-x/a2a", f"D1 url=self_base+/agents/id/a2a: {url}")
    check("x-my-agents" not in card and "myAgents" not in card, "D1 x-my-agents 없음(connect→external)")
    check(agent_card.extract_my_agents(card) is None, "D1 extract_my_agents=None(제3자 분류)")

    # ---- H1(적대리뷰): Host 헤더 오염 방어 ----
    from fastapi import HTTPException  # noqa: E402

    # (a) 공인 Host + A2A_SELF_BASE_URL 미설정 → 카드 서빙 거부(503, fail-closed).
    pub_req = types.SimpleNamespace(base_url="http://attacker.example/")
    try:
        await a2a_server.exposed_agent_card("agt-x", pub_req)
        check(False, "H1 공인 Host+env없음 → 거부돼야 하는데 카드를 서빙함(오염 위험!)")
    except HTTPException as exc:
        check(exc.status_code == 503, f"H1 공인 Host+env없음 → 503 fail-closed (got {exc.status_code})")
    # (b) A2A_SELF_BASE_URL 설정 시 그걸 신뢰, 오염된 Host 무시.
    os.environ["A2A_SELF_BASE_URL"] = "https://trusted.example"
    try:
        card_env = await a2a_server.exposed_agent_card("agt-x", pub_req)
        check(
            card_env["url"] == "https://trusted.example/agents/agt-x/a2a",
            f"H1 env 설정 시 Host 무시하고 env 사용: {card_env['url']}",
        )
    finally:
        os.environ.pop("A2A_SELF_BASE_URL", None)

    # ---- D3: message/send ----
    body_send = {
        "jsonrpc": "2.0", "id": "req-1", "method": "message/send",
        "params": {"message": {"parts": [{"kind": "text", "text": "날씨 알려줘"}]}},
    }
    resp = await a2a_server.exposed_agent_a2a("agt-x", body_send, principal="machine")
    check(resp.get("jsonrpc") == "2.0" and resp.get("id") == "req-1", "D3 send JSONRPCResponse 봉투(id 에코)")
    text = a2a_client.extract_text(resp.get("result"))
    check(RUNTIME_REPLY in text, f"D3 a2a_client.extract_text가 런타임 텍스트 복원: {text!r}")
    check("날씨 알려줘" in text, "D3 응답이 입력 의존(mock 고정문구 아님)")

    # ---- D4: message/stream ----
    stream_resp = await a2a_server.exposed_agent_a2a(
        "agt-x",
        {"jsonrpc": "2.0", "id": "req-2", "method": "message/stream",
         "params": {"message": {"parts": [{"kind": "text", "text": "스트림"}]}}},
        principal="machine",
    )
    body = b""
    async for chunk in stream_resp.body_iterator:
        body += chunk if isinstance(chunk, bytes) else chunk.encode("utf-8")
    raw = body.decode("utf-8")
    frames = _collect_sse(raw)
    check(len(frames) >= 2, f"D4 status-update 프레임 다수 수신: {len(frames)}")
    kinds = {f.get("result", {}).get("kind") for f in frames}
    check(kinds == {"status-update"}, f"D4 전부 status-update: {kinds}")
    finals = [f for f in frames if f.get("result", {}).get("final")]
    check(len(finals) == 1 and finals[-1] is frames[-1], "D4 마지막 1개만 final")
    check(finals[-1]["result"]["status"]["state"] == "completed", "D4 final state=completed")
    check(raw.rstrip().endswith("[DONE]"), "D4 [DONE]로 종료")
    # a2a_client 파서 경로로 텍스트 복원(클라가 실제로 읽는 방식)
    recovered = "".join(
        a2a_client.extract_text(f.get("result")) for f in frames
    )
    check("스트림" in recovered and RUNTIME_REPLY in recovered, f"D4 클라 파서 텍스트 복원: {recovered!r}")

    # ---- -32601: 미지원 메서드 ----
    bad = await a2a_server.exposed_agent_a2a(
        "agt-x", {"jsonrpc": "2.0", "id": "req-3", "method": "tasks/cancel"}, principal="machine"
    )
    check(bad.get("error", {}).get("code") == -32601, f"미지원 메서드 → -32601: {bad.get('error')}")

    # ---- 비에코: 런타임 예외 → -32000, 내부값 미누출 ----
    chat.stream_local_reply = _fake_stream_raises
    err_resp = await a2a_server.exposed_agent_a2a(
        "agt-x",
        {"jsonrpc": "2.0", "id": "req-4", "method": "message/send",
         "params": {"message": {"parts": [{"kind": "text", "text": "x"}]}}},
        principal="machine",
    )
    emsg = err_resp.get("error", {}).get("message", "")
    check(err_resp.get("error", {}).get("code") == -32000, "비에코 send 예외 → -32000")
    check("RuntimeError" in emsg, f"비에코 메시지에 예외 타입만: {emsg!r}")
    check("secret-internal-detail-XYZ" not in emsg, "비에코 내부 예외 값 미누출")
    chat.stream_local_reply = _fake_stream  # 복원


asyncio.run(main())

print()
if _fails:
    print(f"FAIL — {len(_fails)}건")
    for f in _fails:
        print("  - " + f)
    sys.exit(1)
print("ALL PASS — VERIFY061_OK")

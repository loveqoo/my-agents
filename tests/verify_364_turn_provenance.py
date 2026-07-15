"""스펙 364 검증 — 대화 이력에 턴 id + 프롬프트(프롬프트) 출처 기록.

실서버(8000)에 로그인→에이전트 생성→채팅 여러 턴→messages 테이블 실측(HTTP+DB 통합 rung).
단순 에이전트가 유저 메시지와 답을 각각 한 행으로 저장하던 이력에, 한 턴의 두 행이 같은 turn_id로
묶이고 assistant 행에 프롬프트 id/이름 + trace.promptSnapshot(body)이 남는지 확인한다.

  C1  한 턴의 user+assistant가 같은 turn_id(비어있지 않음), 서로 다른 턴은 다른 turn_id.
  C3  assistant.prompt_id=프롬프트 id·prompt_name=프롬프트 이름, trace.promptSnapshot.body=그 턴 본문.
  C4  systemPrompt 오버라이드 턴은 prompt_id/name=null(라이브러리 참조 아님)·스냅샷 body=오버라이드 텍스트.
  C6  ephemeral 에이전트는 메시지 미저장(무회귀 — 스탬프도 없음).

전제: 서버 8000(새 코드), 시드 프롬프트 존재. 실행: .venv/bin/python tests/verify_364_turn_provenance.py
"""
import os
import sys

import httpx
from sqlalchemy import create_engine, text

BASE = os.environ.get("API_BASE", "http://127.0.0.1:8000")
EMAIL = os.environ.get("ADMIN_EMAIL", "admin@example.com")
PASSWORD = os.environ.get("ADMIN_PASSWORD", "adminpass123")
DB = os.environ.get("DATABASE_URL", "postgresql+asyncpg://agent:agent@localhost:5432/agents").replace(
    "+asyncpg", "+psycopg"
)

_fails: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def _session_from_sse(text_body: str) -> str | None:
    for line in text_body.splitlines():
        if line.startswith("data: ") and '"session"' in line:
            import json

            try:
                return json.loads(line[6:]).get("session")
            except Exception:
                return None
    return None


def main() -> None:
    eng = create_engine(DB)
    with eng.connect() as c:
        prow = c.execute(text("select id, name, body from prompts order by name limit 1")).first()
    if prow is None:
        raise SystemExit("시드 프롬프트 없음 — 전제 불충족")
    prompt_id, prompt_name, prompt_body = str(prow[0]), prow[1], prow[2]
    print(f"  --  대상 프롬프트: {prompt_name} ({prompt_id[:8]})")

    cli = httpx.Client(base_url=BASE, timeout=120.0)
    r = cli.post("/auth/login", data={"username": EMAIL, "password": PASSWORD})
    check(r.status_code < 400 and "agentauth" in cli.cookies, f"로그인 (status={r.status_code})")
    if "agentauth" not in cli.cookies:
        raise SystemExit("로그인 실패")

    def make_agent(name: str, config: dict) -> str:
        cr = cli.post("/agents", json={"name": name, "description": None, "config": config})
        cr.raise_for_status()
        j = cr.json()
        draft = next((v for v in j.get("versions", []) if v.get("status") == "draft"), None) or (
            j.get("versions") or [{}]
        )[0]
        cli.post(f"/agents/{j['id']}/activate", json={"version": draft.get("version")}).raise_for_status()
        return j["id"]

    def chat(aid: str, msg: str, session: str | None, overrides: dict | None = None) -> str | None:
        body: dict = {"messages": [{"role": "user", "content": msg}], "sessionId": session}
        if overrides is not None:
            body["overrides"] = overrides
        resp = cli.post(f"/agents/{aid}/chat", json=body)
        resp.raise_for_status()
        return _session_from_sse(resp.text) or session

    import uuid as _uuid

    tag = _uuid.uuid4().hex[:6]
    # ── 일반(라이브러리 프롬프트) 에이전트: 두 턴 ──────────────────────────────
    aid = make_agent(
        f"v364-lib-{tag}",
        {"model": "mock-llm", "prompt": prompt_name, "mcps": [], "memories": [], "vectorTables": []},
    )
    sess = chat(aid, "364 첫 번째 턴입니다", None)
    check(bool(sess), f"채팅 턴1 세션 생성 (session={sess})")
    chat(aid, "364 두 번째 턴입니다", sess)
    if overrides_supported := True:  # C4 — 같은 세션에서 systemPrompt 오버라이드 턴
        chat(aid, "364 오버라이드 턴입니다", sess, overrides={"systemPrompt": "임시 오버라이드 프롬프트 364"})

    with eng.connect() as c:
        rows = c.execute(
            text(
                "select m.role, m.turn_id, m.prompt_id, m.prompt_name, m.trace "
                "from messages m join sessions s on s.id = m.session_pk "
                "where s.session_id = :sid order by m.created_at"
            ),
            {"sid": sess},
        ).fetchall()

    # 6행(3턴 × user+assistant)
    check(len(rows) == 6, f"C1: 3턴 = 6행 저장 (실제 {len(rows)})")
    # 턴별로 (user,assistant) 쌍이 같은 turn_id
    turns = [(rows[i], rows[i + 1]) for i in range(0, len(rows) - 1, 2)]
    tids = []
    for i, (u, a) in enumerate(turns, 1):
        check(
            u.turn_id and a.turn_id and u.turn_id == a.turn_id,
            f"C1: 턴{i} user·assistant turn_id 동일·비어있지 않음 (u={u.turn_id}, a={a.turn_id})",
        )
        tids.append(a.turn_id)
    check(len(set(tids)) == len(tids), f"C1: 세 턴의 turn_id 서로 다름 ({tids})")

    # C3 — 턴1·2 assistant: 라이브러리 프롬프트 id/name + 스냅샷 body
    for i in (0, 1):
        a = turns[i][1]
        snap = (a.trace or {}).get("promptSnapshot") or {}
        check(a.prompt_id == prompt_id, f"C3: 턴{i+1} assistant.prompt_id=프롬프트 id")
        check(a.prompt_name == prompt_name, f"C3: 턴{i+1} assistant.prompt_name=프롬프트 이름")
        check(snap.get("body") == prompt_body, f"C3: 턴{i+1} promptSnapshot.body=프롬프트 본문")

    # C4 — 오버라이드 턴 assistant: 라이브러리 참조 아님(null) + 스냅샷=오버라이드 텍스트
    ov = turns[2][1]
    ov_snap = (ov.trace or {}).get("promptSnapshot") or {}
    check(ov.prompt_id is None and ov.prompt_name is None, "C4: 오버라이드 턴 prompt_id/name=null(라이브러리 아님)")
    check(ov_snap.get("body") == "임시 오버라이드 프롬프트 364", "C4: 오버라이드 턴 스냅샷 body=오버라이드 텍스트")

    # ── C6 ephemeral: 메시지 미저장 ───────────────────────────────────────────
    eid = make_agent(
        f"v364-eph-{tag}",
        {"model": "mock-llm", "prompt": prompt_name, "mcps": [], "memories": [], "vectorTables": [], "ephemeral": True},
    )
    esess = chat(eid, "364 ephemeral 턴", None)
    with eng.connect() as c:
        n = c.execute(
            text("select count(*) from messages m join sessions s on s.id=m.session_pk where s.session_id=:sid"),
            {"sid": esess or ""},
        ).scalar()
    check((n or 0) == 0, f"C6: ephemeral 턴 메시지 미저장 (rows={n})")

    # 정리
    for a in (aid, eid):
        cli.delete(f"/agents/{a}")
    cli.close()

    print()
    if _fails:
        print(f"FAILED ({len(_fails)}):")
        for f in _fails:
            print("  - " + f)
        sys.exit(1)
    print("ALL PASS (verify_364)")


if __name__ == "__main__":
    main()

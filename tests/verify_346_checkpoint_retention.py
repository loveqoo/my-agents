"""verify_346 — 체크포인트 누적 종식(관문 + 스윕) (스펙 346).

  R1 **관문 실동작**(라이브 HTTP): 3턴 대화 후 그 세션의 체크포인트 행 = **0**(끝난 턴의 시체 0).
  R2 durability="exit" 배선(정적 스캔): 그래프 실행 두 지점(chat.astream · chat_approval.ainvoke)에
     실제로 전달되는가 — 주석/독스트링은 제외하고 **코드에서만** 센다.
  R3 **승인 대기는 보존**: pending Approval이 가리키는 스레드는 release_thread가 남긴다('kept:approval').
     승인이 해소되면 같은 스레드가 폐기된다('deleted') — HIL의 생명줄이 턴 종료로 끊기지 않는다.
  R4 **폼 대기는 보존**: _PENDING_ARTIFACT가 가리키는 스레드는 keep_reason='artifact'.
  R5 **나이 문턱**: 방금 만든 스레드는 스윕 후보 0(진행 중 턴·폼 대기 보호).
  R6 **고아 회수**: TTL을 넘긴 스레드는 dry-run 후보 → 실행 시 삭제.
  R7 **조용한 삭제 금지**: 방치된 pending 승인은 status='expired'로 기록된 뒤에야 스레드가 삭제된다
     (회고 038의 적대리뷰 결함 — 체크포인트만 지우면 화면엔 대기 중인데 재개만 실패).
  R8 **파괴적 노브 바닥**: ttl_hours=0이면 아무 것도 안 지운다(0을 delete-all로 매핑 금지, learning 037).

실행: uv run python tests/verify_346_checkpoint_retention.py   (dev 서버 8000 필요)
"""

import asyncio
import io
import json
import os
import pathlib
import sys
import tokenize
import urllib.request
import uuid
from datetime import UTC, datetime, timedelta

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "api" / "src"))

from sqlalchemy import text  # noqa: E402

from api import checkpoint_retention, checkpointer  # noqa: E402
from api.db import SessionLocal  # noqa: E402
from api.models import Approval  # noqa: E402

BASE = os.environ.get("VERIFY_BASE", "http://127.0.0.1:8000")  # 스펙 390: 격리 서버 주입
EMAIL, PW = "admin@example.com", "adminpass123"

_fails: list[str] = []
passed = 0


def check(cond: object, msg: str) -> None:
    global passed
    print(("  ok  " if cond else " FAIL ") + msg)
    if cond:
        passed += 1
    else:
        _fails.append(msg)


def _code_only(path: pathlib.Path) -> str:
    """주석·독스트링을 제거한 코드 텍스트 — '주석에 썼는데 코드엔 없는' 거짓 통과 방지(스펙 343 V10 패턴)."""
    src = path.read_text()
    out = []
    prev_type = tokenize.INDENT
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.COMMENT:
            continue
        if tok.type == tokenize.STRING and prev_type in (
            tokenize.INDENT,
            tokenize.NEWLINE,
            tokenize.NL,
            tokenize.DEDENT,
        ):
            continue  # 독스트링
        out.append(tok.string)
        if tok.type not in (tokenize.NL, tokenize.NEWLINE):
            prev_type = tok.type
    return " ".join(out)


_cookie = ""


def login() -> None:
    global _cookie
    req = urllib.request.Request(
        BASE + "/auth/login", data=f"username={EMAIL}&password={PW}".encode(), method="POST"
    )
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=20) as r:
        _cookie = "; ".join(c.split(";")[0] for c in r.headers.get_all("Set-Cookie") or [])


def _chat(agent_id: str, msg: str, session_id: str | None) -> str:
    body: dict = {"messages": [{"role": "user", "content": msg}]}
    if session_id:
        body["sessionId"] = session_id
    req = urllib.request.Request(
        BASE + f"/agents/{agent_id}/chat", data=json.dumps(body).encode(), method="POST"
    )
    req.add_header("Content-Type", "application/json")
    req.add_header("Cookie", _cookie)
    sid = session_id or ""
    with urllib.request.urlopen(req, timeout=60) as r:
        for line in r:  # 스트림을 끝까지 소비해야 관문(finally)이 돈다
            s = line.decode().strip()
            if s.startswith("data: ") and not sid:
                try:
                    sid = json.loads(s[6:]).get("session", "")
                except Exception:
                    pass
    return sid


def _agents() -> list[dict]:
    return _req("/agents")


def _req(path: str, method: str = "GET", body: dict | None = None):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(body).encode() if body else None, method=method
    )
    req.add_header("Cookie", _cookie)
    if body:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read().decode()
        return json.loads(raw) if raw else {}


def _chat_frames(
    agent_id: str, msg: str, session_id: str | None, form: dict | None = None
) -> list[str]:
    """SSE 프레임 전량 — 스트림을 끝까지 소비해야 관문(finally)이 돈다."""
    body: dict = {"messages": [{"role": "user", "content": msg}]}
    if session_id:
        body["sessionId"] = session_id
    if form:
        body["form"] = form
    req = urllib.request.Request(
        BASE + f"/agents/{agent_id}/chat", data=json.dumps(body).encode(), method="POST"
    )
    req.add_header("Content-Type", "application/json")
    req.add_header("Cookie", _cookie)
    with urllib.request.urlopen(req, timeout=60) as r:
        return [line.decode().strip() for line in r if line.strip()]


async def _rows(thread_id: str) -> int:
    async with SessionLocal() as s:
        return (
            await s.execute(
                text("select count(*) from checkpoints where thread_id = :t"), {"t": thread_id}
            )
        ).scalar_one()


async def _plant_thread(thread_id: str, *, age_hours: float) -> None:
    """합성 체크포인트 1행 — ts를 과거로 박아 '나이 든 스레드'를 만든다(스윕 대상 판정 실증)."""
    ts = (datetime.now(UTC) - timedelta(hours=age_hours)).isoformat()
    async with SessionLocal() as s:
        await s.execute(
            text(
                "insert into checkpoints (thread_id, checkpoint_ns, checkpoint_id, type, checkpoint, metadata) "
                "values (:t, '', :cid, 'msgpack', cast(:ck as jsonb), '{}'::jsonb)"
            ),
            {"t": thread_id, "cid": str(uuid.uuid4()), "ck": json.dumps({"v": 4, "ts": ts})},
        )
        await s.commit()


async def _cleanup(prefix: str) -> None:
    async with SessionLocal() as s:
        await s.execute(
            text("delete from checkpoints where thread_id like :p"), {"p": prefix + "%"}
        )
        await s.execute(
            text("delete from approvals where approval_id like :p"), {"p": prefix + "%"}
        )
        await s.commit()


async def main() -> None:
    login()
    await checkpointer.init_checkpointer()  # 테스트 프로세스에도 saver 필요(배치와 동형)
    tag = f"verify346-{uuid.uuid4().hex[:6]}"

    # ---- R1: 관문 실동작 — 3턴 대화 후 그 세션의 체크포인트 0행
    agent = _agents()[0]
    sid = _chat(agent["id"], "첫 턴", None)
    for i in range(2):
        _chat(agent["id"], f"{i + 2}번째 턴", sid)
    await asyncio.sleep(0.5)  # 스트림 finally(관문)가 끝나도록
    async with SessionLocal() as s:
        left = (
            await s.execute(
                text("select count(*) from checkpoints where thread_id like :p"),
                {"p": f"%{sid}%"},
            )
        ).scalar_one()
    check(left == 0, f"R1 3턴 대화 후 그 세션의 체크포인트 0행 (남은 행: {left})")

    # ---- R2: durability="exit" 배선(코드에서만 — 주석 제외)
    src_dir = ROOT / "packages" / "api" / "src" / "api"
    chat_code = _code_only(src_dir / "chat.py")
    appr_code = _code_only(src_dir / "chat_approval.py")
    check(
        'durability = "exit"' in chat_code.replace("durability='exit'", 'durability = "exit"')
        or 'durability="exit"' in chat_code.replace(" ", ""),
        "R2a chat.py astream이 durability='exit' 전달(코드)",
    )
    check(
        'durability="exit"' in appr_code.replace(" ", ""),
        "R2b chat_approval.py 재개도 durability='exit' 전달(코드)",
    )

    # ---- R3: 승인 대기는 보존 → 해소되면 폐기
    t_appr = f"{tag}:approval"
    await _plant_thread(t_appr, age_hours=0.1)
    async with SessionLocal() as s:
        s.add(
            Approval(
                approval_id=f"{tag}-a1",
                checkpoint=t_appr,
                status="pending",
                agent_name="verify346",
                permission="data.delete",
            )
        )
        await s.commit()
    r = await checkpoint_retention.release_thread(t_appr)
    check(
        r == "kept:approval" and await _rows(t_appr) == 1,
        f"R3a 승인 대기 스레드는 관문이 보존 (got {r!r}, rows={await _rows(t_appr)})",
    )
    async with SessionLocal() as s:  # 승인 해소
        await s.execute(
            text("update approvals set status='approved' where approval_id = :a"),
            {"a": f"{tag}-a1"},
        )
        await s.commit()
    r = await checkpoint_retention.release_thread(t_appr)
    check(
        r == "deleted" and await _rows(t_appr) == 0,
        f"R3b 승인 해소 후 같은 스레드는 폐기 (got {r!r}, rows={await _rows(t_appr)})",
    )

    # ---- R4: 폼 대기는 보존(프로세스 메모리)
    from api.chat_approval import _PENDING_ARTIFACT

    t_art = f"{tag}:artifact"
    await _plant_thread(t_art, age_hours=0.1)
    _PENDING_ARTIFACT["sess-verify346"] = {"thread_id": t_art}
    reason = await checkpoint_retention.keep_reason(t_art)
    check(reason == "artifact", f"R4 폼 대기 스레드는 보존 판정 (got {reason!r})")
    _PENDING_ARTIFACT.pop("sess-verify346", None)

    # ---- R5: 나이 문턱 — 방금 만든 스레드는 스윕 후보 아님
    t_fresh = f"{tag}:fresh"
    await _plant_thread(t_fresh, age_hours=0.5)
    dry = await checkpoint_retention.sweep(dry_run=True, ttl_hours=24)
    check(
        t_fresh not in (dry.get("sample") or []) and await _rows(t_fresh) == 1,
        f"R5 24h 미만 스레드는 스윕 대상 아님 (후보 {dry.get('candidates')}건)",
    )

    # ---- R6/R7: 고아 회수 + 방치 승인은 '만료'로 기록된 뒤 삭제
    t_orphan = f"{tag}:orphan"
    t_stale = f"{tag}:stale-approval"
    await _plant_thread(t_orphan, age_hours=30)
    await _plant_thread(t_stale, age_hours=30)
    async with SessionLocal() as s:
        s.add(
            Approval(
                approval_id=f"{tag}-a2",
                checkpoint=t_stale,
                status="pending",
                agent_name="verify346",
                permission="data.delete",
            )
        )
        await s.commit()

    dry = await checkpoint_retention.sweep(dry_run=True, ttl_hours=24)
    sample = dry.get("sample") or []
    check(
        t_orphan in sample
        and t_stale in sample
        and dry.get("would_expire", 0) >= 1
        and await _rows(t_orphan) == 1,
        f"R6a dry-run은 대상만 집계하고 **삭제하지 않음** (would_delete={dry.get('would_delete')}, "
        f"would_expire={dry.get('would_expire')})",
    )

    res = await checkpoint_retention.sweep(dry_run=False, ttl_hours=24)
    check(await _rows(t_orphan) == 0, f"R6b 고아 스레드 회수 (deleted={res.get('deleted')})")

    async with SessionLocal() as s:
        st = (
            await s.execute(
                text("select status from approvals where approval_id = :a"), {"a": f"{tag}-a2"}
            )
        ).scalar_one()
    check(
        st == "expired" and await _rows(t_stale) == 0,
        f"R7 방치 승인은 'expired'로 기록된 뒤 스레드 삭제(조용한 삭제 0) (status={st!r})",
    )

    # ---- R8: 파괴적 노브 바닥 — ttl=0이면 아무 것도 안 지운다
    t_floor = f"{tag}:floor"
    await _plant_thread(t_floor, age_hours=100)
    res0 = await checkpoint_retention.sweep(dry_run=False, ttl_hours=0)
    check(
        res0.get("status") == "disabled" and await _rows(t_floor) == 1,
        f"R8 ttl=0은 비활성(0을 delete-all로 매핑 금지) (got {res0.get('status')!r}, "
        f"rows={await _rows(t_floor)})",
    )

    # ---- R9/R10: **라이브 HIL 왕복**(실 HTTP) — 정적 스캔이 아니라 실동작.
    # 폼형(artifact_form) 에이전트는 mock 모델로도 interrupt를 낸다(위험 도구 승인은 실모델의 도구
    # 호출이 필요해 라이브 재현이 불가 — 같은 interrupt/재개 기계를 폼으로 관통 검증한다).
    models = _req("/models")
    chat_model = next(m for m in models if m.get("kind") == "chat")
    form_agent = _req(
        "/agents",
        "POST",
        {
            "name": f"{tag}-form",
            "prompt": "폼 수집기",
            "modelId": chat_model["id"],
            "config": {
                "impl": "artifact_form",
                "artifactSpec": {
                    "kind": "signup",
                    "fields": [{"key": "email", "label": "이메일", "required": True}],
                },
            },
        },
    )
    try:
        frames = _chat_frames(form_agent["id"], "가입할래", None)
        fsid = json.loads(frames[0][6:])["session"]
        frame = next(json.loads(f[6:]) for f in frames if f.startswith("data: ") and '"form"' in f)
        async with SessionLocal() as s:
            n = (
                await s.execute(
                    text("select count(*) from checkpoints where thread_id like :p"),
                    {"p": f"%{fsid}%"},
                )
            ).scalar_one()
        # 1행 = durability="exit"의 실증(기본 async 모드였다면 슈퍼스텝마다 쌓여 3행 이상).
        check(
            n == 1, f"R9 폼 interrupt: 체크포인트 **1행**만 남고 보존됨(exit 모드 실증) (got {n})"
        )

        _chat_frames(
            form_agent["id"],
            "제출",
            fsid,
            form={"formId": frame["formId"], "values": {"email": "u@example.com"}},
        )
        await asyncio.sleep(0.4)
        async with SessionLocal() as s:
            n2 = (
                await s.execute(
                    text("select count(*) from checkpoints where thread_id like :p"),
                    {"p": f"%{fsid}%"},
                )
            ).scalar_one()
        check(n2 == 0, f"R10 폼 제출·재개 완료 후 그 스레드 폐기 (남은 행: {n2})")
    finally:
        _req(f"/agents/{form_agent['id']}", "DELETE")

    # ---- R11: **codex P1 핀** — 멈춘 그래프는 핀이 아직 없어도 지우지 않는다.
    # 핀(승인 행·폼 포인터)은 interrupt **이후**에 심긴다. 그 사이 클라이언트가 끊기면 관문이
    # 먼저 도는데, 'paused'를 안 보면 재개 근거를 지워버린다. 규칙은 "핀이 있나"가 아니라
    # **"턴이 정말 끝났나"**여야 한다.
    t_paused = f"{tag}:paused"
    await _plant_thread(t_paused, age_hours=0.1)  # 핀 없음(승인 행도, 폼 포인터도 없음)
    r_paused = await checkpoint_retention.release_thread(t_paused, paused=True)
    check(
        r_paused == "kept:paused" and await _rows(t_paused) == 1,
        f"R11 멈춘 그래프는 핀 없이도 보존(취소 창 봉인) (got {r_paused!r}, rows={await _rows(t_paused)})",
    )
    r_done = await checkpoint_retention.release_thread(t_paused, paused=False)
    check(
        r_done == "deleted" and await _rows(t_paused) == 0,
        f"R11b 끝난 턴은 여전히 폐기(보존이 만능이 되지 않게) (got {r_done!r})",
    )

    # 관문 호출부가 실제로 paused를 넘기는가(코드 스캔 — 넘기지 않으면 위 보장은 죽은 코드).
    # 스펙 403서 SSE finally 관문이 release_thread→shielded_release(취소-보호 래퍼, paused 그대로
    # release_thread에 전달)로 개명 — 노후 문자열 현행화(보장 자체는 R11/R11b가 검증).
    check(
        "shielded_release(thread_id,paused=bool(interrupts))" in chat_code.replace(" ", ""),
        "R11c chat.py 관문이 paused=bool(interrupts)를 실제로 전달",
    )

    await _cleanup(tag)
    print()
    if _fails:
        print(f"FAIL {len(_fails)}건: {_fails}")
        sys.exit(1)
    print(f"VERIFY346_OK — {passed}건 전부 통과")


asyncio.run(main())

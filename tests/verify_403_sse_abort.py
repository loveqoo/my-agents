"""verify_403 — SSE 이탈 커넥션 풀 오염 봉합(스펙 403) 공격형 회귀.

402의 068 조사에서 실측된 실구멍의 방어를 공격으로 검증한다:
  A1 설정 단언(installed≠covering — 장치가 꺼지면 여기서 잡힘):
     메인 엔진 pool_pre_ping=True(런타임 플래그) + 체크포인터 풀 check 배선(소스).
  A2 abort 폭격: chat SSE를 첫 프레임만 읽고 의도적으로 끊기 ×N — 구(pre-403) 코드에서
     ASGI 취소가 커넥션을 오염시키던 바로 그 패턴.
  A3 오염 검출: 폭격 직후 인증 요청(GET /sessions) ×M 전부 200 — poison이 남았다면
     비결정 500이 여기서 튄다(402 실측: 인증 쿼리 "connection is closed").
  A4 정상 경로 무회귀: 드레인 채팅 1회 완주(세션 에코 수신).
반복 3라운드(비결정 대비).

실행: uv run --project packages/api python tests/_throwaway_server.py tests/verify_403_sse_abort.py
"""

import asyncio
import json
import os
import sys
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))

import httpx  # noqa: E402

BASE = os.environ.get("VERIFY_BASE", "http://127.0.0.1:8000")

_fails: list[str] = []
passed = 0


def check(cond: bool, msg: str) -> None:
    global passed
    print(("  ok  " if cond else " FAIL ") + msg)
    if cond:
        passed += 1
    else:
        _fails.append(msg)


def _auth() -> dict:
    from api.auth import _token

    return {"Authorization": f"Bearer {_token()}"}


def unit_config() -> None:
    # A1a — 메인 엔진 pool_pre_ping(런타임 플래그: 코드 경로 그대로 재생성해 단언).
    from api.db import engine

    check(
        bool(engine.sync_engine.pool._pre_ping),
        "A1a 메인 엔진 pool_pre_ping=True(오염 커넥션 checkout 자가치유)",
    )
    # A1b — 체크포인터 풀 check 배선(소스 단언: 초기화는 DB 필요라 소스 계약으로).
    src = open(
        os.path.join(ROOT, "packages", "api", "src", "api", "checkpointer.py"), encoding="utf-8"
    ).read()
    check(
        "check=AsyncConnectionPool.check_connection" in src,
        "A1b 체크포인터 풀 check=check_connection 배선",
    )
    # A1c — release_thread 취소-보호(shield) 배선.
    csrc = open(
        os.path.join(ROOT, "packages", "api", "src", "api", "chat.py"), encoding="utf-8"
    ).read()
    check(
        "checkpoint_retention.shielded_release" in csrc,
        "A1c event_stream 정리가 관문 헬퍼(shielded_release — 강참조+shield 완주 보장) 경유",
    )
    # A1d — A2A 로컬 서빙에도 폐기 관문(codex 403 P1②: 388 P2 체크포인터 도입 후 관문 부재였음).
    asrc = open(
        os.path.join(ROOT, "packages", "api", "src", "api", "chat_a2a_serve.py"), encoding="utf-8"
    ).read()
    check(
        "shielded_release" in asrc,
        "A1d A2A 서빙 chunks()도 같은 관문(shielded_release)으로 폐기+취소-보호",
    )
    # A1e — 관문 헬퍼가 강참조 세트를 유지(고아 방지 — 참조 없는 shield는 완주가 아니라 방치).
    rsrc = open(
        os.path.join(ROOT, "packages", "api", "src", "api", "checkpoint_retention.py"),
        encoding="utf-8",
    ).read()
    check(
        "_RELEASE_TASKS" in rsrc and "add_done_callback" in rsrc,
        "A1e shielded_release가 강참조 세트+완료 콜백(고아 0)",
    )


async def _abort_chat(c: httpx.AsyncClient, aid: str) -> int:
    """SSE를 첫 프레임만 읽고 끊는다(의도적 early-abort — 402의 오염 유발 패턴). status 반환."""
    body = {"messages": [{"role": "user", "content": "abort probe"}]}
    async with c.stream("POST", f"/agents/{aid}/chat", json=body) as r:
        if r.status_code != 200:
            return r.status_code
        async for _line in r.aiter_lines():
            break  # 첫 줄만 읽고 즉시 이탈 → 서버 턴이 도는 중에 연결 abort
    return 200


async def _drained_chat(c: httpx.AsyncClient, aid: str) -> str | None:
    """정상 드레인 채팅 — 세션 에코를 회수하고 스트림을 끝까지 소진."""
    body = {"messages": [{"role": "user", "content": "안녕"}]}
    echo = None
    async with c.stream("POST", f"/agents/{aid}/chat", json=body) as r:
        if r.status_code != 200:
            return None
        async for line in r.aiter_lines():
            if line.startswith("data: ") and echo is None:
                try:
                    obj = json.loads(line[6:])
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict) and "session" in obj:
                    echo = obj["session"]
    return echo


async def _checkpoint_rows() -> int:
    """throwaway DB의 checkpoints 행 수(테이블 부재=0 — 체크포인터 미초기화 폴백)."""
    from sqlalchemy import text as _text

    from api.db import SessionLocal

    async with SessionLocal() as s:
        try:
            return int((await s.execute(_text("SELECT count(*) FROM checkpoints"))).scalar_one())
        except Exception:
            return 0


async def main() -> None:
    unit_config()

    tag = f"v403-{uuid.uuid4().hex[:6]}"
    async with httpx.AsyncClient(base_url=BASE, headers=_auth(), timeout=60) as c:
        r = await c.post(
            "/agents",
            json={"name": tag, "config": {"model": "mock-llm", "prompt": "짧게 답한다."}},
        )
        check(r.status_code == 201, f"셋업 에이전트 생성 201 (got {r.status_code})")
        aid = r.json()["id"]
        try:
            for rnd in (1, 2, 3):
                # A2 — abort 폭격 8발.
                statuses = [await _abort_chat(c, aid) for _ in range(8)]
                check(
                    all(s == 200 for s in statuses),
                    f"A2 r{rnd} abort 폭격 8발 전부 200 시작 (got {statuses})",
                )
                # A3 — 직후 인증 요청 15발: poison이 남았다면 여기서 비결정 500.
                codes = []
                for _ in range(15):
                    codes.append((await c.get("/sessions", params={"limit": 1})).status_code)
                check(
                    all(x == 200 for x in codes),
                    f"A3 r{rnd} 폭격 직후 인증 요청 15발 500 무발생 (got {sorted(set(codes))})",
                )
                # A4 — 정상 경로 무회귀.
                echo = await _drained_chat(c, aid)
                check(echo is not None, f"A4 r{rnd} 드레인 채팅 완주(세션 {str(echo)[:12]}…)")
                await asyncio.sleep(1.5)  # 서버측 취소 정리(강참조 shield 완주) 여유
                # A5 — 체크포인트 무잔류: abort 경로에서도 346 폐기 관문이 완주했는가
                # (codex 403 P2②: 방어 효과만 보지 말고 정리 불변식을 단언하라).
                n_ck = await _checkpoint_rows()
                check(n_ck == 0, f"A5 r{rnd} abort 후 체크포인트 잔류 0 (got {n_ck})")
        finally:
            await c.delete(f"/agents/{aid}")

    print(f"\n{passed} passed, {len(_fails)} failed")
    if _fails:
        sys.exit(1)
    print("VERIFY403_OK")


if __name__ == "__main__":
    asyncio.run(main())

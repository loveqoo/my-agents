"""verify_388 — A2A 서빙 v2 P1: contextId 세션 연속성+영속(스펙 388).

- C1: contextId 없이 send → 응답에 contextId(sess- 발급). 같은 contextId로 2턴째 → 동일 contextId
      에코 + 세션·메시지 영속(4행, channel="a2a", user_id 스탬프).
- C2: 위조 contextId → 새 세션으로 접음(에러/구분 없음 — 오라클 0). 타 userId로 남의 contextId
      재개 → 새 세션(userId 바인딩).
- C3: 자동 기억 저장 스코프가 user+run 축(세션 축 개방 — 계측 단언).

전제: 실모델 등록(mem_cfg — 기억 계측용)·시드. 픽스처 자체 생성·정리(v388- 접두=리퍼 패턴).
실행: cd packages/api && uv run python ../../tests/verify_388_a2a_session.py
"""

from __future__ import annotations

import asyncio
import secrets

import httpx
from sqlalchemy import select

from api.auth import _token
from api.db import SessionLocal
from api.main import app
from api.models import Message, Session

PASS, FAIL = "PASS", "FAIL"
results: list[tuple[str, str, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, PASS if ok else FAIL, detail))


def _rpc(text: str, *, context_id: str | None = None, user_id: str | None = None) -> dict:
    msg: dict = {"role": "user", "parts": [{"kind": "text", "text": text}]}
    if context_id:
        msg["contextId"] = context_id
    if user_id:
        msg["metadata"] = {"userId": user_id}
    return {"jsonrpc": "2.0", "id": "1", "method": "message/send", "params": {"message": msg}}


async def main() -> int:
    # HIL 체크포인터+authz(스펙 388 P2) — 인프로세스는 lifespan을 안 타므로 직접 초기화(실서버는 lifespan).
    from api import authz as _authz
    from api import checkpointer as _ckpt

    await _ckpt.init_checkpointer()
    await _authz.init_authz()
    auth = {"Authorization": f"Bearer {_token()}"}
    transport = httpx.ASGITransport(app=app)
    uid_a, uid_b = "v388-user-a", "v388-user-b"
    agent_id = None
    async with httpx.AsyncClient(
        transport=transport, base_url="http://t", headers=auth, timeout=180
    ) as c:
        try:
            r = await c.post(
                "/agents",
                json={
                    "name": "v388-mem",
                    "description": "스펙 388 P1 검증 픽스처",
                    "config": {
                        "model": "mock-llm",
                        "prompt": "간결한 도우미",
                        "memories": ["장기 기억 (mem0)"],
                        "historyDepth": 6,
                    },
                },
            )
            check("F0 픽스처 생성 201", r.status_code == 201, f"{r.status_code} {r.text[:100]}")
            agent_id = r.json()["id"]
            r = await c.put(f"/agents/{agent_id}/expose", json={"a2a": True})
            check("F1 노출 200", r.status_code == 200, f"{r.status_code}")

            # ---- C3 준비: 자동 저장 스코프 계측(LLM 추출 비결정 무관 — 배선 단언)
            from api import memory

            add_scopes: list[dict] = []
            _orig_add = memory.add

            def _rec_add(scope, msgs, cfg, infer=True):  # noqa: ANN001, ANN202
                add_scopes.append(dict(scope))
                return [{"event": "ADD", "text": "stub"}]

            # ---- C1: 1턴(contextId 없음) → 발급
            memory.add = _rec_add
            try:
                r = await c.post(f"/agents/{agent_id}/a2a", json=_rpc("첫 턴입니다", user_id=uid_a))
            finally:
                memory.add = _orig_add
            body = (r.json() or {}).get("result") or {}
            ctx1 = body.get("contextId")
            check(
                "C1a 발급된 contextId(sess-)",
                isinstance(ctx1, str) and ctx1.startswith("sess-"),
                f"contextId={ctx1!r}",
            )
            check(
                "C3 자동 저장 스코프 = user+run 축",
                any(s == {"user_id": uid_a, "run_id": ctx1} for s in add_scopes),
                f"scopes={add_scopes[:2]}",
            )

            # ---- C1: 2턴(같은 contextId) → 동일 에코 + 영속 4행
            r = await c.post(
                f"/agents/{agent_id}/a2a", json=_rpc("두 번째 턴", context_id=ctx1, user_id=uid_a)
            )
            ctx2 = ((r.json() or {}).get("result") or {}).get("contextId")
            check("C1b 재개 시 동일 contextId 에코", ctx2 == ctx1, f"{ctx2} vs {ctx1}")
            async with SessionLocal() as s:
                sess = (
                    await s.execute(select(Session).where(Session.session_id == ctx1))
                ).scalar_one_or_none()
                n_msgs = 0
                if sess:
                    n_msgs = len(
                        (await s.execute(select(Message.id).where(Message.session_pk == sess.id)))
                        .scalars()
                        .all()
                    )
            check(
                "C1c 세션 영속(channel=a2a)",
                sess is not None and sess.channel == "a2a",
                f"channel={getattr(sess, 'channel', None)}",
            )
            check(
                "C1d 소유자 스탬프(user_id=uid_a)",
                sess is not None and sess.user_id == uid_a,
                f"user_id={getattr(sess, 'user_id', None)}",
            )
            check("C1e 메시지 4행(2턴)", n_msgs == 4, f"{n_msgs}행")

            # ---- C2: 위조 contextId → 새 세션으로 접음(오라클 0)
            fake = "sess-" + secrets.token_hex(16)
            r = await c.post(
                f"/agents/{agent_id}/a2a", json=_rpc("위조 시도", context_id=fake, user_id=uid_a)
            )
            ctx_f = ((r.json() or {}).get("result") or {}).get("contextId")
            check(
                "C2a 위조 contextId → 새 세션(에러 없음·미에코)",
                r.status_code == 200 and isinstance(ctx_f, str) and ctx_f not in (fake, ctx1),
                f"응답 contextId={ctx_f!r}",
            )
            # ---- C2: 타 userId가 남의 contextId 재개 → 접음(userId 바인딩)
            r = await c.post(
                f"/agents/{agent_id}/a2a",
                json=_rpc("남의 대화 재개 시도", context_id=ctx1, user_id=uid_b),
            )
            ctx_b = ((r.json() or {}).get("result") or {}).get("contextId")
            check(
                "C2b 타 userId 재개 → 새 세션(바인딩)",
                r.status_code == 200 and isinstance(ctx_b, str) and ctx_b != ctx1,
                f"응답 contextId={ctx_b!r}",
            )
            # ================= P2 — 승인(HIL) 브리지 =================
            # 위험 도구 픽스처: local-tools의 delete_record(승인 필요). mock-llm 트리거="삭제".
            r = await c.post(
                "/agents",
                json={
                    "name": "v388-hil",
                    "config": {
                        "model": "mock-llm",
                        "prompt": "도구 도우미",
                        "mcps": ["local-tools"],
                        "tools": ["local-tools__delete_record"],
                        "historyDepth": 6,
                    },
                },
            )
            check(
                "P2-F0 위험도구 픽스처 201", r.status_code == 201, f"{r.status_code} {r.text[:100]}"
            )
            hil_id = r.json()["id"]
            created_hil = hil_id
            r = await c.put(f"/agents/{hil_id}/expose", json={"a2a": True})
            check("P2-F1 노출 200", r.status_code == 200, f"{r.status_code}")

            # P2-C1: 삭제 요청 → input-required Task(+approvalId), 도구 미실행
            r = await c.post(
                f"/agents/{hil_id}/a2a", json=_rpc("레코드 rec-1 을 삭제해줘", user_id=uid_a)
            )
            res = (r.json() or {}).get("result") or {}
            ap_meta = res.get("metadata") or {}
            apid = ap_meta.get("approvalId")
            check(
                "P2-C1a input-required Task 응답",
                res.get("kind") == "task"
                and (res.get("status") or {}).get("state") == "input-required",
                f"kind={res.get('kind')} state={(res.get('status') or {}).get('state')}",
            )
            check(
                "P2-C1b approvalId 동봉",
                isinstance(apid, str) and apid.startswith("apr-"),
                f"{apid!r}",
            )
            hil_ctx = res.get("contextId")

            # P2-C3(소유권): 타 userId가 결정 시도 → 부재와 동일 응답(-32001)
            deny = {
                "jsonrpc": "2.0",
                "id": "9",
                "method": "message/send",
                "params": {
                    "message": {
                        "role": "user",
                        "parts": [{"kind": "text", "text": "approve"}],
                        "metadata": {"userId": uid_b, "approvalId": apid, "decision": "approve"},
                    }
                },
            }
            r = await c.post(f"/agents/{hil_id}/a2a", json=deny)
            err = (r.json() or {}).get("error") or {}
            check("P2-C3 타 userId 결정 → 접기(-32001)", err.get("code") == -32001, str(err)[:100])

            # P2-C2: 정당한 userId로 approve → 재개·최종 답변 수신 + 승인 상태 approved
            ok_msg = {
                "jsonrpc": "2.0",
                "id": "10",
                "method": "message/send",
                "params": {
                    "message": {
                        "role": "user",
                        "parts": [{"kind": "text", "text": "approve"}],
                        "metadata": {"userId": uid_a, "approvalId": apid, "decision": "approve"},
                    }
                },
            }
            r = await c.post(f"/agents/{hil_id}/a2a", json=ok_msg)
            res2 = (r.json() or {}).get("result") or {}
            reply_text = "".join(
                pt.get("text", "") for pt in (res2.get("parts") or []) if isinstance(pt, dict)
            )
            check(
                "P2-C2a approve → 재개 답변 수신",
                res2.get("kind") == "message" and bool(reply_text.strip()),
                f"reply={reply_text[:80]!r}",
            )
            check(
                "P2-C2b contextId 에코(원 세션)",
                res2.get("contextId") == hil_ctx,
                f"{res2.get('contextId')} vs {hil_ctx}",
            )
            rr = await c.get(f"/approvals/{apid}")
            check(
                "P2-C2c 승인 상태 approved",
                rr.status_code == 200 and rr.json().get("status") == "approved",
                f"{rr.status_code} {rr.text[:80]}",
            )
            # 이중 결정 → already(-32002)
            r = await c.post(f"/agents/{hil_id}/a2a", json=ok_msg)
            err = (r.json() or {}).get("error") or {}
            check("P2-C2d 이중 결정 → -32002", err.get("code") == -32002, str(err)[:80])

            # P2-C3b(codex 봉합 여집합): 비-admin 쿠키 유저가 자기 승인을 A2A로 self-approve 시도
            # → REST와 동일 인가(-32003, _may_resolve 공유). admin 승인 필요 도구라 본인도 불가.
            from api.auth import current_principal
            import uuid as _uuid

            class _Member:
                id = _uuid.UUID("00000388-0000-0000-0000-000000000388")
                is_superuser = False
                is_active = True
                is_verified = True
                email = "v388-member@local"

            app.dependency_overrides[current_principal] = lambda: _Member()
            try:
                r = await c.post(f"/agents/{hil_id}/a2a", json=_rpc("레코드 rec-3 을 삭제해줘"))
                res_m = (r.json() or {}).get("result") or {}
                apid_m = (res_m.get("metadata") or {}).get("approvalId")
                check(
                    "P2-C3b-1 쿠키 유저도 승인 대기 생성",
                    isinstance(apid_m, str),
                    f"{apid_m!r}",
                )
                selfok = {
                    "jsonrpc": "2.0",
                    "id": "12",
                    "method": "message/send",
                    "params": {
                        "message": {
                            "role": "user",
                            "parts": [{"kind": "text", "text": "approve"}],
                            "metadata": {"approvalId": apid_m, "decision": "approve"},
                        }
                    },
                }
                r = await c.post(f"/agents/{hil_id}/a2a", json=selfok)
                err_m = (r.json() or {}).get("error") or {}
                check(
                    "P2-C3b-2 비-admin self-approve → -32003(결재 인가)",
                    err_m.get("code") == -32003,
                    str(err_m)[:100],
                )
            finally:
                app.dependency_overrides.pop(current_principal, None)

            # P2-C2e: 거부 경로 — 새 승인 생성 → reject → 상태 rejected(미실행 종결)
            r = await c.post(
                f"/agents/{hil_id}/a2a", json=_rpc("레코드 rec-2 도 삭제해줘", user_id=uid_a)
            )
            apid2 = (((r.json() or {}).get("result") or {}).get("metadata") or {}).get("approvalId")
            rej = {
                "jsonrpc": "2.0",
                "id": "11",
                "method": "message/send",
                "params": {
                    "message": {
                        "role": "user",
                        "parts": [{"kind": "text", "text": "reject"}],
                        "metadata": {"userId": uid_a, "approvalId": apid2, "decision": "reject"},
                    }
                },
            }
            r = await c.post(f"/agents/{hil_id}/a2a", json=rej)
            res3 = (r.json() or {}).get("result") or {}
            rr = await c.get(f"/approvals/{apid2}")
            check(
                "P2-C2e reject → rejected 종결(응답 수신)",
                res3.get("kind") == "message"
                and rr.status_code == 200
                and rr.json().get("status") == "rejected",
                f"status={rr.json().get('status') if rr.status_code == 200 else rr.status_code}",
            )
        finally:
            if "created_hil" in dir() or "created_hil" in locals():
                try:
                    await c.delete(f"/agents/{locals().get('created_hil')}")
                except Exception:
                    pass
            if agent_id:
                await c.delete(f"/agents/{agent_id}")
            # 프로브 기억 정리(전용 uid만)
            try:
                from api import memory
                from api.mem_config import default_mem_cfg

                async with SessionLocal() as s:
                    cfg = await default_mem_cfg(s)
                for uid in (uid_a, uid_b):
                    for m in memory.list_memories({"user_id": uid}, cfg):
                        if m.get("id"):
                            memory.delete_memory(m["id"], cfg)
            except Exception as exc:
                print(f"  (정리 경고: {type(exc).__name__})")

    npass = sum(1 for _, s, _ in results if s == PASS)
    for name, status, detail in results:
        print(f"  [{status:4}] {name}" + (f" — {detail}" if detail else ""))
    print(f"\n요약: {npass}/{len(results)} PASS")
    print("VERIFY388_OK" if npass == len(results) else "VERIFY388_FAIL")
    return 0 if npass == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

"""verify_387 — 기억 표면 정직화 + A2A 유저 정체성(스펙 387).

- U1~U5: resolve_memory_user_id 단일 관문 매트릭스(머신 수용·쿠키 거부·위생).
- I1(C3): 쿠키 유저 + body.userId → 422(032 보안 보존 여집합).
- I2(C2): 머신 토큰 + body.userId → 200 + trace.memoryScope.user_id == 지정값(user 축 회상 스코프 증명).
- I3(C4): A2A message/send + metadata.userId → 성공 + mem0 user 축에 행 생성(서빙 인라인 add 증명).
- I4(②a): 존재하지 않는 기억 이름으로 에이전트 저장 → 422.
- I5(②b): 참조 중인 memory-type 삭제 → 409(참조 가드).

전제: 실모델(qwen/e5) 등록(mem_cfg 해석) + MLX 서버 가동. 픽스처는 자체 생성·정리(v387- 접두 —
clean-test-agents 리퍼 패턴 포함). 실행: cd packages/api && uv run python ../../tests/verify_387_memory_identity.py
"""

from __future__ import annotations

import asyncio
import uuid

import httpx
from fastapi import HTTPException

from api.auth import _token, current_principal, resolve_memory_user_id
from api.main import app

PASS, FAIL = "PASS", "FAIL"
results: list[tuple[str, str, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, PASS if ok else FAIL, detail))


class _CookieUser:
    id = uuid.UUID("00000387-0000-0000-0000-000000000387")
    is_superuser = True
    is_active = True
    is_verified = True
    email = "verify-387@local"


def unit_gate() -> None:
    u = _CookieUser()
    check("U1 머신+userId → 수용", resolve_memory_user_id("machine", "ext-42") == "ext-42")
    check("U2 머신+미지정 → None(세션 축)", resolve_memory_user_id("machine", None) is None)
    check("U3 쿠키+미지정 → 자기 id", resolve_memory_user_id(u, None) == str(u.id))
    try:
        resolve_memory_user_id(u, "someone-else")
        check("U4 쿠키+userId → 422", False, "예외 없음")
    except HTTPException as e:
        check("U4 쿠키+userId → 422", e.status_code == 422, f"status={e.status_code}")
    try:
        resolve_memory_user_id("machine", "bad\x00id")
        check("U5 NUL userId → 422", False, "예외 없음")
    except HTTPException as e:
        check("U5 NUL userId → 422", e.status_code == 422, f"status={e.status_code}")
    check("U6 공백 userId → 미지정 폴백", resolve_memory_user_id("machine", "   ") is None)


def _sse_trace_field(body: str, key: str) -> str:
    """SSE 본문에서 key 포함 data 라인의 그 값 주변을 추출(느슨한 존재/값 검사용)."""
    import json

    for line in body.splitlines():
        if line.startswith("data: ") and key in line:
            try:
                d = json.loads(line[6:])
            except Exception:
                continue
            if isinstance(d, dict) and key in str(d):
                return json.dumps(d, ensure_ascii=False)
    return ""


async def main() -> int:
    unit_gate()

    auth = {"Authorization": f"Bearer {_token()}"}
    transport = httpx.ASGITransport(app=app)
    uid_a = "verify387-ext-user-a"
    uid_b = "verify387-ext-user-b"
    agent_id = None
    async with httpx.AsyncClient(
        transport=transport, base_url="http://t", headers=auth, timeout=180
    ) as c:
        try:
            # ---- C1: 죽은 '단기(세션)' 옵션이 없다 — fresh DB(virgin 실행)에서도. 스펙 387이 라이브
            # 행을 지웠지만 마이그레이션 c1d2e3f4a5b6이 데이터 시드로 부활시켰던 회귀(2026-07-17,
            # DB 초기화 후 재등장)를 새 리비전 40079d14052f가 체인 끝 DELETE로 봉합 — 그 회귀 고정.
            mts0 = (await c.get("/memory-types")).json()
            check(
                "C1 죽은 '단기(세션)' 옵션 부재(fresh DB 포함)",
                all(x["name"] != "단기(세션)" for x in mts0),
                f"현재 옵션={[x['name'] for x in mts0]}",
            )

            # ---- 픽스처: mem0 켠 로컬 에이전트 + A2A 노출(자체 생성, v387- 접두 = 리퍼 패턴)
            r = await c.post(
                "/agents",
                json={
                    "name": "v387-mem",
                    "description": "스펙 387 검증 픽스처",
                    "config": {
                        "model": "mock-llm",
                        "prompt": "간결한 한국어 도우미",
                        "memories": ["장기 기억 (mem0)"],
                        "historyDepth": 6,
                    },
                },
            )
            check(
                "F0 픽스처 에이전트 생성 201",
                r.status_code == 201,
                f"{r.status_code} {r.text[:120]}",
            )
            agent_id = r.json()["id"]
            r = await c.put(f"/agents/{agent_id}/expose", json={"a2a": True})
            check("F1 A2A 노출 200", r.status_code == 200, f"{r.status_code}")

            # ---- I1(C3): 쿠키 유저 + userId → 422
            app.dependency_overrides[current_principal] = lambda: _CookieUser()
            r = await c.post(
                f"/agents/{agent_id}/chat",
                json={
                    "messages": [{"role": "user", "content": "안녕"}],
                    "userId": "someone-else",
                },
            )
            check("I1 쿠키+userId → 422", r.status_code == 422, f"status={r.status_code}")
            app.dependency_overrides.pop(current_principal, None)

            # ---- I2(C2): 머신 토큰 + userId → 200 + memoryScope.user_id == 지정값
            r = await c.post(
                f"/agents/{agent_id}/chat",
                json={
                    "messages": [
                        {"role": "user", "content": "내 별명은 v387-알파 입니다. 기억해줘."}
                    ],
                    "userId": uid_a,
                },
            )
            ok = r.status_code == 200
            scope_blob = _sse_trace_field(r.text, "memoryScope") if ok else ""
            check("I2a 머신+userId 채팅 200", ok, f"status={r.status_code}")
            check(
                "I2b trace.memoryScope.user_id == 지정 userId",
                f'"user_id": "{uid_a}"' in scope_blob,
                scope_blob[:160] or "(memoryScope 미발견)",
            )

            # ---- I3(C4): A2A message/send + metadata.userId → 성공 + user 축 add(인라인)
            rpc = {
                "jsonrpc": "2.0",
                "id": "1",
                "method": "message/send",
                "params": {
                    "message": {
                        "role": "user",
                        "parts": [
                            {"kind": "text", "text": "내 좌우명은 v387-베타 입니다. 기억해줘."}
                        ],
                        "metadata": {"userId": uid_b},
                    }
                },
            }
            # 서빙 add 배선 계측(결정적) — 실 LLM 추출은 JSON 파싱이 비결정적(qwen이 마크다운 등으로
            # 감싸면 mem0가 0행)이라, "add가 지정 userId 스코프로 호출됐는가"를 인프로세스 패치로 단언.
            from api import memory

            add_calls: list[dict] = []
            _orig_add = memory.add

            def _recording_add(scope, msgs, cfg, infer=True):  # noqa: ANN001, ANN202
                add_calls.append(dict(scope))
                return [{"event": "ADD", "text": "stub"}]

            memory.add = _recording_add
            try:
                r = await c.post(f"/agents/{agent_id}/a2a", json=rpc)
            finally:
                memory.add = _orig_add
            body = r.json() if r.status_code == 200 else {}
            check(
                "I3a A2A send(metadata.userId) 성공",
                r.status_code == 200 and "result" in body,
                f"status={r.status_code} {str(body)[:120]}",
            )
            check(
                "I3b 서빙 자동 저장이 지정 userId 스코프로 호출됨",
                # 스펙 388 P1: 스코프에 run 축(세션)이 추가됨 — user 축 값만 고정 단언(정확일치 금지).
                any(s.get("user_id") == uid_b for s in add_calls),
                f"add_calls={add_calls[:3]}",
            )

            # ---- I3c: 쿠키 유저의 A2A metadata.userId → JSON-RPC 에러(-32602)
            app.dependency_overrides[current_principal] = lambda: _CookieUser()
            r = await c.post(f"/agents/{agent_id}/a2a", json=rpc)
            err = (r.json() or {}).get("error") or {}
            check(
                "I3c 쿠키+metadata.userId → JSON-RPC 거부",
                err.get("code") == -32602,
                str(err)[:120],
            )
            app.dependency_overrides.pop(current_principal, None)

            # ---- I3d(codex P1): 비-dict metadata → 500 아님(무시 or 정상 처리)
            bad = {
                "jsonrpc": "2.0",
                "id": "2",
                "method": "message/send",
                "params": {
                    "message": {
                        "role": "user",
                        "parts": [{"kind": "text", "text": "hi"}],
                        "metadata": ["not-object"],
                    }
                },
            }
            r = await c.post(f"/agents/{agent_id}/a2a", json=bad)
            check(
                "I3d 비-dict metadata → 500 아님", r.status_code == 200, f"status={r.status_code}"
            )

            # ---- I2c(codex P2): 81자 userId → 422(세션 컬럼 String(80) 정렬)
            r = await c.post(
                f"/agents/{agent_id}/chat",
                json={"messages": [{"role": "user", "content": "hi"}], "userId": "x" * 81},
            )
            check("I2c 81자 userId → 422", r.status_code == 422, f"status={r.status_code}")

            # ---- I4(②a): 존재하지 않는 기억 이름 저장 → 422
            r = await c.post(
                "/agents",
                json={
                    "name": "v387-badmem",
                    "config": {"model": "mock-llm", "memories": ["존재하지 않는 기억 xyz"]},
                },
            )
            check(
                "I4 없는 기억 이름 저장 → 422",
                r.status_code == 422,
                f"status={r.status_code} {r.text[:120]}",
            )

            # ---- I5(②b→봉인): 기억 블록은 시스템 정의 — 삭제 403(생성 불가와 대칭, 참조 무관).
            mts = (await c.get("/memory-types")).json()
            mt = next(x for x in mts if x["name"] == "장기 기억 (mem0)")
            r = await c.delete(f"/memory-types/{mt['id']}")
            check(
                "I5 기억 블록 삭제 → 403(시스템 정의 봉인)",
                r.status_code == 403,
                f"status={r.status_code} {r.text[:120]}",
            )
            # ---- I6(봉인): 생성 403 · 개명 403 · 설명 수정은 200(문구 정정 경로 보존).
            r = await c.post(
                "/memory-types", json={"key": "x387", "name": "x387", "scope": "s", "body": "b"}
            )
            check("I6a 기억 블록 생성 → 403", r.status_code == 403, f"status={r.status_code}")
            r = await c.put(
                f"/memory-types/{mt['id']}",
                json={
                    "key": mt["key"],
                    "name": "개명시도",
                    "scope": mt["scope"],
                    "body": mt["body"],
                },
            )
            check("I6b 기억 블록 개명 → 403", r.status_code == 403, f"status={r.status_code}")
            r = await c.put(
                f"/memory-types/{mt['id']}",
                json={
                    "key": mt["key"],
                    "name": mt["name"],
                    "scope": mt["scope"],
                    "body": mt["body"],
                },
            )
            check(
                "I6c 설명 수정(무개명) → 200",
                r.status_code == 200,
                f"status={r.status_code} {r.text[:100]}",
            )
        finally:
            app.dependency_overrides.pop(current_principal, None)
            # 정리 — 픽스처 에이전트 + 프로브 기억(실 사용자 데이터 무접촉: verify387 전용 uid만)
            if agent_id:
                await c.delete(f"/agents/{agent_id}")
            try:
                from api.db import SessionLocal
                from api.mem_config import default_mem_cfg
                from api import memory

                async with SessionLocal() as s:
                    cfg = await default_mem_cfg(s)
                for uid in (uid_a, uid_b):
                    for m in memory.list_memories({"user_id": uid}, cfg):
                        if m.get("id"):
                            memory.delete_memory(m["id"], cfg)
            except Exception as exc:  # 정리 실패는 보고만(검증 판정과 분리)
                print(f"  (정리 경고: {type(exc).__name__})")

    npass = sum(1 for _, s, _ in results if s == PASS)
    for name, status, detail in results:
        print(f"  [{status:4}] {name}" + (f" — {detail}" if detail else ""))
    print(f"\n요약: {npass}/{len(results)} PASS")
    print("VERIFY387_OK" if npass == len(results) else "VERIFY387_FAIL")
    return 0 if npass == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

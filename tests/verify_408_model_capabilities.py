"""verify_408 — 모델 능력(capabilities)·설정 캐스케이드(스펙 408).

  U1 유효식 단위: build_chat_openai — 능력 false→disable_streaming, 능력 true+사용 끔→disable,
     기본→스트리밍. enable_thinking 캐스케이드(모델→에이전트 병합→세션 인자).
  U2 _apply_agent_model_params: 화이트리스트(enable_thinking·stream)만 덮고 그 외 무시·미명시 상속.
  H1 API 왕복: capabilities 저장/조회/수정(PUT — 참조 중에도 능력 편집 가능해야).
  H2 실행: streaming=false 모델의 에이전트 채팅 → 정상 응답+trace.responseMode="single".
  H3 에이전트 층: 능력 true 모델+modelParams.stream=false → single. 기본(모두 미설정) → 필드 없음.
  H4 능력 불가침: 능력 false + 에이전트 stream=true → 여전히 single.

실행: uv run --project packages/api python tests/_throwaway_server.py tests/verify_408_model_capabilities.py
"""

import asyncio
import json
import os
import sys
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))
sys.path.insert(0, os.path.join(ROOT, "packages", "agent", "src"))

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


def unit_checks() -> None:
    from agent.model import build_chat_openai

    base = {"base_url": "http://x/v1", "api_key": "k", "model_id": "m"}
    # U1a 능력 false → 단건
    c = build_chat_openai({**base, "capabilities": {"streaming": False}})
    check(c.disable_streaming is True, "U1a 능력 false → disable_streaming")
    # U1b 능력 true + 사용 끔(모델 params) → 단건
    c = build_chat_openai({**base, "capabilities": {"streaming": True}, "params": {"stream": False}})
    check(c.disable_streaming is True, "U1b 능력 true+사용 끔 → disable_streaming")
    # U1c 기본 → 스트리밍
    c = build_chat_openai(base)
    check(c.disable_streaming is False, "U1c 기본 → 스트리밍")
    # U1d thinking 캐스케이드: cfg(모델·에이전트 병합) false ← 세션 인자 true가 최우선.
    # 스펙 409: thinking도 능력 게이트라 capabilities.thinking=True를 선언해야 켤 수 있다.
    thk = {"capabilities": {"thinking": True}}
    c = build_chat_openai({**base, **thk, "params": {"enable_thinking": False}}, {"enable_thinking": True})
    check(
        c.extra_body["chat_template_kwargs"]["enable_thinking"] is True,
        "U1d thinking: 세션 인자 > cfg params(능력 true)",
    )
    c = build_chat_openai({**base, **thk, "params": {"enable_thinking": True}})
    check(
        c.extra_body["chat_template_kwargs"]["enable_thinking"] is True,
        "U1e thinking: cfg params 기본(능력 true)",
    )
    # U1f thinking 능력 게이트(스펙 409): 능력 false면 세션이 켜도 못 켬(부분집합 불가침).
    c = build_chat_openai({**base, "capabilities": {"thinking": False}}, {"enable_thinking": True})
    check(
        c.extra_body["chat_template_kwargs"]["enable_thinking"] is False,
        "U1f thinking: 능력 false는 세션도 못 켬(게이트)",
    )

    from api.chat_context_models import _apply_agent_model_params

    mc = {"base_url": "b", "params": {"temperature": 0.3, "enable_thinking": False}}
    out = _apply_agent_model_params(mc, {"modelParams": {"enable_thinking": True, "stream": False, "evil": 1}})
    check(
        out["params"]["enable_thinking"] is True and out["params"]["stream"] is False,
        "U2a 에이전트 modelParams가 모델 params 위에 덮임",
    )
    check("evil" not in out["params"], "U2b 화이트리스트 밖 키 무시")
    check(out["params"]["temperature"] == 0.3, "U2c 미명시 키 상속(temperature — 기존 축 보존)")
    out2 = _apply_agent_model_params(mc, {})
    check(out2 is mc, "U2d modelParams 없으면 원본 그대로(무회귀)")
    # U3 세션 per-key 병합(_apply_overrides 특례) — 세션이 stream만 보내도 에이전트 thinking 생존.
    from api.chat_context_overrides import _apply_overrides

    class _FakeAgent:
        source = "ui"

    cfg3 = {"model": "m", "modelParams": {"enable_thinking": True}}
    out3, _p, _n, _pt = _apply_overrides(
        cfg3, "", {"modelParams": {"stream": False}}, _FakeAgent(), {"modelParams"}
    )
    check(
        out3["modelParams"] == {"enable_thinking": True, "stream": False},
        f"U3 세션 modelParams per-key 병합(에이전트 키 생존) (got {out3['modelParams']})",
    )


async def main() -> None:
    unit_checks()
    tag = f"v408-{uuid.uuid4().hex[:6]}"
    async with httpx.AsyncClient(base_url=BASE, headers=_auth(), timeout=120) as c:
        provs = (await c.get("/providers")).json()
        mock_p = next(p for p in provs if "_remote" in (p.get("base_url") or ""))

        # H1 — capabilities 저장/조회/수정
        r = await c.post(
            "/models",
            json={
                "name": f"{tag}-single",
                "provider_id": mock_p["id"],
                "model_id": "mock-chat",
                "kind": "chat",
                "is_default": False,
                "params": {},
                "capabilities": {"streaming": False, "thinking": False, "vision": False},
                "meta": {},
            },
        )
        check(r.status_code == 201, f"H1a 모델 생성(streaming=false) 201 (got {r.status_code})")
        mdl = r.json()
        check(
            mdl.get("capabilities", {}).get("streaming") is False,
            f"H1b 능력 저장/노출 (got {mdl.get('capabilities')})",
        )
        r = await c.put(
            f"/models/{mdl['id']}",
            json={**{k: mdl[k] for k in ("name", "provider_id", "model_id", "kind", "is_default", "params", "meta")},
                  "capabilities": {"streaming": False, "thinking": True, "vision": False}},
        )
        check(
            r.status_code == 200 and r.json()["capabilities"]["thinking"] is True,
            f"H1c PUT으로 능력 편집(참조 유무 무관 경로) (got {r.status_code})",
        )

        async def _chat_trace(aid: str) -> dict:
            sse = ""
            async with c.stream(
                "POST", f"/agents/{aid}/chat",
                json={"messages": [{"role": "user", "content": "안녕"}]},
            ) as resp:
                async for line in resp.aiter_lines():
                    sse += line + "\n"
            tr = next(
                (json.loads(ln[6:]) for ln in sse.splitlines()
                 if ln.startswith("data: ") and '"latencyMs"' in ln),
                {},
            )
            return {"sse": sse, "trace": tr}

        made: list[str] = []
        try:
            # H2 — streaming=false 모델 → single + 정상 응답
            ag = (await c.post("/agents", json={"name": f"{tag}-a1", "config": {"model": f"{tag}-single"}})).json()
            made.append(ag["id"])
            out = await _chat_trace(ag["id"])
            check(
                out["trace"].get("responseMode") == "single",
                f"H2a 능력 false → trace.responseMode=single (got {out['trace'].get('responseMode')})",
            )
            check("data:" in out["sse"] and '"latencyMs"' in out["sse"], "H2b 단건이어도 정상 완주(SSE 계약 유지)")

            # H3 — 능력 true 모델 + 에이전트 stream=false → single / 기본 → 필드 없음
            ag2 = (
                await c.post(
                    "/agents",
                    json={"name": f"{tag}-a2", "config": {"model": "mock-llm", "modelParams": {"stream": False}}},
                )
            ).json()
            made.append(ag2["id"])
            out2 = await _chat_trace(ag2["id"])
            check(
                out2["trace"].get("responseMode") == "single",
                f"H3a 에이전트 층 stream=false → single (got {out2['trace'].get('responseMode')})",
            )
            ag3 = (await c.post("/agents", json={"name": f"{tag}-a3", "config": {"model": "mock-llm"}})).json()
            made.append(ag3["id"])
            out3 = await _chat_trace(ag3["id"])
            check(
                "responseMode" not in out3["trace"],
                f"H3b 기본(스트리밍) → responseMode 무필드(조용) (got {out3['trace'].get('responseMode')})",
            )

            # H4 — 능력 불가침: 능력 false 모델 + 에이전트 stream=true → 여전히 single
            ag4 = (
                await c.post(
                    "/agents",
                    json={"name": f"{tag}-a4", "config": {"model": f"{tag}-single", "modelParams": {"stream": True}}},
                )
            ).json()
            made.append(ag4["id"])
            out4 = await _chat_trace(ag4["id"])
            check(
                out4["trace"].get("responseMode") == "single",
                f"H4 능력 false는 에이전트가 못 켬(불가침) (got {out4['trace'].get('responseMode')})",
            )
            # H5 — 능력 PUT 후 같은 에이전트 재호출: 그래프 캐시가 능력 지문으로 회전(codex P1①).
            r = await c.put(
                f"/models/{mdl['id']}",
                json={**{k: mdl[k] for k in ("name", "provider_id", "model_id", "kind", "is_default", "params", "meta")},
                      "capabilities": {"streaming": True, "thinking": False, "vision": False}},
            )
            check(r.status_code == 200, f"H5a 능력 PUT(streaming true로) 200 (got {r.status_code})")
            out5 = await _chat_trace(ag["id"])
            check(
                "responseMode" not in out5["trace"],
                f"H5b PUT 직후 재호출이 새 능력 반영(캐시 회전 — 배지 소멸) (got {out5['trace'].get('responseMode')})",
            )

            # H6 — 세션 층(3층 완성): 능력 true 기본 에이전트 + 세션 overrides.modelParams.stream=false.
            sse6 = ""
            async with c.stream(
                "POST", f"/agents/{ag3['id']}/chat",
                json={"messages": [{"role": "user", "content": "안녕"}], "overrides": {"modelParams": {"stream": False}}},
            ) as resp6:
                async for line in resp6.aiter_lines():
                    sse6 += line + "\n"
            tr6 = next(
                (json.loads(ln[6:]) for ln in sse6.splitlines()
                 if ln.startswith("data: ") and '"latencyMs"' in ln), {},
            )
            check(
                tr6.get("responseMode") == "single",
                f"H6 세션 오버라이드 stream=false → single(3층 최상위) (got {tr6.get('responseMode')})",
            )
        finally:
            for aid in made:
                await c.delete(f"/agents/{aid}")
            await c.delete(f"/models/{mdl['id']}")

    print(f"\n{passed} passed, {len(_fails)} failed")
    if _fails:
        sys.exit(1)
    print("VERIFY408_OK")


if __name__ == "__main__":
    asyncio.run(main())

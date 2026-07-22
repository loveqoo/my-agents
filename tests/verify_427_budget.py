"""스펙 427 검증 — 사고 바닥(B1)·잘림 표면화(A) 서버 계약 라이브 실증.

두 축(신선 nonce — 서버 프롬프트 캐시 재생 회피, learning never-blame-infra-without-fresh-probe):
- B1: 사고 ON + max_tokens 512(바닥 미만) → 이번 요청만 8192로 올려 굶김 해소.
      trace.thinkingBudgetApplied==8192 & 답 본문 존재 & truncated 없음.
- A : 사고 OFF + max_tokens 16(아주 작게) + 긴 답 요청 → finish_reason=length.
      trace.truncated==True & thinkingBudgetApplied 없음(사고 OFF라 bump 미개입).

보고 플랫폼 vLLM(atom-spark, qwen36)로 override해 실측한다 — MLX는 max_tokens를 하드캡하지 않아
A(잘림)가 재현되지 않으므로 vLLM에서 검증한다(B1 bump 자체는 model.py 단일 지점이라 모델 무관).

실행(라이브 서버·실모델 필요, 그물과 동시 금지): uv run python tests/verify_427_budget.py
환경: ADMIN_API(기본 http://127.0.0.1:8000), AGENT_ID(기본 personal-secretary), VLLM_MODEL(기본 qwen36).
"""

from __future__ import annotations

import asyncio
import os
import secrets
import subprocess
import sys
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "suite"))
from _sse import parse_sse  # noqa: E402

BASE = os.environ.get("ADMIN_API", "http://127.0.0.1:8000")
AGENT_ID = os.environ.get("AGENT_ID", "8dd12a3c-e03a-4be2-ae9a-2d2ed97c0376")  # personal-secretary
VLLM_MODEL = os.environ.get("VLLM_MODEL", "qwen36")
PROV = REPO / "tests" / "_provision_super.py"

fails: list[str] = []


def ok(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        fails.append(msg)


async def login(c: httpx.AsyncClient) -> None:
    email = f"verify427_{secrets.token_hex(3)}@example.com"  # 던짐용 prefix(_provision_super 화이트리스트)
    pw = "Verify427!pw"
    subprocess.run(["uv", "run", "python", str(PROV), "create", email, pw], check=True, capture_output=True)
    r = await c.post(
        f"{BASE}/auth/login",
        data={"username": email, "password": pw},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert r.status_code in (200, 204), f"login {r.status_code}: {r.text[:120]}"


async def chat(c: httpx.AsyncClient, over: dict, prompt: str) -> dict:
    r = await c.post(
        f"{BASE}/agents/{AGENT_ID}/chat",
        json={"messages": [{"role": "user", "content": prompt}], "overrides": over},
    )
    assert r.status_code == 200, f"chat {r.status_code}: {r.text[:160]}"
    return parse_sse(r.text)


async def main() -> None:
    async with httpx.AsyncClient(timeout=httpx.Timeout(240.0, connect=10.0)) as c:
        await login(c)
        n1, n2 = secrets.token_hex(3), secrets.token_hex(3)

        # B1 — 사고 ON + 512 → 8192 적용, 굶김 해소
        res = await chat(
            c,
            {"model": VLLM_MODEL, "modelParams": {"enable_thinking": True, "max_tokens": 512}},
            f"[{n1}] 세 단계로 생각한 뒤, 라면을 더 맛있게 끓이는 법을 한 문단으로 알려줘.",
        )
        tr = res.get("trace") or {}
        ok(tr.get("thinkingBudgetApplied") == 8192, f"B1 thinkingBudgetApplied==8192 (got {tr.get('thinkingBudgetApplied')})")
        ok(len(res.get("text") or "") > 20, f"B1 답 본문 존재(굶김 해소) (len={len(res.get('text') or '')})")
        ok(not tr.get("truncated"), f"B1 truncated 없음(바닥으로 안 잘림) (got {tr.get('truncated')})")

        # A — 사고 OFF + 16 + 긴 답 → finish_reason=length 표면화
        res2 = await chat(
            c,
            {"model": VLLM_MODEL, "modelParams": {"enable_thinking": False, "max_tokens": 16}},
            f"[{n2}] 조선 왕조 전체 역사를 아주 길고 자세하게 열 문단 이상으로 서술해줘.",
        )
        tr2 = res2.get("trace") or {}
        ok(tr2.get("truncated") is True, f"A truncated==True(잘림 표면화) (got {tr2.get('truncated')})")
        ok(not tr2.get("thinkingBudgetApplied"), f"A thinkingBudgetApplied 없음(사고 OFF 미개입) (got {tr2.get('thinkingBudgetApplied')})")

    print("\n" + ("VERIFY427_OK" if not fails else f"FAIL {len(fails)}"))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    asyncio.run(main())

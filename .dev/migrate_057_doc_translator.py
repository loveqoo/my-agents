"""스펙 057 라이브 마이그레이션 — 기존 code 에이전트 행을 A2A 단일화에 맞춤(비가역, dry-run 우선).

문제: 시드된 Doc Translator(agt_xlt_a17c33)는 endpoint=/_remote/agent(폐기된 자체 SSE)·card 없음.
_remote_stream 삭제 후 채팅이 _a2a_stream으로 가 비-A2A 엔드포인트를 호출 → 깨짐.

해결: endpoint를 mock A2A(/_remote/a2a)로, config["card"]를 seed와 동형(x-my-agents 확장)으로 패치.
다른 컬럼(versions·persona 등)은 이미 정상이라 건드리지 않는다(최소 변경).

실행:
  dry-run(기본):  .venv/bin/python .dev/migrate_057_doc_translator.py
  적용:           .venv/bin/python .dev/migrate_057_doc_translator.py --apply
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "packages", "api", "src"))

from sqlalchemy import select  # noqa: E402

from api.db import SessionLocal  # noqa: E402
from api.mock_mcp import MOCK_MCP_SERVER_NAME  # noqa: E402
from api.models import Agent  # noqa: E402
from api.seed import CHAT_MODEL_NAME  # noqa: E402

AGENT_ID = "agt_xlt_a17c33"
A2A_ENDPOINT = os.environ.get("REMOTE_AGENT_BASE", "http://127.0.0.1:8000/_remote/a2a")
DEAD_ENDPOINT = "http://127.0.0.1:8000/_remote/agent"


def _seed_card() -> dict:
    """seed.py의 code_card와 동형 — connect 빌더가 만드는 것과 같은 x-my-agents 카드."""
    return {
        "name": "Doc Translator",
        "description": "my-agents-sdk로 배포한 번역 에이전트(시드 스냅샷).",
        "url": A2A_ENDPOINT,
        "version": "1.0.0",
        "provider": {"organization": "acme", "url": "https://acme.example"},
        "capabilities": {"streaming": True, "pushNotifications": False},
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain"],
        "skills": [
            {"id": "translate", "name": "문서 번역", "description": "문서를 대상 언어로 번역",
             "tags": ["translation", "i18n"]},
        ],
        "x-my-agents": {
            "manifest": {
                "model": CHAT_MODEL_NAME, "persona": "코드 정의 (SDK)", "memories": ["단기(세션)"],
                "mcps": [MOCK_MCP_SERVER_NAME], "permissions": ["web.search"], "historyDepth": 10,
            },
            "deploy": {
                "repo": "acme/doc-translator", "commit": "f3a91c2",
                "runtime": "my-agents-sdk · Python 2.4.1",
                "versions": [
                    {"version": "f3a91c2", "status": "active", "note": "Deploy · 용어집 조회 추가"},
                    {"version": "9b22d01", "status": "archived", "note": "Deploy · 초기 배포"},
                ],
            },
        },
    }


async def main(apply: bool) -> None:
    async with SessionLocal() as s:
        agent = (await s.execute(select(Agent).where(Agent.agent_id == AGENT_ID))).scalar_one_or_none()
        if agent is None:
            print(f"행 없음: {AGENT_ID} — 마이그레이션 불필요(또는 미시드)")
            return
        cfg = dict(agent.config or {})
        has_card = isinstance(cfg.get("card"), dict) and "x-my-agents" in cfg["card"]
        print("── BEFORE ──")
        print(f"  endpoint = {agent.endpoint}")
        print(f"  config.card = {'있음(x-my-agents)' if has_card else 'NONE/불완전'}")

        already = agent.endpoint == A2A_ENDPOINT and has_card
        if already:
            print("\n이미 마이그레이션됨 — 변경 없음.")
            return

        new_endpoint = A2A_ENDPOINT
        cfg["card"] = _seed_card()
        print("\n── AFTER (예정) ──")
        print(f"  endpoint = {new_endpoint}  (was {agent.endpoint})")
        print("  config.card = 있음(x-my-agents, seed 동형)")

        if not apply:
            print("\n[dry-run] --apply 없이는 커밋하지 않음.")
            return

        agent.endpoint = new_endpoint
        agent.config = cfg
        await s.commit()
        print("\n[APPLIED] 커밋 완료.")


if __name__ == "__main__":
    asyncio.run(main("--apply" in sys.argv))

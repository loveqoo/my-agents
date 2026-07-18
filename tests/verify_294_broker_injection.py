"""스펙 294 — 브로커가 `_CapabilityProvider` 추상에만 의존함을 *증명*한다.

리팩터 전에는 불가능했던 것: 구체 provider·DB(session_factory) 없이 **가짜 provider 리스트를 주입**해
디스패치·정책·invoke가 동작함을 단언. 이 테스트가 통과한다는 사실 자체가 "broker는 구체를 모르고
조립은 외부(build_providers)"라는 구조 규약의 실증이다(스펙 294 목표 5).

추가 구조 단언: core.py 소스에 구체 provider 생성이 0건(조립은 composition.py 단일 출처).
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "packages/api/src"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "packages/agent/src"))

from agent.runtime import Capability, InvokeResult  # noqa: E402

from api.broker import CapabilityNotFoundError, PolicyScopedBroker  # noqa: E402

FAKE_CAP = "rag:fake294"


class _FakeProvider:
    """`_CapabilityProvider` 구조 적합 — DB·네트워크 0. kind=rag로 라우팅(cap_id 접두사)."""

    kind = "rag"

    def __init__(self) -> None:
        self.invoked: list[dict] = []

    async def candidates(self, allow: set[str]) -> list[Capability]:
        return (
            [Capability(id=FAKE_CAP, kind="rag", name="Fake294", hook="fake_hook")]
            if (FAKE_CAP in allow)
            else []
        )

    async def load(self, cap_id: str) -> object | None:
        return {"id": cap_id} if cap_id == FAKE_CAP else None

    def describe(self, row: object) -> Capability:
        return Capability(id=FAKE_CAP, kind="rag", name="Fake294", hook="fake_hook")

    async def invoke(self, row: object, args: dict) -> InvokeResult:
        self.invoked.append(args)
        return InvokeResult(text="INVOKED294")

    def node_label(self, row: object) -> str:
        return "broker_invoke:rag:fake294"

    def approval_for(
        self, row: object, cap_id: str, args: dict, tool_policy: dict | None = None
    ) -> dict | None:
        return None


def _ok(cond: bool, msg: str) -> None:
    print(f"  {'ok ' if cond else 'FAIL'} {msg}")
    if not cond:
        raise SystemExit(f"FAIL: {msg}")


async def main() -> None:
    fake = _FakeProvider()
    # 순수 주입 — 구체 provider·session_factory 없음. 이 생성 자체가 리팩터의 증거.
    b = PolicyScopedBroker({FAKE_CAP}, lambda k, name=None: True, [fake])
    _ok(set(b._by_kind) == {"rag"}, "주입한 fake만 _by_kind에 (구체 provider 0)")

    caps = await b.discover("fake", limit=5)
    _ok([c.id for c in caps] == [FAKE_CAP], "discover가 주입 provider로 디스패치")

    desc = await b.describe(FAKE_CAP)
    _ok(desc.name == "Fake294", "describe가 주입 provider로 디스패치")

    res = await b.invoke(FAKE_CAP, {"q": 1})
    _ok(res.text == "INVOKED294" and fake.invoked == [{"q": 1}], "invoke가 주입 provider로 전달")

    # 정책 게이트는 provider 종류와 무관하게 유지(추상 위에서 동작)
    b_deny = PolicyScopedBroker({FAKE_CAP}, lambda k, name=None: False, [fake])
    _ok(await b_deny.discover("fake") == [], "RBAC deny → discover [](추상 위 정책 유지)")
    b_noallow = PolicyScopedBroker(set(), lambda k, name=None: True, [fake])
    raised = False
    try:
        await b_noallow.describe(FAKE_CAP)
    except CapabilityNotFoundError:
        raised = True
    _ok(raised, "allowlist 밖 → NotFound(존재 비노출, 주입 provider에도 성립)")

    # 빈 provider 리스트도 정상 — 브로커는 조립을 강제하지 않는다(순수 소비자)
    b_empty = PolicyScopedBroker({FAKE_CAP}, lambda k, name=None: True, [])
    _ok(await b_empty.discover("x") == [], "빈 provider 주입 → 공집합(조립 비강제)")

    # 구조 단언: core.py 소스에 구체 provider 생성 0건(조립은 composition 단일 출처)
    core_src = (
        pathlib.Path(__file__).resolve().parents[1] / "packages/api/src/api/broker/core.py"
    ).read_text()
    concretes = [
        "AgentProvider(",
        "McpProvider(",
        "RagProvider(",
        "MemoryProvider(",
        "MemoryWriteProvider(",
        "MemEditProvider(",
    ]
    found = [c for c in concretes if c in core_src]
    _ok(not found, f"core.py에 구체 provider 생성 0건(발견: {found or '없음'})")

    print("\n✅ ALL PASS (VERIFY294_OK) — 브로커는 _CapabilityProvider 추상에만 의존")


if __name__ == "__main__":
    asyncio.run(main())

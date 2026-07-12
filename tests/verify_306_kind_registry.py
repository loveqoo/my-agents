"""스펙 306 검증 — 브로커 kind 파싱 OCP 흡수(레지스트리 구동).

순수 리팩터라 **행위 불변**이 핵심 불변식이다. 두 축:
  R. 라운드트립 — 전 kind에 대해 `_kind_of(f"{k}:x")==k`·`_cap_resource(f"{k}:x",k)=="x"`, agent bare,
     빈 리소스, cross-kind 격리.
  E. 동치 — 신규 균일 규칙이 **옛 하드코딩 if-체인과 전 표본 바이트 동일**(RBAC 리소스 드리프트 0).
  D. 드리프트 핀 — `_PREFIXED_KINDS ∪ {agent}` == 정의된 전 CAP_KIND_*(새 kind가 레지스트리 누락 시 실패).

실행: uv run python tests/verify_306_kind_registry.py
전제: 없음(라이브 인프라 불필요).
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))

from api.broker import common as broker_common  # noqa: E402
from api.broker.common import (  # noqa: E402
    _PREFIXED_KINDS,
    CAP_KIND_AGENT,
    CAP_KIND_MCP,
    CAP_KIND_MEMORY,
    CAP_KIND_MEMORY_EDIT,
    CAP_KIND_MEMORY_WRITE,
    CAP_KIND_RAG,
    _cap_resource,
    _kind_of,
)

# 드리프트 핀의 진짜 기준(codex 지적) — 수동 리스트가 아니라 **모듈의 CAP_KIND_* 상수를 introspect**해
# 실제 kind 집합을 센다. 새 `CAP_KIND_FOO`를 추가하고 `_PREFIXED_KINDS`를 안 고치면 여기서 잡힌다.
ALL_KINDS = sorted(
    v for k, v in vars(broker_common).items() if k.startswith("CAP_KIND_") and isinstance(v, str)
)

_fails: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


# ── 옛 하드코딩 if-체인(스펙 306 이전) 재현 — 동치 오라클 ─────────────────────────────
def _old_kind_of(item: str) -> str:
    if isinstance(item, str):
        if item.startswith(f"{CAP_KIND_MCP}:"):
            return CAP_KIND_MCP
        if item.startswith(f"{CAP_KIND_RAG}:"):
            return CAP_KIND_RAG
        if item.startswith(f"{CAP_KIND_MEMORY_WRITE}:"):
            return CAP_KIND_MEMORY_WRITE
        if item.startswith(f"{CAP_KIND_MEMORY_EDIT}:"):
            return CAP_KIND_MEMORY_EDIT
        if item.startswith(f"{CAP_KIND_MEMORY}:"):
            return CAP_KIND_MEMORY
    return CAP_KIND_AGENT


def _old_cap_resource(cap_id: str, kind: str) -> str:
    if kind == CAP_KIND_MCP:
        return cap_id[len(CAP_KIND_MCP) + 1 :] if cap_id.startswith(f"{CAP_KIND_MCP}:") else cap_id
    if kind == CAP_KIND_RAG:
        return cap_id[len(CAP_KIND_RAG) + 1 :] if cap_id.startswith(f"{CAP_KIND_RAG}:") else cap_id
    if kind == CAP_KIND_MEMORY:
        return (
            cap_id[len(CAP_KIND_MEMORY) + 1 :]
            if cap_id.startswith(f"{CAP_KIND_MEMORY}:")
            else cap_id
        )
    if kind == CAP_KIND_MEMORY_WRITE:
        return (
            cap_id[len(CAP_KIND_MEMORY_WRITE) + 1 :]
            if cap_id.startswith(f"{CAP_KIND_MEMORY_WRITE}:")
            else cap_id
        )
    if kind == CAP_KIND_MEMORY_EDIT:
        return (
            cap_id[len(CAP_KIND_MEMORY_EDIT) + 1 :]
            if cap_id.startswith(f"{CAP_KIND_MEMORY_EDIT}:")
            else cap_id
        )
    return cap_id


def main() -> None:
    # ── D. 드리프트 핀(introspection 기준) ──────────────────────────────────
    check(
        set(_PREFIXED_KINDS) | {CAP_KIND_AGENT} == set(ALL_KINDS),
        f"D _PREFIXED_KINDS∪agent == 정의된 전 CAP_KIND_* ({ALL_KINDS})",
    )
    check(CAP_KIND_AGENT not in _PREFIXED_KINDS, "D agent는 bare fallback이라 레지스트리 밖")

    # ── R. 라운드트립(전 접두사 kind) ──────────────────────────────────────
    for k in _PREFIXED_KINDS:
        check(_kind_of(f"{k}:user") == k, f"R {k}: 접두사 → kind {k}")
        check(_cap_resource(f"{k}:user", k) == "user", f"R {k}:user → 리소스 user")
        check(_cap_resource(f"{k}:", k) == "", f"R {k}: → 빈 리소스")
    # mcp 2레벨 body 전체
    check(_cap_resource("mcp:srv/tool", CAP_KIND_MCP) == "srv/tool", "R mcp:srv/tool → srv/tool")
    # agent bare
    check(_kind_of("agt_rsch_7f3a91") == CAP_KIND_AGENT, "R bare agt_ → agent")
    check(
        _cap_resource("agt_rsch_7f3a91", CAP_KIND_AGENT) == "agt_rsch_7f3a91", "R agent bare 원본"
    )
    # cross-kind 격리(memwrite 파서는 memory: 안 벗김)
    check(_cap_resource("memory:user", CAP_KIND_MEMORY_WRITE) == "memory:user", "R cross-kind 격리")

    # ── E. 옛 if-체인과 동치(전 표본 바이트 동일) ────────────────────────────
    samples = [
        "mcp:server",
        "mcp:server/tool",
        "mcp:",
        "rag:docs-kb",
        "rag:a:b/c",
        "memory:user",
        "memwrite:user",
        "memedit:user",
        "agt_rsch_7f3a91",
        "agent:weird",  # 이론적 엣지 — agent cap은 bare뿐이라 도달불가, 동치만 확인
        "",
        "no-colon-bare",
    ]
    for s in samples:
        check(_kind_of(s) == _old_kind_of(s), f"E _kind_of 동치: {s!r}→{_kind_of(s)!r}")
        for k in ALL_KINDS:
            new, old = _cap_resource(s, k), _old_cap_resource(s, k)
            check(new == old, f"E _cap_resource 동치: ({s!r},{k})→{new!r} (old {old!r})")

    print()
    if _fails:
        print(f"FAIL {len(_fails)}건")
        sys.exit(1)
    print("PASS — kind 레지스트리 파생이 행위 불변(라운드트립·옛 if-체인 동치·드리프트 핀).")


if __name__ == "__main__":
    main()

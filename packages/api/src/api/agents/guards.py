"""저장 시점 게이트 — toolPolicy 완화(스펙 177 P2)·비영속 경계(스펙 237)."""

import logging

from fastapi import HTTPException

from ..models import User
from ..ownership import is_privileged, owner_of

# 로거명은 분할 전 문자열("api.agents") 유지 — 감사 로그 연속성.
log = logging.getLogger("api.agents")


def _collect_relaxing_caps(tool_policy: dict) -> list[str]:
    """완화 의도(required=False 또는 approver=self) 오버라이드가 걸린 cap 목록을 반환."""
    relaxing: list[str] = []
    for cap, entry in tool_policy.items():
        appr = entry.get("approval") if isinstance(entry, dict) else None
        if not isinstance(appr, dict):
            continue
        # 검증기가 required→bool, approver→{admin,self} 정규화. required=false 또는 approver=self = 완화 의도.
        if appr.get("required") is False or appr.get("approver") == "self":
            relaxing.append(cap)
    return relaxing


def _enforce_tool_policy_gate(config: dict, principal: User | str) -> None:
    """스펙 177 P2 D4 — `toolPolicy` **완화 의도는 관리자만**. 강화(required:true·approver:admin)는 자유.

    완화 의도 = 오버라이드가 `required=false`(승인 끄기) 또는 `approver="self"`(본인 승인으로 약화). 이
    판정은 **오버라이드 값 자체로**(현재 도구 기본과 *무관*) 한다 — 그래야 **TOCTOU가 없다**(적대 검토 M):
    비교 기반(기본 대비 완화 여부)이면, member가 아직 승인 없는 도구에 `required:false`를 심어두고(그 순간
    엔 no-op이라 게이트 통과) admin이 나중에 그 도구를 승인 필요로 조이면, 저장 시점엔 안 걸렸던 override가
    런타임에 승인을 끄는 우회가 생긴다. 값 기반이면 **완화 의도를 표현하는 저장 자체가 비-admin에 막혀**
    어떤 버전·시점에도 비-admin이 저작한 완화 override가 존재할 수 없다(promote/activate가 재적용해도 안전).
    admin이 완화를 저장하면 감사 로그(전용 테이블 없음 — 구조화 로그로 주체·cap 기록)."""
    tp = (config or {}).get("toolPolicy") or {}
    if not tp:
        return
    relaxing = _collect_relaxing_caps(tp)
    if not relaxing:
        return
    if not is_privileged(principal):
        raise HTTPException(
            status_code=403,
            detail=f"도구 승인 완화(끄기·본인승인)는 관리자만 가능합니다: {', '.join(relaxing[:5])}",
        )
    log.info(
        "audit tool-policy 완화(스펙 177 P2): user=%s relaxing=%s",
        owner_of(principal) or "machine",
        relaxing,
    )


# 비영속에 금지되는 능력 kind(스펙 237) — 우리 DB에 **직접 쓰는** 유일한 도구 표면(기억 저장·수정).
# MCP 도구·RAG 조회·읽기 능력은 허용(사용자 결정: "DB 쓰기 도구만 금지, 읽기는 상관없음").
_EPHEMERAL_FORBIDDEN_CAP_KINDS = ("memwrite", "memedit")


def _enforce_ephemeral_boundary(config: dict) -> None:
    """스펙 237 — 비영속(ephemeral) 에이전트에 DB 쓰기 능력(memwrite/memedit) 연결을 입구에서 거부.

    비영속 계약(스펙 235)은 "채팅 1턴 DB 쓰기 0"인데 기억 저장·수정 능력은 정의상 DB에 쓴다 — 조용히
    무시(런타임 필터만)하면 사용자가 "연결했는데 안 된다"를 또 추적하게 되므로(회고 214) 저장 시점에
    명시적으로 막는다. 런타임 ctx 필터는 과거 저장분 대비 방어층."""
    if not (config or {}).get("ephemeral"):
        return
    bad = [
        c
        for c in (config.get("capabilities") or [])
        if isinstance(c, str) and c.split(":", 1)[0] in _EPHEMERAL_FORBIDDEN_CAP_KINDS
    ]
    if bad:
        raise HTTPException(
            status_code=422,
            detail=f"비영속(1회성) 에이전트에는 기억 저장·수정 능력을 연결할 수 없습니다(DB에 기록하는 도구): {', '.join(bad[:5])}",
        )

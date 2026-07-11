"""능력 브로커 UI(스펙 106)용 메타 라우트 — 실행 방식(impl) 목록(스펙 206)."""

from pydantic import BaseModel

from .routers import meta_router


class ImplMetaOut(BaseModel):
    """실행 방식 메타(스펙 206) — key + 소비 표면 선언(consumes). consumes null=미선언(폼 전부 노출)."""

    key: str
    consumes: list[str] | None = None


@meta_router.get("/agent-impls", response_model=list[ImplMetaOut])
async def list_impls() -> list[ImplMetaOut]:
    """등록된 실행 방식(impl) 키+소비 표면 — 신뢰 레지스트리 단일 출처(drift 0). 편집 폼이 소비
    (스펙 206: consumes로 안 읽는 표면 숨김/경고). 키일 뿐(런타임 eval 없음, 스펙 085).
    agent.runtime import가 `_bootstrap_builtins()`를 이미 실행."""
    from agent.runtime import get_agent_impl, list_agent_impls

    out = []
    for key in list_agent_impls():
        impl = get_agent_impl(key)
        consumes = None
        try:
            c = impl.describe().consumes if impl else None
            consumes = list(c) if c is not None else None
        except Exception:
            consumes = None
        out.append(ImplMetaOut(key=key, consumes=consumes))
    return out

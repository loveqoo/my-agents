"""버전·핀·프롬프트 출처 해석 — chat_context.py에서 분할(스펙 394 P2, 순수 이동).

파사드는 chat_context.py(재수출 계약).
"""

import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .chat_context_types import _is_remote
from .models import Agent


async def _resolve_version_and_prompt(
    db: AsyncSession, agent: Agent, cfg: dict, version: str | None
) -> tuple[dict, str, str | None]:
    """버전 지정 실행(스펙 242) — 그 버전의 config 스냅샷으로 소스 전환(초안 미리보기·버전 테스트).

    prompt는 스냅샷에 이름만 있으므로 지금 본문으로 재해석(activate와 동일 규칙).
    반환 (cfg, prompt, pinned_version). version 미지정이면 저장 config·prompt 그대로."""
    if not version:
        return cfg, agent.prompt, None
    if _is_remote(agent.source):
        raise HTTPException(
            status_code=400,
            detail="원격(code/external) 에이전트는 버전 지정 실행을 지원하지 않습니다",
        )
    from .models import AgentVersion

    vrow = (
        await db.execute(
            select(AgentVersion).where(
                AgentVersion.agent_pk == agent.id, AgentVersion.version == version
            )
        )
    ).scalar_one_or_none()
    if vrow is None:
        raise HTTPException(status_code=404, detail=f"버전을 찾을 수 없습니다: {version}")
    cfg = dict(vrow.config or {})
    # 미리보기 실행도 pin 우선(스펙 370) — 그 버전이 못박은 본문으로(head 폴백=레거시·literal).
    from .block_versions import resolve_pinned

    pinned = await resolve_pinned(db, vrow.pins, "prompt", cfg.get("prompt", ""))
    if pinned is not None:
        prompt = pinned.get("body", "")
    else:
        from .models import Prompt as _Prompt

        prow = (
            await db.execute(select(_Prompt).where(_Prompt.name == cfg.get("prompt", "")))
        ).scalar_one_or_none()
        prompt = prow.body if prow is not None else cfg.get("prompt", "")
    return cfg, prompt, version


async def _resolve_prompt_provenance(
    db: AsyncSession, cfg: dict, applied_overrides: dict | None, remote: bool
) -> tuple[str | None, str | None]:
    """프롬프트 출처(스펙 364) — 이 턴에 실제 쓰인 프롬프트의 (이름, id). 턴 분석/재현 근거.

    systemPrompt 오버라이드로 임시 프롬프트가 쓰였으면 라이브러리 참조가 아니므로 이름/id 없음(정직).
    cfg["prompt"]는 이름이거나 인라인 본문 — 실제 Prompt 행이 매칭될 때만 이름/id를 남기고(짧은
    라이브러리 키), 인라인이면 (None, None)(본문은 promptSnapshot이 보존). 원격(code/external)은
    프롬프트가 원격 측에 있어 로컬 라이브러리 참조가 무의미 → 미기록."""
    _sp = (applied_overrides or {}).get("systemPrompt")
    _override_prompt = isinstance(_sp, str) and bool(_sp.strip())
    _ref = "" if (remote or _override_prompt) else (cfg.get("prompt") or "")
    if not _ref:
        return None, None
    from .models import Prompt as _Prompt

    _prow = (await db.execute(select(_Prompt.id).where(_Prompt.name == _ref))).scalar_one_or_none()
    if _prow is None:
        return None, None
    return _ref, str(_prow)


async def _resolve_exec_pins(
    db: AsyncSession, agent_pk: uuid.UUID, exec_version: str | None, remote: bool
) -> dict:
    """실행 버전의 pins(스펙 370) — 못박은 블록 버전으로 해석(모델·MCP·노드 모델). 원격/레거시
    (pins 없음)는 빈 dict → 전부 head 폴백(무회귀)."""
    if remote or not exec_version:
        return {}
    from .models import AgentVersion as _AgentVer

    _vrow = (
        await db.execute(
            select(_AgentVer.pins).where(
                _AgentVer.agent_pk == agent_pk, _AgentVer.version == exec_version
            )
        )
    ).scalar_one_or_none()
    return dict(_vrow or {})

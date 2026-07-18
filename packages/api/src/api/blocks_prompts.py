"""프롬프트 라우트 — blocks.py에서 분할(스펙 393 P3).

prompt_apply(구 CC 14)는 PromptApplyCommand(Replace Function with Command — 392 선례)로 분해:
라우트는 조회+command 호출만, 자격 판정(_eligible)과 채택 스크래치 생성(_adopt)은 메서드로.
파사드는 blocks.py(재수출 계약).
"""

import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from agent.runtime import is_first_party

from .auth import current_principal
from .block_versions import delete_block_history, record_block_version
from .blocks_shared import _commit_or_409, _norm_description
from .db import get_or_404, get_session
from .models import Agent, Prompt, User
from .naming import assert_valid_name
from .ownership import may_manage, may_use_agent
from .references import _config_has, agents_referencing, referenced_message
from .schemas import PromptApplyIn, PromptApplyOut, PromptIn, PromptOut, PromptUsageAgentOut

router = APIRouter(tags=["blocks"])


@router.get("/prompts", response_model=list[PromptOut])
async def list_prompts(session: AsyncSession = Depends(get_session)) -> Any:
    result = await session.execute(select(Prompt))
    return result.scalars().all()


@router.post("/prompts", response_model=PromptOut, status_code=201)
async def create_prompt(body: PromptIn, session: AsyncSession = Depends(get_session)) -> Any:
    assert_valid_name(body.name)  # 식별 이름 규칙(스펙 148)
    obj = Prompt(**_norm_description(body.model_dump()))
    session.add(obj)
    await _commit_or_409(session, "같은 식별 이름의 프롬프트가 이미 있습니다.")
    await session.refresh(obj)
    await record_block_version(session, "prompt", obj)  # v1 이력(스펙 369)
    await session.commit()
    return obj


@router.get("/prompts/{id}", response_model=PromptOut)
async def get_prompt(id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> Any:
    return await get_or_404(session, Prompt, id)


@router.put("/prompts/{id}", response_model=PromptOut)
async def update_prompt(
    id: uuid.UUID, body: PromptIn, session: AsyncSession = Depends(get_session)
) -> Any:
    obj = await get_or_404(session, Prompt, id)
    if body.name != obj.name:
        assert_valid_name(body.name)  # 이름 변경 시에만 규칙(기존은 grandfather, 스펙 148)
        # rename도 config["prompt"] 참조를 깬다 — MCP(093)와 동일 가드(codex 148 High)
        refs = await agents_referencing(session, "prompt", obj.name)
        if refs:
            raise HTTPException(
                status_code=409, detail=referenced_message(refs, "프롬프트", action="이름 변경")
            )
    for key, value in _norm_description(body.model_dump()).items():
        setattr(obj, key, value)
    # 콘텐츠 변경이면 버전+1 + 이력 append(스펙 369 관문) — 동시 편집 레이스는 UNIQUE가 commit서 막음.
    await record_block_version(session, "prompt", obj)
    await _commit_or_409(session, "같은 식별 이름의 프롬프트가 이미 있거나 동시 편집과 겹쳤습니다.")
    await session.refresh(obj)
    return obj


@router.get("/prompts/{id}/agents", response_model=list[PromptUsageAgentOut])
async def prompt_agents(
    id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    principal: User | str = Depends(current_principal),
) -> Any:
    """이 프롬프트를 쓰는 에이전트 + 각 오래됨(stale) 상태(스펙 161). 편집 화면이 "N개 사용·M개
    오래됨"과 선택 반영 대상을 그린다. stale = 에이전트 스냅샷(agent.prompt) != 현재 본문(obj.body)."""
    obj = await get_or_404(session, Prompt, id)
    agents = (await session.execute(select(Agent))).scalars().all()
    return [
        PromptUsageAgentOut(
            id=a.id,
            agentId=a.agent_id,
            name=a.name,
            description=a.description,
            stale=(a.prompt != obj.body),
            canManage=may_manage(a.owner_id, principal),
        )
        for a in agents
        # may_use_agent 가시성 필터(스펙 147, codex 161 High) — 타인 private 에이전트의 식별자·stale를
        # 누출하지 않는다(일반 list/get/chat과 동일 게이트). admin/machine은 전부, member는 본인+public.
        if is_first_party(a.source)
        and may_use_agent(a, principal)
        and _config_has(a.config, "prompt", obj.name)
    ]


@dataclass
class PromptApplyCommand:
    """프롬프트 최신 본문 반영(스펙 161→370) — 선택 에이전트마다 **채택 스크래치 버전** 생성.

    각 에이전트 can_manage 게이트(남의 에이전트 무단 변경 금지)·이 프롬프트 미참조/미존재는 skip으로
    정직 보고. in-place 스냅샷 갱신(구 161)은 불변 버전 모델과 비정합이라 스크래치 채택(스펙 370) —
    반영은 각 에이전트에서 오픈해야 서빙된다(명시적)."""

    session: AsyncSession
    principal: User | str
    prompt: Prompt
    want: set[uuid.UUID]
    applied: list[uuid.UUID] = field(default_factory=list)
    skipped: list[uuid.UUID] = field(default_factory=list)

    def _is_eligible(self, agent: Agent) -> bool:
        return (
            is_first_party(agent.source)
            and _config_has(agent.config, "prompt", self.prompt.name)
            and may_manage(agent.owner_id, self.principal)
        )

    async def _adopt(self, agent: Agent) -> None:
        """채택 스크래치 생성/갱신 — 활성 버전 config 기반, 참조 핀 동결(freeze_pins)."""
        from .agents.helpers import _today, scratch_target
        from .block_versions import freeze_pins
        from .models import AgentVersion

        loaded = (
            await self.session.execute(
                select(Agent).where(Agent.id == agent.id).options(selectinload(Agent.versions))
            )
        ).scalar_one()
        scratch, target_ver = scratch_target(loaded)
        base = next((v for v in loaded.versions if v.version == loaded.active_version), None)
        cfg = dict((base.config if base is not None else loaded.config) or {})
        pins = await freeze_pins(self.session, cfg)
        note = f"프롬프트 새 버전 채택 {_today()}"
        if scratch is not None:
            scratch.version = target_ver
            scratch.config = cfg
            scratch.pins = pins
            scratch.note = note
        else:
            loaded.versions.append(
                AgentVersion(
                    version=target_ver, ever_opened=False, pins=pins, note=note, config=cfg
                )
            )

    async def run(self) -> PromptApplyOut:
        agents = (
            (await self.session.execute(select(Agent).where(Agent.id.in_(self.want))))
            .scalars()
            .all()
        )
        for agent in agents:
            if self._is_eligible(agent):
                await self._adopt(agent)
                self.applied.append(agent.id)
            else:
                self.skipped.append(agent.id)
        found = {a.id for a in agents}
        self.skipped.extend(aid for aid in self.want if aid not in found)  # 미존재도 skip 정직 보고
        if self.applied:
            await self.session.commit()
        return PromptApplyOut(applied=self.applied, skipped=self.skipped)


@router.post("/prompts/{id}/apply", response_model=PromptApplyOut)
async def prompt_apply(
    id: uuid.UUID,
    body: PromptApplyIn,
    session: AsyncSession = Depends(get_session),
    principal: User | str = Depends(current_principal),
) -> Any:
    """선택 에이전트들의 프롬프트 스냅샷을 이 프롬프트 최신 본문으로 반영(스펙 161). **각 에이전트
    can_manage 게이트** — 관리 불가/이 프롬프트 미참조 대상은 건너뛴다(남의 에이전트 무단 변경 금지)."""
    obj = await get_or_404(session, Prompt, id)
    return await PromptApplyCommand(
        session=session, principal=principal, prompt=obj, want=set(body.agentIds)
    ).run()


@router.delete("/prompts/{id}", status_code=204)
async def delete_prompt(id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> None:
    obj = await get_or_404(session, Prompt, id)
    # 참조 중 삭제 차단(093 operation-symmetry를 프롬프트에도 — codex 148 High): 지우면
    # resolve_prompt가 name 문자열 자체를 시스템 프롬프트로 쓰는 조용한 degrade가 생긴다.
    refs = await agents_referencing(session, "prompt", obj.name)
    if refs:
        raise HTTPException(status_code=409, detail=referenced_message(refs, "프롬프트"))
    await delete_block_history(session, "prompt", obj.id)  # 폴리모픽 이력 동일 tx 정리(스펙 369)
    await session.delete(obj)
    await session.commit()

# ruff: noqa: F401
"""에이전트 서비스 라우터 — 버전 관리 + A2A 노출 + 코드 에이전트 등록.

비동기 SQLAlchemy 2.0 + Pydantic v2. 모든 응답은 serializers.agent_to_out 경유.
agent.versions 는 lazy 관계라 async 세션 밖에서 로드하면 실패하므로,
조회/뮤테이션 후 항상 selectinload(Agent.versions) 로 eager-load 한다.

스펙 291 분할 파사드: api/agents.py 단일 모듈을 패키지로 분할하되 전 심볼을 여기서 재수출한다
(main.py의 agents.router/meta_router, verify의 AG.X 접근 무변경). 라우트 모듈 import가
공유 router/meta_router(routers.py)에 라우트를 등록하는 부수효과를 완성한다(24개 무손실).
"""

import asyncio
import logging
import re
import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from agent.runtime import is_first_party, is_third_party

from .. import agent_card, crypto, memory, net_guard
from ..auth import current_principal
from ..background import spawn
from ..chat import derive_pipeline_pool, resolve_agent_mem_cfg
from ..db import get_session
from ..models import Agent, AgentVersion, Prompt
from ..naming import slugify_name
from ..ownership import assert_may_manage, is_privileged, may_manage, may_use_agent, owner_of
from ..schemas import (
    ActivateIn,
    AgentCreate,
    AgentOut,
    AgentUpdate,
    ConnectAgentIn,
    ExposeIn,
    MemoryHit,
    MemoryPageItem,
    MemoryPageOut,
    MemorySearchDiag,
    MemorySearchIn,
    MemorySearchOut,
    RegisterCodeAgentIn,
    RegisterExternalAgentIn,
)
from ..serializers import agent_to_out
from .card_builder import (
    _build_code_agent_from_card,
    _build_external_agent,
    _clip,
    _norm_endpoint,
)

# 라우트 모듈 import = 공유 router/meta_router에 라우트 등록(부수효과 필수 — 스펙 291 지도 주의점).
from .crud_routes import (
    AgentOpsOut,
    VersionOps,
    agent_ops,
    clone_agent,
    create_agent,
    delete_agent,
    get_agent,
    list_agents,
    update_agent,
)
from .exposure_routes import VisibilityIn, expose_agent, set_agent_visibility
from .guards import (
    _EPHEMERAL_FORBIDDEN_CAP_KINDS,
    _enforce_ephemeral_boundary,
    _enforce_tool_policy_gate,
    log,
)
from .helpers import (
    _commit_or_409,
    _dedupe_agent_name,
    _find_version,
    _load_agent,
    _new_agent_id,
    _reload_out,
    _slugify_remote_agent,
    _today,
    next_version,
    resolve_prompt,
)
from .memory_routes import (
    AgentMemoryIn,
    _agent_mem_cfg,
    _assert_owns,
    add_agent_memory,
    delete_agent_memory,
    list_agent_memory,
    page_agent_memory,
    search_agent_memory,
    update_agent_memory,
)
from .meta_routes import ImplMetaOut, list_impls
from .remote_routes import (
    connect_agent,
    register_code_agent,
    register_external_agent,
    resync_agent,
)
from .routers import meta_router, router
from .version_routes import activate_version, adopt_block_versions

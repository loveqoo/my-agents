"""평가 하네스 제품화 라우터 — 문제집/케이스 CRUD + 실행/성적표 (스펙 137·178).

**인가(스펙 178)**: 컬렉션 패턴 = **읽기 공개·관리 소유자**. require("eval",*) admin 게이트를 제거하고
current_principal + ownership.py 술어로 전환 — 멤버가 본인 문제집·본인 쓸 수 있는 에이전트를 자율 평가.
읽기(list/get)는 전 유저 공개(D1), 관리(생성/수정/삭제/실행/출제)는 소유자만(비소유 404-fold). 실행·출제
대상 에이전트는 may_use_agent 게이트(남의 private 평가 차단). asserts는 선언적 JSON →
`eval_harness.build_asserts`가 **닫힌 type 집합**으로 검증(미지 type=400 — 평가는 fail-closed).

스펙 291(Phase 3b): 관심사별 형제 모듈(eval_schemas/common/guards/datasets/cases/env/runs/authoring)로
분할 — 이 모듈은 **파사드**로 전 심볼을 재수출한다. 외부의 `from api.eval_routes import X` /
`from api import eval_routes` 접근은 전부 무변경(재배선 없는 분할 계약).
"""

# ── 파사드 재수출(스펙 291) — 분할 전 eval_routes.py의 공개 표면 전량 보존(외부 import 무변경) ──
import logging  # noqa: F401
import uuid  # noqa: F401
from datetime import UTC, datetime  # noqa: F401

from fastapi import APIRouter, Depends, HTTPException, Query  # noqa: F401
from pydantic import BaseModel, Field  # noqa: F401
from sqlalchemy import and_, func, or_, select, text  # noqa: F401
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: F401

# 라우트 등록 부수효과 import(스펙 291 지도) — 라우트 모듈이 eval_common.router에 데코레이터로
# 등록한다. 이 import가 빠지면 라우트가 조용히 비어 404(아래 심볼 import도 같은 모듈을 로드하지만
# side-effect 의도를 명시).
from . import eval_authoring, eval_cases, eval_datasets, eval_runs  # noqa: F401
from .auth import current_principal  # noqa: F401
from .background import spawn  # noqa: F401
from .db import SessionLocal, get_session  # noqa: F401
from .eval_authoring import (  # noqa: F401
    _execute_generation,
    _execute_generation_append,
    _execute_harvest,
    _execute_suggestion,
    _unharvested_count,
    generate_dataset,
    harvest_count,
    harvest_feedback,
    helper_status,
    suggest_cases,
)
from .eval_cases import create_case, delete_case, list_cases, update_case  # noqa: F401
from .eval_common import (  # noqa: F401
    _dataset_or_404,
    _dataset_out,
    _gate_harvest_read,
    _ilike_literal,
    _is_generating,
    _validate_asserts,
    log,
    router,
)
from .eval_datasets import (  # noqa: F401
    create_dataset,
    delete_dataset,
    get_dataset,
    list_datasets,
    update_dataset,
)
from .eval_env import _ENV_SECRET_KEYS, _env_redact, _env_snapshot, _model_env  # noqa: F401
from .eval_guards import (  # noqa: F401
    _MEMBER_MAX_CONCURRENT_JOBS,
    _MEMBER_MAX_CONCURRENT_RUNS,
    _MEMBER_MAX_RUN_WORK,
    _active_jobs,
    _helper_llm,
    _member_job_guard,
    _member_run_guard,
)
from .eval_harness import EvalCase as HarnessCase  # noqa: F401
from .eval_harness import build_asserts, run_eval  # noqa: F401
from .eval_runner import eval_run_agent  # noqa: F401
from .eval_runs import (  # noqa: F401
    _execute_group,
    _execute_run,
    get_run,
    list_runs,
    start_run,
    sweep_zombie_datasets,
    sweep_zombie_runs,
    trigger_auto_regression,
)
from .eval_schemas import (  # noqa: F401
    CaseIn,
    CaseOut,
    CaseResultOut,
    DatasetIn,
    DatasetOut,
    DatasetPageOut,
    GenerateIn,
    HarvestCountOut,
    HarvestIn,
    HelperStatusOut,
    RunDetailOut,
    RunOut,
    RunStartIn,
    SuggestIn,
)
from .models import (  # noqa: F401
    Agent,
    EvalCase,
    EvalCaseResult,
    EvalDataset,
    EvalRun,
    MessageFeedback,
    Session,
)
from .ownership import (  # noqa: F401
    assert_may_manage,
    is_privileged,
    may_manage,
    may_use_agent,
    owner_of,
)

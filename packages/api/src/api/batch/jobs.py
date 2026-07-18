"""배치 작업 — **파사드**(스펙 395: 가족별 형제 모듈로 분할, 재수출 계약). 스펙 038.

각 작업은 `async def job(*, dry_run: bool, run_id=None) -> dict` 시그니처 — runner가 키워드
호출(스펙 383)하고 결과 dict를 BatchRun.summary로 박제한다. 작업은 자체 SessionLocal로 DB를
다룬다(요청 컨텍스트 밖에서도 돌아야 하므로). 전부 idempotent.

스펙 395 분할(chat_*/blocks_*/chat_context_* 관례 — 평면 형제 + 파사드, 서브패키지 금지:
api.batch.jobs가 모듈→패키지로 바뀌면 직접 임포트·monkeypatch가 흔들린다):
  jobs_shared(_get_config) · jobs_guards(순수 가드 — 전체삭제 패턴·사설망·keep-list·최후 super) ·
  jobs_sessions(세션 정리) · jobs_memory_consolidation(기억 통합 — monkeypatch 소비자는 이 모듈의
  `_consolidate`·`default_mem_cfg`를 패치) · jobs_agents(A2A 정크) · jobs_users(테스트 유저) ·
  jobs_retention(토큰·승인·이력·체크포인트·mem0 orphan).
외부의 `from api.batch.jobs import X` / `from api.batch import jobs` 접근은 전부 무변경.
JOBS 레지스트리는 이 파사드가 소유(CLI choices·API 트리거·스케줄러 공유 단일 출처).
"""

from ..mem_config import default_mem_cfg  # noqa: F401  (구 표면 보존 — 039 계열 소비)
from .jobs_agents import cleanup_a2a_agents
from .jobs_guards import (  # noqa: F401
    _A2A_PRIVATE_NETS,
    _USER_CLEANUP_KEEP,
    _is_private_host,
    _protect_last_supers,
    _survives_keep_list,
    is_delete_all_pattern,
)
from .jobs_memory_consolidation import (  # noqa: F401
    _MAX_CONSOLIDATE_INPUT,
    _candidates,
    _consolidate,
    _consolidate_one_user,
    _consolidation_preview,
    _is_valid_consolidation,
    consolidate_user_memories,
)
from .jobs_retention import (  # noqa: F401
    _KEEP_RUNS_PER_DATASET,
    _TOKEN_GRACE,
    cleanup_approvals,
    cleanup_checkpoints,
    cleanup_history,
    cleanup_memories,
    cleanup_tokens,
)
from .jobs_sessions import (  # noqa: F401
    _TURN_CLEANUP_IDLE_GUARD,
    _age_criterion_active,
    _cleanup_criteria_labels,
    _pending_approval_clause,
    _session_cleanup_clauses,
    _session_cleanup_meta,
    _turn_criterion_active,
    cleanup_sessions,
)
from .jobs_shared import _get_config  # noqa: F401
from .jobs_users import (  # noqa: F401
    _purge_casbin_rules,
    _reload_enforcer_after_user_delete,
    cleanup_test_users,
)

# 작업 레지스트리 — CLI choices·API 트리거·스케줄러가 공유하는 단일 출처.
JOBS = {
    "session-cleanup": cleanup_sessions,
    "memory-consolidation": consolidate_user_memories,
    "a2a-cleanup": cleanup_a2a_agents,
    "user-cleanup": cleanup_test_users,
    "checkpoint-cleanup": cleanup_checkpoints,
    "token-cleanup": cleanup_tokens,
    "approval-cleanup": cleanup_approvals,
    "history-cleanup": cleanup_history,
    "memory-cleanup": cleanup_memories,
}

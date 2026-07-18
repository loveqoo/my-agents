"""빌딩 블록 카탈로그 — **파사드**(스펙 393: 가족별 형제 모듈로 분할, 재수출 계약).

프롬프트·메모리타입·MCP 서버 CRUD + 관리자 UI 집계(`GET /blocks`) + 블록 버전 이력.
스펙 393 분할(chat_* 291/392와 동형 — 평면 형제 모듈 + 파사드):
  blocks_shared(공유 헬퍼) · blocks_presenters(직렬화·마스킹) · blocks_mcp_discovery(라이브 탐색·
  도구 메타) · blocks_prompts(/prompts) · blocks_memory_types(/memory-types) · blocks_mcp
  (/mcp-servers) · blocks_catalog(/blocks 집계) · blocks_versions_routes(/block-versions).
외부의 `from api.blocks import X` / `from api import blocks` 접근은 전부 무변경(재배선 없는
분할 계약). embedding 카테고리는 RAG 컬렉션(스펙 036)을 읽기 전용으로 비춘다 — 컬렉션
CRUD/인제스트는 `rag.py`(`/collections`)가 담당한다.
"""

from fastapi import APIRouter

from . import (
    blocks_catalog,
    blocks_mcp,
    blocks_memory_types,
    blocks_prompts,
    blocks_versions_routes,
)

# ── 파사드 재수출 — 분할 전 blocks.py의 **공개 표면**(실소비 심볼) 전량 보존(외부 import 무변경).
# 옛 모듈이 지나가며 임포트했던 이름(select·McpServer 등)은 재수출하지 않는다 — repo 전수 실측
# 소비자 0(codex 393 적대 리뷰 확인), 정직한 경계로 문서화(잡동사니 네임스페이스 미보존). ──
from .blocks_catalog import _CATEGORY_META, _count_by, get_blocks  # noqa: F401
from .blocks_mcp import (  # noqa: F401
    _apply_auth_patch,
    _assert_removed_tools_unreferenced,
    _assert_renameable,
    _assert_source_immutable,
    _build_test_server,
    _validate_tool_testable,
    create_mcp_server,
    delete_mcp_server,
    discover_mcp_tools,
    get_mcp_server,
    list_mcp_servers,
    publish_mcp_server,
    rediscover_mcp_server,
    test_mcp_tool,
    update_mcp_server,
)
from .blocks_mcp_discovery import (  # noqa: F401
    _live_discover,
    _tool_info,
    _tools_meta_from_details,
)
from .blocks_memory_types import (  # noqa: F401
    assert_memory_names_exist,
    create_memory_type,
    delete_memory_type,
    get_memory_type,
    list_memory_types,
    update_memory_type,
)
from .blocks_presenters import (  # noqa: F401
    _audit_json,
    _mcp_auth_masked,
    _mcp_served_url,
    mcp_to_out,
)
from .blocks_prompts import (  # noqa: F401
    PromptApplyCommand,
    create_prompt,
    delete_prompt,
    get_prompt,
    list_prompts,
    prompt_agents,
    prompt_apply,
    update_prompt,
)
from .blocks_shared import _commit_or_409, _norm_description  # noqa: F401
from .blocks_versions_routes import get_block_version, list_block_versions  # noqa: F401

# 캡 상수 재수출 — 구 blocks.py가 임포트해 노출하던 표면(verify_151 등 소비, 출처는 mcp_tool_meta 단일).
from .mcp_tool_meta import (  # noqa: F401
    PARAM_NAME_CAP,
    PARAM_TYPE_CAP,
    TOOL_DESC_CAP,
    TOOL_NAME_CAP,
    TOOL_PARAMS_CAP,
    TOOLS_META_CAP,
)

# 가족 라우터 조립 — prefix 없이 include(기존 path 불변, main.py는 blocks.router 하나만 include).
router = APIRouter()
router.include_router(blocks_prompts.router)
router.include_router(blocks_memory_types.router)
router.include_router(blocks_mcp.router)
router.include_router(blocks_catalog.router)
router.include_router(blocks_versions_routes.router)

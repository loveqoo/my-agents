"""Pydantic 입출력 스키마 (007 도메인) — 도메인별 모듈 분할(스펙 378, 캠페인 374 T2).

공개 API는 이 패키지에서 그대로 노출(`from api.schemas import X`) — 기존 임포터 무변경.
기존 단일 파일(1054줄·76클래스)을 base/blocks/collections/memory/mcp/registry/agents/sessions/admin로.
"""

from .admin import (  # noqa: F401
    AdminUserOut,
    PolicyIn,
    PolicyOut,
    RoleAssignIn,
    RoleOut,
    UserCreate,
    UserRead,
    UserUpdate,
)
from .agents import (  # noqa: F401
    ActivateIn,
    AgentConfig,
    AgentCreate,
    AgentOut,
    AgentUpdate,
    ConnectAgentIn,
    ExposeIn,
    RegisterCodeAgentIn,
    RegisterExternalAgentIn,
    VersionOut,
)
from .base import ORM, AuditOut  # noqa: F401
from .blocks import (  # noqa: F401
    BlockVersionOut,
    MemoryTypeIn,
    MemoryTypeOut,
    PromptApplyIn,
    PromptApplyOut,
    PromptIn,
    PromptOut,
    PromptUsageAgentOut,
)
from .collections import (  # noqa: F401
    CollectionHealth,
    CollectionIn,
    CollectionOut,
    CollectionSearchIn,
    CollectionSearchOut,
    CollectionUpdate,
    DocumentContentOut,
    DocumentEditIn,
    DocumentEditOut,
    DocumentOut,
    DocumentPageOut,
    ReindexEventOut,
    ReindexIn,
    SearchHit,
)
from .mcp import (  # noqa: F401
    McpDiscoverIn,
    McpDiscoverResult,
    McpPublishIn,
    McpServerIn,
    McpServerOut,
    McpToolInfo,
    McpToolParam,
    McpToolTestIn,
    McpToolTestOut,
)
from .memory import (  # noqa: F401
    MemoryHit,
    MemoryPageItem,
    MemoryPageOut,
    MemorySearchDiag,
    MemorySearchIn,
    MemorySearchOut,
)
from .registry import (  # noqa: F401
    AvailableModel,
    AvailableModelsOut,
    ModelIn,
    ModelOut,
    ModelProbeIn,
    ModelProbeResult,
    ProviderIn,
    ProviderOut,
    ProviderProbeIn,
)
from .sessions import (  # noqa: F401
    ApprovalOut,
    ApprovalPage,
    ChatFormSubmission,
    ChatMessage,
    ChatRequest,
    FeedbackOut,
    MessageFeedbackIn,
    MessageOut,
    ResolveIn,
    SessionOut,
    SessionPage,
)

"""도메인 테이블 — 도메인별 모듈 분할(스펙 379, 캠페인 374 T2).

공개 API는 이 패키지에서 그대로(`from api.models import X`) — 임포터 무변경. 모든 모델을
여기서 import해 SQLAlchemy 레지스트리에 등록(relationship 문자열 참조 해결 보장).
"""

from .agents import Agent, AgentVersion, NodeTemplate  # noqa: F401
from .auth import AccessToken, Role, User  # noqa: F401
from .base import RAG_EMBED_DIMS, Base, _pk  # noqa: F401
from .batch import AllowedHost, BatchConfig, BatchRun, MemorySnapshot  # noqa: F401
from .blocks import BlockVersion, MemoryType, Prompt  # noqa: F401
from .core import AppSetting  # noqa: F401
from .eval import EvalCase, EvalCaseResult, EvalDataset, EvalRun  # noqa: F401
from .mcp import McpServer  # noqa: F401
from .rag import Chunk, Collection, CollectionReindexEvent, Document, DocumentBlob  # noqa: F401
from .registry import ModelConfig, Provider  # noqa: F401
from .sessions import Approval, Message, MessageFeedback, Session  # noqa: F401

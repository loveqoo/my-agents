"""mem0 mem_cfg 해석기 — 레지스트리 모델 → mem0 설정(llm+embedder dict). 스펙 039.

chat.py에서 추출한 경량 모듈. `ModelConfig`·`crypto`만 의존하고 langgraph/fastapi를 끌지 않는다 →
격리 배치 서비스(`api.batch`, 스펙 038)가 chat.py(=`from agent.main import build_agent`)를 임포트하지
않고도 유저 메모리 mem_cfg를 해석할 수 있다. chat.py·memory_routes.py가 여기서 re-import한다.

mem_cfg 구조·축 규칙은 memory.py 모듈 docstring 참고. 지배 스펙: 008(레지스트리), 020(스코프), 039.
"""

from typing import TypeGuard

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from . import crypto
from .models import ModelConfig


def model_usable(cm: ModelConfig | None) -> TypeGuard[ModelConfig]:
    """기본 chat/embedding 모델이 실사용 가능한가 — provider·base_url·model_id 완비(정본, 스펙 300).
    TypeGuard: positive 분기(`if model_usable(cm):`)서 mypy가 cm을 ModelConfig로 narrow(연결 dict 조립부).
    값-유효성 체크라 TypeIs는 불건전(빈 base_url 모델도 False) — positive만 narrow하는 TypeGuard가 건전."""
    return (
        cm is not None
        and cm.provider is not None
        and bool(cm.provider.base_url)
        and bool(cm.model_id)
    )


def llm_cfg_of(cm: ModelConfig) -> dict:
    """ModelConfig → LLM 연결 cfg(정본, 스펙 300). **api_key 평문 복호화** — API 응답에 넣지 말 것
    (serializers 마스킹과 반대 목적, 런타임 ChatOpenAI 구성용). `model_usable`로 검증 후 호출."""
    assert cm.provider is not None  # model_usable 검증 후 호출 전제(provider 보장)
    return {
        "base_url": cm.provider.base_url,
        "api_key": crypto.decrypt(cm.provider.api_key),
        "model_id": cm.model_id,
    }


def _build_mem_cfg(chat_m: ModelConfig | None, emb_m: ModelConfig | None) -> dict | None:
    """레지스트리 chat+embedding 모델 → mem0 mem_cfg(llm+embedder dict, 복호화 포함).
    연결처는 각 모델의 provider에서 상속(스펙 035). 어느 쪽이라도 provider base_url/model_id가
    없으면 None. get_all/update/delete는 embedder만 쓰지만 mem0 인스턴스화에 llm 자리가 필요하다
    (스펙 030 공유 빌더). 호출 측은 provider 관계를 eager-load해야 한다."""
    if model_usable(chat_m) and model_usable(emb_m):
        return {"llm": llm_cfg_of(chat_m), "embedder": llm_cfg_of(emb_m)}
    return None


async def _default_chat_model(db: AsyncSession) -> ModelConfig | None:
    return (
        (
            await db.execute(
                select(ModelConfig)
                .where(ModelConfig.kind == "chat", ModelConfig.is_default.is_(True))
                .options(selectinload(ModelConfig.provider))
            )
        )
        .scalars()
        .first()
    )


async def _default_embed_model(db: AsyncSession) -> ModelConfig | None:
    return (
        (
            await db.execute(
                select(ModelConfig)
                .where(ModelConfig.kind == "embedding", ModelConfig.is_default.is_(True))
                .options(selectinload(ModelConfig.provider))
            )
        )
        .scalars()
        .first()
    )


async def default_mem_cfg(db: AsyncSession) -> dict | None:
    """특정 에이전트에 안 묶인 mem0 설정 — 기본 chat + 기본 embedding. 유저 메모리
    관리(스펙 030)·통합(스펙 039)용. 공유 pgvector·user_id 키라 기본 설정으로 조회·교정이 가능하다."""
    return _build_mem_cfg(await _default_chat_model(db), await _default_embed_model(db))

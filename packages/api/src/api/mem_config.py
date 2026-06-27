"""mem0 mem_cfg 해석기 — 레지스트리 모델 → mem0 설정(llm+embedder dict). 스펙 039.

chat.py에서 추출한 경량 모듈. `ModelConfig`·`crypto`만 의존하고 langgraph/fastapi를 끌지 않는다 →
격리 배치 서비스(`api.batch`, 스펙 038)가 chat.py(=`from agent.main import build_agent`)를 임포트하지
않고도 유저 메모리 mem_cfg를 해석할 수 있다. chat.py·memory_routes.py가 여기서 re-import한다.

mem_cfg 구조·축 규칙은 memory.py 모듈 docstring 참고. 지배 스펙: 008(레지스트리), 020(스코프), 039.
"""

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from . import crypto
from .models import ModelConfig


def _build_mem_cfg(chat_m, emb_m) -> dict | None:
    """레지스트리 chat+embedding 모델 → mem0 mem_cfg(llm+embedder dict, 복호화 포함).
    연결처는 각 모델의 provider에서 상속(스펙 035). 어느 쪽이라도 provider base_url/model_id가
    없으면 None. get_all/update/delete는 embedder만 쓰지만 mem0 인스턴스화에 llm 자리가 필요하다
    (스펙 030 공유 빌더). 호출 측은 provider 관계를 eager-load해야 한다."""
    cp = chat_m.provider if chat_m else None
    ep = emb_m.provider if emb_m else None
    if chat_m is None or cp is None or not cp.base_url or not chat_m.model_id:
        return None
    if emb_m is None or ep is None or not ep.base_url or not emb_m.model_id:
        return None
    return {
        "llm": {
            "base_url": cp.base_url, "api_key": crypto.decrypt(cp.api_key), "model_id": chat_m.model_id,
        },
        "embedder": {
            "base_url": ep.base_url, "api_key": crypto.decrypt(ep.api_key), "model_id": emb_m.model_id,
        },
    }


async def _default_chat_model(db):
    return (
        await db.execute(
            select(ModelConfig)
            .where(ModelConfig.kind == "chat", ModelConfig.is_default.is_(True))
            .options(selectinload(ModelConfig.provider))
        )
    ).scalars().first()


async def _default_embed_model(db):
    return (
        await db.execute(
            select(ModelConfig)
            .where(ModelConfig.kind == "embedding", ModelConfig.is_default.is_(True))
            .options(selectinload(ModelConfig.provider))
        )
    ).scalars().first()


async def default_mem_cfg(db) -> dict | None:
    """특정 에이전트에 안 묶인 mem0 설정 — 기본 chat + 기본 embedding. 유저 메모리
    관리(스펙 030)·통합(스펙 039)용. 공유 pgvector·user_id 키라 기본 설정으로 조회·교정이 가능하다."""
    return _build_mem_cfg(await _default_chat_model(db), await _default_embed_model(db))

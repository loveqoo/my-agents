"""FastAPI 앱 — 페르소나 등록 + chat 노출.

지배 스펙: docs/spec/002-persona-registry-and-chat.md
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from fastapi import Depends

from . import agents, approvals, blocks, chat, mock_remote, model_registry, sessions
from .auth import require_auth
from .db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="Agent Service", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
# 도메인 라우터는 Bearer 토큰 인증 필요. mock_remote(외부 에이전트 스탠드인)는 제외 —
# 자체 인증 영역이며 chat 프록시가 에이전트 토큰을 보낸다.
_auth = [Depends(require_auth)]
app.include_router(blocks.router, dependencies=_auth)
app.include_router(model_registry.router, dependencies=_auth)
app.include_router(agents.router, dependencies=_auth)
app.include_router(chat.router, dependencies=_auth)
app.include_router(sessions.router, dependencies=_auth)
app.include_router(approvals.router, dependencies=_auth)
app.include_router(mock_remote.router)


def run():
    import uvicorn

    uvicorn.run("api.main:app", host="127.0.0.1", port=8000)

"""FastAPI 앱 — 페르소나 등록 + chat 노출.

지배 스펙: docs/spec/002-persona-registry-and-chat.md
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import agents, approvals, blocks, chat, sessions
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
app.include_router(blocks.router)
app.include_router(agents.router)
app.include_router(chat.router)
app.include_router(sessions.router)
app.include_router(approvals.router)


def run():
    import uvicorn

    uvicorn.run("api.main:app", host="127.0.0.1", port=8000)

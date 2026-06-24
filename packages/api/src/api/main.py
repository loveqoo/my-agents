"""FastAPI 앱 — 페르소나 등록 + chat 노출.

지배 스펙: docs/spec/002-persona-registry-and-chat.md
"""

import os
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

# CORS 허용 오리진 — 기본은 로컬 개발만. Tailscale 등 추가 오리진은
# EXTRA_CORS_ORIGINS(쉼표 구분) 환경변수로만 연다(소스에 머신별 IP 비하드코딩).
# "*" 지정 시 전체 허용 — 노출 경계는 `tailscale serve`/바인딩이 보장하므로,
# tailnet 안에서 IP·MagicDNS 어느 호스트로 접속하든 Origin을 통과시킨다.
_cors_origins = ["http://localhost:5173", "http://127.0.0.1:5173"]
_extra = os.environ.get("EXTRA_CORS_ORIGINS", "").strip()
if _extra == "*":
    _cors_origins = ["*"]
elif _extra:
    _cors_origins += [o.strip() for o in _extra.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
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

    # 기본은 loopback(외부 비노출). Tailscale 노출은 API_HOST로만 켠다.
    # 예: API_HOST=100.72.45.58 → 이 맥 + tailnet에서만 닿고 그 외 인터페이스는 안 열림.
    host = os.environ.get("API_HOST", "127.0.0.1")
    port = int(os.environ.get("API_PORT", "8000"))
    uvicorn.run("api.main:app", host=host, port=port)

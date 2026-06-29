"""FastAPI 앱 — 페르소나 등록 + chat 노출.

지배 스펙: docs/spec/002-persona-registry-and-chat.md
"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from fastapi import Depends

from . import (
    a2a_server,
    agents,
    allowed_hosts,
    approvals,
    batch_routes,
    blocks,
    chat,
    memory_routes,
    mock_mcp,
    mock_remote,
    model_registry,
    net_guard,
    providers,
    rag,
    sessions,
    user_admin,
    users,
)
from . import checkpointer
from .auth import current_principal
from .authz import init_authz
from .db import init_db
from .schemas import UserRead, UserUpdate


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await net_guard.refresh_allowed_hosts(force=True)  # SSRF allowlist 스냅샷 warm(스펙 064)
    await init_authz()  # casbin_rule + enforcer + 기본 정책(멱등)
    await users.seed_admin()  # superuser 시드(env, fail-closed)
    await checkpointer.init_checkpointer()  # HIL durable 체크포인터(스펙 041, graceful)
    # self-host mock MCP(스펙 054)의 세션 매니저 lifespan을 직접 연다 — 마운트된 서브앱 lifespan은
    # Starlette가 자동 호출하지 않으므로 부모가 진입해야 streamable-HTTP 핸들러가 동작한다.
    async with mock_mcp.mcp.session_manager.run():
        yield
    await checkpointer.close_checkpointer()


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
    # 세션 쿠키 인증(스펙 031)은 크로스오리진에서 자격증명 동행이 필요하다. allow_credentials가
    # 없으면 브라우저가 Set-Cookie/쿠키 동행을 거부해 별도 호스트(VITE_API_BASE)·tailnet 직접
    # 오리진 로그인이 조용히 실패한다. same-origin /api 프록시 경로에는 무영향. "*"는 starlette가
    # 자격증명 요청에 한해 Origin을 반사(reflect)하므로 함께 동작한다.
    allow_credentials=True,
)
# 도메인 라우터는 인증 필요 — 세션 쿠키 유저 OR 머신 Bearer 토큰(하위호환). mock_remote(외부
# 에이전트 스탠드인)는 제외 — 자체 인증 영역이며 chat 프록시가 에이전트 토큰을 보낸다.
_auth = [Depends(current_principal)]
app.include_router(blocks.router, dependencies=_auth)
app.include_router(providers.router, dependencies=_auth)
app.include_router(model_registry.router, dependencies=_auth)
app.include_router(agents.router, dependencies=_auth)
app.include_router(chat.router, dependencies=_auth)
app.include_router(sessions.router, dependencies=_auth)
app.include_router(memory_routes.router, dependencies=_auth)
app.include_router(rag.router, dependencies=_auth)
app.include_router(approvals.router, dependencies=_auth)
app.include_router(batch_routes.router)  # 자체 보호(admin) — user_admin과 동일 패턴
app.include_router(allowed_hosts.router)  # 자체 보호(admin) — SSRF allowlist 관리(스펙 064)
app.include_router(mock_remote.router)
# 로컬(ui) 에이전트 A2A 노출(스펙 061) — mock_remote처럼 전역 _auth 미적용(self-fetch 호환).
# 카드는 공개, JSON-RPC 호출만 라우트 단위 current_principal 인증. 게이트=ui+exposed.a2a.
app.include_router(a2a_server.router)
# self-host 실 mock MCP 서버(스펙 054) — streamable-HTTP. mock_remote와 같이 인증 비적용(dev 스탠드인).
app.mount("/_remote/mcp", mock_mcp.mcp_app)

# 인증·권한 라우터 (스펙 031). register_router는 마운트하지 않는다(공개 등록 금지) — 유저 생성은
# user_admin(/admin/users, admin 보호)으로만.
app.include_router(
    users.fastapi_users.get_auth_router(users.auth_backend), prefix="/auth", tags=["auth"]
)
app.include_router(
    users.fastapi_users.get_users_router(UserRead, UserUpdate), prefix="/users", tags=["users"]
)
app.include_router(user_admin.router)


def run():
    import uvicorn

    # 기본은 loopback(외부 비노출). Tailscale 노출은 API_HOST로만 켠다.
    # 예: API_HOST=100.72.45.58 → 이 맥 + tailnet에서만 닿고 그 외 인터페이스는 안 열림.
    host = os.environ.get("API_HOST", "127.0.0.1")
    port = int(os.environ.get("API_PORT", "8000"))
    uvicorn.run("api.main:app", host=host, port=port)

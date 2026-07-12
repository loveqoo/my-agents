"""FastAPI 앱 — 페르소나 등록 + chat 노출.

지배 스펙: docs/spec/002-persona-registry-and-chat.md
"""

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import (
    a2a_server,
    agents,
    allowed_hosts,
    app_settings,
    approvals,
    batch_routes,
    blocks,
    chat,
    checkpointer,
    eval_routes,
    memory_routes,
    mock_mcp,
    mock_remote,
    model_registry,
    net_guard,
    node_templates,
    providers,
    rag,
    served_mcp,
    sessions,
    user_admin,
    users,
)
from .auth import current_principal
from .authz import init_authz
from .db import init_db
from .schemas import UserRead, UserUpdate


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    await init_db()
    await net_guard.refresh_allowed_hosts(force=True)  # SSRF allowlist 스냅샷 warm(스펙 064)
    await init_authz()  # casbin_rule + enforcer + 기본 정책(멱등)
    await users.seed_admin()  # superuser 시드(env, fail-closed)
    await node_templates.sync_code_nodes()  # 코드 노드 카탈로그 동기화(스펙 317 — 발행=코드 배포 반영)
    await checkpointer.init_checkpointer()  # HIL durable 체크포인터(스펙 041, graceful)
    # 좀비 평가 런 정리(스펙 137, codex #1) — create_task는 재시작을 못 넘기므로 부팅 시 running은
    # 전부 죽은 실행 → error 박제("영원한 실행 중" 잔류 방지).
    swept = await eval_routes.sweep_zombie_runs()
    if swept:
        logging.getLogger("api.eval").info("죽은 평가 런 %d건을 error로 정리(재시작 잔류)", swept)
    swept_ds = await eval_routes.sweep_zombie_datasets()
    if swept_ds:
        logging.getLogger("api.eval").info("죽은 골든 생성 %d건을 중단 박제(재시작 잔류)", swept_ds)
    # self-host mock MCP(스펙 054)의 세션 매니저 lifespan을 직접 연다 — 마운트된 서브앱 lifespan은
    # Starlette가 자동 호출하지 않으므로 부모가 진입해야 streamable-HTTP 핸들러가 동작한다.
    # 서빙 커스텀 MCP(스펙 156)도 동일 — 각 FastMCP의 session_manager를 스택으로 함께 연다.
    from contextlib import AsyncExitStack

    async with AsyncExitStack() as stack:
        await stack.enter_async_context(mock_mcp.mcp.session_manager.run())
        for _mcp in served_mcp.SERVED_MCPS.values():
            await stack.enter_async_context(_mcp.session_manager.run())
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
app.include_router(node_templates.router, dependencies=_auth)  # 노드 라이브러리(스펙 316)
app.include_router(agents.router, dependencies=_auth)
app.include_router(
    agents.meta_router, dependencies=_auth
)  # /agent-impls(스펙 106) — uuid 경로 충돌 회피
app.include_router(chat.router, dependencies=_auth)
app.include_router(sessions.router, dependencies=_auth)
app.include_router(memory_routes.router, dependencies=_auth)
app.include_router(rag.router, dependencies=_auth)
app.include_router(approvals.router, dependencies=_auth)
app.include_router(batch_routes.router)  # 자체 보호(admin) — user_admin과 동일 패턴
app.include_router(eval_routes.router)  # 자체 보호(admin) — 평가 하네스 제품화(스펙 137)
app.include_router(allowed_hosts.router)  # 자체 보호(admin) — SSRF allowlist 관리(스펙 064)
app.include_router(
    app_settings.router, dependencies=_auth
)  # 앱 설정(스펙 153) — 변이는 자체 특권 게이트
app.include_router(mock_remote.router)
# 로컬(ui) 에이전트 A2A 노출(스펙 061) — mock_remote처럼 전역 _auth 미적용(self-fetch 호환).
# 카드는 공개, JSON-RPC 호출만 라우트 단위 current_principal 인증. 게이트=ui+exposed.a2a.
app.include_router(a2a_server.router)
# self-host 실 mock MCP 서버(스펙 054) — streamable-HTTP. mock_remote와 같이 인증 비적용(dev 스탠드인).
app.mount("/_remote/mcp", mock_mcp.mcp_app)

# 내부(커스텀) MCP 외부 서빙(스펙 156, 실사용 #4) — 우리가 코드로 정의한 도구를 진짜 MCP 엔드포인트로
# 노출해 외부 MCP 클라이언트가 붙게 한다(에이전트 A2A 서빙의 MCP판). 각 이름을 `/_served/mcp/{name}`에
# 공개 게이트(published+source=custom, 요청마다 DB 확인)와 함께 마운트. external은 서빙 불가(152 봉인).
for _name, _served in served_mcp.SERVED_MCPS.items():
    app.mount(
        f"{served_mcp.SERVED_MCP_PREFIX}/{_name}",
        served_mcp.guarded_app(_name, _served.streamable_http_app()),
    )

# 인증·권한 라우터 (스펙 031). register_router는 마운트하지 않는다(공개 등록 금지) — 유저 생성은
# user_admin(/admin/users, admin 보호)으로만.
app.include_router(
    users.fastapi_users.get_auth_router(users.auth_backend), prefix="/auth", tags=["auth"]
)
app.include_router(
    users.fastapi_users.get_users_router(UserRead, UserUpdate), prefix="/users", tags=["users"]
)
app.include_router(user_admin.router)


def run() -> None:
    from pathlib import Path

    import uvicorn

    # 기본은 loopback(외부 비노출). Tailscale 노출은 API_HOST로만 켠다.
    # 예: API_HOST=100.72.45.58 → 이 맥 + tailnet에서만 닿고 그 외 인터페이스는 안 열림.
    host = os.environ.get("API_HOST", "127.0.0.1")
    port = int(os.environ.get("API_PORT", "8000"))
    # 개발 편의: 코드 변경 자동 반영. reload_dirs에 **api·agent 소스를 둘 다** 명시한다 —
    # uvicorn 기본 watch는 CWD 하나라 packages/agent 수정이 반영 안 돼, 노드/flow 코드를 고친 뒤
    # 수동 재기동이 필요했다(스펙 302 회귀=produce_node config가 그 함정에 오래 숨음). 두 워크스페이스
    # 소스를 watch해 agent flow도 hot-reload. 배포/프로덕션 실행은 uvicorn을 직접(reload 없이) 띄운다.
    src = Path(__file__).resolve()
    reload_dirs = [str(src.parents[1]), str(src.parents[4] / "packages" / "agent" / "src")]
    uvicorn.run("api.main:app", host=host, port=port, reload=True, reload_dirs=reload_dirs)

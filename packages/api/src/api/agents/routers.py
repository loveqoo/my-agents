"""agents 패키지 공유 라우터 — main.py는 분할 전과 동일하게 agents.router/meta_router만 include.

각 라우트 모듈이 이 라우터를 import해 데코레이트하고, `__init__`이 라우트 모듈 전부를 import해
등록 부수효과를 완성한다(스펙 291 분할 — 라우트 24개 무손실, 단일 공유 router 전략).
"""

from fastapi import APIRouter

router = APIRouter(prefix="/agents", tags=["agents"])

# 능력 브로커 UI(스펙 106)용 메타 라우터 — `/agents/{id}`(uuid) 경로와 충돌 않게 top-level에 둔다.
meta_router = APIRouter(tags=["agents"])

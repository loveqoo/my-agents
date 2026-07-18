"""RAG 라우터 조립점 — shared.py에서 분할(스펙 398 P1).

라우터는 공용 유틸이 아니라 패키지 조립점(codex 398) — 단일 APIRouter 정의만 둔다.
도메인 모듈(collections·documents·reindex·search)이 여기서 import해 데코레이터로 라우트 등록.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/collections", tags=["rag"])

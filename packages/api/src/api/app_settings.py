"""앱 설정 라우터 (스펙 153) — 소수의 전역 설정을 관리자 UI에서 무재시작 변경.

키는 닫힌 집합(_KEYS) — 미지 키 400(쓰레기 키 적치 방지), 값 검증은 키별. env는 배포 정체성
(A2A_SELF_BASE_URL 등), 여긴 운영 중 바꾸는 값(A2A org 등). 변이는 특권 게이트(스펙 150 동형).
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from .db import SessionLocal, get_session
from .model_registry import require_model_manage
from .models import AppSetting, User

router = APIRouter(prefix="/admin/settings", tags=["settings"])

_manage = Depends(require_model_manage)


def _check_short_str(v: Any, label: str, maxlen: int = 80) -> str:
    if not isinstance(v, str) or not v.strip():
        raise HTTPException(
            status_code=400, detail=f"{label}은(는) 비어있지 않은 문자열이어야 합니다."
        )
    if len(v.strip()) > maxlen:
        raise HTTPException(status_code=400, detail=f"{label}은(는) 최대 {maxlen}자입니다.")
    return v.strip()


# 닫힌 키 집합 — key: (기본값, 검증기). 새 설정은 여기에 추가(스펙 153).
def _check_gate_runs(v: Any) -> int:
    """평가 게이트 최소 성공 회수(스펙 372) — 0=게이트 꺼짐, 음수/비정수 400."""
    if isinstance(v, bool) or not isinstance(v, int) or v < 0:
        raise HTTPException(status_code=400, detail="최소 평가 회수는 0 이상의 정수여야 합니다.")
    return v


def _check_gate_score(v: Any) -> float:
    """평가 게이트 최소 평균 점수(스펙 372) — 0~1, 0=게이트 꺼짐."""
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not (0 <= float(v) <= 1):
        raise HTTPException(status_code=400, detail="최소 평균 점수는 0~1 사이여야 합니다.")
    return float(v)


_KEYS: dict[str, tuple[Any, Any]] = {
    "a2a_org_name": ("my-agents", lambda v: _check_short_str(v, "organization 이름")),
    # 평가 게이트(스펙 372=367-E) — 둘 다 0이면 꺼짐(무회귀 기본). 켜면 스크래치 첫 오픈이
    # "성공 평가 회수 ≥ min_runs AND 평균 점수 ≥ min_score"를 통과해야 한다(롤백은 면제).
    "eval_gate_min_runs": (0, _check_gate_runs),
    "eval_gate_min_score": (0.0, _check_gate_score),
}


class SettingIn(BaseModel):
    value: Any


async def get_setting_stored(key: str) -> tuple[bool, Any]:
    """(저장됨 여부, 값) 조회 — 저장/미저장을 구분(codex 153: 값 비교로 미설정을 추정하면 관리자가
    기본 문자열로 의도 저장한 경우와 구분 불가 = 의미 역전). 저장값은 **읽기 시 재검증** — DB 오염
    (수동 수정·마이그레이션 실수)으로 비문자 타입이 공개 카드에 새지 않게 실패는 미저장으로 접는다.
    미지 키는 KeyError(호출측 버그)."""
    default, validator = _KEYS[key]
    async with SessionLocal() as s:
        row = await s.get(AppSetting, key)
    if row is None or not isinstance(row.value, dict) or "v" not in row.value:
        return False, default
    try:
        return True, validator(row.value["v"])
    except HTTPException:
        return False, default  # 오염 값 fail-safe


async def get_setting(key: str) -> Any:
    """설정값 조회(서빙 경로용, 자체 세션) — 미저장 시 기본값."""
    _found, value = await get_setting_stored(key)
    return value


@router.get("")
async def list_settings(
    session: AsyncSession = Depends(get_session), _p: User | str = _manage
) -> dict[str, Any]:
    """전체 설정(기본값 포함) — UI 폼 로드용."""
    out: dict[str, Any] = {}
    for key, (default, _v) in _KEYS.items():
        row = await session.get(AppSetting, key)
        out[key] = (
            row.value.get("v", default)
            if row is not None and isinstance(row.value, dict)
            else default
        )
    return out


@router.put("/{key}")
async def put_setting(
    key: str,
    body: SettingIn,
    session: AsyncSession = Depends(get_session),
    _p: User | str = _manage,
) -> dict[str, Any]:
    if key not in _KEYS:
        raise HTTPException(status_code=400, detail=f"알 수 없는 설정 키입니다: {key}")
    _, validator = _KEYS[key]
    value = validator(body.value)
    row = await session.get(AppSetting, key)
    if row is None:
        row = AppSetting(key=key, value={"v": value})
        session.add(row)
    else:
        row.value = {"v": value}  # JSONB 재대입(변이 미추적)
    await session.commit()
    return {key: value}

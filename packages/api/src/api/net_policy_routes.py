"""외부호출 정책 관측 라우트(스펙 430) — "어디에 뭐가 걸려 있나"를 API 한 번으로.

read-only: 정책 대장(net_policy.POLICIES)과 서킷브레이커 현재 상태(snapshot)를 그대로 노출.
kpas 비교 #5(지표 대시보드)는 회사 층 — 우리는 정책·회로 가시화까지(과투자 금지, 발단은 스펙 430).
편집 표면 없음(값 변경=코드 한 줄이 의도된 통로 — 승인 수치가 대장에 박제).
"""

from fastapi import APIRouter, Depends

from agent import net_policy

from . import authz

router = APIRouter(prefix="/admin/net-policies", tags=["net-policies"])

# 읽기 전용이지만 admin 표면(운영 정보) — batch/allowed-hosts와 같은 보호 결.
_view = Depends(authz.require("batch", "manage"))


@router.get("", dependencies=[_view])
async def list_net_policies() -> dict:
    """정책 대장 + 회로 상태. breaker 상태는 프로세스-로컬(멀티 인스턴스는 k8s 백로그와 합류)."""
    return {
        "policies": [
            {
                "key": p.key,
                "timeoutS": p.timeout_s,
                "retries": p.retries,
                "breaker": p.breaker,
                "note": p.note,
            }
            for p in net_policy.POLICIES
        ],
        "breakerThreshold": net_policy.BREAKER_THRESHOLD,
        "breakerCooldownS": net_policy.BREAKER_COOLDOWN_S,
        "circuits": net_policy.breaker_snapshot(),
    }

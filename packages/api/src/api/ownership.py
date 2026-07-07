"""자원 소유권 헬퍼 — **단일 출처**(스펙 112, RBAC 체크리스트 §3 drift 0).

공유 카탈로그(Agent·McpServer·Collection)에 owner_id를 붙여 브로커 능력 인가를 kind 단위에서
**소유자 단위**로 좁힌다. 규칙(learning 069·070):
- **생성 시 1회 스탬프**(`owner_of`), **소유권 이전 기본 금지**(`next_owner` — 기존 보존).
- **NULL-owned = admin/superuser 전용(fail-closed)** — 레거시 행이 일반 유저에게 열리면 안 된다(070).
- 읽기/발견은 **owner 스코프를 SELECT WHERE에 밀어** 거부행을 로드조차 안 함(각 라우터가 `_own_scope`
  로 직접 조건화 — 존재 비노출, 체크리스트 §2a).
"""
from __future__ import annotations

from agent.runtime import is_third_party


def owner_of(principal) -> str | None:
    """생성 주체의 owner_id(auth User UUID str). 머신 토큰(str principal)·익명 → None(=admin 전용)."""
    if principal is None or isinstance(principal, str):
        return None
    pid = getattr(principal, "id", None)
    return str(pid) if pid is not None else None


def next_owner(current: str | None, incoming: str | None) -> str | None:
    """소유권 무덮어쓰기 불변식(스펙 068, learning 069) — **단일 출처**. 소유권은 *생성 시 1회*만
    부여하고, 기존 non-null 소유자를 *다른* 유저로 덮어쓰지 않는다(소유권 탈취 → 탈취 후 전사 누출 방지).
    chat resume·수정·버전·활성화가 이 규칙을 공유한다(스펙 182서 chat 사본 _next_owner를 여기로 통합).
    - incoming 빈 값(머신/빈 userId) → current 보존(빈칸 대화가 소유자를 지우지 않음).
    - current 미소유(None) 또는 동일 유저 → incoming 부여(생성 시 1회).
    - 그 외(다른 유저) → current 유지(이전 거부). current==""(빈 문자열)도 기존 소유자로 보존(fail-closed —
      미소유로 취급해 새 소유자를 얹지 않는다)."""
    if not incoming:
        return current
    if current is None or current == incoming:
        return incoming
    return current


def may_use(owner_id: str | None, user_id: str | None, is_privileged: bool) -> bool:
    """이 주체가 이 자원을 브로커로 쓸 수 있나. 특권(admin/superuser)=전부, 아니면 **소유자 본인만**
    (owner_id == user_id). NULL-owned는 특권만(fail-closed). 판정 단일 술어."""
    if is_privileged:
        return True
    return bool(user_id) and owner_id == user_id


def is_privileged(principal, enforcer=None) -> bool:
    """관리(수정/삭제) 특권 — 소유자 아니어도 카탈로그를 만질 수 있나(스펙 112).
    - **머신 토큰(str principal) = 특권**: 신뢰 서비스/CI 자격(오늘 전권), 위협 모델 밖 → 무회귀.
      (브로커 *오케스트레이션*은 정반대로 머신 토큰 deny — 그건 유저 세션 대상이라 별개 맥락.)
    - superuser = 특권(부트스트랩 안전판). admin 역할 = casbin `(*,*)` → enforce(id,'*','*') True.
    - 그 외(member) = 비특권 → 자기 소유 자원만.

    **enforcer는 지연 로드**(머신·superuser는 casbin 불요라 먼저 단락). 미초기화(ASGI 테스트가 lifespan을
    안 돌린 경우 등)면 admin 역할 확인 불가 → **비특권으로 안전측**(소유자 판정으로 폴백, fail-closed)."""
    if principal is None:
        return False
    if isinstance(principal, str):
        return True  # 머신 토큰 = 신뢰 서비스 자격(관리 전권; 위협은 로그인 member)
    if getattr(principal, "is_superuser", False):
        return True
    pid = getattr(principal, "id", None)
    if pid is None:
        return False
    if enforcer is None:
        from . import authz
        try:
            enforcer = authz.get_enforcer()
        except RuntimeError:
            return False  # authz 미초기화 → admin 역할 확인 불가 → 비특권(안전측)
    return bool(enforcer.enforce(str(pid), "*", "*"))  # admin 역할 = (*,*)


def may_manage(row_owner: str | None, principal, enforcer=None) -> bool:
    """관리 가능 여부 **불리언 술어**(스펙 114) — assert_may_manage의 형제(단일 술어, drift 0).
    특권(머신·superuser·admin 역할) or 소유자 본인. UI가 can_manage를 이걸로 파생(프론트 재계산 금지)."""
    if is_privileged(principal, enforcer):
        return True
    oid = owner_of(principal)
    return bool(oid) and row_owner == oid


def assert_may_manage(resource, principal, enforcer=None, not_found_detail: str = "not found") -> None:
    """카탈로그 항목 수정/삭제 게이트(스펙 112) — 특권 or 소유자 본인만. 아니면 **404-fold**(존재
    비노출, 068 — 남의/NULL-owned 항목을 403으로 구분해주지 않는다). NULL-owned는 특권만(fail-closed).
    호출자는 resource를 이미 로드한 상태(존재 404는 먼저 처리). 단일 게이트 헬퍼(drift 0).
    enforcer 미전달이면 is_privileged가 지연 로드(머신·superuser는 casbin 미접촉).

    **`not_found_detail`은 그 라우트의 존재-404 detail과 반드시 일치시킨다**(codex 112 P1): 비소유 거부가
    "not found"인데 미존재가 "agent not found"면 body 차이로 존재가 새어(068 위반). 같은 status+같은 body라야
    404-fold가 성립한다."""
    from fastapi import HTTPException

    if may_manage(getattr(resource, "owner_id", None), principal, enforcer):
        return
    raise HTTPException(status_code=404, detail=not_found_detail)


# (스펙 211) agent_may_wire(스펙 113 배선 인가 술어)는 "사용=공용" 정책 전환으로 제거.
# MCP/RAG 등 카탈로그 자원의 **사용(배선)**은 등록만 되면 허용, **관리(수정/삭제)**는
# assert_may_manage(소유자/특권)가 계속 게이트한다. 커스텀 MCP의 외부 노출은 published가
# 서빙 게이트(served_mcp._is_served)로만 소비된다.
def may_use_agent(agent, principal) -> bool:
    """에이전트 **사용**(채팅·목록 노출) 게이트 — 스펙 147 트리:
    public(owner 없음)=모두, private(owner 있음)=소유자·특권만, external=항상(가져다 쓰는 것).
    관리(may_manage)와 축이 다르다 — public은 모두 사용하지만 관리는 특권만."""
    if is_third_party(getattr(agent, "source", "ui")):
        return True  # 가져다 쓰는 것(external) — 사용 항상 허용(스펙 147)
    owner = getattr(agent, "owner_id", None)
    if owner is None:
        return True  # public
    if is_privileged(principal):
        return True
    return owner_of(principal) == owner

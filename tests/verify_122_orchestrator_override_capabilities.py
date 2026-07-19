"""verify_122 — 조율형 플레이그라운드 오버라이드에 capabilities 반영 (스펙 122, 버그2).

버그: 조율형 에이전트의 MCP는 config.capabilities로 담기는데, 오버라이드 병합 허용목록에 capabilities가
없어 세션 오버라이드가 무시됐다(패널 누락 + 백엔드 미반영). 스펙 122가 허용목록에 capabilities를 추가.

검증(실 DB 통합, 자기 픽스처):
  - B1 조율형 + overrides={"capabilities":[...]} → ctx.capabilities가 오버라이드 반영.
  - B2 overrides에 capabilities 키 없음 → 저장분 그대로(무회귀).
  - B3 overrides=None → 저장분 그대로.
  - B4 빈 리스트 오버라이드 → 빈 리스트 반영(위임 대상 전부 해제).
  - B5 confused-deputy 방어 확인: 브로커가 build_broker(principal, capabilities)로 **호출자 RBAC** 게이트
    (_permitted = allowlist ∩ RBAC(principal))를 하는 구조인지 소스 단언(주입분도 호출자 스코프).

전제: DB 마이그레이션 적용됨(SessionLocal). API 서버 실행 불요(_load_context 직접 호출).
실행: uv run python tests/verify_122_orchestrator_override_capabilities.py
"""

import asyncio
import inspect
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))

from api import broker as broker_mod  # noqa: E402
from api import chat  # noqa: E402
from api.db import SessionLocal  # noqa: E402
from api.models import Agent  # noqa: E402

_fails: list[str] = []
_TAG = "_verify122"
passed = 0


def check(cond: bool, msg: str) -> None:
    global passed
    print(("  ok  " if cond else " FAIL ") + msg)
    if cond:
        passed += 1
    else:
        _fails.append(msg)


async def _cleanup(s) -> None:
    from sqlalchemy import select

    for a in (await s.execute(select(Agent).where(Agent.name.like(f"{_TAG}%")))).scalars():
        await s.delete(a)
    await s.commit()


async def integration() -> None:
    print("② 실 DB 통합 — 조율형 capabilities 오버라이드")
    async with SessionLocal() as s:
        await _cleanup(s)
        # 조율형 에이전트: 저장 config.capabilities = ["mcp:srv_a"].
        agent = Agent(
            agent_id=f"agt_{_TAG}",
            name=f"{_TAG}_orchestrator",
            source="ui",
            # model 명시: 이 테스트의 축은 capabilities 병합 — 모델 축은 B6(스펙 401 회귀 핀)이
            # 모델 미지정 에이전트로 별도 검증한다(None==None 오폭은 스펙 401서 수리됨).
            config={"impl": "orchestrate", "model": "mock-llm", "capabilities": ["mcp:srv_a"]},
            active_version="v1",
        )
        s.add(agent)
        await s.commit()
        await s.refresh(agent)
        aid = agent.id

    # own=None(admin/내부) — confused-deputy 게이트는 verify_113 담당, 여기선 병합만 본다.
    # B1: capabilities 오버라이드 반영.
    ctx = await chat._load_context(
        aid, None, {"capabilities": ["mcp:srv_a", "mcp:srv_b"]}, own=None
    )
    check(
        ctx.capabilities == ["mcp:srv_a", "mcp:srv_b"],
        f"B1 capabilities 오버라이드 반영(got {ctx.capabilities!r})",
    )

    # B2: capabilities 키 없는 오버라이드 → 저장분 유지.
    ctx = await chat._load_context(aid, None, {"model": "mock-llm"}, own=None)
    check(
        ctx.capabilities == ["mcp:srv_a"],
        f"B2 capabilities 미전송 시 저장분 유지(got {ctx.capabilities!r})",
    )

    # B3: overrides=None → 저장분.
    ctx = await chat._load_context(aid, None, None, own=None)
    check(
        ctx.capabilities == ["mcp:srv_a"],
        f"B3 overrides=None 저장분 유지(got {ctx.capabilities!r})",
    )

    # B4: 빈 리스트 → 위임 대상 전부 해제.
    ctx = await chat._load_context(aid, None, {"capabilities": []}, own=None)
    check(ctx.capabilities == [], f"B4 빈 리스트 오버라이드 반영(got {ctx.capabilities!r})")

    # B6(스펙 401 회귀 핀): 오버라이드 모델 거절 게이트는 **실명을 댄** 오버라이드에만.
    # 모델 미지정 에이전트 + model 없는/null 오버라이드 = 기본 폴백, 명시 미등록 이름 = 400(290 유지).
    from fastapi import HTTPException as _HTTPExc

    from sqlalchemy import select

    from api.models import ModelConfig as _MC

    # 폴백 기대값은 하드코딩(mock-chat) 금지 — 라이브 DB에선 기본 chat이 실모델일 수 있다.
    async with SessionLocal() as s:
        _default_mid = (
            await s.execute(
                select(_MC.model_id).where(_MC.kind == "chat", _MC.is_default.is_(True))
            )
        ).scalar_one()

    async with SessionLocal() as s:
        bare = Agent(
            agent_id=f"agt_{_TAG}b6",
            name=f"{_TAG}_bare",
            source="ui",
            config={},  # model 미지정 — None==None 오폭의 트리거였던 형태
            active_version="v1",
        )
        s.add(bare)
        await s.commit()
        await s.refresh(bare)
        bare_id = bare.id
    try:
        # model_cfg는 연결 cfg(base_url/model_id/params — name 없음): 기본 mock 모델의 model_id로 단언.
        ctx = await chat._load_context(bare_id, None, {"capabilities": []}, own=None)
        check(
            (ctx.model_cfg or {}).get("model_id") == _default_mid,
            f"B6a 모델 미지정+model 키 없는 오버라이드 → 400 없이 기본 해석(got {(ctx.model_cfg or {}).get('model_id')!r})",
        )
        ctx = await chat._load_context(bare_id, None, {"model": None}, own=None)
        check(
            (ctx.model_cfg or {}).get("model_id") == _default_mid,
            f"B6b overrides={{model: None}} → 동일 폴백(got {(ctx.model_cfg or {}).get('model_id')!r})",
        )
        # B6d 경계 핀(codex 401 P2 — 선택된 시맨틱의 문서화): 빈 문자열 오버라이드는 "명시 이름"이
        # 아니라 미선언으로 접는다(저장 config의 빈값과 동형 — 스펙 401 승인 축). 400이 아님을 핀.
        ctx = await chat._load_context(bare_id, None, {"model": ""}, own=None)
        check(
            (ctx.model_cfg or {}).get("model_id") == _default_mid,
            f"B6d overrides={{model: \"\"}} → 미선언 취급·기본 폴백(got {(ctx.model_cfg or {}).get('model_id')!r})",
        )
        try:
            await chat._load_context(bare_id, None, {"model": "없는모델401"}, own=None)
            check(False, "B6c 명시 미등록 이름이 통과함(290 회귀!)")
        except _HTTPExc as e:
            check(
                e.status_code == 400 and "없는모델401" in str(e.detail),
                f"B6c 명시 미등록 이름 → 400 유지(스펙 290) (got {e.status_code}, {e.detail!r})",
            )
    finally:
        async with SessionLocal() as s:
            row = await s.get(Agent, bare_id)
            if row:
                await s.delete(row)
                await s.commit()

    async with SessionLocal() as s:
        await _cleanup(s)


def unit_broker_caller_scoped() -> None:
    """B5 — 브로커가 principal(호출자) RBAC로 게이트하는지 소스 단언. build_broker(principal, caps)의
    시그니처가 principal을 첫 인자로 받아야(호출자 스코프) 주입분도 caller RBAC 교집합에 걸린다."""
    print("① 단위 — 브로커 호출자 스코프(confused-deputy 방어 구조)")
    sig = inspect.signature(broker_mod.build_broker)
    params = list(sig.parameters)
    check(
        len(params) >= 2 and params[0] in ("principal", "user", "caller"),
        f"build_broker 첫 인자=principal(호출자 스코프, got {params[:2]})",
    )
    # 오버라이드 허용목록에 capabilities 포함(스펙 122 핵심 변경) — 스펙 394 분할로 allowlist가
    # chat_context_loader._OVERRIDE_ALLOWED 상수가 됨(소스 문자열 검사보다 강한 값 단언).
    from api.chat_context_loader import _OVERRIDE_ALLOWED

    check(
        "capabilities" in _OVERRIDE_ALLOWED,
        "오버라이드 허용목록(_OVERRIDE_ALLOWED)에 capabilities 포함(스펙 122)",
    )


async def main() -> None:
    unit_broker_caller_scoped()
    await integration()
    print(f"\n{passed} passed, {len(_fails)} failed")
    if _fails:
        for f in _fails:
            print("  ✗", f)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

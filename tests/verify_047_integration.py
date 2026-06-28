"""스펙 047 통합 검증 — 실 DB + 실 HTTP(자기 픽스처, learning 045).

데모 시드에 결합하지 않고 *자체* provider/model/agent를 만들어 검증한 뒤 정리한다. HTTP 대상은
실행 중 API의 내장 목 `/_remote/v1/models`(불변·안정) — available-models 전체 경로를 실제로 탄다.
provider.kind/description·model.meta 영속, available-models 토글, 삭제 가드(409) 두 종을 본다.

검증:
  I1. Provider kind/description 영속 — 새 컬럼이 DB 왕복에서 보존.
  I2. available-models(등록 전) — 목이 reachable, mock-chat가 registered=False.
  I3. ModelConfig.meta 영속 — 등록 시 meta JSONB 왕복.
  I4. available-models(등록 후) — mock-chat가 registered=True + registered_name/id.
  I5. 모델 삭제 가드 — 에이전트가 *이름*으로 참조 중이면 409(learning 042).
  I6. 참조 해제 후 모델 삭제 성공.
  I7. provider 삭제 RESTRICT — 매달린 모델 있으면 409, 제거 후 성공.

전제: API 서버가 127.0.0.1:8000에서 실행 중(`/_remote/v1/models` 응답). DB 마이그레이션 적용됨.
실행: uv run python tests/verify_047_integration.py
"""

import asyncio
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))

from fastapi import HTTPException  # noqa: E402

from api import crypto, model_registry, providers  # noqa: E402
from api.db import SessionLocal  # noqa: E402
from api.models import Agent, AgentVersion, ModelConfig, Provider  # noqa: E402
from api.schemas import ModelIn  # noqa: E402

_fails: list[str] = []
_TAG = "_verify047"  # 픽스처 식별 접두사(정리용)


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


async def main() -> None:
    async with SessionLocal() as s:
        # ── 픽스처 정리(이전 실패 잔재) ──────────────────────────────────────
        await _cleanup(s)

        # ── I1. Provider kind/description 영속 ──────────────────────────────
        prov = Provider(
            name=f"{_TAG}_prov", protocol="openai-compatible",
            base_url="http://127.0.0.1:8000/_remote/v1",
            api_key=crypto.encrypt("sk-noauth"),
            kind="mock", description="047 통합 픽스처",
        )
        s.add(prov)
        await s.commit()
        await s.refresh(prov)
        prov_id = prov.id  # 이후 commit/rollback로 ORM 객체가 만료되므로 PK는 평문으로 보관
        got = await s.get(Provider, prov_id)
        check(got.kind == "mock" and got.description == "047 통합 픽스처",
              "I1 Provider kind/description DB 왕복 보존")

        # ── I2. available-models(등록 전) ──────────────────────────────────
        out = await providers.available_models(prov_id, s)
        check(out.reachable is True, f"I2 목 reachable (detail={out.detail!r})")
        mc = next((m for m in out.models if m.model_id == "mock-chat"), None)
        check(mc is not None and mc.registered is False,
              "I2 mock-chat 노출 + registered=False(미등록)")

        # ── I3. ModelConfig.meta 영속 ──────────────────────────────────────
        body = ModelIn(
            name=f"{_TAG}_model", provider_id=prov_id, model_id="mock-chat",
            kind="chat", is_default=False, params={}, meta={"catalog_id": "x", "n": 7},
        )
        created = await model_registry.create_model(body, s)
        check(created.meta.get("n") == 7, "I3 model.meta JSONB 등록 왕복 보존")
        model_pk = created.id

        # ── I4. available-models(등록 후) ──────────────────────────────────
        out2 = await providers.available_models(prov_id, s)
        mc2 = next((m for m in out2.models if m.model_id == "mock-chat"), None)
        check(mc2 is not None and mc2.registered is True
              and mc2.registered_name == f"{_TAG}_model" and mc2.registered_id == model_pk,
              "I4 등록 후 mock-chat registered=True + name/id 채워짐(토글 OFF 가능)")

        # ── I5. 삭제 가드 — 에이전트가 이름으로 참조 ──────────────────────────
        agent = Agent(
            agent_id=f"{_TAG}_agt", name=f"{_TAG} agent",
            model=f"{_TAG}_model", config={"model": f"{_TAG}_model"},
        )
        s.add(agent)
        await s.commit()
        blocked = False
        try:
            await model_registry.delete_model(model_pk, s)
        except HTTPException as e:
            blocked = e.status_code == 409
            await s.rollback()
        check(blocked, "I5 에이전트가 이름 참조 중 → 모델 삭제 409 차단(learning 042)")

        # ── I5b. 아카이브 버전 스냅샷만 참조해도 차단(적대 리뷰 047) ──────────
        # live 참조(I5의 agent)를 지운 뒤, *버전 config*만 모델을 가리키는 상황을
        # 만든다 → 롤백 시 고아가 되므로 삭제는 여전히 409여야 한다.
        await s.delete(agent)
        await s.commit()
        agent2 = Agent(
            agent_id=f"{_TAG}_agt2", name=f"{_TAG} agent2",
            model="some-other-model", config={"model": "some-other-model"},
        )
        s.add(agent2)
        await s.commit()
        await s.refresh(agent2)
        s.add(AgentVersion(
            agent_pk=agent2.id, version="v1", status="archived",
            config={"model": f"{_TAG}_model"},
        ))
        await s.commit()
        ver_blocked = False
        try:
            await model_registry.delete_model(model_pk, s)
        except HTTPException as e:
            ver_blocked = e.status_code == 409
            await s.rollback()
        check(ver_blocked, "I5b 버전 스냅샷이 참조 중 → 모델 삭제 409 차단(적대 리뷰 047)")

        # ── I6. 참조 해제 후 삭제 성공 ──────────────────────────────────────
        await s.delete(agent2)  # CASCADE로 버전 스냅샷도 제거 → 참조 완전 해제
        await s.commit()
        await model_registry.delete_model(model_pk, s)
        check(await s.get(ModelConfig, model_pk) is None, "I6 참조 해제 후 모델 삭제 성공")

        # ── I7. provider 삭제 RESTRICT ─────────────────────────────────────
        m2 = ModelConfig(name=f"{_TAG}_m2", provider_id=prov_id, model_id="mock-chat",
                         kind="chat", is_default=False, params={}, meta={})
        s.add(m2)
        await s.commit()
        await s.refresh(m2)
        m2_id = m2.id
        prov_blocked = False
        try:
            await providers.delete_provider(prov_id, s)
        except HTTPException as e:
            prov_blocked = e.status_code == 409
            await s.rollback()
        check(prov_blocked, "I7 매달린 모델 있으면 provider 삭제 409")
        await s.delete(await s.get(ModelConfig, m2_id))
        await s.commit()
        await providers.delete_provider(prov_id, s)
        check(await s.get(Provider, prov_id) is None, "I7 모델 제거 후 provider 삭제 성공")

        await _cleanup(s)

    print()
    if _fails:
        print(f"FAILED {len(_fails)}건:")
        for f in _fails:
            print("  - " + f)
        sys.exit(1)
    print("ALL PASS")


async def _cleanup(s) -> None:
    """접두사 픽스처 전부 제거(에이전트→모델→프로바이더 순, FK 안전)."""
    from sqlalchemy import select

    for a in (await s.execute(select(Agent).where(Agent.agent_id.like(f"{_TAG}%")))).scalars():
        await s.delete(a)
    for m in (await s.execute(select(ModelConfig).where(ModelConfig.name.like(f"{_TAG}%")))).scalars():
        await s.delete(m)
    await s.flush()
    for p in (await s.execute(select(Provider).where(Provider.name.like(f"{_TAG}%")))).scalars():
        await s.delete(p)
    await s.commit()


if __name__ == "__main__":
    asyncio.run(main())

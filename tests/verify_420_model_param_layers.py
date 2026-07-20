"""verify_420 — 모델 파라미터 캐스케이드 층 정책(스펙 420) 계약 핀.

FE(modelParamLayerApplies)가 숨긴 층 == BE(layer_applies)가 안 적용을 못박는다 — FE/BE 드리프트 봉인.

  P  정책 단위: layer_applies 매트릭스(model-default 항상·node=pipeline만·agent/session=non-pipeline만).
  W  쓰기 경계: AgentConfig가 노드형 modelParams를 비운다(illegal state 표현 불가), 비노드형은 보존.
  R  해석 관문(실 DB): 노드형에 agent·session 층 modelParams가 노드 model_cfg에 **안 실림**(명시 모델
     노드·모델없는 폴백 노드 둘 다). 비노드형은 agent 층이 실림(무회귀).

실행: uv run python tests/_throwaway_db.py tests/verify_420_model_param_layers.py
"""

import asyncio
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "packages" / "api" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "agent" / "src"))

import uuid  # noqa: E402

from sqlalchemy import delete, select, text, update  # noqa: E402

from api.chat_context import _load_context, _resolve_model, _resolve_node_models  # noqa: E402
from api.db import SessionLocal  # noqa: E402
from api.model_param_layers import layer_applies, strip_disallowed_agent_config  # noqa: E402
from api.models import Agent, ModelConfig  # noqa: E402

_TAG = f"v420-{uuid.uuid4().hex[:8]}"

_fails: list[str] = []
passed = 0


def check(cond: object, msg: str) -> None:
    global passed
    print(("  ok  " if cond else " FAIL ") + msg)
    if cond:
        passed += 1
    else:
        _fails.append(msg)


def _p_policy() -> None:
    print("== P 정책 단위(layer_applies) ==")
    check(layer_applies("model-default", "pipeline") and layer_applies("model-default", None),
          "model-default: 항상")
    check(layer_applies("node", "pipeline") and not layer_applies("node", None),
          "node: pipeline만")
    check(not layer_applies("agent", "pipeline") and layer_applies("agent", None),
          "agent: non-pipeline만")
    check(not layer_applies("session", "pipeline") and layer_applies("session", None),
          "session: non-pipeline만")
    try:
        layer_applies("bogus", None)
        check(False, "알 수 없는 층 → ValueError")
    except ValueError:
        check(True, "알 수 없는 층 → ValueError(오타 조기 발견)")


def _w_pure() -> None:
    print("== W 순수 정책 함수(strip_disallowed_agent_config) ==")
    stripped = strip_disallowed_agent_config({"impl": "pipeline", "modelParams": {"temperature": 0.9}})
    check(stripped["modelParams"] == {}, f"노드형 → modelParams 비움(사본) (got {stripped['modelParams']})")
    src = {"impl": None, "modelParams": {"temperature": 0.9}}
    kept = strip_disallowed_agent_config(src)
    check(kept["modelParams"].get("temperature") == 0.9 and src["modelParams"], "비노드형 보존·입력 무변이")


async def _o_orm_chokepoint() -> None:
    """스펙 420 원천 차단 — Agent/AgentVersion.config **ORM @validates**가 저장의 모든 경로(create·
    clone·activate·adopt·직접 ORM add)를 덮는 단일 관문. 여기 통과 못 하면 codex가 반복 지적한 입구
    누락이 재발한다. 직접 ORM add로 노드형 불법 modelParams를 넣어도 저장본은 비어야."""
    print("== O ORM 관문(@validates, 모든 저장 경로) ==")
    async with SessionLocal() as s:
        s.add(Agent(
            agent_id=f"agt_{_TAG}_orm", name=f"{_TAG}_orm", source="ui", active_version="v1",
            config={"impl": "pipeline", "model": "m", "modelParams": {"temperature": 0.9},
                    "nodes": [{"prompt": "n"}]},
        ))
        await s.commit()
    try:
        async with SessionLocal() as s:
            saved = (await s.execute(select(Agent).where(Agent.agent_id == f"agt_{_TAG}_orm"))).scalar_one()
            check(saved.config.get("modelParams") == {},
                  f"ORM add → 노드형 modelParams 저장 차단(관문) (got {saved.config.get('modelParams')})")
            check(saved.config.get("nodes"), "노드는 보존(agent 층 modelParams만 제거)")
    finally:
        async with SessionLocal() as s:
            await s.execute(delete(Agent).where(Agent.agent_id == f"agt_{_TAG}_orm"))
            await s.commit()


async def _t_temperature_channel(model_name: str) -> None:
    """P1② codex — temperature 병렬 통로 봉인: 노드형 에이전트(레거시 불법 저장 config, raw 시드로
    validator 우회)의 ctx.temperature가 None이어야(agent·session 둘 다). 이게 run_params로 4입구+노드에
    새던 실우회. 비노드형은 ctx.temperature 유지(무회귀)."""
    print("== T temperature 병렬 통로(ctx.temperature, 실 로더 — 레거시 dirty 행) ==")
    illegal = {"impl": "pipeline", "model": model_name, "modelParams": {"temperature": 0.9},
               "nodes": [{"prompt": "n", "model": model_name}]}
    async with SessionLocal() as s:
        # ORM @validates가 노드형 modelParams를 막으므로, **선재 dirty 행**(마이그레이션 이전 저장분)을
        # 재현하려면 raw SQL로 JSONB를 직접 주입한다. 런타임 관문이 이런 레거시 행도 안전 처리하나 검증.
        s.add(Agent(agent_id=f"agt_{_TAG}_pipe", name=f"{_TAG}_pipe", source="ui", active_version="v1",
                    config={"impl": "pipeline", "model": model_name}))
        s.add(Agent(agent_id=f"agt_{_TAG}_direct", name=f"{_TAG}_direct", source="ui", active_version="v1",
                    config={"impl": None, "model": model_name, "modelParams": {"temperature": 0.5}}))
        await s.commit()
        pipe = (await s.execute(select(Agent).where(Agent.agent_id == f"agt_{_TAG}_pipe"))).scalar_one()
        direct = (await s.execute(select(Agent).where(Agent.agent_id == f"agt_{_TAG}_direct"))).scalar_one()
        pipe_id, direct_id = pipe.id, direct.id
        # raw JSONB 주입(@validates 우회) — 선재 불법 config 시뮬레이션.
        await s.execute(update(Agent).where(Agent.id == pipe_id).values(config=illegal).execution_options(synchronize_session=False))
        await s.commit()
    # 주입 확인(우회 성공해야 이 테스트가 의미 있음).
    async with SessionLocal() as s:
        raw = (await s.execute(text("select config->'modelParams'->>'temperature' as t from agents where id = :i"), {"i": str(pipe_id)})).scalar_one_or_none()
        check(raw == "0.9", f"레거시 dirty 행 주입됨(raw SQL 우회 확인) (got {raw})")
    try:
        ctx = await _load_context(pipe_id, None, {}, own=None)
        check(ctx.temperature is None, f"노드형 ctx.temperature=None(agent 층 병렬통로 봉인) (got {ctx.temperature})")
        ctx_s = await _load_context(pipe_id, None, {"modelParams": {"temperature": 0.01}}, own=None)
        check(ctx_s.temperature is None, f"노드형 ctx.temperature=None(session 오버라이드도 봉인) (got {ctx_s.temperature})")
        ctx_d = await _load_context(direct_id, None, {}, own=None)
        check(ctx_d.temperature == 0.5, f"비노드형 ctx.temperature 유지(무회귀) (got {ctx_d.temperature})")
    finally:
        async with SessionLocal() as s:
            await s.execute(delete(Agent).where(Agent.agent_id.like(f"agt_{_TAG}_%")))
            await s.commit()


async def _r_resolution() -> None:
    print("== R 해석 관문(실 DB) ==")
    async with SessionLocal() as s:
        m = (
            await s.execute(
                select(ModelConfig).where(ModelConfig.kind == "chat").limit(1)
            )
        ).scalar_one_or_none()
    if m is None:
        check(False, "등록 chat 모델 없음 — 시드 확인")
        return None
    model_name = m.name

    # 노드형: agent 층(temperature) + session 층(top_p)이 노드에 안 실려야. + node 층은 실려야(양성).
    node_cfg = {"impl": "pipeline", "model": model_name, "modelParams": {"temperature": 0.9}}
    async with SessionLocal() as s:
        default_cfg = await _resolve_model(s, node_cfg, None)
        nodes = [
            {"prompt": "with-model", "model": model_name},  # 자기 모델 노드(경로 A)
            {"prompt": "no-model"},  # 모델 없는 노드 → default_cfg 폴백(경로 B)
            {"prompt": "own-mp", "model": model_name, "modelParams": {"temperature": 0.42}},  # node 층(양성)
        ]
        resolved = await _resolve_node_models(
            s, nodes, default_cfg, agent_cfg=node_cfg, session_mp={"top_p": 0.5}
        )
    by_tag = {r.get("prompt"): (r.get("model_cfg") or {}).get("params") or {} for r in resolved}
    for tag in ("with-model", "no-model", "own-mp"):
        params = by_tag[tag]
        check(params.get("temperature") != 0.9, f"[{tag}] 노드형: agent 층(temperature) 미적용 (got {params.get('temperature')})")
        check(params.get("top_p") != 0.5, f"[{tag}] 노드형: session 층(top_p) 미적용 (got {params.get('top_p')})")
    # node 층 양성 무회귀(codex 재검 P2) — 노드 자기 modelParams는 실제로 model_cfg.params에 실린다.
    check(by_tag["own-mp"].get("temperature") == 0.42,
          f"node 층 양성: 노드 자기 modelParams(temperature) 적용됨 (got {by_tag['own-mp'].get('temperature')})")

    # 노드형 default_cfg(폴백 원천)도 agent 층 없어야(경로 B 봉인 확인).
    check((default_cfg.get("params") or {}).get("temperature") != 0.9,
          "노드형 default_cfg: agent 층 미적용(폴백 경로 봉인)")

    # 비노드형: agent 층이 실려야(무회귀).
    direct_cfg = {"impl": None, "model": model_name, "modelParams": {"temperature": 0.9}}
    async with SessionLocal() as s:
        mc = await _resolve_model(s, direct_cfg, None)
    check((mc.get("params") or {}).get("temperature") == 0.9,
          f"비노드형: agent 층(temperature) 적용됨(무회귀) (got {(mc.get('params') or {}).get('temperature')})")
    return model_name


async def main() -> None:
    _p_policy()
    _w_pure()
    await _o_orm_chokepoint()
    model_name = await _r_resolution()
    if model_name:
        await _t_temperature_channel(model_name)
    print()
    if _fails:
        print(f"FAILED: {len(_fails)}건")
        for f in _fails:
            print("  -", f)
        sys.exit(1)
    print(f"VERIFY420_OK — {passed}건 전부 통과")


if __name__ == "__main__":
    asyncio.run(main())

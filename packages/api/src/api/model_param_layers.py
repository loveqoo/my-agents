"""모델 파라미터 캐스케이드 층 정책(스펙 420) — FE `CapabilitySettings.tsx`의 `modelParamLayerApplies`
BE 형제(대칭). modelParams가 적용되는 4층(model-default → agent → node → session) 중 **어느 층이 어느
에이전트 유형에서 유효한가**를 한 곳에서 판정한다.

여기가 BE의 유일한 판정처다 — 캐스케이드를 적용하는 관문(`_resolve_model`·`_resolve_node_models`,
chat_context_models)이 이 함수를 참조한다. 그래서 노드형에 agent·session 층이 새지 않는 게 특정
호출자(chat/resume/serve/eval)가 아니라 **관문 자체**에서 강제된다([[policy-at-the-chokepoint]]).

규칙(FE와 동일): model-default=항상 · node=노드형(pipeline)만 · agent·session=노드형이 **아닐** 때만
(노드형은 노드가 모델 파라미터를 소유 — 에이전트·세션 층이 노드로 새면 중복/혼란, 스펙 417·419·420).
"""

from __future__ import annotations

_PIPELINE = "pipeline"


def layer_applies(layer: str, impl: str | None) -> bool:
    """이 캐스케이드 층이 주어진 에이전트 impl에서 유효(적용/편집 가능)한가.

    layer: 'model-default' | 'agent' | 'node' | 'session'. 알 수 없는 층은 ValueError(오타 조기 발견).
    """
    is_pipeline = impl == _PIPELINE
    if layer == "model-default":
        return True
    if layer == "node":
        return is_pipeline
    if layer in ("agent", "session"):
        return not is_pipeline
    raise ValueError(f"알 수 없는 모델 파라미터 층: {layer!r}")


def strip_disallowed_agent_config(config: dict) -> dict:
    """에이전트 config에서 그 impl에 **유효하지 않은** 층의 modelParams를 제거한 얕은 사본을 돌려준다
    (스펙 420). 지금은 노드형(pipeline)의 agent 층 modelParams가 대상: 노드형은 모델 파라미터를 노드가
    소유(nodes[].modelParams)하므로 agent 층 config.modelParams는 없어야 한다.

    **관문 정확한 계약(codex 재검 — 과장 금지)**: 이 함수는 Agent·AgentVersion.config **ORM @validates**가
    부른다. @validates는 **ORM 속성 대입**(생성자 `Agent(config=…)`·대입 `a.config=…`)에만 발화한다 —
    라우트로 config를 저장하는 정상 경로(create·update·clone·activate·adopt·프롬프트채택·remote resync)는
    모두 로컬 cfg를 완성해 **마지막에 대입**하므로 이 한 관문을 지난다(라우트별 strip 뿌리기 불요 —
    codex가 놓친 입구를 반복 지적한 안티패턴 제거). **우회 경로(런타임이 방어)**: Core `insert/update`·
    bulk·raw SQL·대입 후 in-place 변이는 @validates 밖이다 — 현재 제품 라우트엔 이런 config 쓰기가
    없고(있는 건 삭제뿐), 있더라도 실행부 관문(_resolve_model·_resolve_node_models·ctx.temperature)이
    저장값과 무관하게 정책을 강제해 **동작은 안전**하다. 절대적 DB 불변식이 필요하면 before_flush나 DB
    CHECK가 별도 장치(현존 우회 0이라 미도입). 순수 함수(사본 반환, 입력 무변이)."""
    if not isinstance(config, dict):
        return config
    if config.get("impl") == _PIPELINE and config.get("modelParams"):
        return {**config, "modelParams": {}}
    return config

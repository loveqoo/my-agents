"""세션 오버라이드·노드 병합 — chat_context.py에서 분할(스펙 394 P1).

_merge_node_overrides(구 CC 12)는 노드별 병합(_merge_one_node) 추출로 분해.
파사드는 chat_context.py(재수출 계약 — verify_317이 직접 임포트).
"""

from .chat_context_types import _is_remote
from .models import Agent

# 노드 오버라이드 필드 화이트리스트(스펙 287) — 구조 식별자(name)는 제외해 저장본 유지.
# 노드 추가/삭제는 테스트 범위 밖(사용자 결정): 오버라이드는 "이 에이전트 그대로, 설정만 바꿔
# 테스트"가 목적이라 구조 변경 요청은 받지 않는다(서버 강제 — 클라이언트 신뢰 금지).
_NODE_OVERRIDE_FIELDS = {
    "prompt",
    "model",
    "tools",
    "historyDepth",
    "memories",
    "memoryQuery",
    "context",
    "format",
    "fields",
}


def _node_patch_fields(base_n: dict) -> set[str]:
    """이 노드에 병합 가능한 오버라이드 필드(스펙 317) — 설정 노드=화이트리스트 전체, 코드 노드=
    manifest.overridable ∩ 화이트리스트(나머지는 코드가 소유 — 세션 패치로 못 바꾼다). 미등록
    impl은 빈 집합(fail-closed — 어차피 실행이 설정 오류로 거부됨)."""
    impl = base_n.get("impl")
    if not isinstance(impl, str) or not impl.strip():
        return _NODE_OVERRIDE_FIELDS
    from agent.nodes import get_node_impl

    node_impl = get_node_impl(impl)
    if node_impl is None:
        return set()
    return _NODE_OVERRIDE_FIELDS & set(node_impl.describe().overridable)


def _merge_one_node(base_n: object, ov_n: object) -> tuple[dict, bool] | None:
    """노드 하나 병합 — (병합본, 코드소유 필드 드롭 여부). 형식 오류는 None(mismatch 신호)."""
    if not isinstance(base_n, dict) or not isinstance(ov_n, dict):
        return None
    allowed = _node_patch_fields(base_n)
    patch = {k: v for k, v in ov_n.items() if k in allowed}
    dropped = any(k in _NODE_OVERRIDE_FIELDS and k not in allowed for k in ov_n)
    return {**base_n, **patch}, dropped


def _merge_node_overrides(saved: list, ov: object) -> tuple[list, str]:
    """노드형 세션 오버라이드 merge(스펙 287). 길이(=구조)가 같을 때만 인덱스별로 필드
    화이트리스트를 저장 노드 위에 덮는다. 불일치·형식 오류는 저장본 그대로 + "mismatch"
    (조용한 드롭 금지 — 트레이스가 표면화, 스펙 125 계열). 코드 노드(스펙 317)는 manifest가
    선언한 표면만 병합하고, 화이트리스트 필드가 표면 밖이라 떨어지면 "partial"로 표면화
    (조용한 무시 금지 — 무엇이 안 먹었는지 트레이스가 말한다). 순수 함수(테스트 단위)."""
    if not isinstance(ov, list) or len(ov) != len(saved):
        return saved, "mismatch"
    merged: list = []
    dropped = False
    for base_n, ov_n in zip(saved, ov, strict=True):
        one = _merge_one_node(base_n, ov_n)
        if one is None:
            return saved, "mismatch"
        node, one_dropped = one
        dropped = dropped or one_dropped  # 코드 소유 필드를 덮으려 함 — 병합은 계속, 정직 표기
        merged.append(node)
    return merged, ("partial" if dropped else "applied")


def _coerce_history_depth(cfg: dict, agent: Agent) -> None:
    """historyDepth 형 가드(codex 287 Low) — 비정수(예: 문자열)는 _window의 `depth < 0` 비교에서
    TypeError 500. 정수화 실패 시 저장값 폴백(요청 하나로 500 못 만들게)."""
    if isinstance(cfg.get("historyDepth"), int):
        return
    try:
        cfg["historyDepth"] = int(cfg["historyDepth"])
    except (TypeError, ValueError):
        cfg["historyDepth"] = (agent.config or {}).get("historyDepth", 20)


def _apply_overrides(
    cfg: dict, prompt: str, overrides: dict | None, agent: Agent, allowed: set
) -> tuple[dict, str, str | None, dict | None]:
    """web 한정 세션 오버라이드 병합(스펙 025) — 화이트리스트 키만, 저장 에이전트는 불변.

    코드·외부(원격) 에이전트는 미적용(bypass 보존 — 026 read-only 취급). 모델은 여전히
    cfg["model"] 이름으로 레지스트리에서만 해석 → [012] 단일 소스 불변식 유지.
    - capabilities(스펙 122): 브로커가 build_broker(principal=호출자)로 호출자 RBAC 게이트
      (_permitted = allowlist ∩ RBAC)하므로 주입분도 안전(confused-deputy 무관).
    - tools(스펙 276): 직접형 도구 단위 배선 — 노출 축소/서버별 필터라 완화 아님.
    - vectorTables(스펙 287): 노드형 문서 풀 파생의 실효 축 — RAG 읽기(사용=공용 정책 211).
    - nodes(스펙 287): 구조 불변 강제 merge(allowed와 분리 — 통짜 교체가 아니라 저장 노드 위
      필드 merge, 추가/삭제=범위 밖). 미적용 사유(mismatch)는 트레이스가 표면화.
    반환 (cfg, prompt, nodes_status, passthrough) — passthrough=적용된 원본 오버라이드(미적용=None):
    in-process 커스텀 에이전트가 화이트리스트 밖 키도 읽게 ctx["overrides"]로 전달(스펙 085)."""
    if not overrides or _is_remote(agent.source):
        return cfg, prompt, None, None
    # modelParams(스펙 408)는 통짜 교체가 아니라 per-key 병합 — 세션이 stream만 보내도 에이전트의
    # enable_thinking 오버라이드가 살아남아야 3층 캐스케이드가 키 단위로 성립한다.
    saved_mp = dict(cfg.get("modelParams") or {})
    cfg.update({k: v for k, v in overrides.items() if k in allowed})
    if "modelParams" in overrides and isinstance(overrides["modelParams"], dict):
        cfg["modelParams"] = {**saved_mp, **overrides["modelParams"]}
    if "historyDepth" in overrides:
        _coerce_history_depth(cfg, agent)
    # systemPrompt는 비어있지 않을 때만 prompt를 덮어쓴다 — 빈/공백 문자열로
    # 저장된 프롬프트를 지우지 않도록(백엔드 자체 가드, 클라이언트 신뢰 안 함. codex P1).
    sp = overrides.get("systemPrompt")
    if isinstance(sp, str) and sp.strip():
        prompt = sp
    nodes_status: str | None = None
    if overrides.get("nodes") is not None:
        if isinstance(cfg.get("nodes"), list):
            cfg["nodes"], nodes_status = _merge_node_overrides(cfg["nodes"], overrides["nodes"])
        else:
            nodes_status = "mismatch"  # 노드형이 아닌 에이전트에 nodes를 보냄
    return cfg, prompt, nodes_status, overrides


def _filter_capabilities(cfg: dict) -> list:
    """능력 브로커 allowlist(스펙 100) — 오케스트레이션 허용 cap id 목록(없으면 [] = deny-by-default).

    비영속(스펙 237) 방어층: DB 쓰기 능력(memwrite/memedit)은 걸러낸다 — 정본 게이트는 저장 시
    422(agents._enforce_ephemeral_boundary), 여기는 과거 저장분·우회 대비 fail-closed."""
    return [
        c
        for c in cfg.get("capabilities", [])
        if not (
            cfg.get("ephemeral")
            and isinstance(c, str)
            and c.split(":", 1)[0] in ("memwrite", "memedit")
        )
    ]

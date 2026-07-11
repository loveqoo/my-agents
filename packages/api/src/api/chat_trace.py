"""트레이스 조립(오버라이드·브로커 호출 투영) — chat.py에서 분할(스펙 291 Phase 3b).

파사드는 chat.py(재수출 계약) — 인스펙터가 소비하는 trace 필드의 정화·화이트리스트 단일 출처.
"""

# 트레이스에 기록할 오버라이드 허용 키(스펙 134) — _load_context 병합 allowlist + systemPrompt.
_OVERRIDE_TRACE_KEYS = (
    "model",
    "temperature",
    "historyDepth",
    "mcps",
    "memories",
    "capabilities",
    "tools",
    "vectorTables",
    "systemPrompt",
)


def _trace_override_value(key: str, v: object) -> str | int | float | bool | list[str] | None:
    """오버라이드 값 1개를 트레이스 표시용으로 정화(131 프레임 재사용) — 기록 제외면 None.

    문자열=비밀 마스킹+캡 300, 리스트=항목별 캡 100·개수 20, 숫자 통과. systemPrompt는
    _load_context가 **비어있지 않을 때만 적용**(빈/공백은 무시) — 트레이스도 같은 가드를 미러
    (적용 안 된 값을 "적용됨"으로 기록 금지, codex 134 #1)."""
    from .memory import _sanitize

    if isinstance(v, str):
        if key == "systemPrompt" and not v.strip():
            return None
        return _sanitize(v, cap=300)
    if isinstance(v, (int, float, bool)):
        return v
    if isinstance(v, list):
        return [_sanitize(str(it), cap=100) for it in v[:20]]
    return None


def _overrides_trace(overrides: dict | None, nodes_status: str | None = None) -> dict | None:
    """이 턴에 적용된 오버라이드를 트레이스 표시용으로 정화(스펙 134) — 한 세션에 설정이 다른 턴이
    섞여도 턴별로 구분 가능하게 영구 기록. 실제 온 허용 키만 — 없으면 None(필드 미기록=무회귀)."""
    if not isinstance(overrides, dict):
        return None
    out: dict = {}
    for key in _OVERRIDE_TRACE_KEYS:
        if key not in overrides or overrides[key] is None:
            continue
        v = _trace_override_value(key, overrides[key])
        if v is not None:
            out[key] = v
    # 노드 오버라이드(스펙 287) — 프롬프트 전문 대신 요약(개수+적용 상태). mismatch도 기록해
    # "왜 안 먹었는지"를 표면화(스펙 125 계열 — 조용한 드롭 금지).
    if nodes_status is not None and isinstance(overrides.get("nodes"), list):
        out["nodes"] = {"count": len(overrides["nodes"]), "status": nodes_status}
    return out or None


def _broker_calls_trace(invocations: list[dict]) -> list[dict]:
    """브로커 호출 이력 → 트레이스 표시용 투영(스펙 130) — **키 화이트리스트 단일 출처**(메인/승인대기/
    재개 세 경로 공유, drift 0). 본문·args 불포함(087/092 원문 누출 0 유지)."""
    return [
        {
            k: v
            for k, v in inv.items()
            if k
            in (
                "node",
                "cap_id",
                "ms",
                "hits",
                "topScore",
                "error",
                "resultPreview",
                "hitsDetail",
                "minScore",
                "query",
                "local",
                "subTraceNodes",
            )
        }
        for inv in invocations
    ]

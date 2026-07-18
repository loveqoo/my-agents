"""트레이스 안전 계층(마스킹·캡·정규화) — runtime.py에서 분할(스펙 397 P4).

스펙 086/087/092/125/320의 **보안 계약 정본**: 민감 키 패턴·캡 상수군·redaction이 한 모듈에
동거한다(codex 397 — 상수와 로직 분리 금지). polarity 계약: args는 키-blocklist(평범 값 보존 —
디버깅 가치), 노드 델타는 값-allowlist(_VALUE_SAFE_KEYS만 원문). _redact_args(구 CC 13)는
scalar 분리(_redact_scalar)만 — 보안 계약이라 광범위 재구성 금지. 파사드는 runtime.py(재수출).
"""

import math
import re
from typing import Any


def _content_text(result: Any) -> str:
    """메시지/도구 content를 표시·트레이스·영속용 문자열로 정규화.

    실 MCP 도구는 물론 모델 메시지(AIMessageChunk.content)도 문자열이 아니라
    content-block 리스트(`[{'type':'text','text':...}]`)일 수 있다(probe로 확인).
    텍스트 블록을 추출·결합하고, 그 외 타입은 str()로 폴백한다. 채팅 본문 sink가
    `"".join(acc)`로 합치므로 여기서 str을 보장하지 않으면 list content가 TypeError를
    낸다 — 스펙 092 적대 검증(codex P1)이 잡은 선재 잠복 크래시를 이 정규화가 막는다."""
    if isinstance(result, str):
        return result
    if isinstance(result, (list, tuple)):
        parts: list[str] = []
        for block in result:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
            elif block is not None:
                parts.append(str(block))
        return "\n".join(p for p in parts if p)
    if result is None:
        return ""
    return str(result)


def _sink_from(config: Any, fallback: list[dict]) -> list[dict]:
    """호출 시점 트레이스 sink 해석(스펙 371 D3) — RunnableConfig.configurable["mcp_calls_sink"]
    우선(그래프 캐시 경로: per-turn 값을 호출 인자로), 없으면 빌드 시 클로저(비캐시 경로 무회귀)."""
    try:
        sink = (config or {}).get("configurable", {}).get("mcp_calls_sink")
    except AttributeError:
        sink = None
    return sink if isinstance(sink, list) else fallback


def _sanitize_preview(text: object, cap: int) -> str:
    """trace 표시용 본문 프리뷰 — 비밀 마스킹 + 캡(스펙 087/092/125). 브로커 resultPreview·직접 result·
    hitsDetail이 **한 경로**로 정화(drift 0). _sanitize가 비밀을 치환한 뒤 cap자로 자른다."""
    from .memory import _sanitize  # 지연 임포트(순환 import 방지, broker와 동일 패턴)

    return _sanitize(text, cap=cap)


# 노드 상태 델타에서 비밀값을 띄우지 않기 위한 민감 키 패턴(닫힌 집합, 스펙 086 §2).
# 키 *이름*으로 마스킹한다 — 값 휴리스틱이 아니라(저장 크레덴셜용 crypto.is_masked와 별개).
# `[_-]key$`·`^key$`는 private_key·access_key·client_key·signing_key·encryption_key 등 *_key 비밀명을
# 포괄(codex 087 F1: api_key만으론 표준 비밀키 이름을 놓침). monkey/top_k는 구분자 없어 안 걸림.
_SENSITIVE_KEY = re.compile(
    r"(api[_-]?key|secret|token|password|passwd|auth|credential|bearer|[_-]key$|^key$)", re.I
)
_FIELD_CAP = 300  # 필드(값) 1개 표시 상한(자)
_MSG_PREVIEW_CAP = (
    160  # messages 델타의 메시지 1건 본문 프리뷰 상한(자) — 채팅 중복이라 짧게(스펙 192 후속)
)
_MSG_PREVIEW_N = 3  # 프리뷰로 펼칠 앞쪽 메시지 수(나머지는 "+N건"으로 카운트만)
_NODE_SUMMARY_CAP = 1200  # 노드 요약 전체 상한(자) — 필드 캡보다 커야 단일 필드가 이중 캡 안 됨
# (codex F3 후속: per-field 캡 후 join이 또 잘려 생략 길이가 거짓이 되던 버그)
_REDACTED = "«redacted»"


# 값 원문을 *노출해도 되는* 알려진 안전 필드(최소 allowlist). 이 기능의 존재이유가 "그 값을 보여주는
# 것"인 필드만. 그 외 임의 키의 문자열 값은 원문 미표시(fail-closed): 키 이름이 평범/비영문이라
# _SENSITIVE_KEY가 못 잡아도 *값 자체* 비밀이 안 샌다(codex 적대 리뷰 F2: 값-비밀 차단). 새 안전 필드
# 추가는 "그 키는 절대 비밀이 아니다"를 보증할 때만.
# 스펙 131 확대: query(analyze가 뽑은 유저 질의)·route(분류 라벨)·delegated(위임 결과 fold, 인스펙터
# brokerCalls resultPreview와 같은 내용) — 출하 그래프(route/plan_execute/orchestrate)의 닫힌 상태 키로
# 전부 비-비밀임을 코드로 확인(131 조사). 미지 키는 여전히 길이만(F2 유지 — 커스텀 플로우 안전).
_VALUE_SAFE_KEYS = frozenset(
    {"plan", "query", "route", "delegated", "delegationNote"}
)  # delegationNote=스펙 289 P3(우리가 생성한 사유 문자열)

# 스펙 087: MCP 호출 인자·결과 redaction(형제 trace 표면). 086 노드델타와 달리 args는 *보여주는 게
# 목적*(인스펙터 디버깅 가치)이라 평범한 키의 값은 보존하고 민감 *키*만 마스킹한다(value-allowlist
# 아닌 key-blocklist — polarity가 정당하게 다름, learning 089 §3 형제 표면판). 시스템 자기 비밀은
# 이 표면에 안 온다(서버 토큰=헤더·모델 키=설정, args 아님) → defense-in-depth.
_ARG_VALUE_CAP = (
    500  # args 문자열 leaf 1개 표시 상한(자) — query·path 등 정상 인자 보존하되 거대값 캡
)
_RESULT_CAP = (
    2000  # 도구 결과 문자열 상한(자) — calls_sink에 무제한 적재(trace 비대) 방어(learning 059)
)
_ERR_CAP = 500  # 실패 사유(에러 메시지) 상한(스펙 320) — 한 줄 사유+캡, 전문 스택은 서버 로그만(learning 092)
_REDACT_MAX_DEPTH = 6  # args 재귀 깊이 상한 — 사이클/거대 중첩 fail-closed


def _redact_scalar(obj: Any) -> Any:
    """스칼라 leaf 정화(스펙 397 분해) — 문자열=budgeted 캡, 비유한 float=마커, 미지 타입=타입명만."""
    if isinstance(obj, str):
        return _cap(obj, _ARG_VALUE_CAP)
    if isinstance(obj, float):
        # NaN/Infinity는 JSONB(Approval.args)·JSON 직렬화에 비유효 → 안전 마커로(codex 087 F2 fail-closed).
        return obj if math.isfinite(obj) else f"<{obj}>"
    if obj is None or isinstance(obj, (bool, int)):
        return obj  # 스칼라(유한 길이, 비밀 위험 낮음)
    return f"<{type(obj).__name__}>"  # 미지 타입은 타입명만(fail-closed)


def _redact_args(obj: Any, _depth: int = 0) -> Any:
    """MCP 도구 인자(kwargs)를 표시·영속(calls_sink·interrupt·Approval.args) 전에 정화한다(스펙 087).

    - 민감 *키*(_SENSITIVE_KEY)의 값은 `«redacted»`로. 평범한 키의 값은 *원문 보존*(args는 사람에게
      보일 표면이라 086 노드델타와 polarity가 다름 — 디버깅 가치 유지).
    - 문자열 leaf는 _cap(_ARG_VALUE_CAP)로 budgeted 캡(raw에서, learning 059).
    - fail-closed: 비문자 키는 str(k)·깊이 상한·전체 try/except → 실패 시 안전 마커(스트림 안 깸).
    JSON 직렬화 가능한 구조만 반환(calls_sink→json.dumps·Approval.args JSONB).
    """
    try:
        if _depth > _REDACT_MAX_DEPTH:
            return "«depth-capped»"
        if isinstance(obj, dict):
            out: dict[str, Any] = {}
            for k, v in obj.items():
                key = str(k)
                out[key] = _REDACTED if _SENSITIVE_KEY.search(key) else _redact_args(v, _depth + 1)
            return out
        if isinstance(obj, (list, tuple)):
            return [_redact_args(v, _depth + 1) for v in obj]
        return _redact_scalar(obj)
    except Exception:
        return "«redact-failed»"


def _cap(s: str, limit: int = _NODE_SUMMARY_CAP) -> str:
    """raw 문자열에서 캡 — 초과분은 정직 표기(no silent truncation). 원문 길이(`len(s)`=O(1))로 표기하되
    복사는 `s[:limit]`만(budgeted) — 거대 문자열을 통째 다시 만들지 않는다(codex F3: post-build cap 금지)."""
    if len(s) <= limit:
        return s
    return s[:limit] + f"…({len(s) - limit}자 생략)"

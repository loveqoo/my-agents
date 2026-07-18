"""엔티티 스키마 입력 가드(스펙 149) — shared.py에서 분할(스펙 398 P2, 순수 이동).

ReDoS 금지키·직렬화 캡 — 컬렉션 생성·수정 양쪽이 같은 가드를 공유(codex 398 함정 6).
"""

from fastapi import HTTPException

_SCHEMA_MAX_CHARS = 20_000  # 스키마 직렬화 캡 — 거대 스키마의 행당 검증 비용 폭주 방지(codex 149)
_SCHEMA_BANNED_KEYS = ("pattern", "patternProperties")  # 정규식 키워드 금지(v1)


def _has_banned_key(node: object) -> str | None:
    """스키마 트리에서 금지 키워드 탐색 — 병적 정규식(`^(a+)+$` 류)이 행 전수 검증에서 CPU를
    폭주시키는 ReDoS 표면을 등록 시점에 차단(codex 149 High). v1 경계: 정규식 제약 미지원."""
    if isinstance(node, dict):
        for k, v in node.items():
            if k in _SCHEMA_BANNED_KEYS:
                return k
            found = _has_banned_key(v)
            if found:
                return found
    elif isinstance(node, list):
        for item in node:
            found = _has_banned_key(item)
            if found:
                return found
    return None


def _check_entity_schema(schema: dict | None, kind: str) -> None:
    """entity_schema 입력 검증(스펙 149) — 스키마 자체가 유효한 JSON Schema인지 등록 시점에 확인
    (업로드 때 처음 터지면 원인 추적이 어렵다). 문서형에 스키마를 주면 400(의미 없음)."""
    if schema is None:
        return
    if kind != "entity":
        raise HTTPException(
            status_code=400, detail="entity_schema는 엔티티 컬렉션에만 설정할 수 있습니다."
        )
    import json

    import jsonschema

    if len(json.dumps(schema)) > _SCHEMA_MAX_CHARS:
        raise HTTPException(
            status_code=400, detail=f"JSON Schema가 너무 큽니다(최대 {_SCHEMA_MAX_CHARS}자)."
        )
    banned = _has_banned_key(schema)
    if banned:
        raise HTTPException(
            status_code=400,
            detail=f"JSON Schema의 '{banned}' 키워드는 지원하지 않습니다(정규식 제약은 v1 미지원 — 검증 비용 경계).",
        )
    try:
        jsonschema.Draft202012Validator.check_schema(schema)
    except jsonschema.SchemaError as exc:
        raise HTTPException(
            status_code=400, detail=f"JSON Schema가 유효하지 않습니다: {exc.message[:200]}"
        ) from exc

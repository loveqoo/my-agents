"""리소스 네이밍 규칙 (스펙 148·217) — 식별 이름 검증·자동 변환.

식별 이름(name)=참조·검색 키(규칙 적용), 설명(description)=자유 표기. 규칙(스펙 217, 사용자 지시):
허용=**영소문자·숫자·대시(-)만**. 한글·마침표·공백·밑줄·영대문자 금지. 원격 유래 이름(A2A 카드·SDK
등록)은 거부 대신 slugify_name으로 자동 변환하고 원문을 설명(description)으로 보존한다.
"""

import re

from fastapi import HTTPException

NAME_RE = re.compile(r"^[a-z0-9\-]+$")

_HINT = "영소문자·숫자·대시(-)만 쓸 수 있습니다(한글·마침표·공백·밑줄·대문자 금지)."


def validate_resource_name(name: str) -> str | None:
    """식별 이름 규칙 검사 — 위반이면 사용자용 오류 메시지, 통과면 None. 순수 함수."""
    if not name or not name.strip():
        return "이름을 입력하세요."
    if not NAME_RE.match(name):
        return f"이름 규칙 위반: {_HINT}"
    return None


def assert_valid_name(name: str) -> None:
    """식별 이름 규칙(스펙 148·296 정본) — 위반이면 400. 생성·이름 변경 시에만(기존은 grandfather)."""
    err = validate_resource_name(name)
    if err:
        raise HTTPException(status_code=400, detail=err)


def slugify_name(name: str, fallback: str = "unnamed") -> str:
    """원격 유래·레거시 이름 → 규칙 준수 식별 이름(자동 변환). 소문자화, 공백/`_`→`-`,
    불허 문자(한글·마침표 포함) 제거, 연속 대시 압축, 양끝 대시 제거. 전부 탈락하면 fallback.
    fallback도 규칙을 지켜야 하므로 영문(스펙 217 — 한글 폴백은 새 규칙 위반). 순수 함수."""
    s = (name or "").strip().lower()
    s = re.sub(r"[\s_]+", "-", s)
    s = re.sub(r"[^a-z0-9\-]", "", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s or fallback

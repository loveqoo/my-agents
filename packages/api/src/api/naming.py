"""리소스 네이밍 규칙 (스펙 148) — 식별 이름 검증·자동 변환.

식별 이름(name)=참조·검색 키(규칙 적용), 설명(description)=자유 표기. 규칙: `_`/공백/영대문자 금지,
허용=한글·영소문자·숫자·대시·마침표. 원격 유래 이름(A2A 카드·SDK 등록)은 거부 대신
slugify_name으로 자동 변환하고 원문을 설명(description)으로 보존한다.
"""

import re

NAME_RE = re.compile(r"^[가-힣a-z0-9.\-]+$")

_HINT = "한글·영소문자·숫자·대시(-)·마침표만 쓸 수 있습니다(공백·밑줄·대문자 금지)."


def validate_resource_name(name: str) -> str | None:
    """식별 이름 규칙 검사 — 위반이면 사용자용 오류 메시지, 통과면 None. 순수 함수."""
    if not name or not name.strip():
        return "이름을 입력하세요."
    if not NAME_RE.match(name):
        return f"이름 규칙 위반: {_HINT}"
    return None


def slugify_name(name: str, fallback: str = "이름-미상") -> str:
    """원격 유래·레거시 이름 → 규칙 준수 식별 이름(자동 변환). 소문자화, 공백/`_`→`-`,
    불허 문자 제거, 연속 대시 압축, 양끝 대시·마침표 제거. 전부 탈락하면 fallback. 순수 함수."""
    s = (name or "").strip().lower()
    s = re.sub(r"[\s_]+", "-", s)
    s = re.sub(r"[^가-힣a-z0-9.\-]", "", s)
    s = re.sub(r"-{2,}", "-", s).strip("-.")
    return s or fallback

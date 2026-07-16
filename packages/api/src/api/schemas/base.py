"""schemas.base — 007 도메인 스키마(스펙 378 분할).

원본 schemas.py에서 verbatim 이관."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

ORM = ConfigDict(from_attributes=True)


class AuditOut(BaseModel):
    """감사 4값 응답 믹스인 (스펙 344) — DB엔 343으로 쌓이는데 API가 안 내려주던 것.

    값 공간이 **열려 있다**(스펙 343 전제): 관리자 이메일 로컬파트 · `system`(배경 작업) ·
    `unknown`(343 이전 행) · **추후 채팅으로 들어올 미등록 최종 사용자 ID**. 그래서 이 값들은
    `user` 테이블로 resolve하지 않고 **문자열 그대로** 내려간다(조인·프로필 링크 금지).

    노출 경계: 관리 API(인증 뒤)에만 싣는다. A2A 카드·서빙 MCP 등 **외부 노출 경로엔 절대 싣지
    않는다** — 내부 계정명이자 (추후) 고객 식별자이기 때문(verify_344 누출 핀).
    """

    created_at: datetime | None = None
    updated_at: datetime | None = None
    created_by: str | None = None
    updated_by: str | None = None


def _require_non_blank(v: str) -> str:
    """검색 질의 공백 거부(스펙 296 정본) — min_length는 strip 전 길이라 공백("   ")이 통과해
    코어서 빈값으로 502가 됐다. 입력 경계서 strip 후 비면 422로 거부(서버 오류가 아니라 잘못된 입력)."""
    s = v.strip()
    if not s:
        raise ValueError("질의는 공백일 수 없습니다.")
    return s

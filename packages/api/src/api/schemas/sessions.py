"""schemas.sessions — 007 도메인 스키마(스펙 378 분할).

원본 schemas.py에서 verbatim 이관."""

import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field


# ----------------------------- 세션/승인 -----------------------------
class SessionOut(BaseModel):
    id: str  # session_id (sess_...)
    agentId: str
    agent: str
    channel: str
    status: str
    turns: int
    tokens: int
    started: str | None = None
    lastActivity: str | None = None
    preview: str | None = None  # 첫 사용자 메시지 일부 — 사람이 알아볼 세션 라벨(스펙 055)


class SessionPage(BaseModel):
    """세션 목록 페이지 엔벌로프 (스펙 034)."""

    items: list[SessionOut]
    total: int  # 현재 필터 적용 총 건수 (페이지네이터용)
    counts: dict[str, int]  # 배지용 전체 집계, 키 all|live (필터 무관 — 스펙 324 죽은 버킷 제거)


class FeedbackOut(BaseModel):
    rating: Literal["up", "down"]
    reason: str = ""


class MessageFeedbackIn(BaseModel):
    rating: Literal["up", "down"]
    # 이유 상한(codex 209 F3) — 무제한이면 저장/응답 팽창. 사유는 짧은 메모라 2000자면 충분.
    reason: str = Field(default="", max_length=2000)


class MessageOut(BaseModel):
    id: uuid.UUID | None = None  # 스펙 209 — 피드백 부착 대상(구 응답엔 없어 optional)
    role: str
    content: str
    trace: dict[str, Any] | None = None
    feedback: FeedbackOut | None = None  # 스펙 209 — 요청 사용자의 이 메시지 피드백(없으면 None)


class ApprovalOut(BaseModel):
    id: str  # approval_id
    sessionId: str | None = None
    agentId: str | None = None
    agent: str
    permission: str
    action: str
    args: dict[str, Any] = Field(default_factory=dict)
    summary: str
    checkpoint: str | None = None
    status: str
    requestedAt: str | None = None
    approver: str | None = None  # 승인자(스펙 177 P2) — "admin"=관리자·"self"=본인. UI 태그 표기용.
    resolvedAt: str | None = None  # 처리 시각(스펙 181, 감사) — 미처리면 None
    resolvedBySelf: bool | None = (
        None  # 처리자=요청자면 True(본인), 다르면 False(관리자), 미처리 None
    )


class ApprovalPage(BaseModel):
    # 승인 페이지 응답(스펙 251) — 세션 페이지와 같은 계약({items, total}).
    items: list[ApprovalOut]
    total: int


class ResolveIn(BaseModel):
    decision: Literal["approve", "reject"]


# ----------------------------- 채팅 -----------------------------
class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatFormSubmission(BaseModel):
    """산출물형 폼 제출(스펙 188 P2) — 대기 중 폼 프레임(formId)에 대한 값. 서버가 pending의
    필드 명세로 검증(값∈후보) 후 Command(resume={"type":"form",...})로 그래프를 재개한다."""

    formId: str
    values: dict


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    sessionId: str | None = None  # 이어서 대화할 세션(없으면 새로 생성)
    # mem0 user_id 축은 더는 클라이언트가 보내지 않는다(스펙 032). chat 핸들러가 인증 주체
    # (current_principal)에서 도출한다: 쿠키 유저면 str(user.id)(UUID), 머신 토큰이면 None(세션 단기).
    # Playground "Proxy" 세션 한정 오버라이드(스펙 025). **web 에이전트에만** 적용, 화이트리스트
    # 키만 의미(model/temperature/systemPrompt/mcps/memories/historyDepth). 저장된 에이전트는 불변.
    # 코드 에이전트는 원격 실행이라 무시(bypass).
    overrides: dict | None = None
    # 산출물형 폼 제출(스펙 188 P2) — 이중 입력의 폼 입구. 텍스트 입구는 messages 그대로.
    form: ChatFormSubmission | None = None
    # 버전 지정 실행(스펙 242) — 지정하면 그 AgentVersion의 config로 실행(초안 미리보기·버전별 테스트).
    # 내부(관리 API) 전용 축: A2A·공개 서빙 경로는 이 필드가 없어 활성 버전만 나간다(외부 경계 공짜).
    version: str | None = None

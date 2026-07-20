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
    """content 상한 15만자(스펙 415 P2) = **구조 DoS 캡** — 클라 관리 모드(플레이그라운드 세션
    복원)가 서버의 첨부 주입 영속본(최대 3×3만+유저 5만+펜스≈14만자)을 그대로 되보내는 걸 수용.
    **현재 턴 유저 입력의 가시 한계는 5만자**(승인값) — chat.py 입구가 마지막 user 메시지에 강제."""

    role: Literal["user", "assistant"]
    content: str = Field(max_length=150_000)


class ChatAttachment(BaseModel):
    """파일첨부(스펙 404, A안) — 추출 엔드포인트가 돌려준 텍스트를 클라이언트가 되보내는 운반체.
    캡(개수·길이)은 서버 주입 관문(chat_attachments.apply_attachments)이 재강제한다."""

    filename: str = Field(max_length=200)
    text: str = Field(
        max_length=30_000
    )  # 추출 캡과 동일(초과는 스키마 422 — 주입 관문이 한 번 더 자름)


class ChatFormSubmission(BaseModel):
    """산출물형 폼 제출(스펙 188 P2) — 대기 중 폼 프레임(formId)에 대한 값. 서버가 pending의
    필드 명세로 검증(값∈후보) 후 Command(resume={"type":"form",...})로 그래프를 재개한다."""

    formId: str = Field(max_length=200)  # 스펙 415 P2 — 문자열 필드 상한(전역 2MB의 이중 그물)
    values: dict  # 구조/깊이는 전역 2MB body limit이 관할(스펙 415 P1)


class ChatRequest(BaseModel):
    # 턴 예산 계약(스펙 415 P2, 승인값): messages ≤200개 — 초과 대화는 sessionId+새 메시지 1개
    # 계약(스펙 289 서버 재구성)으로 이관하면 무제한(서버가 depth 상한으로 절단).
    messages: list[ChatMessage] = Field(max_length=200)
    sessionId: str | None = None  # 이어서 대화할 세션(없으면 새로 생성)
    # mem0 user 축 정체성(스펙 032→387): 쿠키 유저는 인증 주체에서 도출(임의 지정 금지 — 422).
    # **머신 토큰 호출만** userId 지정 가능(owner 전권의 위임 — 외부 시스템이 자기 유저를 대신).
    # 판정은 auth.resolve_memory_user_id 단일 관문. 미지정 시 기존 동작(쿠키=자기 id, 머신=세션 축만).
    userId: str | None = Field(default=None, max_length=80)  # 세션 컬럼 String(80) 정렬
    # Playground "Proxy" 세션 한정 오버라이드(스펙 025). **web 에이전트에만** 적용, 화이트리스트
    # 키만 의미(model/temperature/systemPrompt/mcps/memories/historyDepth). 저장된 에이전트는 불변.
    # 코드 에이전트는 원격 실행이라 무시(bypass).
    overrides: dict | None = None
    # 산출물형 폼 제출(스펙 188 P2) — 이중 입력의 폼 입구. 텍스트 입구는 messages 그대로.
    form: ChatFormSubmission | None = None
    # 파일첨부(스펙 404) — 마지막 user 메시지에 nonce 펜스로 주입(1회성·무상태). 개수는 스키마서도 캡.
    attachments: list[ChatAttachment] | None = Field(default=None, max_length=3)
    # 버전 지정 실행(스펙 242) — 지정하면 그 AgentVersion의 config로 실행(초안 미리보기·버전별 테스트).
    # 내부(관리 API) 전용 축: A2A·공개 서빙 경로는 이 필드가 없어 활성 버전만 나간다(외부 경계 공짜).
    version: str | None = Field(default=None, max_length=80)  # 스펙 415 P2 — 문자열 상한
    # overrides·form.values dict의 구조/깊이 상한은 전역 2MB body limit(스펙 415 P1)이 관할한다 —
    # 개별 스키마 캡 대신 raw 크기 한 곳에서(커스텀 impl로 흐르는 overrides도 그 상한 안).

"""대화 창·재구성·전송 페이로드 — chat.py에서 분할(스펙 291 Phase 3b).

historyDepth 절단(_window), 세션 영속 대화 재구성(스펙 289 P1), 노드별 단기 기억 창 프록시
(스펙 270), 전송 프롬프트 캡처(스펙 131/205)를 담당한다. 파사드는 chat.py(재수출 계약).
"""

import uuid

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from sqlalchemy import select

from .db import SessionLocal
from .models import Message, Session


def _window(messages: list[dict], depth: int | None) -> list[dict]:
    """실행 컨텍스트를 최근 N개로 절단. 0=현재 턴만, 음수/None=전체.
    ([-0:]가 전체가 되는 파이썬 함정 처리)."""
    if depth is None or depth < 0:
        return messages
    if depth == 0:
        return messages[-1:]
    return messages[-depth:]


def _to_base_messages(dicts: list[dict]) -> list:
    """{role, content} dict 리스트 → BaseMessage 리스트(스펙 270 히스토리 프록시용). 엔진이 ainvoke에
    splat하므로 노드 상태의 BaseMessage와 정합해야 함. role: assistant→AI, system→System, 그 외→Human."""
    out: list = []
    for m in dicts:
        role = m.get("role")
        content = m.get("content") or ""
        if role == "assistant":
            out.append(AIMessage(content=content))
        elif role == "system":
            out.append(SystemMessage(content=content))
        else:
            out.append(HumanMessage(content=content))
    return out


class _HistoryWindowProxy:
    """단기 기억 창 프록시(스펙 270, _MemoryRecallProxy의 형제) — 노드형 노드가 **각자** 자기 depth로
    이전 대화를 슬라이스한다. 원본 대화를 생성 시 고정하고 depth로 캐싱(같은 depth=같은 슬라이스 공유).

    - 수명 = 한 턴(요청). 스코프 = 원본 대화(요청 것)로 **고정**(RBAC — 노드가 남의 대화 못 봄).
    - 슬라이스 = `_window(전체대화, depth)[:-1]` — 현재 턴은 그래프가 별도 시드하므로 분리(회귀 등가:
      depth=D면 D-1개 이전 대화 + 시드된 현재 턴 = 총 D개, 오늘 _window(conv, D)와 동일 집합).
    - depth=None → 기본(에이전트 historyDepth) 상속. 반환은 **BaseMessage 리스트**(엔진이 splat).
    - 조회마다 (node, depth, count) 기록 → trace["historyWindows"](082 조회 계측). **내용 아닌 건수만**
      기록 → 대화 누출 0(243 ③ 형제 표면 마스킹 규약). record=False면 기록 생략(도구 루프 재진입용)."""

    def __init__(
        self,
        conversation: list,
        default_depth: int | None,
        records: list[dict],
        drop_last: bool = True,
    ):
        # drop_last(codex 270 High): 메인 경로의 conversation은 **현재 턴 포함**(body.messages 끝=현재 턴,
        # 그래프가 별도 시드)이라 [:-1]로 분리. 재개 경로의 conversation은 세션 DB서 로드한 **이전 대화만**
        # (현재 턴은 아직 미영속 — 체크포인트가 보유)이라 drop_last=False(안 버림). 이 구분이 없으면 재개가
        # 직전 assistant 메시지를 잘못 떨궈 원 턴과 다른 창을 본다.
        self._conv = conversation
        self._default = default_depth
        self._drop = drop_last
        self._cache: dict = {}  # depth 키 → 슬라이스(BaseMessage 리스트)
        self.records = records

    async def __call__(self, depth: int | None = None, node: str = "", record: bool = True) -> list:
        d = self._default if depth is None else depth
        key = "all" if (d is None or d < 0) else d
        if key not in self._cache:
            win = _window(self._conv, d) if self._conv else []
            self._cache[key] = win[:-1] if (self._drop and win) else win
        sliced = self._cache[key]
        if record:
            self.records.append({"node": node, "depth": d, "count": len(sliced)})
        return sliced


async def _load_session_conversation(
    session_id: str | None, agent_pk: uuid.UUID, limit: int | None = None
) -> list[dict]:
    """세션의 영속 대화를 {role, content} 리스트로 로드(스펙 270 재개 + 289 P1 서버 재구성 공용).

    limit(스펙 289 — 캐시 대신 읽기량 상수 고정): 최신 N개만 역순 조회 후 정순 반환. None=전체
    (재개 경로 무회귀). 세션·메시지 없으면 빈 리스트(graceful — 새/타인 세션 id는 해석 단계에서
    이미 빈 새 세션으로 접혀 있어 여기서 자연히 [])."""
    if not session_id:
        return []
    async with SessionLocal() as db:
        sess_pk = (
            await db.execute(
                select(Session.id).where(
                    Session.session_id == session_id, Session.agent_pk == agent_pk
                )
            )
        ).scalar_one_or_none()
        if sess_pk is None:
            return []
        q = select(Message).where(Message.session_pk == sess_pk).order_by(Message.id.desc())
        if limit is not None and limit >= 0:
            q = q.limit(limit)
        rows = list((await db.execute(q)).scalars().all())
        return [{"role": m.role, "content": m.content} for m in reversed(rows)]


def _node_history_depths(nodes: list) -> list[int] | None:
    """노드별 historyDepth 수집 — 음수(전체) depth가 하나라도 있으면 None(전량 신호).
    노드 depth None은 '상속'이라 에이전트 값으로 이미 대표된다(스킵)."""
    depths: list[int] = []
    for n in nodes:
        d = n.get("historyDepth")
        if d is None:
            continue
        if isinstance(d, int) and d < 0:
            return None
        if isinstance(d, int):
            depths.append(d)
    return depths


def _history_load_limit(ctx: dict) -> int | None:
    """서버 재구성 시 읽을 이전 대화 상한(스펙 289 P1) — 에이전트·노드가 요구할 수 있는 최대 depth.
    None(전체)·음수(전체) depth가 하나라도 있으면 전량(None)."""
    agent_d = ctx.get("history_depth")
    if agent_d is None or (isinstance(agent_d, int) and agent_d < 0):
        return None
    node_depths = _node_history_depths(ctx.get("nodes_resolved") or [])
    if node_depths is None:
        return None
    return max([int(agent_d), *node_depths])


# 전송 프롬프트 캡처 상한(스펙 131) — 메시지당 자수 캡 + **개수 캡**(codex 131 #3: historyDepth
# 오버라이드로 무제한 히스토리가 trace JSONB에 통째 영속되는 비대 차단).
_SENT_MSG_CHAR_CAP = 2000
_SENT_MSG_COUNT_CAP = 30


def _build_sent_messages(persona_prompt: str, messages: list[dict]) -> list[dict]:
    """전송 프롬프트 전문 캡처(스펙 131) — 실제 그래프 입력(system=persona+회상 포함)을 표시용으로.

    안전장치: (a) 메시지당 자수 캡, (b) 개수 캡(초과분은 생략 표식 1건으로), (c) **비밀 마스킹 백스톱**
    (codex 131 #2 — 페르소나/오버라이드에 사용자가 적은 API 키가 trace JSONB에 복제되지 않게,
    125 _sanitize 재사용). 원문 전문은 저장하지 않는다(캡 절단본)."""
    from .memory import _sanitize as _mask

    out = [{"role": "system", "content": _mask(persona_prompt, cap=_SENT_MSG_CHAR_CAP)}]
    tail = messages[-_SENT_MSG_COUNT_CAP:]
    omitted = len(messages) - len(tail)
    if omitted > 0:
        out.append(
            {
                "role": "notice",
                "content": f"(이전 {omitted}개 메시지 생략 — 표시 상한 {_SENT_MSG_COUNT_CAP}개)",
            }
        )
    out.extend(
        {"role": m["role"], "content": _mask(m["content"] or "", cap=_SENT_MSG_CHAR_CAP)}
        for m in tail
    )
    return out


def _format_sent_measured(call: list[dict]) -> list[dict]:
    """실측 모델 호출 메시지 → 표시용(스펙 205) — 131과 같은 캡·마스킹. 첫 메시지(system)는 항상
    보존하고 나머지는 꼬리 캡(재구성판과 동일 시맨틱)."""
    from .memory import _sanitize as _mask

    if not call:
        return []
    head, rest = call[0], call[1:]
    out = [
        {
            "role": head.get("role", "system"),
            "content": _mask(head.get("content") or "", cap=_SENT_MSG_CHAR_CAP),
        }
    ]
    tail = rest[-_SENT_MSG_COUNT_CAP:]
    omitted = len(rest) - len(tail)
    if omitted > 0:
        out.append(
            {
                "role": "notice",
                "content": f"(이전 {omitted}개 메시지 생략 — 표시 상한 {_SENT_MSG_COUNT_CAP}개)",
            }
        )
    out.extend(
        {
            "role": m.get("role", "?"),
            "content": _mask(m.get("content") or "", cap=_SENT_MSG_CHAR_CAP),
        }
        for m in tail
    )
    return out

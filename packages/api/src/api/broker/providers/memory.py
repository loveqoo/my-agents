"""kind=memory/memwrite/memedit provider 3종(스펙 104/105/111) — 유저 장기 기억 능력.

3종 묶음 유지 근거(지도 G5): `_MemBacking` 공유·self-scope 불변식(스코프=principal 도출 user_id,
cap_id·args로 남을 가리킬 수 없음) 공유 — 쪼개면 상호참조만 생긴다. `_memwrite_text`↔Write,
`_memedit_args`↔Edit는 승인·실행 공유 헬퍼(드리프트 0 짝, 같은 모듈 필수).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from agent.runtime import Capability, InvokeResult

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..common import (
    CAP_KIND_MEMORY,
    CAP_KIND_MEMORY_EDIT,
    CAP_KIND_MEMORY_WRITE,
    _kind_of,
    _parse_mem,
    _parse_memedit,
    _parse_memwrite,
)


class _MemBacking:
    """MemoryProvider.load가 돌려주는 backing — 리소스 종류만 담는다(첫 출하 `"user"`).
    **대상 user_id는 여기 없다** — invoke가 provider의 self._user_id(principal 도출값)만 스코프로 쓴다."""

    __slots__ = ("resource",)

    def __init__(self, resource: str) -> None:
        self.resource = resource


class MemoryProvider:
    """kind=memory — 유저 장기 기억(user_id 축)을 **읽기 전용** 검색 능력으로. 첫 **per-user 소유** 능력.

    핵심(스펙 104): 능력은 `memory:user` 하나뿐이고 **누구의 기억인지는 cap_id·args가 아니라 런타임
    principal에서 도출한 `user_id`**로 정한다. 그래서 능력 이름으로 남을 가리킬 방법이 없어 교차 유저
    유출이 구조적으로 불가능하다. 검색 코어 `memory.recall_probe`(챗 회상·retrieval 시험 084와 공유) +
    `memory.format_memory_hits`(챗 회상 주입 포맷 추출, drift 0) 재사용. 읽기 전용 → `approval_for` None.
    결과는 기억 내용 = **untrusted 데이터**(learning 100 채널 격리는 flow synthesize 몫).
    """

    kind = CAP_KIND_MEMORY

    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], user_id: str | None
    ) -> None:
        self._session_factory = session_factory
        self._user_id = (
            user_id  # principal 도출값(build_broker). None=머신 → 자기 스코프 없음 → deny.
        )

    def _cap(self, *, with_schema: bool) -> Capability:
        cap = Capability(
            id=f"{CAP_KIND_MEMORY}:user",
            kind=CAP_KIND_MEMORY,
            name="내 장기 기억",
            hook="내 장기 기억(user_id 축)에서 관련 사실 회상",
        )
        if with_schema:
            cap.input_schema = {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "limit": {"type": "integer", "default": 4},
                },
                "required": ["text"],
            }
        return cap

    async def candidates(self, allow: set[str]) -> list[Capability]:
        # user_id 없음(머신 principal) → 자기 스코프가 없으므로 능력 없음(DB·백엔드 미접촉). cap 문법상
        # `memory:` 항목 중 리소스가 `user`인 것만 승격(빈/미지원 리소스 거부, 적대 리뷰 대비).
        if not self._user_id:
            return []
        if not any(_kind_of(a) == CAP_KIND_MEMORY and _parse_mem(a) == "user" for a in allow):
            return []
        return [self._cap(with_schema=False)]

    async def load(self, cap_id: str) -> _MemBacking | None:
        # 리소스가 `user`가 아니거나(미지원/빈) user_id 없으면 없는 것으로(존재 비노출).
        if not self._user_id or _parse_mem(cap_id) != "user":
            return None
        return _MemBacking("user")

    def describe(self, _row: _MemBacking) -> Capability:
        return self._cap(with_schema=True)

    async def invoke(self, _row: _MemBacking, args: dict) -> InvokeResult:
        cap_id = f"{CAP_KIND_MEMORY}:user"
        raw = {"cap_id": cap_id, "kind": CAP_KIND_MEMORY}
        # 스코프는 **오직** principal 도출 user_id — args의 어떤 필드(user_id 등)도 무시(anti-leak 불변식).
        text = str(args.get("text", "")) if isinstance(args, dict) else str(args)
        limit = args.get("limit", 4) if isinstance(args, dict) else 4
        from ... import memory
        from ...mem_config import default_mem_cfg

        async with self._session_factory() as db:
            mem_cfg = await default_mem_cfg(db)
        # recall_probe: 백엔드 *가용성*을 결과와 구분(None=미가용). 챗 경로 `search`와 코어 공유(drift 0).
        # 스펙 158: 전 축 검색 실패는 recall_probe가 던진다 → 여기서 잡아 error로 표면화([]로 접으면
        # "실패를 0건으로 위장"이 재발). invoke 자체는 안 죽고(런타임 견고) error 필드로 정직히 알린다.
        try:
            hits = await asyncio.to_thread(
                memory.recall_probe, {"user_id": self._user_id}, text, mem_cfg, limit
            )
        except Exception as exc:
            return InvokeResult(
                text="",
                trust="untrusted",
                error=f"메모리 회상 실행 실패({type(exc).__name__}).",
                raw=raw,
            )
        if hits is None:
            return InvokeResult(
                text="",
                trust="untrusted",
                error="메모리 백엔드가 구성되지 않아 회상할 수 없습니다.",
                raw=raw,
            )
        # 결과 = 기억 내용 = **데이터**(지시 아님). 챗 회상 주입과 동일 포맷(drift 0).
        return InvokeResult(
            text=memory.format_memory_hits(hits), trust="untrusted", error=None, raw=raw
        )

    def node_label(self, _row: _MemBacking) -> str:
        return f"broker_invoke:{CAP_KIND_MEMORY}:user"

    def approval_for(
        self, _row: _MemBacking, _cap_id: str, _args: dict, _tool_policy: dict | None = None
    ) -> dict | None:
        return None  # 메모리 읽기=부수효과 없음 → 승인 게이트 불요(memory write는 스펙 105).


# memory write 승인 permission — 066 self-approve/민감도 라벨(memory.write는 member 소유자 self-승인 기본).
MEMWRITE_PERMISSION = "memory.write"
_MEMWRITE_PREVIEW = 200  # 승인 summary에 노출할 저장 사실 미리보기 상한.
# 저장·승인 사실 길이 상한(적대 리뷰 105 P2). 브로커는 args.text를 무검증으로 받아 거대 사실이 승인
# DB(JSONB)·응답·저장 기억을 무제한 점유할 수 있었다. memory 질의 상한(4000, MemorySearchIn)과 같은
# 경계로. **approval_for와 invoke가 동일 헬퍼로 자르므로 "승인한 것 == 저장되는 것"**(길이도 일치).
MEMWRITE_MAX_CHARS = 4000


def _memwrite_text(args: dict) -> str:
    """저장할 사실 추출 — strip + 길이 상한(승인·저장 공유 = 드리프트 0). 비-dict args 방어."""
    text = str(args.get("text", "")) if isinstance(args, dict) else str(args)
    return text.strip()[:MEMWRITE_MAX_CHARS]


class MemoryWriteProvider:
    """kind=memwrite — 유저 장기 기억(user_id 축)에 사실을 **저장**. 브로커 **첫 부수효과 능력**이라
    승인 게이트가 처음 발화한다(`approval_for` **항상 non-None** — 읽기 provider들과 정반대).

    두 구조적 방어(스펙 105):
    1. **쓰기 축=user_id(자기)만·principal 바인딩** — `{"user_id": self._user_id}`에만 쓴다(agent_id 금지,
       051 교차유저 누출 축). user_id는 cap_id·args가 아니라 principal 도출값(104와 동일) → 남의 기억에
       쓸 방법이 구조적으로 없다. 자기 스코프 쓰기는 정의상 교차유저 누출 불가.
    2. **승인 게이트** — 브로커가 `memory.add`(부수효과) 이전 `interrupt`로 멈추고 승인돼야 저장(learning
       031: "기억해줘"를 프롬프트 금지보다 우선하는 LLM은 프롬프트 아닌 *구조*로 막는다). 승인 payload는
       저장될 사실을 **그대로 노출**(마스킹 X — 승인하려면 봐야 함). 저장은 **infer=False**(승인=저장 일치).
    """

    kind = CAP_KIND_MEMORY_WRITE

    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], user_id: str | None
    ) -> None:
        self._session_factory = session_factory
        self._user_id = (
            user_id  # principal 도출값(build_broker) — read provider와 공유. None=머신→deny.
        )

    def _cap(self, *, with_schema: bool) -> Capability:
        cap = Capability(
            id=f"{CAP_KIND_MEMORY_WRITE}:user",
            kind=CAP_KIND_MEMORY_WRITE,
            name="내 장기 기억에 저장",
            hook="내 장기 기억(user_id 축)에 사실 저장 — 저장 전 승인 필요",
        )
        if with_schema:
            cap.input_schema = {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            }
        return cap

    async def candidates(self, allow: set[str]) -> list[Capability]:
        # user_id 없음(머신) → 자기 스코프 없음 → 능력 없음. `memwrite:user`만 승격(빈/미지원 거부).
        if not self._user_id:
            return []
        if not any(
            _kind_of(a) == CAP_KIND_MEMORY_WRITE and _parse_memwrite(a) == "user" for a in allow
        ):
            return []
        return [self._cap(with_schema=False)]

    async def load(self, cap_id: str) -> _MemBacking | None:
        if not self._user_id or _parse_memwrite(cap_id) != "user":
            return None  # 미지원 리소스·머신 → 존재 비노출
        return _MemBacking("user")

    def describe(self, _row: _MemBacking) -> Capability:
        return self._cap(with_schema=True)

    async def invoke(self, _row: _MemBacking, args: dict) -> InvokeResult:
        # 여기 도달 = 브로커가 approval_for→interrupt로 **이미 승인**을 받은 경우만(부수효과 1회, §7 멱등).
        cap_id = f"{CAP_KIND_MEMORY_WRITE}:user"
        raw = {"cap_id": cap_id, "kind": CAP_KIND_MEMORY_WRITE}
        text = _memwrite_text(
            args
        )  # strip + 길이 상한(승인 payload와 동일 = 승인한 것 == 저장되는 것)
        if not text:
            # 빈 사실은 **저장하지 않는다**(부수효과 0). 무의미 기억 방지.
            return InvokeResult(
                text="", trust="untrusted", error="저장할 내용이 비어 있습니다.", raw=raw
            )
        from ... import memory
        from ...mem_config import default_mem_cfg

        async with self._session_factory() as db:
            mem_cfg = await default_mem_cfg(db)
        if memory.resolve_backend(mem_cfg) is None:
            return InvokeResult(
                text="",
                trust="untrusted",
                error="메모리 백엔드가 구성되지 않아 저장할 수 없습니다.",
                raw=raw,
            )
        # 스코프는 **오직** principal 도출 user_id(agent_id·run_id·args 불가). infer=False=승인한 원문 저장.
        await asyncio.to_thread(
            memory.add,
            {"user_id": self._user_id},
            [{"role": "user", "content": text}],
            mem_cfg,
            False,
        )
        # 결과=저장 확인. 반향된 사실이 데이터 채널로 흐를 수 있어 trust=untrusted(일관).
        return InvokeResult(
            text=f"장기 기억에 저장했습니다: {text}", trust="untrusted", error=None, raw=raw
        )

    def node_label(self, _row: _MemBacking) -> str:
        return f"broker_invoke:{CAP_KIND_MEMORY_WRITE}:user"

    def approval_for(
        self, _row: _MemBacking, _cap_id: str, args: dict, _tool_policy: dict | None = None
    ) -> dict | None:
        # 쓰기=부수효과 → **항상 승인**(None 절대 안 돌림). 저장될 사실을 마스킹 없이 노출(승인 가시성).
        text = _memwrite_text(args)  # invoke와 동일 헬퍼(길이 상한 일치) → 승인한 것 == 저장되는 것
        preview = text[:_MEMWRITE_PREVIEW] + ("…" if len(text) > _MEMWRITE_PREVIEW else "")
        return {
            "permission": MEMWRITE_PERMISSION,  # 066 self-approve — 소유자 본인 승인(member 기본 정책)
            "action": MEMWRITE_PERMISSION,
            "args": {"text": text},  # 미마스킹 — 사람이 무엇이 저장되는지 봐야 승인 가능
            "summary": f"장기 기억에 저장: {preview} — 승인 필요",
        }


# ---- 스펙 111: 메모리 수정/삭제(memedit) — 대상 있는 첫 브로커 부수효과 --------------------------
# add(105)와 결정적 차이: add는 자기 스코프 *생성*(대상 없음)이나 update/delete는 **기존 mem_id 대상**
# → 소유권 선행(learning 054·069). approval_for와 invoke가 `_memedit_args`로 동일 정규화 → "승인한 것 ==
# 실행되는 것". 삭제 비가역이라 RBAC는 fail-closed(member 시드 없음, admin/superuser만; 105 self_approve
# 보다 민감도 상향). 소유권 술어는 `memory.user_owns` 단일 출처(HTTP 라우트와 공유, 드리프트 0).
MEMEDIT_PERMISSION = (
    "memory.edit"  # admin('*','*')만 승인 가능 — member 시드 없음(삭제 비가역 fail-closed).
)
MEMEDIT_MAX_CHARS = 4000
_MEMEDIT_PREVIEW = 200


def _memedit_args(args: dict) -> tuple[str, str, str]:
    """(op, mem_id, text) 정규화 — 승인·실행 공유(드리프트 0). 비-dict 방어. text는 update 전용."""
    if not isinstance(args, dict):
        return "", "", ""
    op = str(args.get("op", "")).strip().lower()
    mem_id = str(args.get("mem_id", "")).strip()
    text = str(args.get("text", "")).strip()[:MEMEDIT_MAX_CHARS]
    return op, mem_id, text


class MemEditProvider:
    """kind=memedit — 유저 장기 기억(user_id 축)을 **수정/삭제**. 대상 있는 첫 브로커 부수효과.

    세 구조적 방어(스펙 111):
    1. **스코프=principal 도출 user_id 고정** — args의 user_id 등 무시(104/105 anti-leak 불변식).
    2. **대상 소유권 선행** — mem_id가 자기 것인지 `memory.user_owns`로 확인(미소유·부재 동일 error로
       404-fold = 존재 비노출, 068). add(105)엔 없던 축(대상이 있으므로).
    3. **승인 게이트 항상** — 부수효과 이전 interrupt. 승인 payload는 op·mem_id·(update)새 본문을
       마스킹 없이 노출. 삭제 비가역이라 RBAC fail-closed(member 시드 없음).
    """

    kind = CAP_KIND_MEMORY_EDIT

    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], user_id: str | None
    ) -> None:
        self._session_factory = session_factory
        self._user_id = (
            user_id  # principal 도출값(build_broker) — read/write provider와 공유. None=머신→deny.
        )

    def _cap(self, *, with_schema: bool) -> Capability:
        cap = Capability(
            id=f"{CAP_KIND_MEMORY_EDIT}:user",
            kind=CAP_KIND_MEMORY_EDIT,
            name="내 장기 기억 수정·삭제",
            hook="내 장기 기억(user_id 축) 수정/삭제 — 실행 전 승인 필요",
        )
        if with_schema:
            cap.input_schema = {
                "type": "object",
                "properties": {
                    "op": {"type": "string", "enum": ["update", "delete"]},
                    "mem_id": {"type": "string"},
                    "text": {"type": "string"},
                },
                "required": ["op", "mem_id"],
            }
        return cap

    async def candidates(self, allow: set[str]) -> list[Capability]:
        # user_id 없음(머신) → 자기 스코프 없음 → 능력 없음(DB 미접촉). `memedit:user`만 승격.
        if not self._user_id:
            return []
        if not any(
            _kind_of(a) == CAP_KIND_MEMORY_EDIT and _parse_memedit(a) == "user" for a in allow
        ):
            return []
        return [self._cap(with_schema=False)]

    async def load(self, cap_id: str) -> _MemBacking | None:
        if not self._user_id or _parse_memedit(cap_id) != "user":
            return None  # 미지원 리소스·머신 → 존재 비노출
        return _MemBacking("user")

    def describe(self, _row: _MemBacking) -> Capability:
        return self._cap(with_schema=True)

    @staticmethod
    def _validate(op: str, mem_id: str, text: str) -> str | None:
        """입력 검증(부수효과 0) — 실패 사유 메시지 또는 None(통과)."""
        if op not in ("update", "delete"):
            return "지원하지 않는 작업입니다 (update/delete)."
        if not mem_id:
            return "대상 기억 id가 없습니다."
        if op == "update" and not text:
            return "수정할 내용이 비어 있습니다."
        return None

    async def _apply(
        self, op: str, mem_id: str, text: str, mem_cfg: dict | None, raw: dict
    ) -> InvokeResult:
        """소유권 선행 확인 후 update/delete 실행 — 미소유·부재 **동일 error**(404-fold, 존재 비노출).

        **check-then-act 하중 가정(codex 111 [P1] — 정직화)**: user_owns 확인과 mutation이 원자적으로
        묶이지 않는다(백엔드 계약이 scope 없는 전역 mem_id 대상). 안전한 이유 두 사실: (1) mem_id =
        **전역 유일 UUID**(mem0 memory_id), (2) 기억 소유자(user_id)는 **불변**(이전 연산 없음) → "확인 후
        다른 유저 행으로 해석"되는 창이 구조적으로 없다(HTTP `_assert_user_owns`→`update_memory`와 동일
        잔존). 두 가정을 깨는 백엔드는 scope-bound 원자 mutation을 제공해야 한다(fail-closed; 현 mem0
        API엔 없어 재구조화 불가 = OUT). 안전 불변식은 verify_111 교차유저 거부가 실증.
        스코프=self._user_id(고정).
        """
        from ... import memory

        def err(msg: str) -> InvokeResult:  # 부수효과 0으로 실패 반환(guard)
            return InvokeResult(text="", trust="untrusted", error=msg, raw=raw)

        assert self._user_id is not None  # load()가 user_id 부재 시 None → invoke/_apply 미도달
        if not await asyncio.to_thread(memory.user_owns, self._user_id, mem_id, mem_cfg):
            return err("이 유저의 기억이 아닙니다.")
        if op == "update":
            ok = await asyncio.to_thread(memory.update_memory, mem_id, text, mem_cfg)
            if not ok:
                return err("메모리 수정 실패")
            preview = text[:_MEMEDIT_PREVIEW] + ("…" if len(text) > _MEMEDIT_PREVIEW else "")
            return InvokeResult(text=f"기억을 수정했습니다: {preview}", trust="untrusted", raw=raw)
        ok = await asyncio.to_thread(memory.delete_memory, mem_id, mem_cfg)
        if not ok:
            return err("메모리 삭제 실패")
        return InvokeResult(text="기억을 삭제했습니다.", trust="untrusted", raw=raw)

    async def invoke(self, _row: _MemBacking, args: dict) -> InvokeResult:
        # 여기 도달 = approval_for→interrupt로 **이미 승인**된 경우만(부수효과 1회, 멱등).
        cap_id = f"{CAP_KIND_MEMORY_EDIT}:user"
        raw = {"cap_id": cap_id, "kind": CAP_KIND_MEMORY_EDIT}
        op, mem_id, text = _memedit_args(
            args
        )  # 승인 payload와 동일 정규화(승인한 것 == 실행되는 것)
        invalid = self._validate(op, mem_id, text)
        if invalid:
            return InvokeResult(text="", trust="untrusted", error=invalid, raw=raw)
        from ... import memory
        from ...mem_config import default_mem_cfg

        async with self._session_factory() as db:
            mem_cfg = await default_mem_cfg(db)
        if memory.resolve_backend(mem_cfg) is None:
            return InvokeResult(
                text="",
                trust="untrusted",
                error="메모리 백엔드가 구성되지 않아 수정/삭제할 수 없습니다.",
                raw=raw,
            )
        return await self._apply(op, mem_id, text, mem_cfg, raw)

    def node_label(self, _row: _MemBacking) -> str:
        return f"broker_invoke:{CAP_KIND_MEMORY_EDIT}:user"

    def approval_for(
        self, _row: _MemBacking, _cap_id: str, args: dict, _tool_policy: dict | None = None
    ) -> dict | None:
        # 수정/삭제=부수효과 → **항상 승인**(None 절대 안 돌림). 마스킹 없이 노출(승인 가시성).
        op, mem_id, text = _memedit_args(args)  # invoke와 동일 정규화 → 승인한 것 == 실행되는 것
        if op == "delete":
            summary = f"장기 기억 삭제(id={mem_id}) — 승인 필요"
            payload_args = {"op": "delete", "mem_id": mem_id}
        elif op == "update":
            preview = text[:_MEMEDIT_PREVIEW] + ("…" if len(text) > _MEMEDIT_PREVIEW else "")
            summary = f"장기 기억 수정(id={mem_id}): {preview} — 승인 필요"
            payload_args = {"op": "update", "mem_id": mem_id, "text": text}
        else:
            summary = f"장기 기억 작업(op={op or '미지정'}, id={mem_id}) — 승인 필요"
            payload_args = {"op": op, "mem_id": mem_id}
        return {
            "permission": MEMEDIT_PERMISSION,  # admin 전용(member 시드 없음 — 삭제 비가역 fail-closed)
            "action": MEMEDIT_PERMISSION,
            "args": payload_args,  # 미마스킹 — 사람이 무엇이 바뀌는지 봐야 승인 가능
            "summary": summary,
        }

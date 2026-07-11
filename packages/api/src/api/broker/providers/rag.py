"""kind=rag provider(스펙 103) — 문서 컬렉션을 읽기 전용 검색 능력으로."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from agent.runtime import Capability, InvokeResult

from ..common import CAP_KIND_RAG, _first_line, _kind_of, _parse_rag, _rt

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from ...models import Collection


class _RagBacking:
    """RagProvider.load가 돌려주는 backing — 컬렉션 이름·설명 + retrieval 코어용 `col` dict.
    `col`이 None이면 임베딩 설정 불완전(describe는 되고 invoke가 graceful 오류로 표면화)."""

    __slots__ = ("col", "description", "name")

    def __init__(self, name: str, description: str, col: dict | None) -> None:
        self.name = name
        self.description = description
        self.col = col


class RagProvider:
    """kind=rag — `Collection`(문서 컬렉션)을 **읽기 전용** 검색 능력으로. 전송은 `runtime.search_collections`
    코어(인-챗 RAG 도구·retrieval 시험 072와 공유) + `runtime.format_rag_hits`(스펙 103 공유 포맷터)를
    재사용 = 평행 구현 0. 부수효과 없음 → `approval_for` 항상 None(HIL 불요, 저위험의 핵심).
    결과는 문서 내용 = **untrusted 데이터**(learning 100 채널 격리는 flow synthesize 몫)."""

    kind = CAP_KIND_RAG

    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], min_scores: dict | None = None
    ) -> None:
        self._session_factory = session_factory
        # 컬렉션별 최소 유사도 맵(스펙 191 v2) — invoke가 row.name으로 조회해 그 컬렉션 임계값을 적용.
        self._min_scores = min_scores if isinstance(min_scores, dict) else {}

    async def _load_rows(self, names: set[str]) -> list:
        """Collection 행을 embedding_model.provider까지 selectinload(col dict 구성에 필요)."""
        from sqlalchemy.orm import selectinload

        from ...models import Collection, ModelConfig

        async with self._session_factory() as db:
            return (
                (
                    await db.execute(
                        select(Collection)
                        .where(Collection.name.in_(names))
                        .options(
                            selectinload(Collection.embedding_model).selectinload(
                                ModelConfig.provider
                            )
                        )
                    )
                )
                .scalars()
                .all()
            )

    def _col_dict(self, c: Collection) -> dict | None:
        """Collection → retrieval 코어 계약 dict. **chat._load_context와 동일 규칙**(drift 0). 임베딩
        모델/provider 불완전하거나 kind!=embedding이면 None(search_collection 400 가드와 동형)."""
        from ... import crypto

        em = c.embedding_model
        ep = em.provider if em else None
        if em is None or ep is None or not ep.base_url or not em.model_id or em.kind != "embedding":
            return None
        return {
            "id": c.id,
            "name": c.name,
            "embed_base_url": ep.base_url,
            "embed_api_key": crypto.decrypt(ep.api_key),  # 백엔드 전용 — 응답/로그 미노출
            "embed_model_id": em.model_id,
        }

    async def candidates(self, allow: set[str]) -> list[Capability]:
        # 빈 리소스 이름(`rag:`)은 능력으로 승격 안 함(적대 리뷰 103 P2 — cap_id 문법상 빈 id 거부).
        # 근본(컬렉션 이름 min_length)은 스펙 037 CRUD 영역이라 여기선 파싱 층에서 방어만 한다.
        names = {n for a in allow if _kind_of(a) == CAP_KIND_RAG and (n := _parse_rag(a))}
        if not names:
            return []  # rag-kind 항목 없음 → DB 미접촉
        # allowlist를 SELECT WHERE에 밀어 거부 대상을 로드조차 안 함(체크리스트 §2 존재 오라클 차단).
        rows = await self._load_rows(names)
        return [
            Capability(
                id=f"{CAP_KIND_RAG}:{c.name}",
                kind=CAP_KIND_RAG,
                name=c.name,
                hook=_first_line(c.description or "", c.name),
            )
            for c in rows
        ]

    async def load(self, cap_id: str) -> _RagBacking | None:
        name = _parse_rag(cap_id)
        if not name:
            return None  # 빈 리소스 이름 → 없는 것으로(적대 리뷰 103 P2)
        rows = await self._load_rows({name})
        if not rows:
            return None  # 미존재 → 존재 비노출
        c = rows[0]
        return _RagBacking(c.name, c.description or "", self._col_dict(c))

    def describe(self, row: _RagBacking) -> Capability:
        return Capability(
            id=f"{CAP_KIND_RAG}:{row.name}",
            kind=CAP_KIND_RAG,
            name=row.name,
            hook=_first_line(row.description, row.name),
            input_schema={
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "top_k": {"type": "integer", "default": 4},
                },
                "required": ["text"],
            },
        )

    async def invoke(self, row: _RagBacking, args: dict) -> InvokeResult:
        cap_id = f"{CAP_KIND_RAG}:{row.name}"
        if row.col is None:
            return InvokeResult(
                text="",
                trust="untrusted",
                error=f"컬렉션 '{row.name}'의 임베딩 설정이 불완전해 검색할 수 없습니다.",
                raw={"cap_id": cap_id, "kind": CAP_KIND_RAG},
            )
        text = str(args.get("text", "")) if isinstance(args, dict) else str(args)
        top_k = args.get("top_k", 4) if isinstance(args, dict) else 4
        rt = _rt()
        # 검색 질의 표시(스펙 191) — 직접 인-챗 RAG 도구는 이미 args.query를 trace에 노출한다.
        # 조율형(브로커)도 같은 표시-안전 값을 보이게 raw에 싣되, 비밀 마스킹(_sanitize)+캡을
        # 백스톱으로 건다(일반 args 노출이 아니라 RAG 질의 1개만 — 087/092 원문 누출 경계 유지).
        from ...memory import _sanitize as _san

        query_disp = _san((text or "").strip(), cap=300)
        # 이 컬렉션의 임계값(스펙 191 v2) — 맵에서 조회, 없으면 0(무필터).
        thr = rt._norm_score(self._min_scores.get(row.name, 0.0))
        try:
            hits = await rt.search_collections(
                [row.col], text, top_k, {row.name: thr}
            )  # 커트라인 annotate
            # 결과 = 문서 내용 = **데이터**(지시 아님). trust=untrusted 불변(인젝션 방어).
            # 스펙 192: used(커트라인 통과분)만 에이전트에 넘긴다(미달 문서 안 봄). trace(hitsDetail)엔 전부
            # (used+dropped 플래그) — 인스펙터가 "못 쓴 문서"까지 보이게. hits=used 수·topScore=used 최고.
            used = rt.used_hits(hits)
            top = max((float(h.get("score", 0.0)) for h in used), default=0.0)
            return InvokeResult(
                text=rt.format_rag_hits(used),  # 인-챗 도구와 공유 포맷(drift 0)
                trust="untrusted",
                error=None,
                raw={
                    "cap_id": cap_id,
                    "kind": CAP_KIND_RAG,
                    "hits": len(used),
                    "topScore": round(top, 3),
                    "hitsDetail": rt._hits_detail(hits),
                    "minScore": round(thr, 3),
                    "query": query_disp,
                },
            )
        except rt.RagSearchError as exc:
            # 코어가 이미 분류(empty/embed/db) — graceful 오류로 접어 에이전트를 죽이지 않는다.
            # 실패해도 무엇을 검색했는지(query)는 남긴다(스펙 191 — 진단 가치).
            return InvokeResult(
                text="",
                trust="untrusted",
                error=exc.tool_msg,
                raw={"cap_id": cap_id, "kind": CAP_KIND_RAG, "query": query_disp},
            )

    def node_label(self, row: _RagBacking) -> str:
        return f"broker_invoke:{CAP_KIND_RAG}:{row.name}"

    def approval_for(
        self, _row: _RagBacking, _cap_id: str, _args: dict, _tool_policy: dict | None = None
    ) -> dict | None:
        return None  # RAG=읽기 전용(부수효과 없음) → 승인 게이트 불요.

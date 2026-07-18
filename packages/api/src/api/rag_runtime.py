"""RAG 런타임 — 검색 코어·RAG 도구 어댑터(스펙 380·캠페인 374 T2, runtime.py에서 분리).

MCP 런타임(runtime.py)과 분리된 RAG 검색 도메인(search_collections·format·cutoff·build_rag_tool).
표시/트레이스 헬퍼(_sink_from·_cap·_redact_args·_sanitize_preview)는 runtime 공용 유틸 재사용 —
**단방향 의존**(runtime은 rag_runtime을 import 안 함 → 순환 0). DB/모델/임베딩은 함수 내 지연 import."""

import time
from typing import Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import StructuredTool

# 표시/트레이스 헬퍼(_sink_from·_redact_args·_sanitize_preview·캡 상수)는 runtime 공용 유틸을
# **함수 내 지연 import**로 재사용한다 — runtime이 rag_runtime을 re-export하므로 모듈 레벨 import는
# 순환이 된다(단방향·지연으로 회피). 스펙 380.


class RagSearchError(Exception):
    """공유 retrieval 코어(`search_collections`)의 실패를 호출자가 표현할 수 있게 분류해 올린다.

    도구(`build_rag_tool`)는 graceful 문자열 + calls_sink status="error"로, 시험 엔드포인트(스펙 072)는
    HTTP 상태로 매핑한다. `kind`로 분기, `record_label`은 calls_sink 라벨, `tool_msg`는 도구 반환 문자열.
    """

    def __init__(self, kind: str, record_label: str, tool_msg: str) -> None:
        self.kind = kind  # "empty" | "embed" | "db"
        self.record_label = record_label
        self.tool_msg = tool_msg
        super().__init__(tool_msg)


async def search_collections(
    collections: list[dict], query: str, top_k: int = 4, min_scores: dict | None = None
) -> list[dict]:
    """RAG 검색 공유 코어(스펙 037 본체, 072로 추출). 질의 임베딩 → pgvector cosine → 상위 청크.

    `build_rag_tool`(인-챗 도구, 문자열 포맷)과 `POST /collections/{cid}/search`(시험 엔드포인트, JSON)가
    **같은 코어**를 호출한다 — 평행 구현을 새로 짜면 drift나 "엔드포인트는 초록인데 채팅은 다름"이 된다.

    핵심 불변식: 질의는 **각 컬렉션이 인제스트에 쓴 임베딩 모델로** 임베딩해야 같은 벡터 공간에서
    cosine이 의미를 가진다(learning 035 — 진실원을 따른다). `RAG_EMBED_DIMS`로 컬럼 차원은 공유되지만
    모델이 다르면 공간이 달라 검색이 무의미하므로, (base_url, model_id)별로 질의 임베딩을 1회만 호출·캐시.

    `collections`: `_load_context`가 해석한 dict 리스트
    `{id, name, embed_base_url, embed_api_key(복호화됨), embed_model_id}`.
    반환: score(=1-cosine_distance) 내림차순 hit 리스트 `[{"score","filename","text","meta"}]`
    (관련 0건이면 []). meta=엔티티 metadata(스펙 149, 문서형은 None) — 유사도 검색 결과로
    원본 행(각 테이블 id)을 특정하는 축. 실패는 `RagSearchError`로 올린다 — 표현은 호출자가 정한다.
    """
    from sqlalchemy import select  # 지연 임포트(모듈 경량 유지)

    from . import rag_ingest
    from .db import SessionLocal
    from .models import Chunk, Document

    q = (query or "").strip()
    if not q:
        raise RagSearchError("empty", "빈 검색어", "검색어가 비어 있습니다.")
    # 질의 길이 상한(적대 리뷰 103 P2): 엔드포인트는 스키마서 4000자로 막지만 인-챗 도구·브로커 위임
    # 경로는 상한이 없어 거대 질의 1건으로 임베딩 provider를 장시간 점유할 수 있었다. 공유 코어에서
    # 한 번 잘라 세 입구(엔드포인트≤4000이라 무영향·도구·브로커)를 같은 경계로 맞춘다.
    q = q[:4000]
    # top_k 방어적 강제(타자검증): 비정상 값이 새어 들어와도 크래시 없이 기본 4로 폴백.
    try:
        k = max(1, min(int(top_k), 10))
    except (TypeError, ValueError):
        k = 4

    # 무중단 재인덱싱(스펙 313): 검색은 재인덱싱 잠금을 **보지 않는다**. `_do_reindex`가 새 벡터를
    # 전량 계산한 뒤 삭제+삽입을 **한 트랜잭션으로 원자 스왑**하므로, Postgres MVCC상 동시 검색(리더)은
    # 커밋 전까지 옛 청크를, 커밋 순간부터 새 청크를 본다 — 반쪽(옛+새 혼출)은 스냅샷 격리로 원천 불가.
    # 리더는 라이터를 기다리지 않아 스왑에 블로킹되지도 않는다. 그래서 여기서 잠금을 검사하지 않고
    # 검색을 무중단으로 흘려보낸다(스펙 312의 검색 409 배타는 이 통찰로 폐기). 쓰기(인제스트·수정·삭제·
    # 재인덱싱)끼리는 여전히 CAS 잠금으로 직렬화된다 — 검색만 예외.

    # (base_url, model_id)별 질의 임베딩 캐시 — 같은 모델을 쓰는 컬렉션은 1회만 호출.
    qvec_cache: dict[tuple[str, str], list[float]] = {}
    try:
        for col in collections:
            key = (col["embed_base_url"], col["embed_model_id"])
            if key not in qvec_cache:
                vecs = await rag_ingest.embed_texts(
                    col["embed_base_url"], col["embed_api_key"], col["embed_model_id"], [q]
                )
                qvec_cache[key] = vecs[0]
    except rag_ingest.IngestError as exc:
        raise RagSearchError("embed", "임베딩 실패", f"문서 검색 실패(질의 임베딩): {exc}") from exc
    except Exception as exc:
        raise RagSearchError(
            "embed", "임베딩 예외", "문서 검색 실패(질의 임베딩 중 오류)."
        ) from exc

    # 컬렉션별 cosine 검색 → 통합. 각 행: (dist, filename, text, meta, collection). dist 오름차순 =
    # 가까움. collection = 컬렉션명 — 컬렉션별 유사도 임계값(스펙 191 v2) 후필터·인스펙터 표시.
    # (히트→편집 진입 좌표(333·337)는 스펙 338에서 기능과 함께 제거 — 편집은 문서 목록으로 일원화.)
    hits: list[tuple[float, str, str, dict | None, str]] = []
    try:
        async with SessionLocal() as db:
            for col in collections:
                qvec = qvec_cache[(col["embed_base_url"], col["embed_model_id"])]
                dist = Chunk.embedding.cosine_distance(qvec).label("dist")
                rows = (
                    await db.execute(
                        select(Chunk.text, Document.filename, Chunk.meta, dist)
                        .join(Document, Chunk.document_id == Document.id)
                        .where(Chunk.collection_id == col["id"])
                        .order_by(dist)
                        .limit(k)
                    )
                ).all()
                for text, filename, meta, d in rows:
                    hits.append(
                        (float(d), filename or "(파일 미상)", text, meta, col.get("name", ""))
                    )
    except RagSearchError:
        raise  # 의도된 검색 오류는 원 메시지 보존(generic 재포장 금지)
    except Exception as exc:
        raise RagSearchError("db", "검색 예외", "문서 검색 실패(유사도 검색 중 오류).") from exc

    # 음수 유사도(cosine 거리>1 = 벡터가 반대 방향) 제거: 반-상관 청크는 '근거'가 될 수 없다.
    # 임의 임계값이 아니라 수학적 경계(직교=0)라 정상 매치(양수)는 절대 탈락하지 않는다. 양수
    # 구간의 관련도 임계 튜닝(예 0.3 미만 컷)은 recall 트레이드오프가 있어 빚으로 남긴다(타자검증).
    relevant = [h for h in hits if h[0] <= 1.0 + 1e-9]
    # 컬렉션 간 통합 정렬 후 상위 k. (동일 임베딩 모델 가정 — 다른 모델 간 dist 스케일 차는 빚:
    # 서로 다른 벡터 공간의 거리를 한 리스트로 정렬하면 순위가 의미를 잃는다. 멀티모델 컬렉션
    # 동시 사용은 비권장이며, 강제 방지/스코어 정규화는 후속 스펙으로 남긴다.)
    relevant.sort(key=lambda h: h[0])
    out = [
        {"score": 1.0 - d, "filename": filename, "text": text, "meta": meta, "collection": name}
        for d, filename, text, meta, name in relevant[:k]
    ]
    # 컬렉션별 커트라인을 **표시(annotate)** — 스펙 192. 드롭이 아니라 belowCutoff/cutoff 부착:
    # 인스펙터가 "쓴 문서(used) vs 커트라인 미달로 못 쓴 문서(dropped)"를 구분해 보이게. 에이전트가
    # 실제로 보는 것(used)은 호출자(build_rag_tool·RagProvider)가 `not belowCutoff`로 거른다.
    return _annotate_cutoffs(out, min_scores)


def _norm_score(v: Any) -> float:
    """유사도 임계값 정규화 — 비수치/음수/1 초과는 0(무필터)으로 접는다."""
    try:
        s = float(v)
    except (TypeError, ValueError):
        return 0.0
    return s if 0.0 < s <= 1.0 else 0.0


def _annotate_cutoffs(hits: list[dict], min_scores: dict | None) -> list[dict]:
    """컬렉션별 커트라인 표시(스펙 192) — 각 히트에 `cutoff`(그 컬렉션 임계값)+`belowCutoff`(미달 여부)를
    부착한다. **드롭하지 않는다** — 인스펙터가 used/dropped를 구분해 "못 쓴 문서"까지 보이게. 커트라인이
    없는(0/미설정) 컬렉션의 히트는 키를 안 붙인다(외부 호출자·SearchHit 스키마 안전). 순수 함수.
    used(에이전트가 보는 것)는 호출자가 `[h for h in ... if not h.get("belowCutoff")]`로 거른다."""
    if not isinstance(min_scores, dict) or not min_scores:
        return hits
    norm = {k: _norm_score(v) for k, v in min_scores.items()}
    if not any(norm.values()):
        return hits
    out: list[dict] = []
    for hit in hits:
        cut = norm.get(hit.get("collection", ""), 0.0)
        if cut > 0:
            hit = {
                **hit,
                "cutoff": round(cut, 3),
                "belowCutoff": float(hit.get("score", 0.0)) < cut,
            }
        out.append(hit)
    return out


def used_hits(annotated: list[dict]) -> list[dict]:
    """커트라인 통과분만(스펙 192) — 에이전트가 실제로 보는 문서. belowCutoff=True(미달) 제외.
    build_rag_tool·RagProvider가 format_rag_hits에 넘기기 전에 거른다(에이전트는 미달 문서 안 봄)."""
    return [h for h in annotated if not h.get("belowCutoff")]


def format_rag_hits(results: list[dict]) -> str:
    """검색 hit 리스트 → 사람이 읽을 텍스트 블록(스펙 103 공유 포맷터).

    `build_rag_tool`(인-챗 도구)와 `RagProvider.invoke`(브로커 위임, 스펙 103)가 **같은 포맷**을 쓰도록
    추출한다 — 각자 포맷하면 "도구는 이렇게, 위임은 저렇게" drift(072가 경계한 평행 구현 함정). 관련
    0건도 여기서 문자열로 확정한다(호출자별 재판단 금지).
    """
    if not results:
        return "관련 문서를 찾지 못했습니다."
    lines = [f"[문서 검색 결과 {len(results)}건]"]
    for i, h in enumerate(results, 1):
        snippet = h["text"].strip().replace("\n", " ")
        if len(snippet) > 500:
            snippet = snippet[:500] + "…"
        row = f"{i}. ({h['filename']}, 유사도 {h['score']:.3f}) {snippet}"
        # 엔티티 hit(스펙 149)은 metadata를 함께 — 에이전트가 원본 행 id를 인용/후속 조회에 쓴다.
        meta = h.get("meta")
        if isinstance(meta, dict) and meta:
            import json as _json

            mtxt = _json.dumps(meta, ensure_ascii=False)
            if len(mtxt) > 300:
                mtxt = mtxt[:300] + "…"
            row += f" [metadata: {mtxt}]"
        lines.append(row)
    return "\n".join(lines)


def _hits_detail(results: list[dict], cap: int = 240) -> list[dict]:
    """히트별 표시 구조(스펙 191) — 인스펙터가 컬렉션·파일명·유사도·본문 프리뷰를 카드로 그릴 수 있게.
    본문 프리뷰는 **캡(cap자) + 비밀 마스킹**한다(브로커 resultPreview와 동일 규율, 087/092/125 —
    trace에 원문·비밀 누출 0)."""
    from .runtime_trace_safety import (
        _sanitize_preview,  # 스펙 397: 정의 모듈로 하강(파사드 역참조 제거)
    )

    out: list[dict] = []
    for hit in results:
        # 개행 보존(스펙 255) — 엔티티 직렬화 텍스트("key: value" 라인들)를 인스펙터가 구조화
        # 렌더(EntityFields)하려면 라인 경계가 필요. 평문 청크도 pre-wrap이라 개행 무해.
        snippet = _sanitize_preview(str(hit.get("text", "")).strip(), cap)
        item = {
            "score": round(float(hit.get("score", 0.0)), 3),
            "filename": hit.get("filename", ""),
            "collection": hit.get("collection", ""),
            "textPreview": snippet,
        }
        # 엔티티 meta 관통(스펙 255 후속) — 인스펙터=디버그 영역이라 원본 행 데이터를 JSON 뷰어로
        # 제대로 보여준다. JSON 직렬화 2000자 캡(폭주 방지 — 표시-안전 규율의 상한 축), 원문 그대로
        # (스펙 149의 검색 응답과 동일 정밀도 — 마스킹으로 JSON을 깨느니 상한으로 지킨다).
        meta = hit.get("meta")
        if isinstance(meta, dict) and meta:
            import json as _json

            if len(_json.dumps(meta, ensure_ascii=False)) <= 2000:
                item["meta"] = meta
        # 스펙 192: 커트라인 표시(used/dropped). belowCutoff/cutoff가 있으면 그대로 전달(인스펙터가
        # "커트라인 미달로 못 쓴 문서"를 회색으로 구분). 커트라인 없는 히트는 키 없음(=used).
        if "belowCutoff" in hit:
            item["belowCutoff"] = bool(hit["belowCutoff"])
            item["cutoff"] = hit.get("cutoff")
        out.append(item)
    return out


def _norm_min_scores(min_scores: dict | None, names: list[str] | None = None) -> dict:
    """컬렉션별 임계값 맵 정규화(스펙 191 v2) — 값 0<x≤1인 항목만 남긴다(0/무효는 무필터라 제외).
    names 주면 그 컬렉션으로 한정(무관 항목 소거)."""
    if not isinstance(min_scores, dict):
        return {}
    allow = set(names) if names is not None else None
    out = {}
    for k, v in min_scores.items():
        if allow is not None and k not in allow:
            continue
        s = _norm_score(v)
        if s > 0:
            out[k] = round(s, 3)
    return out


def build_rag_tool(
    collections: list[dict],
    calls_sink: list[dict],
    min_scores: dict | None = None,
    name: str = "search_documents",
) -> StructuredTool:
    """RAG 문서 검색 도구(스펙 037). `search_collections` 코어를 호출해 결과를 문자열로 포맷한다.

    이 함수는 **얇은 포맷터**다 — 검색 로직은 `search_collections`에 있고(시험 엔드포인트와 공유),
    여기서는 도구 계약(graceful 문자열 + calls_sink 기록)만 책임진다. 실패는 코어가 `RagSearchError`로
    올리고, 도구는 그 `tool_msg`/`record_label`로 매핑해 에이전트를 죽이지 않는다.

    `name`(스펙 268 P1): 노드형은 컬렉션별 도구(`search_documents__<컬렉션>`)로 분리 빌드해 노드가
    컬렉션을 골라 참조한다 — 기본값은 기존 단일 도구 이름(무회귀). calls_sink 기록도 이 이름을 실어
    인스펙터가 어느 컬렉션 검색인지 구분한다.
    """
    from .runtime_trace_safety import (  # 스펙 397: 정의 모듈로 하강(파사드 역참조 제거)
        _ERR_CAP,
        _RESULT_CAP,
        _redact_args,
        _sanitize_preview,
        _sink_from,
    )

    names = ", ".join(c["name"] for c in collections)
    # 컬렉션별 임계값 맵 정규화(스펙 191 v2) — 배선된 컬렉션으로 한정, 값 0<x≤1만 유효.
    min_scores = _norm_min_scores(min_scores, [c.get("name", "") for c in collections])

    async def _search(
        query: str = "",
        top_k: int = 4,
        config: RunnableConfig = None,
    ) -> str:
        t0 = time.perf_counter()
        sink = _sink_from(config, calls_sink)  # 스펙 371 D3 — per-turn sink를 호출 인자로

        def _record(
            status: str,
            result: str,
            n: int = 0,
            detail: list[dict] | None = None,
            reason: str | None = None,
        ) -> None:
            entry = {
                "server": "rag",
                "tool": name,
                "status": status,
                "ms": int((time.perf_counter() - t0) * 1000) + 1,
                "args": _redact_args({"query": (query or "").strip(), "top_k": top_k}),
                # 스펙 191(codex 적대검토): result도 비밀 마스킹(_sanitize) — 브로커 resultPreview·
                # hitsDetail과 대칭. 직접 경로만 _cap(마스킹 없음)이던 비대칭(문서 본문 내 비밀 노출)을 닫는다.
                "result": _sanitize_preview(result, _RESULT_CAP),
                "hits": n,
                # 스펙 191 v2: 히트별 구조(컬렉션 포함) + 컬렉션별 최소 유사도 맵(인스펙터 카드·기준선용).
                "hitsDetail": detail or [],
                "minScores": dict(min_scores),
                **(
                    {"error": _sanitize_preview(reason, _ERR_CAP)} if reason else {}
                ),  # 실패 사유(스펙 320)
            }
            sink.append(entry)

        try:
            results = await search_collections(
                collections, query, top_k, min_scores
            )  # 커트라인 annotate(미드롭)
        except RagSearchError as exc:
            # record_label은 짧은 라벨(무엇을), tool_msg는 사람 사유(왜) — 사유를 인스펙터에 표면화(스펙 320).
            _record("error", exc.record_label, reason=exc.tool_msg)
            return exc.tool_msg

        # 스펙 192: 에이전트가 **실제로 보는 것은 used(커트라인 통과분)** — 미달 문서는 안 넘긴다(필터 의미
        # 유지). trace(hitsDetail)에는 전부 싣는다(used+dropped, 플래그) — 인스펙터가 "못 쓴 문서"를 보이게.
        used = used_hits(results)
        # 결과 본문 스니펫(스펙 131) — "N건 반환" 카운트 대신 실제 구절(_record가 _RESULT_CAP 캡).
        _record(
            "ok",
            format_rag_hits(used) if used else "관련 결과 0건",
            len(used),
            _hits_detail(results),
        )
        return format_rag_hits(used)

    return StructuredTool.from_function(
        coroutine=_search,
        name=name,
        description=(
            f"등록된 문서 컬렉션({names})에서 관련 구절을 의미(semantic) 검색한다. 사용자의 질문이 "
            "특정 문서·지식베이스의 내용을 요구하면 **답하기 전에 먼저** 이 도구로 근거 구절을 찾아라. "
            "입력: query(검색할 질문/키워드), top_k(가져올 구절 수, 기본 4)."
        ),
    )

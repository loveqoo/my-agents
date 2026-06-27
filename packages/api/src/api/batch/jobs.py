"""배치 작업 함수 — 모두 idempotent, mem0 미접촉. 스펙 038.

각 작업은 `async def job(*, dry_run: bool) -> dict` 시그니처. 결과 dict를 runner가 BatchRun.summary로
박제한다. 작업은 자체 SessionLocal로 DB를 다룬다(요청 컨텍스트 밖에서도 돌아야 하므로).
"""

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from .. import memory
from ..db import SessionLocal
from ..mem_config import default_mem_cfg
from ..models import BatchConfig, MemorySnapshot, Session, User

log = logging.getLogger("api.batch.jobs")


async def _get_config(session) -> BatchConfig:
    """싱글톤 BatchConfig 1행 확보(없으면 생성). 값은 기본 NULL."""
    cfg = (await session.execute(select(BatchConfig).limit(1))).scalars().first()
    if cfg is None:
        cfg = BatchConfig()
        session.add(cfg)
        await session.flush()
    return cfg


async def cleanup_sessions(*, dry_run: bool, run_id=None) -> dict:
    """오래된 세션 정리 — `last_activity < now() - retention_days`. 메시지는 FK ondelete CASCADE로
    DB가 자동 삭제한다(messages.session_pk).

    - 보존창(session_retention_days)이 NULL이면 no-op(disabled) — 명시 설정 전엔 절대 삭제 안 함.
    - 나이 기준 삭제라 자연히 idempotent(이미 지워진 행은 다시 못 찾음).
    - mem0 장기기억(별 저장소, user_id/run_id 키)은 건드리지 않는다 — 전사 ≠ 장기기억(#6은 039).
    """
    async with SessionLocal() as session:
        cfg = await _get_config(session)
        days = cfg.session_retention_days
        # 비활성: NULL은 명시 미설정. days<1(0/음수)도 비활성으로 막는다 — days=0이면 cutoff=now()라
        # 모든 세션이 대상이 되는 delete-all 푸트건이 된다. API에서도 ge=1로 거르지만 삭제 지점에서
        # 한 겹 더(방어적). 설정값이 잘못돼도 절대 전체 삭제로 번지지 않게 한다.
        if days is None or days < 1:
            log.info("session-cleanup: 보존창 비활성(days=%s) → no-op", days)
            return {"status": "disabled", "deleted": 0}

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        rows = (
            await session.execute(
                select(Session.id, Session.session_id).where(Session.last_activity < cutoff)
            )
        ).all()
        ids = [r[0] for r in rows]

        if dry_run:
            log.info("session-cleanup DRY-RUN: 대상 %d건 (cutoff=%s)", len(ids), cutoff.isoformat())
            return {
                "status": "dry_run",
                "retention_days": days,
                "cutoff": cutoff.isoformat(),
                "would_delete": len(ids),
                "sample": [r[1] for r in rows[:20]],
            }

        if ids:
            # Core bulk DELETE — ORM cascade는 안 걸리지만 messages FK가 ondelete CASCADE라 DB가 정리.
            await session.execute(delete(Session).where(Session.id.in_(ids)))
            await session.commit()
        log.info("session-cleanup: %d건 삭제 (cutoff=%s)", len(ids), cutoff.isoformat())
        return {
            "status": "ok",
            "retention_days": days,
            "cutoff": cutoff.isoformat(),
            "deleted": len(ids),
        }


_CONSOLIDATE_PROMPT = (
    "당신은 유저에 대한 장기기억 사실들을 정리하는 도우미입니다. 아래 사실 목록을 중복·중첩을 "
    "제거하고 서로 모순되지 않게 더 적은 수의 명료한 사실로 통합하세요. 각 사실은 한 줄에 하나씩, "
    "번호·머리말·따옴표 없이 사실 문장만 출력하세요. 정보를 새로 지어내지 말고 주어진 내용만 "
    "사용하세요. 통합 후에도 의미가 보존돼야 합니다."
)


def _consolidate(texts: list[str], mem_cfg: dict | None) -> list[str]:
    """기억 사실 목록을 LLM으로 더 적고 일관된 사실로 통합 → 줄 단위 리스트. 스펙 039.

    mem_cfg["llm"](레지스트리 기본 chat 모델, openai-호환)을 직접 호출한다. 실패·빈 응답이면 []를
    반환해 **그 유저의 기억을 절대 삭제하지 않게**(안전 불변식 2) 한다. 동기 호출 → 호출 측이
    asyncio.to_thread로 감싼다(memory_routes 패턴과 동형).
    """
    llm = (mem_cfg or {}).get("llm") or {}
    if not texts or not llm.get("base_url") or not llm.get("model_id"):
        return []
    try:
        from openai import OpenAI  # 지연 임포트(mem0 의존, 항상 설치됨)

        client = OpenAI(base_url=llm["base_url"], api_key=llm.get("api_key") or "sk-noauth")
        resp = client.chat.completions.create(
            model=llm["model_id"],
            messages=[
                {"role": "system", "content": _CONSOLIDATE_PROMPT},
                {"role": "user", "content": "\n".join(f"- {t}" for t in texts)},
            ],
            temperature=0,
        )
        content = (resp.choices[0].message.content or "").strip()
    except Exception as exc:  # noqa: BLE001 — 실패는 흡수, 빈 결과로 삭제 차단
        log.warning("memory consolidation LLM 호출 실패: %s", exc)
        return []
    facts: list[str] = []
    seen: set[str] = set()
    for line in content.splitlines():
        s = re.sub(r"^\s*\d+[.)]\s*", "", line.strip().lstrip("-*•").strip())
        if s and s.lower() not in seen:
            seen.add(s.lower())
            facts.append(s)
    return facts


# 한 번에 LLM에 넣는 최대 기억 수. 이보다 많으면 프롬프트가 모델 컨텍스트를 넘겨 입력이 조용히
# 잘릴 수 있고, 잘린 사실은 통합 결과에서 누락된 채 원본이 삭제되면 영구 손실이 된다. 그러느니
# 그 유저를 통째로 스킵(원본 보존)한다. 청크 단위 통합은 debt(스펙 §7). learning 037 — 파괴적
# 작업은 실행 지점에서 바닥을 깐다.
_MAX_CONSOLIDATE_INPUT = 200


def _valid_consolidation(new_facts: list[str], original_count: int) -> bool:
    """통합 결과를 '파괴적 교체해도 되는가'로 판정. 비었거나(불변식 2) 원본보다 줄지 않으면
    (확장·무변 = 모델이 거부문/머리말/원문 에코를 뱉은 쓰레기일 수 있음) 무효 → 그 유저 스킵.
    파괴적 교체는 **명백히 더 적은 사실**일 때만 허용한다(learning 037)."""
    return bool(new_facts) and len(new_facts) < original_count


async def _candidates(mem_cfg: dict, user_ids: list[str], threshold: int) -> list[tuple[str, list[dict]]]:
    """임계치 초과 유저만 (user_id, 기억목록) 쌍으로. mem0 list_memories는 to_thread."""
    out: list[tuple[str, list[dict]]] = []
    for uid in user_ids:
        mems = await asyncio.to_thread(memory.list_memories, {"user_id": uid}, mem_cfg)
        if len(mems) > threshold:
            out.append((uid, mems))
    return out


async def consolidate_user_memories(*, dry_run: bool, run_id=None) -> dict:
    """유저 장기기억(user_id 축) 통합·재적재 — 임계치 초과 유저의 기억을 LLM으로 통합하고,
    원본을 MemorySnapshot에 백업한 뒤 교체. 스펙 039. 안전 불변식(스펙 §2.안전):

    1. threshold NULL/<2 → disabled(파괴적 churn 차단, learning 037). mem_cfg 미해석도 disabled.
    2. 통합 결과가 비거나 원본보다 줄지 않거나(쓰레기 출력 방어) 기억 수가 상한 초과면(잘림 손실
       방지) 그 유저 **전체 스킵**(절대 삭제 안 함). _valid_consolidation·_MAX_CONSOLIDATE_INPUT.
    3. 스냅샷에 담은 그 mem_id만 삭제 → list~delete 사이 라이브 추가분 생존(동시성 안전).
    4. dry-run은 무변형(LLM 미리보기만).
    5. mem0 add/delete는 graceful(실패 흡수), 실제 성공 수를 센다.
    """
    async with SessionLocal() as session:
        cfg = await _get_config(session)
        threshold = cfg.memory_consolidation_threshold
        # 불변식 1 — NULL=미설정, <2=파괴적(0/1은 거의 전원 매번 통합). API ge=2 + 여기 한 겹 더.
        if threshold is None or threshold < 2:
            log.info("memory-consolidation: 임계치 비활성(threshold=%s) → no-op", threshold)
            return {"status": "disabled", "threshold": threshold}
        mem_cfg = await default_mem_cfg(session)
        if mem_cfg is None:
            log.info("memory-consolidation: 기본 mem_cfg 미해석(모델 미설정) → no-op")
            return {"status": "disabled", "reason": "no_mem_cfg", "threshold": threshold}
        user_ids = [str(u) for u in (await session.execute(select(User.id))).scalars().all()]

    candidates = await _candidates(mem_cfg, user_ids, threshold)

    if dry_run:  # 불변식 4 — 변형 전무, 통합 미리보기만(실행 시 무엇이 스킵되는지도 정직히 표기)
        preview = []
        for uid, mems in candidates:
            if len(mems) > _MAX_CONSOLIDATE_INPUT:  # 상한 초과 → 실행 시 스킵(잘림 손실 방지)
                preview.append({"user_id": uid, "before": len(mems), "after": 0, "skip": "too_many", "sample": []})
                continue
            new_facts = await asyncio.to_thread(_consolidate, [m["text"] for m in mems], mem_cfg)
            skip = None if _valid_consolidation(new_facts, len(mems)) else "no_shrink"
            preview.append(
                {"user_id": uid, "before": len(mems), "after": len(new_facts), "skip": skip, "sample": new_facts[:10]}
            )
        log.info("memory-consolidation DRY-RUN: 후보 %d명 (유저 %d명 스캔)", len(preview), len(user_ids))
        return {
            "status": "dry_run",
            "threshold": threshold,
            "users_scanned": len(user_ids),
            "candidates": preview,
        }

    consolidated = []
    total_before = total_after = 0
    for uid, mems in candidates:
        if len(mems) > _MAX_CONSOLIDATE_INPUT:  # 상한 초과 → 스킵(원본 보존, 청크 통합은 debt §7)
            log.warning(
                "memory-consolidation: user=%s 기억 %d개 > 상한 %d → 스킵(프롬프트 잘림 손실 방지)",
                uid, len(mems), _MAX_CONSOLIDATE_INPUT,
            )
            continue
        new_facts = await asyncio.to_thread(_consolidate, [m["text"] for m in mems], mem_cfg)
        if not _valid_consolidation(new_facts, len(mems)):  # 불변식 2 — 빈/미축소면 절대 삭제 안 함
            log.warning(
                "memory-consolidation: 통합 결과 무효(빈/미축소 %d→%d) → user=%s 스킵(원본 보존)",
                len(mems), len(new_facts), uid,
            )
            continue
        # ① 원본을 스냅샷에 박제 + commit (롤백 앵커). 삭제는 이 다음에만 한다.
        async with SessionLocal() as session:
            for m in mems:
                session.add(
                    MemorySnapshot(batch_run_id=run_id, user_id=uid, mem_id=m["id"], text=m["text"])
                )
            await session.commit()
        # ② 통합본 적재 — 이미 정제된 한 줄 사실이라 infer=False(재추출로 모양 안 바뀌게).
        for fact in new_facts:
            await asyncio.to_thread(
                memory.add, {"user_id": uid}, [{"role": "user", "content": fact}], mem_cfg, False
            )
        # ③ 불변식 3 — 박제한 그 mem_id만 삭제(스캔 이후 추가분은 안 건드림).
        deleted = 0
        for m in mems:
            if await asyncio.to_thread(memory.delete_memory, m["id"], mem_cfg):
                deleted += 1
        if deleted != len(mems):  # 일부 원본 잔존 — 통합본과 중복(손실 아님, 가시화만). 스냅샷이 앵커.
            log.warning(
                "memory-consolidation: user=%s 삭제 %d/%d 미달 — 원본 일부 잔존(통합본과 중복 가능, 손실 아님)",
                uid, deleted, len(mems),
            )
        consolidated.append(
            {"user_id": uid, "before": len(mems), "after": len(new_facts), "snapshot": len(mems), "deleted": deleted}
        )
        total_before += len(mems)
        total_after += len(new_facts)

    log.info("memory-consolidation: %d명 통합 (before=%d → after=%d)", len(consolidated), total_before, total_after)
    return {
        "status": "ok",
        "threshold": threshold,
        "users_scanned": len(user_ids),
        "consolidated": consolidated,
        "total_before": total_before,
        "total_after": total_after,
    }


# 작업 레지스트리 — CLI choices·API 트리거·스케줄러가 공유하는 단일 출처.
JOBS = {
    "session-cleanup": cleanup_sessions,
    "memory-consolidation": consolidate_user_memories,
}

"""배치 작업 함수 — 모두 idempotent, mem0 미접촉. 스펙 038.

각 작업은 `async def job(*, dry_run: bool) -> dict` 시그니처. 결과 dict를 runner가 BatchRun.summary로
박제한다. 작업은 자체 SessionLocal로 DB를 다룬다(요청 컨텍스트 밖에서도 돌아야 하므로).
"""

import asyncio
import ipaddress
import logging
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from sqlalchemy import delete, exists, func as safunc, or_, select, text

from .. import memory
from ..db import SessionLocal
from ..mem_config import default_mem_cfg
from ..models import Agent, Approval, BatchConfig, MemorySnapshot, Session, User

log = logging.getLogger("api.batch.jobs")


async def _get_config(session) -> BatchConfig:
    """싱글톤 BatchConfig 1행 확보(없으면 생성). 값은 기본 NULL."""
    cfg = (await session.execute(select(BatchConfig).limit(1))).scalars().first()
    if cfg is None:
        cfg = BatchConfig()
        session.add(cfg)
        await session.flush()
    return cfg


# 턴 기준 정리(스펙 049, #10)의 활성 세션 보호창. turns<N이어도 최근 IDLE_GUARD 안에 활동한
# 세션은 "진행 중"으로 보고 절대 삭제하지 않는다. 어드민 노브가 아니라 내부 안전 상수(옵션3 선택
# 반영) — cron은 보통 일 단위라 1시간이면 진행 중 대화를 안전하게 비껴간다.
_TURN_CLEANUP_IDLE_GUARD = timedelta(hours=1)


async def cleanup_sessions(*, dry_run: bool, run_id=None) -> dict:
    """세션 정리 — 두 기준의 **합집합**(스펙 038 나이 + 스펙 049 턴). 메시지는 FK ondelete CASCADE로
    DB가 자동 삭제(messages.session_pk).

    - 나이 절: `last_activity < now() - retention_days`. retention_days NULL/<1이면 이 절 비활성.
    - 턴 절: `turns < min_session_turns AND last_activity < now() - IDLE_GUARD`(이탈 저턴 세션).
      min_session_turns NULL/<1이면 이 절 비활성. IDLE_GUARD가 활성 세션을 보호.
    - 둘 다 비활성이면 no-op(disabled) — 명시 설정 전엔 절대 삭제 안 함.
    - 둘 다 last_activity 단조 기준이라 idempotent(이미 지워진 행은 다시 못 찾음).
    - mem0 장기기억(별 저장소, user_id/run_id 키)은 건드리지 않는다 — 전사 ≠ 장기기억(#6은 039).
    """
    async with SessionLocal() as session:
        cfg = await _get_config(session)
        days = cfg.session_retention_days
        min_turns = cfg.min_session_turns
        now = datetime.now(timezone.utc)

        # 각 절 비활성 가드(API ge=1 외 한 겹 더, 방어적). days=0/min_turns=0이면 delete-all footgun.
        age_active = days is not None and days >= 1
        turn_active = min_turns is not None and min_turns >= 1
        if not age_active and not turn_active:
            log.info("session-cleanup: 나이·턴 기준 모두 비활성 → no-op")
            return {"status": "disabled", "deleted": 0}

        age_cutoff = now - timedelta(days=days) if age_active else None
        idle_cutoff = now - _TURN_CLEANUP_IDLE_GUARD if turn_active else None

        clauses = []
        if age_active:
            clauses.append(Session.last_activity < age_cutoff)
        if turn_active:
            # 활성 보호: 최근 활동 세션은 turns<N이어도 제외(idle_cutoff보다 오래된 것만).
            clauses.append((Session.turns < min_turns) & (Session.last_activity < idle_cutoff))

        # 미해결 승인(HIL) 세션은 절대 삭제 안 함 — _create_approval이 turns=0으로 lazy-create한
        # 세션이라 턴 절(<N)에 걸리고, 승인 대기는 흔히 IDLE_GUARD(1h)를 넘긴다. 그 사이 정리되면
        # resume_approval의 _load_context가 행을 못 찾아 새 id를 만들어 대화를 고아로 만든다(적대리뷰
        # 결함 #1, 스펙 049). 나이 절에도 동일 노출이므로 양 절에 걸쳐 AND로 제외한다.
        pending_approval = (
            exists()
            .where(Approval.session_id == Session.session_id)
            .where(Approval.status == "pending")
        )

        rows = (
            await session.execute(
                select(Session.id, Session.session_id).where(or_(*clauses), ~pending_approval)
            )
        ).all()
        ids = [r[0] for r in rows]

        meta = {
            "retention_days": days if age_active else None,
            "cutoff": age_cutoff.isoformat() if age_cutoff else None,
            "min_session_turns": min_turns if turn_active else None,
            "idle_cutoff": idle_cutoff.isoformat() if idle_cutoff else None,
        }

        if dry_run:
            log.info(
                "session-cleanup DRY-RUN: 대상 %d건 (나이=%s, 턴<%s)",
                len(ids), age_cutoff.isoformat() if age_cutoff else "off",
                min_turns if turn_active else "off",
            )
            return {"status": "dry_run", **meta, "would_delete": len(ids), "sample": [r[1] for r in rows[:20]]}

        if ids:
            # Core bulk DELETE — ORM cascade는 안 걸리지만 messages FK가 ondelete CASCADE라 DB가 정리.
            await session.execute(delete(Session).where(Session.id.in_(ids)))
            await session.commit()
        log.info("session-cleanup: %d건 삭제 (나이=%s, 턴<%s)",
                 len(ids), age_cutoff.isoformat() if age_cutoff else "off",
                 min_turns if turn_active else "off")
        return {"status": "ok", **meta, "deleted": len(ids)}


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


# ----------------------------- 파괴적 정리 (스펙 050) -----------------------------
# 테스트가 쌓은 정크(A2A 프로브 에이전트·테스트 유저)를 dry-run→검토→실행으로 청소. 가장 비가역이라
# 실행 지점에 바닥을 깐다(learning 037). 규칙이 절대 데모/실데이터로 번지지 않게 source/host/keep-list로 고정.

# user-cleanup의 하드코딩 keep-list — 패턴에 일치해도 절대 삭제 안 함. 부트스트랩 어드민(잠금 방지)과
# 데모 유저(시드 자산). 패턴이 넓게 잡혀도 이 둘은 바닥이 막는다.
_USER_CLEANUP_KEEP = frozenset({"admin@example.com", "alice@example.com"})

# a2a-cleanup이 "사설"로 간주하는 *정확한* 네트워크 — 스펙 050이 열거한 집합만(루프백+RFC1918).
# ipaddress.is_private는 0.0.0.0/8·169.254/16·198.18/15 등 라우팅 가능한 예약대역까지 포함하는
# 상위집합이라, 그 대역에 실 A2A 파트너가 있으면 오삭제한다(적대리뷰 #3). 그래서 명시 멤버십으로 좁힌다.
_A2A_PRIVATE_NETS = tuple(
    ipaddress.ip_network(n)
    for n in ("127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "::1/128")
)


def _is_private_host(endpoint: str | None) -> bool:
    """endpoint의 호스트가 루프백/RFC1918 사설이면 True(=테스트 프로브). 공개 호스트면 False.

    실 A2A 파트너는 공개 endpoint라 절대 안 걸린다. scheme 유무 모두 허용(127.0.0.1:8142,
    http://10.0.0.5:9999 등). localhost는 루프백, IP는 _A2A_PRIVATE_NETS 명시 멤버십으로만 판정한다
    (is_private 상위집합 회피, 적대리뷰 #3). IPv4-mapped IPv6(::ffff:10.0.0.1)는 v4로 언랩 후 판정.
    파싱 불가·호스트 없음·도메인(공개 추정)은 False(보수적 — 못 지우는 쪽이 안전)."""
    if not endpoint:
        return False
    raw = endpoint.strip()
    # scheme 없으면 urlsplit이 netloc을 못 잡으므로 // 프리픽스를 붙여 강제 파싱.
    parsed = urlsplit(raw if "//" in raw else f"//{raw}")
    host = parsed.hostname  # 포트·인증정보·대괄호 IPv6 제거된 순수 호스트
    if not host:
        return False
    if host.lower() == "localhost":
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False  # 도메인명 → 공개 추정, 안 건드림
    if getattr(ip, "ipv4_mapped", None) is not None:  # ::ffff:10.0.0.1 → 10.0.0.1로 언랩
        ip = ip.ipv4_mapped
    return any(ip in net for net in _A2A_PRIVATE_NETS)


def is_delete_all_pattern(pattern: str | None) -> bool:
    """user-cleanup LIKE 패턴이 전체/광범위 유저 삭제 위험인지 판정 — 와일드카드(`%`·`_`)를 제거한
    '리터럴 골격'으로 본다. `%`·`%a%`·`%@%`처럼 리터럴이 약하면 거의 전체를 매치하므로 거부한다.

    바닥(적대리뷰 #1): 리터럴에 `@`(도메인 셀렉터)가 없거나 리터럴 본문이 5자 미만이면 위험으로 본다.
    정상 셀렉터(`verify%@example.com`·`%@test.example.com`)는 통과한다. NULL/빈은 여기서 안 다룬다
    (호출 측이 disabled로 처리). 검증기(batch_routes)와 잡 바닥이 같은 함수를 공유해 드리프트를 막는다."""
    literal = (pattern or "").replace("%", "").replace("_", "").strip()
    return ("@" not in literal) or (len(literal) < 5)


async def cleanup_a2a_agents(*, dry_run: bool, run_id=None) -> dict:
    """A2A 정크 정리(스펙 050, #1) — `source='external'` AND endpoint 호스트가 루프백/RFC1918 사설인
    에이전트 삭제. 테스트가 등록한 프로브 A2A 카드만 걸린다.

    - 바닥: source 비-external(ui/code 데모)은 **절대** 손대지 않음(쿼리에 source 고정). endpoint
      NULL/공개 호스트도 제외. → 규칙이 데모·실 파트너로 번지지 않음(learning 037).
    - cascade: Agent 삭제 → sessions(agent_pk FK ondelete CASCADE)·agent_versions(동일)도 DB가 정리.
      Approval.agent_pk는 SET NULL(고아 무해). dry-run에 딸려 죽을 세션 수를 함께 표기(정직).
    - idempotent: 삭제 후 재실행 deleted=0(매치가 사라짐).
    """
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(Agent.id, Agent.agent_id, Agent.name, Agent.endpoint).where(
                    Agent.source == "external", Agent.endpoint.is_not(None)
                )
            )
        ).all()
        # 호스트 판정은 Python(ipaddress)에서 — SQL로 RFC1918 전 범위를 정확히 긋기 어렵다.
        matched = [r for r in rows if _is_private_host(r[3])]
        ids = [r[0] for r in matched]

        # 함께 죽을 세션 수(정직한 cascade 표기).
        session_count = 0
        if ids:
            session_count = (
                await session.execute(
                    select(safunc.count()).select_from(Session).where(Session.agent_pk.in_(ids))
                )
            ).scalar_one()

        meta = {"matched_agents": len(ids), "cascade_sessions": int(session_count)}
        sample = [{"agent_id": r[1], "name": r[2], "endpoint": r[3]} for r in matched[:20]]

        if dry_run:
            log.info("a2a-cleanup DRY-RUN: 대상 %d 에이전트 (+세션 %d)", len(ids), session_count)
            return {"status": "dry_run", **meta, "would_delete": len(ids), "sample": sample}

        if not ids:
            return {"status": "ok", **meta, "deleted": 0}
        # Core bulk DELETE — sessions/agent_versions는 FK ondelete CASCADE라 DB가 정리.
        await session.execute(delete(Agent).where(Agent.id.in_(ids)))
        await session.commit()
        log.info("a2a-cleanup: %d 에이전트 삭제 (+세션 %d cascade)", len(ids), session_count)
        return {"status": "ok", **meta, "deleted": len(ids)}


async def cleanup_test_users(*, dry_run: bool, run_id=None) -> dict:
    """테스트 유저 정리(스펙 050, #13) — 이메일이 config 패턴(LIKE) 일치 AND keep-list 제외인 유저 삭제.
    가장 비가역이라 바닥 3겹(learning 037):

    1. 패턴 NULL → disabled no-op(명시 설정 전엔 절대 삭제 안 함). 패턴 `%`/빈 → delete-all 가드로 거부.
    2. 하드코딩 keep-list(부트스트랩 admin@·데모 alice@)는 패턴 일치해도 제외.
    3. 마지막 슈퍼유저 보호 — 삭제로 super가 0이 되면 매치된 super 전부 보존(콘솔 잠금 방지).

    cascade·정합성: accesstoken은 user_id FK CASCADE(DB 처리). sessions.user_id는 plain String →
    고아 문자열 무해(049가 정리). Casbin grouping/policy(casbin_rule v0=user_id)는 dangling이라 같은
    실행에서 제거(권한 누수 방지). mem0(user_id 축)는 별 저장소 → 범위 밖(debt §7).
    """
    async with SessionLocal() as session:
        cfg = await _get_config(session)
        pattern = cfg.test_user_email_pattern
        # 바닥 1a — NULL/빈 = 비활성(명시 설정 전엔 no-op).
        if not pattern or not pattern.strip():
            log.info("user-cleanup: 패턴 비활성(pattern=%r) → no-op", pattern)
            return {"status": "disabled", "deleted": 0}
        # 바닥 1b — 광범위(전체) 삭제 패턴 거부. `%`만이 아니라 `%@%`·`%a%`처럼 리터럴이 약해 거의
        # 전부를 매치하는 패턴도 막는다(적대리뷰 #1). API 422 외 여기 한 겹 더(같은 함수 공유).
        if is_delete_all_pattern(pattern):
            log.warning("user-cleanup: 광범위 삭제 패턴(%r) 거부", pattern)
            return {"status": "rejected", "reason": "delete_all_pattern", "deleted": 0}

        rows = (
            await session.execute(
                select(User.id, User.email, User.is_superuser).where(User.email.like(pattern))
            )
        ).all()
        # 바닥 2 — keep-list 제외(패턴 일치해도). 공백·대소문자 차이로 보호가 새지 않게 strip().lower()
        # 양변 정규화(적대리뷰 #8 — 저장 이메일에 끝 공백/대문자가 있어도 부트스트랩 admin 보호).
        candidates = [r for r in rows if (r[1] or "").strip().lower() not in _USER_CLEANUP_KEEP]

        # 바닥 3 — 마지막 super 보호. 매치 super를 다 지우면 시스템 super가 0이 되는지 확인.
        total_supers = (
            await session.execute(
                select(safunc.count()).select_from(User).where(User.is_superuser.is_(True))
            )
        ).scalar_one()
        matched_supers = [r for r in candidates if r[2]]
        protected_super_emails: list[str] = []
        if matched_supers and total_supers - len(matched_supers) <= 0:
            # 매치 super 전부 보존(이 중 누가 마지막인지 고르지 않고 보수적으로 전부 남김 = 잠금 0 보장).
            protected = {r[0] for r in matched_supers}
            protected_super_emails = [r[1] for r in matched_supers]
            candidates = [r for r in candidates if r[0] not in protected]

        ids = [r[0] for r in candidates]
        meta = {
            "pattern": pattern,
            "matched": len(rows),
            "protected_superusers": protected_super_emails,
        }
        sample = [{"email": r[1], "is_superuser": r[2]} for r in candidates[:20]]

        if dry_run:
            log.info(
                "user-cleanup DRY-RUN: 패턴 %r 매치 %d → 삭제대상 %d (super 보존 %d)",
                pattern, len(rows), len(ids), len(protected_super_emails),
            )
            return {"status": "dry_run", **meta, "would_delete": len(ids), "sample": sample}

        if not ids:
            return {"status": "ok", **meta, "deleted": 0}
        # Casbin grouping/policy 제거(dangling 권한 누수 방지) — User 삭제와 같은 트랜잭션(DB 원자성).
        # casbin_rule은 ORM 모델이 없어 raw SQL. v0=삭제 유저 UUID인 행을 g·p 둘 다 제거한다 —
        # 현재는 user-subject가 g뿐이지만 모델이 per-user p-정책을 허용하므로 미래의 dangling p도 막는다
        # (적대리뷰 #5). v0이 role명('admin' 등)인 글로벌 p-정책은 UUID와 안 겹쳐 안전하다.
        uid_strs = [str(i) for i in ids]
        await session.execute(
            text("DELETE FROM casbin_rule WHERE ptype IN ('g','p') AND v0 = ANY(:uids)"),
            {"uids": uid_strs},
        )
        # Core bulk DELETE — accesstoken은 user_id FK ondelete CASCADE라 DB가 정리.
        await session.execute(delete(User).where(User.id.in_(ids)))
        await session.commit()
    # DB는 정리됐다. 인프로세스(API 트리거)면 메모리 enforcer가 부팅 시 로드한 정책을 들고 있어
    # 삭제된 grant가 메모리에 잔존할 수 있다 → reload로 동기화(적대리뷰 #4). 잡이 별 프로세스로
    # 돌면 enforcer 미초기화(_enforcer=None)라 조용히 스킵 — DB가 진실원이라 무해.
    try:
        from .. import authz

        if authz._enforcer is not None:
            await authz._enforcer.load_policy()
    except Exception as exc:  # noqa: BLE001 — reload 실패는 흡수(DB는 이미 정리됨)
        log.warning("user-cleanup: casbin enforcer reload 실패(무해, DB는 정리됨): %s", exc)
    log.info(
        "user-cleanup: %d 유저 삭제 (패턴 %r, super 보존 %d)",
        len(ids), pattern, len(protected_super_emails),
    )
    return {"status": "ok", **meta, "deleted": len(ids)}


# 작업 레지스트리 — CLI choices·API 트리거·스케줄러가 공유하는 단일 출처.
JOBS = {
    "session-cleanup": cleanup_sessions,
    "memory-consolidation": consolidate_user_memories,
    "a2a-cleanup": cleanup_a2a_agents,
    "user-cleanup": cleanup_test_users,
}

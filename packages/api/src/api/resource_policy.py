"""자원 회수 정책 대장 — "이 테이블은 **누가 치우나**"를 선언하게 강제한다 (스펙 347).

**왜 이 파일이 있나**: 스펙 346(체크포인트가 턴마다 3~9행씩 무한 누적)의 교훈은 "체크포인트를 안
지웠다"가 아니라 **아무도 행 수를 안 셌다**는 것이다 — 기능 테스트는 전부 초록이었다. 전수 감사에서
같은 형태가 5건 더 나왔다(쓰기 경로만 있고 회수 경로가 없는 테이블). 개별로 고치면 **다음 테이블에서
또 샌다.**

그래서 **선언을 강제**한다. `verify_347`이 `models.py`의 테이블 집합과 이 대장의 키 집합을 대조하므로,
새 테이블을 만들고 분류를 빠뜨리면 **테스트가 실패**한다 — 사람의 기억이 아니라 게이트가 기억한다.

**정직성 규칙**: 회수 경로가 없으면 `LEAKING`으로 **그렇게 적는다**(그럴듯한 분류로 덮지 않는다).
`LEAKING`은 반드시 `fix_spec`을 갖는다 — "샌다는 걸 알고 있고, 어느 스펙이 고친다"까지가 한 세트다.
**이 대장의 LEAKING 개수가 0이 되는 것이 자원 감사 캠페인의 완료 조건**이다(수치 스코어보드).
"""

from dataclasses import dataclass
from typing import Literal

Kind = Literal["reclaimed", "bounded", "user_data", "leaking"]


@dataclass(frozen=True)
class Policy:
    """한 테이블의 자원 정책.

    kind:
      - `reclaimed`  회수 경로 있음 — `by`에 **누가** 치우는지 명시(실재 검증 대상).
      - `bounded`    자라지 않음 — 싱글톤·읽기전용 카탈로그·관리자 페이스. `note`에 사유.
      - `user_data`  사용자 자산이라 임의 삭제 금지 — 보존정책이 **어디** 있는지 `by`에 명시.
      - `leaking`    **회수 경로 없음**(정직한 자백) — `fix_spec` 필수.

    by 표기법(회수 주체가 실재하는지 게이트가 검사한다):
      - `batch:<잡이름>`        배치 잡(이름이 batch.jobs.JOBS에 있어야 함)
      - `cascade:<부모테이블>`  FK ondelete=CASCADE(메타데이터로 실측)
      - `chokepoint:<심볼>`     관문 함수(임포트 가능해야 함)
      - `route:<설명>`          사용자/관리자가 화면에서 삭제
    """

    kind: Kind
    by: str = ""
    note: str = ""
    fix_spec: str = ""


# ---------------------------------------------------------------------------
# 우리 소유 테이블 전수 (models.py Base.metadata) — 하나도 빠짐없이.
# ---------------------------------------------------------------------------
TABLES: dict[str, Policy] = {
    # --- 관리자가 만드는 카탈로그(사람 페이스, 자동 증식 없음) -------------------
    "agents": Policy("bounded", note="관리자가 생성/삭제(사람 페이스). 삭제 라우트 있음"),
    "personas": Policy("bounded", note="관리자 저작 블록(사람 페이스)"),
    "mcp_servers": Policy("bounded", note="관리자 등록(사람 페이스)"),
    "providers": Policy("bounded", note="관리자 등록(사람 페이스)"),
    "models": Policy("bounded", note="관리자 등록(사람 페이스)"),
    "node_templates": Policy("bounded", note="관리자 저작 + 부팅 시 코드 노드 upsert(멱등)"),
    "allowed_hosts": Policy("bounded", note="SSRF allowlist — 관리자 등록(사람 페이스)"),
    "roles": Policy("bounded", note="RBAC 역할(사람 페이스)"),
    "memory_types": Policy("bounded", note="읽기 전용 카탈로그(마이그레이션 시드, 생성 라우트 없음)"),
    "app_settings": Policy("bounded", note="키-값 설정(유한 키 집합)"),
    "batch_config": Policy("bounded", note="싱글톤 1행"),
    "user": Policy("bounded", by="batch:user-cleanup", note="관리자 계정(사람 페이스). 테스트 유저는 배치가 정리"),
    # --- 회수 경로 있음 ---------------------------------------------------------
    "agent_versions": Policy("reclaimed", by="cascade:agents", note="편집은 draft 재사용, 활성화당 1행(사람 페이스)"),
    "message_feedback": Policy("reclaimed", by="cascade:messages"),
    "eval_case_results": Policy("reclaimed", by="cascade:eval_runs", note="부모(eval_runs)가 history-cleanup으로 회수되면 CASCADE로 함께 사라진다(고아 0)"),
    "eval_cases": Policy("reclaimed", by="cascade:eval_datasets", note="관리자 저작 문제집의 일부"),
    "collection_reindex_events": Policy("reclaimed", by="cascade:collections", note="재인덱싱당 1행(관리자 페이스)"),
    "document_blobs": Policy("reclaimed", by="cascade:documents", note="원본 바이트 보존은 재청킹 근거(의도된 설계, 상한 25MB)"),
    "rag_chunks": Policy("reclaimed", by="cascade:documents"),
    # --- 사용자 자산(임의 삭제 금지 — 보존정책은 관리자 설정) --------------------
    "sessions": Policy("user_data", by="batch:session-cleanup", note="보존정책=BatchConfig(기본 OFF)"),
    "messages": Policy("user_data", by="cascade:sessions", note="세션 보존정책에 종속(턴당 2행)"),
    "collections": Policy("user_data", by="route:RAG 컬렉션 삭제"),
    "documents": Policy("user_data", by="cascade:collections", note="사용자가 올린 원본"),
    "eval_datasets": Policy("user_data", by="route:평가 문제집 삭제"),
    # --- 회수 경로 없음(자백) ---------------------------------------------------
    "accesstoken": Policy(
        "reclaimed",
        by="batch:token-cleanup",
        note="로그인마다 1행. 만료(수명+유예 1일) 지난 토큰만 회수 — 살아 있는 세션은 안 끊는다(스펙 349)",
    ),
    "approvals": Policy(
        "reclaimed",
        by="batch:approval-cleanup",
        note="처리된 승인만 보존기간(기본 30일) 후 회수. **pending은 재개 근거라 절대 안 지운다** — "
        "방치 pending은 346 스윕이 expired로 바꾼 뒤 이 보존기간을 탄다(수명 사슬)",
    ),
    "eval_runs": Policy(
        "reclaimed",
        by="batch:history-cleanup",
        note="평가 실행 이력 — 보존기간(기본 90일) 후 회수. **문제집별 최근 10런은 나이와 무관하게 보존**(성적 추이 앵커)",
    ),
    "batch_runs": Policy(
        "reclaimed",
        by="batch:history-cleanup",
        note="배치 실행 이력 — 보존기간 후 회수(348로 배치가 실제 도니 매시 쌓인다 — 청소부의 발자국도 치운다)",
    ),
    "memory_snapshots": Policy(
        "reclaimed",
        by="batch:history-cleanup",
        note="메모리 통합 롤백 앵커 — 보존기간 후 회수(90일 지난 앵커는 현실적으로 못 쓴다)",
    ),
}


# ---------------------------------------------------------------------------
# 남의 소유 테이블(우리 Base 밖) — 자원은 우리가 만들지만 스키마는 남의 것.
# 대장에 적는 이유: "우리 테이블이 아니라서" 회수 책임이 사라지지 않는다(스펙 346이 그 사례).
# ---------------------------------------------------------------------------
EXTERNAL: dict[str, Policy] = {
    "checkpoints": Policy(
        "reclaimed",
        by="chokepoint:checkpoint_retention.release_thread",
        note="턴 종료 시 폐기 + TTL 스윕(batch:checkpoint-cleanup). 스펙 346",
    ),
    "checkpoint_writes": Policy("reclaimed", by="chokepoint:checkpoint_retention.release_thread"),
    "checkpoint_blobs": Policy("reclaimed", by="chokepoint:checkpoint_retention.release_thread"),
    "checkpoint_migrations": Policy("bounded", note="langgraph 스키마 버전 행(유한)"),
    "mem0_memories": Policy(
        "leaking",
        note="턴마다 장기기억 추가(mem0). 회수는 memory-consolidation 배치뿐인데 기본 OFF + 배치 미가동",
        fix_spec="352",
    ),
    "casbin_rule": Policy("bounded", note="RBAC 정책 행(관리자 페이스)"),
    "alembic_version": Policy("bounded", note="싱글 행"),
}


def leaking() -> dict[str, Policy]:
    """회수 경로가 없는 테이블 — **이 수가 0이 되는 것이 자원 감사 캠페인의 완료 조건**(스펙 347)."""
    return {
        name: p
        for name, p in {**TABLES, **EXTERNAL}.items()
        if p.kind == "leaking"
    }


# 성장 예산(스펙 347 축 B) — 대표 오퍼레이션의 **잔여 행 증가** 상한. 초과하면 게이트 실패.
# "무엇을 얼마나 소모하나"를 상수로 박아, 새 누수가 조용히 들어오지 못하게 한다.
TURN_BUDGET: dict[str, int] = {
    "messages": 2,  # user + assistant
    "checkpoints": 0,  # 관문이 폐기(스펙 346) — 1행이라도 남으면 회귀
    "checkpoint_writes": 0,
    "checkpoint_blobs": 0,
    "approvals": 0,  # 승인 없는 평범한 턴
    "agent_versions": 0,
    "eval_runs": 0,
}
LOGIN_BUDGET: dict[str, int] = {
    "accesstoken": 1,  # 로그인당 1행은 정상. **만료 행이 쌓이는 것**이 누수(349에서 회수 도입)
}

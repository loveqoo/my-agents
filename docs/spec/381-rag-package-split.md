# 381 — rag.py 축 분리: `rag/` 패키지 (캠페인 374 Tier 2 ①)

## 왜

codex 리뷰 D-TOP1: `rag.py`(1256줄) 단일 라우터가 CRUD·health·reindex·retrieval·ingest·문서 편집을
전부 안아 SRP 위반·변경 충돌·탐색 비용. 관심사(컬렉션/재인덱싱/검색/문서)가 독립적이라 축으로 분리.

## 무엇

`rag.py` → `rag/` 패키지(도메인별 라우트 모듈 + 공유 서비스층). 라우트 14개·헬퍼 27개 전부 보존:

- **shared.py**(669) — 서비스/헬퍼 27개 + `router`(단일 APIRouter) + 프리앰블(imports·상수).
  모듈 레벨 상수(`MAX_UPLOAD_BYTES`·`_LOCKABLE_STATUSES`)도 여기 정의(도메인이 import).
- **collections.py**(6 라우트) — list/create/get/update/delete/health.
- **reindex.py**(2) — reindex 트리거·이벤트 목록.
- **search.py**(1) — 검색.
- **documents.py**(5) — 목록/인제스트/삭제/본문 조회·수정.
- **__init__.py** — 도메인 모듈 import로 라우트 등록 발화 + 외부 소비 심볼(`router`·
  `sweep_zombie_ingests`·`resolve_search_collection`) 재수출 → 임포터 무변경.

### 기법 (learning 381 재사용)

- **verbatim 슬라이스**: `split_rag.py`가 원본 줄 범위를 그대로 잘라 새 모듈에 씀(전사 오류 0).
- 도메인 모듈은 원본 import 헤더 + `from .shared import (router, 전 헬퍼)`를 넉넉히 얹고
  `ruff check --fix --select F401`로 미사용 자동 정리.
- `deepen()`이 `from .`→`from ..`(패키지 한 단계 깊어짐).

### 함정 (이번에 잡은 것)

- **함수 사이 모듈 레벨 상수는 블록 추출이 못 따라간다.** 함수 단위 슬라이스라 함수 사이에 낀
  `_LOCKABLE_STATUSES`가 원래 정의 위치의 *직후 route 블록*(collection_health)에 딸려가
  collections.py로 오배치 → shared._acquire_reindex_lock이 F821. **shared로 수동 이동**해 봉합.
- `MAX_UPLOAD_BYTES`(헬퍼 아닌 상수)는 shared엔 잘 안착했으나 documents.py의 `from .shared import`
  헬퍼 목록에 없어 F821 → import에 상수 추가.
- 교훈: **함수 사이 모듈 상수는 "누가 쓰나"로 shared 귀속을 수동 확인**(learning 381의
  keep-shared-util-in-origin 원칙의 상수판).

## 완료 조건 (동작 불변)

- rag.router 라우트 14개 = 원본 동일(메서드·경로 목록 대조 일치) · 재수출 심볼 접근 가능.
- ruff 통과 · app import(순환 0) · make test SUITE_OK · e2e 39/39 · tsc 무영향(백엔드 전용).

## 검증 결과 (2026-07-16 — done)

전부 초록: ruff 통과 · rag.router 14 라우트(원본 경로 목록 완전 일치) · sweep/resolve 재수출 접근 ·
app import 순환 0 · SUITE_OK · e2e 39/39. rag.py 1256줄 단일 라우터 → 4개 도메인 모듈 + shared 서비스층.

## OUT / 후속

- shared.py 669줄이 여전히 큼(헬퍼 27개) — reindex 서비스(_do_reindex·_record_reindex_event 등)를
  별 서비스 모듈로 재분리 가능하나 지금은 라우트 축 분리가 목표(YAGNI). 필요해지면 후속.
- 캠페인 374 Tier 2 잔여: ② chat_context typed builder(ctx dict→DTO 계약 변경) — 다음.

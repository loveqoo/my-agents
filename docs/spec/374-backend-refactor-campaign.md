# 374 — 백엔드 리팩토링 캠페인 (주요 10파일 + codex 비판 리뷰)

## 왜 / 무엇

구남님 지시: 주요 클래스/파일 10개를 선정해 리팩토링하고, codex에게 비판 리뷰를 받아 참고한다.
범위 = **백엔드 Python 중심**(구남님 확정). 방금 끝난 캠페인(367~373)이 chat/runtime/chat_context
코어를 키워 구조 정비 시점이 맞다.

## 대상 10파일 (크기·중심성 선정)

chat.py(1408)·rag.py(1256)·schemas.py(1054)·runtime.py(1043)·blocks.py(957)·batch/jobs.py(881)·
models.py(765)·chat_context.py(730)·eval_runs.py(637)·flows/pipeline.py(456).

## codex 4그룹 리뷰 (read-only, `-o` 최종본) — 정직한 결론

**활성 버그(correctness) P1은 0건.** codex가 낸 "P1"은 전부 **중복→드리프트 위험**과 **파괴 경로
god-function 테스트 사각**이다. 즉 버그 수정이 아니라 진짜 구조 리팩토링. (메인이 대조 검증: MCP 캡
중복은 blocks.py `500/30/100` == schemas.py `max_length` 실재 확인·공유 상수 없음.)

### 합의된 핵심 발견 (그룹 A/B/C/D)

- **A 채팅런타임**: `chat()` 라우트가 권한·컨텍스트·체크포인트·SSE까지 앎→`ChatTurnService`; `_*_frames`
  중복→`PendingTurnEmitter`; `_GRAPH_CACHE` 전역→주입형 `GraphCache`. runtime.py의 RAG 검색(400~729)이
  MCP·redaction과 한 파일→`rag_runtime.py`. `_load_context`(136행) ctx dict 계약이 3파일 관통→typed builder.
- **B 데이터/블록**: (P1) **MCP 도구메타 캡 단일화**(blocks.py+schemas.py 중복 `500/30/100`). models.py·
  schemas.py를 bounded context별 분할(blocks/rag/agents/auth/eval). `AgentConfig` god-class→중첩 모델.
- **C 평가/배치**: (P1) eval **실행 admission 정책 드리프트**(자동회귀 vs 수동이 따로 판정). (P1)
  `_execute_run`·`consolidate_user_memories`·`cleanup_test_users` god-function(파괴 경로). (P1)
  `is_delete_all_pattern` 가드가 무거운 jobs import에 묶임→`batch/guards.py`.
- **D RAG/플로우**: (P1) rag.py 1256행 라우터가 CRUD·health·reindex·retrieval·ingest·편집 전부→축 분리.
  (P1) 임베딩 모델 검증 생성 vs 재인덱싱 중복→단일 validator. (P1) pipeline `build_graph` god-function.

전체 원본: `.dev/`에 codex-A~D 리뷰 보관(참고).

## 실행 계획 — 위험 오름차순 3-tier

각 tier는 **per-spec 커밋**·**회귀 그물**(make test SUITE_OK + e2e 39/39 + tsc 0)로 마감. 순수 이동·
분할은 동작 불변이 완료조건(측정으로 확인). 구조 우선(structure-first)·전체 정합(whole-fix).

### Tier 1 — DRY 단일화 (저위험·높은 드리프트 차단, "자 먼저")
1. **MCP 도구메타 캡 단일 출처** — `mcp_tool_meta.py` 정책 모듈에 `500/30/100` + 정규화 DTO 집중,
   blocks.py·schemas.py가 참조. (캡 **값은 불변** — 단일화만. 값 변경은 product-limit 승인 사항.)
2. **RAG 임베딩 검증 단일 validator** — 생성·재인덱싱·인제스트가 같은 kind/probe/dims 규칙 공유.
3. **eval 실행 admission 단일 서비스** — 자동회귀·수동이 같은 판정(회수·비용가드) 호출.

### Tier 2 — 파일 분할·경계 이동 (중위험, 순수 이동·테스트 그물 가드)
4. **rag.py 축 분리** — collections/documents/reindex/ingest/search 라우터·서비스로.
5. **runtime.py에서 `rag_runtime.py` 추출** — MCP 실행과 RAG 검색 코어 분리.
6. **schemas.py·models.py bounded context 분할** — `schemas/*.py`·`models/*.py`(공통 Base/AuditOut 공유),
   `AgentConfig` 중첩 모델화.
7. **chat_context.py typed builder** — `_load_context`→`ChatContextBuilder` + typed DTO(ctx dict 계약 제거).

### Tier 3 — god-function 수술 (고위험·핫/파괴 경로 — **출하 전 codex 적대 리뷰 필수**)
8. **chat.py `ChatTurnService`** — 라우트는 서비스 호출+StreamingResponse만.
9. **eval_runs.py application service** — executor/factory/scheduler 분리.
10. **batch/jobs.py 도메인별 분할 + plan/execute** — 파괴 잡(삭제·통합·권한 purge)은 순수 판정↔실행 분리.
    (비가역 경로 — adversarial-review-before-destructive-ship 준수.)
11. **pipeline.py `build_graph`/`_make_step` 분해** — PipelineCompiler/NodeStep.

## 완료 조건 (tier별)

- 각 항목: **동작 불변** — 리팩토링 전후 make test SUITE_OK·e2e 39/39·tsc 0 동일(순수 구조 변경).
- Tier 3(핫/파괴): 봉합 후 **codex 적대 리뷰**로 "쪼개며 흘린 것 없는가" 대조 후 출하.
- per-spec 커밋(각 항목 = 스펙 슬롯 or 374 하위 단위), 푸시는 구남님 명시 시만.

## OUT / 열린 결정 (구남님 승인 필요)

- **얼마나·어느 순서로** — Tier 1만? 전체 캠페인? tier별 체크포인트 vs 자율 완주?
- Admin/프론트는 이번 범위 밖(백엔드 확정).
- 캡·한계 **수치 변경 없음**(단일화만) — 값 조정은 별도 승인.

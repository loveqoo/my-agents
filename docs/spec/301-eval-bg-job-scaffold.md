# 301 — eval 배경 작업 스캐폴딩 정본화 (락 lifecycle·마커·실패 스탬프 원자화)

## 배경

census 후보 D(최대 절감, 중간 위험). `eval_authoring.py`의 4개 배경 작업(`_execute_generation`·
`_execute_suggestion`·`_execute_generation_append`·`_execute_harvest`)이 스캐폴딩을 반복:
- **finally `_active_jobs.discard`** 4× 바이트 동일
- **next-order 계산**(`func.coalesce(func.max(order_idx),-1)+1`) 3× 바이트 동일(suggestion·append·harvest)
- **완료 마커 치환**(`cur.endswith(mark)` → rstrip 후 덧붙임) 3× 구조 동일(mark 문자열만 차이)
- **실패 스탬프**(load ds→description=실패msg→commit→swallow) 4× 구조 동일(메시지만 차이)
- `_execute_suggestion` ↔ `_execute_generation_append` **~90% 바이트 동일**(차이=생성기·케이스 빌더뿐)

## 위험 (census 경고 — 반드시 준수)
- **사용자 노출 문자열**(description 마커·tail·실패 메시지)은 codex 142/143/195가 경화한 UX 계약
  (Skeleton 폴링·마커 치환). **바이트 보존 필수** — 드리프트 시 프론트 폴링/배지 깨짐.
- **락 lifecycle**: `_active_jobs.add`는 **엔드포인트가 동기 획득**(create_task 전 창 닫아 flood 카운트
  누락 방지, codex #1/#2). 배경 fn은 `finally`에서 discard만. 정본화가 이 비대칭을 깨면 안 됨 →
  **async 컨텍스트매니저는 discard(finally)만 소유**, add는 엔드포인트에 그대로 둔다.

## 설계 (원자 4 + 통합 1)

모두 `eval_authoring.py` 모듈 레벨(eval-authoring 전용 배경 헬퍼).

1. `async def _next_order_idx(s, dataset_id) -> int` — 다음 order_idx(coalesce max +1).
2. `def _apply_completion_marker(ds, mark, tail) -> None` — `cur.endswith(mark)`면 마커 제거 후 tail
   덧붙임, 아니면 뒤에 붙임(사용자 편집 보존, codex 143). ds.description 변경.
3. `async def _stamp_failure(dataset_id, message) -> None` — load ds→description=message→commit,
   전부 swallow(실패 스탬프 자체 실패도 무시). **메시지는 호출자가 완성**(생성/출제/수확 문구 차이 존치).
4. `@asynccontextmanager async def _job_lock(dataset_id)` — `try: yield finally: _active_jobs.discard`.
   **add는 미포함**(엔드포인트 소유). 4개 배경 fn이 body를 이걸로 감싼다.
5. `async def _execute_append_job(dataset_id, count, prior_desc, *, generate, build_case)` — suggestion·
   generation_append 통합 골격. 차이만 주입: `generate: () -> Awaitable[dict]`(생성기),
   `build_case: (ds_id, order_idx, c) -> EvalCase`(name·asserts). tail("AI 출제 …")·마커("AI 출제 중…")·
   실패("…AI 출제 실패:")는 두 함수가 바이트 동일이라 골격에 흡수.

각 배경 fn 처리:
- **`_execute_suggestion`·`_execute_generation_append`** → `_execute_append_job` 호출하는 **얇은 래퍼**
  (build_case에 name/asserts 차이만). 생성기=suggest_agent_cases / generate_golden_cases.
- **`_execute_generation`** → `_job_lock` + `_stamp_failure`만 차용(order_idx=i·직접 description·자체
  llm_cfg 해석은 본문 존치, 마커/next_idx 안 씀).
- **`_execute_harvest`** → 원자 4개 다 차용(next_idx·마커("피드백 수확 중…")·stamp·lock)하되, 케이스
  루프(flush + MessageFeedback.harvested_case_pk 스탬프)는 append와 달라 **본문 존치**(억지 통합 금지).

## 목표 (측정 가능)
1. 원자 4 + `_execute_append_job` 신설. `finally: _active_jobs.discard` 인라인 0(전부 `_job_lock`).
   next-order 인라인 조립 3→0(전부 `_next_order_idx`). 마커 치환 인라인 3→0(`_apply_completion_marker`).
2. **행위·문자열 바이트 보존**: 4개 배경 작업의 description 마커·tail·name·asserts·실패 메시지 전부 불변.
   `_execute_suggestion`↔append 통합 후 각 케이스의 name/asserts가 원본과 동일.
3. **락 불변식 보존**: add=엔드포인트(4곳)·discard=`_job_lock`(4곳). create_task 실패 경로의 엔드포인트
   discard(324·443)도 불변.

## 검증 (사다리 3런)
- **단위/게이트**: metrics-fast 0(복잡도는 오히려 감소). 인라인 스캐폴드 잔존 0(grep).
- **실인프라 통합**: 스위트 51/51. **verify_142/143/195**(생성·출제·description 마커) — 배경 작업의
  사용자 문자열·Skeleton 계약. 없으면 라이브로 생성→폴링→마커 확인.
- **적대(codex)**: 여집합 — (a) 마커/tail/name/asserts/실패 메시지 4작업 각각 **바이트 동일**? (b) 락 add/
  discard 비대칭 보존(컨텍스트매니저가 add 안 함)? (c) suggestion↔append 통합서 build_case가 각 name(역할
  번호 vs 해시)·asserts(c["asserts"] vs 고정 3종) 정확히 재현? (d) harvest의 flush+harvested_case_pk 스탬프
  본문 보존? (e) generation의 order_idx=i·0건 실패 메시지 보존? (f) `_stamp_failure` swallow 의미 보존?

## OUT
- `_execute_harvest` 케이스 루프·`_execute_generation` 본문 통합 — 구조 상이(억지), 원자만 차용.
- 엔드포인트의 `_active_jobs.add` 이동 — 동기 획득이 flood 가드 핵심(codex #1/#2), 배경 fn/컨텍스트매니저로 옮기지 않음.

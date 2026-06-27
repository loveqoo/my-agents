# 039 — 유저 메모리 통합·재적재 (P3-b, #6)

> 로드맵: `docs/spec/033-feature-roadmap.md` P3-b. 토대: [[038-batch-foundation-session-cleanup]]
> (격리 배치 서비스 — runner/BatchRun/CLI/엔드포인트/BatchView 재사용).
> 관련 learning: 037(파괴적 노브 바닥), 033(autogenerate), 012(런타임 설정=DB), 019/020/021(mem0 스코프),
> 030(브라우저 검증), 036(측정 의심). 회고 [[028-batch-foundation]].

## 1. 문제 — 유저 장기기억이 단조 증가만 한다

mem0 `user_id` 축(세션 가로지르는 유저 사실)은 턴마다 `add(infer=True)`로 쌓이기만 한다(chat.py
add_scope). 같은 사실의 변주·중복·낡은 정보가 누적돼 (a) 회상 품질이 흐려지고(top-k에 중복이 끼고)
(b) 토큰·저장 비용이 늘고 (c) 운영자가 관리 콘솔(스펙 030)에서 큐레이션하기 어려워진다.
**누적 유저기억을 주기적으로 더 적고 일관된 사실로 통합(consolidate)할 토대가 없다.**

세션정리(#3, 038)는 *전사(세션)* 를 지웠지만 *장기기억(mem0)* 은 의도적으로 건드리지 않았다
(jobs.py 주석 "전사 ≠ 장기기억(#6은 039)"). 이 스펙이 그 장기기억 측을 맡는다.

## 2. 목표 — 임계치 초과 유저의 기억을 LLM으로 통합 후 스냅샷 백업하며 교체

038 격리 배치에 **두 번째 작업 `memory-consolidation`** 을 추가한다. cron + per-user 임계치로 발화,
임계치를 넘은 유저의 `user_id` 기억을 LLM으로 통합하고, **원본을 감사 테이블에 스냅샷 백업한 뒤
교체**(롤백 가능)한다. dry-run은 아무 것도 변형하지 않고 미리보기만 제공한다.

### 설계 결정 (사용자 합의 — AskUserQuestion 2026-06-27)

1. **#6 의미 = 누적 유저기억 통합·압축.** `user_id` 축에 쌓인 장기기억이 임계치를 넘은 유저를
   LLM으로 더 적고 일관된 사실로 통합한 뒤 재적재. (세션→유저 승격은 범위 밖.)
2. **재적재 안전 = 스냅샷 백업 후 교체.** 원본을 `MemorySnapshot` 감사 테이블에 박제한 뒤 교체 →
   잘못돼도 원문이 남아 롤백 가능. (append-only는 압축 효과가 없어 탈락, 단순 교체는 비가역이라 탈락.)
3. **트리거 = cron + per-user 임계치.** BatchConfig에 cron + 임계치 필드 추가. 임계치를 넘은
   유저만 대상(불필요한 LLM 호출·파괴 최소화). 038 BatchConfig/스케줄러 재사용.

### 스코프·대상 유저 식별 (비결합)

- **대상 축은 `user_id`만.** `run_id`(세션 단기)·`agent_id`(에이전트 전용)는 절대 건드리지 않는다.
- **대상 유저 열거 = App DB의 `User` 테이블** → `str(user.id)`가 곧 mem0 `user_id` 축
  (chat.py `user_id = str(principal.id)` 확인). 각 유저에 `list_memories({"user_id": ...})`로
  **실제 기억 수를 측정**해 임계치 필터. mem0 내부 스키마(`mem0_memories` JSONB)를 직접 쿼리하지
  않는다 — 우리가 소유한 데이터(User 테이블)로 스코프를 정한다(learning 019/021 정신).
- 머신토큰 대화(user_id=None)는 애초에 user_id 태깅이 안 되므로 대상에서 자연 제외.

### 안전 불변식 (이 스펙의 핵심 — 파괴적 작업)

1. **임계치 바닥(learning 037).** `memory_consolidation_threshold`: NULL=비활성. **API에서 `ge=2`**,
   **실행 지점에서 `< 2 → disabled`**(이중). 0/1은 "거의 모든 유저를 매번 통합"하는 파괴적 churn이라
   입력·실행 양쪽에서 차단. 기본 NULL=비활성(운영자가 명시적 양수를 넣어야 시작).
2. **검증 전 삭제 금지.** 유저별 순서: ① 통합 결과가 **비어있지 않음** 확인(LLM 실패/0건이면 그 유저
   **전체 스킵**, 절대 삭제 안 함) → ② 원본을 `MemorySnapshot`에 박제 + **commit** → ③ 통합본 add →
   ④ **그제서야** 박제한 원본 mem_id만 삭제. 어느 단계라도 실패하면 삭제로 안 번진다(원본+스냅샷 생존).
3. **정확히 박제한 id만 삭제.** "현재 유저 기억 전부"가 아니라 **스냅샷에 담은 그 mem_id들만** 삭제 →
   list와 delete 사이에 라이브 채팅이 추가한 새 기억은 살아남는다(동시성 안전).
4. **dry-run은 무변형.** 스냅샷·add·delete 전무. LLM 통합은 호출해 *미리보기*만 제공(정직한 예측).
5. **graceful.** mem0 add/delete는 best-effort(실패 흡수) — 실제 성공 수를 센다.

## 3. 백엔드

### 3.1 모델 (`models.py`) — Base.metadata 등록 필수(learning 033 autogenerate)

- `BatchConfig`에 2필드 추가:
  - `memory_consolidation_threshold: int | None`(NULL=비활성, 의미상 ≥2)
  - `memory_consolidation_cron: str | None`(NULL=미등록)
- **신규 `MemorySnapshot`**(감사·롤백 앵커):
  - `id`(uuid pk), `batch_run_id`(str, BatchRun.id 참조 — 어느 실행이 만든 백업인지),
    `user_id`(str, mem0 축), `mem_id`(str, 원본 mem0 id), `text`(Text, 원문),
    `created_at`(timestamptz, default now)
- 마이그레이션: batch_config 2컬럼 + memory_snapshots 테이블(앱 방식 적용 — 028 회고의 init_db 경로).

### 3.2 mem_cfg 해석기 추출 (Scaffolding — 격리 유지)

`default_mem_cfg`/`_build_mem_cfg`/`_default_chat_model`/`_default_embed_model`는 `ModelConfig`·`crypto`만
의존(langgraph/fastapi 무관)인데 현재 `chat.py`(=`from agent.main import build_agent`)에 있다. 격리 배치가
chat.py를 임포트하면 langgraph 전체가 배치 프로세스로 딸려온다(038 격리 취지 훼손).

→ **신규 경량 모듈 `api/mem_config.py`** 로 이 4함수를 이동. `chat.py`는 re-import(`resolve_agent_mem_cfg`는
agent 인자를 받으므로 chat.py 잔류, 단 내부에서 mem_config의 헬퍼 사용). `memory_routes.py`의
`from .chat import default_mem_cfg` → `from .mem_config import default_mem_cfg`로 갱신. 행동 불변(순수 이동).

### 3.3 배치 작업 (`api/batch/`)

- **`jobs.py` — `consolidate_user_memories(*, dry_run)`**:
  1. `_get_config` → threshold. `None or < 2` → `{"status":"disabled"}`(안전 불변식 1).
  2. `default_mem_cfg(session)`(mem_config)로 mem_cfg 해석. None(모델 미설정)이면 `{"status":"disabled","reason":"no_mem_cfg"}`.
  3. `select(User.id)` 전수 → 각 `str(uid)`에 `list_memories`(to_thread) → count > threshold인 유저만 후보.
  4. 후보별로 `_consolidate(texts, mem_cfg)`(LLM, to_thread) → 통합 사실 list.
     - **dry_run**: 변형 없이 `candidates`에 `{user_id, before, after, sample}` 적재. 끝.
     - **real**: 통합본 비었으면 스킵(불변식 2). 아니면 MemorySnapshot 박제+commit → `add(infer=False)`로
       통합본 적재(이미 정제된 한 줄 사실 — 재추출 방지) → 박제한 mem_id만 `delete_memory`.
  5. summary: `{status, threshold, users_scanned, consolidated:[{user_id,before,after,snapshot}], total_before, total_after}`.
- **`_consolidate(texts, mem_cfg) -> list[str]`**: openai-호환 chat completion(mem_cfg["llm"]) 직접 호출.
  프롬프트 "다음 유저 사실들을 중복 없이 더 적고 일관되게 통합, 한 줄에 하나". 응답을 줄 단위 파싱.
  실패·빈 응답 → `[]`(→ 그 유저 삭제 안 함). 미리보기 키(sample 등)는 runner의 `_AUDIT_OMIT_KEYS`로
  감사행 미영속(038 데이터 최소화 계승) — 필요 시 `sample` 키를 omit 목록에 추가.
- **`JOBS`에 `"memory-consolidation"` 등록.** runner/CLI/엔드포인트는 무수정(작업명으로 일반화돼 있음).
- **`service.py` `_load_schedules`**: `memory_consolidation_cron`도 등록(session-cleanup과 나란히).

### 3.4 라우트 (`batch_routes.py`)

- `BatchConfigIn`에 `memory_consolidation_threshold: int|None = Field(default=None, ge=2)` +
  `memory_consolidation_cron: str|None` 추가. GET/PATCH/jobs/trigger는 무수정(일반화돼 있음).

## 4. 프론트 (`admin/`) — BatchView 확장

- `api.ts`: `BatchConfig`에 `memory_consolidation_threshold`·`memory_consolidation_cron` 추가.
- `BatchView.tsx`: 두 작업을 패널로 분리.
  - 세션정리(기존) + **메모리 통합**(신규): InputNumber "통합 임계치(기억 수, ≥2)" + Input "스케줄(cron)" +
    설정 저장(dirty 게이트) + Dry-run + 지금 실행(danger, Popconfirm) for `memory-consolidation`.
  - 실행 이력 DataTable은 job_name 컬럼으로 두 작업 공용(무수정).
- summary 칩: disabled/dry_run(candidates 수)/ok(consolidated 유저 수, total_before→after).

## 5. 검증 (자가검증 지양 — 036)

- **수치 `tests/verify_039_memory_consolidation.py`** (실 DB + 실 mem0, `_consolidate`는 결정적 stub로
  monkeypatch — LLM 비결정성 제거하고 **파이프라인**을 단언):
  - seed: 테스트 user_id에 `add(infer=False)`로 임계치 초과 N개 기억.
  - dry-run: status=dry_run, 후보 present(before=N), **변형 0**(이후 list 카운트 불변).
  - real: MemorySnapshot N행(run_id 링크) + 원본 삭제 + 통합본 add(0<after<N). 멱등(재실행 시 임계치 미달→무동작).
  - threshold None/<2 → disabled + 무변형.
  - 안전: `_consolidate`가 `[]` 반환 → **삭제 0**(원본 생존). 임계치 미달 타 user_id 불변.
  - 정리: 테스트가 만든 user_id 기억·스냅샷 cleanup.
- **브라우저 `tests/browser/shot-memory-039.mjs`**(시스템 Chrome, 030 계승): 배치 메뉴 → 메모리 통합 패널
  설정 저장 토스트 → dry-run 토스트. **지금 실행은 클릭 안 함**(데이터 안전). 능동 캡처.
- **적대 검증**: 서브에이전트 + codex 병렬 독립 리뷰. 초점 = 파괴 경로(삭제 전 검증, threshold 경계,
  동시 추가 생존, 스냅샷 완전성, 롤백 가능성).

## 6. 완료 조건

- [x] BatchConfig 2필드 + MemorySnapshot 모델 + 마이그레이션(Base.metadata 등록, 앱 방식 적용 확인).
- [x] `mem_config.py` 추출 + chat.py/memory_routes.py 갱신, 기존 동작 불변(기존 verify 통과).
- [x] `consolidate_user_memories` 작업 + `_consolidate` + JOBS 등록 + service 스케줄.
- [x] batch_routes BatchConfigIn `ge=2` 필드. BatchView 메모리 통합 패널.
- [x] verify_039 ALL PASS(34단언, 실 mem0). 브라우저 3컷(dry-run 실유저 무변형 확인). 적대 리뷰 반영.
- [x] 안전 불변식 1~5 모두 코드+테스트로 박제.
- [x] 적대 리뷰 CRITICAL 2건(미축소 쓰레기 교체·프롬프트 잘림 손실) 실행 지점 floor + 테스트([4b]).

## 7. 빚 (의도적, 이후)

- **자동 롤백 작업.** 현재 job 시그니처(`*, dry_run`)는 `batch_run_id` 같은 파라미터를 못 받는다 →
  자동 restore 작업은 runner/CLI/엔드포인트 시그니처 확장 필요. 이번엔 스냅샷을 **롤백 앵커**(데이터
  보존)로 두고, 복원은 문서화된 수동 절차(스냅샷 text를 `add(infer=False)`로 재적재). 자동화는 후속.
- LLM 통합 품질 튜닝(프롬프트·few-shot), per-user 통합 결과 diff UI, 동시 실행 잠금(038 빚 계승).
- 대규모 유저 시 후보 스캔 비용(전 User list_memories) 최적화 — 필요 시 mem0 카운트 캐시.

### 적대 리뷰(2026-06-27) 잔여 빚 — floor는 코드에, 나머지는 여기

이번에 **실행 지점 floor로 막은 것**(learning 037): ① 미축소/확장 통합 결과는 무효 처리해 스킵
(`_valid_consolidation` — 비거나 `len(new) >= len(orig)`면 삭제 안 함), ② 입력 기억 수 상한
(`_MAX_CONSOLIDATE_INPUT=200`) 초과 유저는 스킵(프롬프트 잘림 → 잘린 사실 통합 누락 후 삭제되는
영구 손실 방지), ③ 삭제 수 < 스냅샷 수면 경고 로그(원본 잔존=통합본과 중복, 손실 아님). dry-run
미리보기는 이 스킵을 `skip` 키로 정직히 표기. **남은 빚**:

- **비-구조적 쓰레기 출력.** 모델이 *줄어든* 거부문 한 줄(예: 20→1 "도와드릴 수 없습니다")을 뱉으면
  shrink 게이트를 통과한다. 구조적(개수)으로는 못 거른다 — 의미 검증(거부/머리말 패턴, 센티넬 래핑,
  입력 파생 여부)은 후속. 현 백스톱: **스냅샷**(롤백 앵커) + **dry-run 미리보기**(운영자가 cron 전
  실제 출력을 눈으로 확인). 임계치 기본 NULL=비활성이라 운영자 명시 opt-in이어야 동작.
- **add-before-delete 비-멱등.** add 후 delete 전 크래시 → 원본+통합본 공존, 재실행 시 재통합 churn.
  의도적 선택: 최악이 **중복(가역)**이지 손실이 아니다(delete-first면 add 실패 시 손실). 수렴화(통합본
  태깅·재통합 제외)는 후속. ③의 경고 로그로 가시화.
- **`batch_run_id` SET NULL.** BatchRun 삭제 시 스냅샷↔run 링크가 끊긴다. 단 스냅샷의 `user_id`·
  `created_at`은 남아 "유저 X의 그 시각 스냅샷"으로 수동 복원은 가능. RESTRICT 또는 run 타임스탬프
  비정규화는 후속.
- **`add(infer=False)` 순수 insert 가정**은 verify_039 `[2]`(deleted==N + 최종==STUB)로 **실측 핀**됨 —
  원본이 add 이후에도 살아 명시 삭제로만 지워짐을 증명. mem0 버전 업 시 이 단언이 회귀 가드.

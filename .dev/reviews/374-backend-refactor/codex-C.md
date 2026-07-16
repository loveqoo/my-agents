[단계 6 — Compounding]

## packages/api/src/api/eval_runs.py

[eval_runs.py:28] (P1) `_execute_run`이 케이스 로딩·judge 모델 해석·agent/RAG 실행 분기·결과 저장·오류 상태 갱신을 100행 넘게 떠안음 → `EvalRunExecutor`와 `JudgeResolver`/`ResultPersister`로 쪼개고 세션 팩토리를 주입하라

[eval_runs.py:68] (P2) `_execute_run` 내부 지연 import가 judge 설정·mem config·RAG runner까지 끌어와 실행 로직과 조립점이 섞임 → import/의존성 조립은 모듈 상단 또는 별도 factory로 빼고 runner는 인터페이스만 받게 하라

[eval_runs.py:222] (P1) 자동 회귀가 케이스 수·running 중복·비특권 비용 가드를 직접 반복하고 수동 실행은 `_assert_run_admission`/`_member_run_guard`로 따로 판단해 드리프트 위험이 있음 → 실행 admission 정책을 하나의 서비스로 추출해 수동/자동 경로가 같은 판정을 호출하게 하라

[eval_runs.py:394] (P2) `_spawn_runs`가 단일 모델·비교 그룹·기본 실행에서 `EvalRun` 생성, env 조립, commit, spawn을 세 번 복제함 → `EvalRunFactory`와 `RunScheduler`를 분리해 분기별 차이는 spec만 넘기게 하라

[eval_runs.py:498] (P2) 라우트 함수 `start_run`이 권한, 대상 해석, admission, 모델 검증, 버전 해석, env 스냅샷, background spawn까지 조율해 API 계층이 런타임 세부를 알고 있음 → 라우트는 request DTO를 application service에 위임하고 HTTP 예외 변환만 남겨라

[eval_runs.py:588] (P1) `get_run`이 `RunDetailOut` 직렬화의 ORM lazy 관계 충돌을 라우트 내부 수동 조립으로 우회해 schema/ORM 결합이 라우트로 누출됨 → response DTO 생성 전용 mapper를 두거나 ORM 관계명과 응답 필드명을 분리해 MissingGreenlet 방지를 한곳에 고정하라

[eval_runs.py:603] (P2) 실행 라우트 파일이 startup zombie dataset/run sweep까지 포함해 HTTP API와 부팅 복구 책임이 섞임 → `eval_startup_recovery.py` 같은 모듈로 sweep 함수를 이동하고 라우트 모듈은 엔드포인트만 유지하라

## packages/api/src/api/batch/jobs.py

[jobs.py:1] (P2) 881행 파일 하나에 세션·메모리·A2A·유저·토큰·승인·이력·checkpoint 정리 잡이 모두 들어 있어 배치 레지스트리와 도메인별 정책이 결합됨 → `batch/jobs/{sessions,memory,agents,users,tokens,approvals,history}.py`로 나누고 이 파일은 registry만 남겨라

[jobs.py:126] (P2) `cleanup_sessions`가 config 조회, 삭제 조건 생성, pending approval 보호, dry-run 응답, 실제 삭제를 한 함수에 섞음 → 조건 빌더와 executor를 분리해 dry-run/execute가 같은 candidate set을 공유하게 하라

[jobs.py:199] (P2) `_consolidate`가 OpenAI client 생성과 프롬프트 실행을 직접 수행해 배치 도메인 로직이 특정 LLM SDK 생성 방식을 앎 → `MemoryConsolidator` 인터페이스로 빼고 jobs는 통합 요청/결과만 다루게 하라

[jobs.py:261] (P1) `consolidate_user_memories`가 후보 스캔, dry-run preview, LLM 통합, snapshot, mem0 add/delete, degraded 보고를 160행 이상에서 처리해 파괴적 경로 테스트가 어려움 → per-user plan/preview/commit 단계로 쪼개고 삭제 전 불변식은 순수 함수로 검증하라

[jobs.py:346] (P2) 메모리 통합 실행 중 각 유저마다 새 `SessionLocal`을 열어 snapshot만 별도 commit하고 이후 mem0 write/delete를 이어가 DB 트랜잭션 경계와 외부 저장소 경계가 함수 내부에 숨음 → snapshot repository와 memory backend 작업 단계를 명시한 saga 형태로 분리하라

[jobs.py:470] (P1) `is_delete_all_pattern`은 `batch_routes.py`가 import하는 API 입력 검증 계약인데 `jobs.py` 전체 import에 묶여 memory/checkpoint 등 무거운 배치 의존성을 함께 로드함 → 공유 guard를 `batch/policies.py` 또는 `batch/guards.py`로 분리해 라우트가 잡 구현을 import하지 않게 하라

[jobs.py:571] (P1) `cleanup_test_users`가 패턴 검증, keep-list, 마지막 super 보호, Casbin raw SQL purge, User delete, enforcer reload를 한 흐름에 묶어 권한 정리와 사용자 삭제 경계가 흐림 → candidate selector, deletion transaction, authz cleanup/reload를 별도 컴포넌트로 분리하라

[jobs.py:666] (P2) `cleanup_tokens`, `cleanup_approvals`, `cleanup_history`가 retention 설정 읽기, disabled 판정, cutoff 계산, dry-run/execute 응답 패턴을 반복함 → 공통 `RetentionJobPolicy`/`DryRunDeletePlan` 헬퍼를 두고 테이블별 selector만 남겨라

## 이 그룹 TOP 3

1. `eval_runs.py`의 실행 admission/생성/scheduling을 application service로 추출 — 수동 실행과 자동 회귀의 드리프트가 실제 비용·중복 실행 위험으로 이어질 수 있다.
2. `jobs.py`의 파괴적 잡을 도메인별 모듈과 plan/execute 구조로 분해 — 삭제·통합·권한 purge가 섞인 긴 함수는 테스트 사각이 크고 실패 시 복구 지점이 불명확하다.
3. `is_delete_all_pattern` 같은 공유 guard를 batch job 구현에서 분리 — API 검증 계층이 잡 구현 전체에 결합되어 경계가 새고 import 부작용/순환 의존 위험을 키운다.


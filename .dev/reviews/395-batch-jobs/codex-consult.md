# codex 자문 원문 — batch/jobs.py 리팩터 (2026-07-18, 스펙 395 입력)

[단계 5 — Verification] read-only로 파일·소비자·verify 표면만 확인했습니다. 수정·테스트 실행은 하지 않았습니다.

**판단**
`packages/api/src/api/batch/jobs.py`는 지금 당장 `batch/jobs/` 서브패키지로 바꾸기보다, 이 저장소의 최근 선례처럼 `batch/jobs.py`를 파사드로 남기고 `batch/jobs_*.py` 평면 형제 모듈로 나누는 쪽이 맞습니다. 이미 `blocks_*.py`, `chat_context_*.py`, `chat_*`가 같은 방식이고, 현재 소비자는 `from api.batch.jobs import ...`를 많이 핀합니다.

**구조 결함 우선순위**
1. `jobs.py`가 레지스트리, API 검증용 guard, 파괴적 실행 정책, 외부 mem0/LLM 호출을 한 import 단위에 묶습니다. 특히 `batch_routes.py`는 `JOBS`와 `is_delete_all_pattern`만 필요하지만 전체 잡 구현을 import합니다: [batch_routes.py](/Users/anthony/Repository/github/{{GITHUB_ORG}}/my-agents/packages/api/src/api/batch_routes.py:15), [jobs.py](/Users/anthony/Repository/github/{{GITHUB_ORG}}/my-agents/packages/api/src/api/batch/jobs.py:480), [jobs.py](/Users/anthony/Repository/github/{{GITHUB_ORG}}/my-agents/packages/api/src/api/batch/jobs.py:894).

2. `_consolidate`는 C급 원인 그대로입니다. 프롬프트, OpenAI client 생성, 동기 LLM 호출, 예외 처리, 라인 파싱, dedupe를 한 함수가 합니다: [jobs.py](/Users/anthony/Repository/github/{{GITHUB_ORG}}/my-agents/packages/api/src/api/batch/jobs.py:199). 분해 방향은 `build_consolidation_messages()`, `parse_consolidation_lines()`, `OpenAIConsolidator.consolidate(texts, cfg)`입니다. 단, 기존 verify가 `jobs_mod._consolidate`를 monkeypatch하므로 파사드 재수출은 유지해야 합니다: [verify_039_memory_consolidation.py](/Users/anthony/Repository/github/{{GITHUB_ORG}}/my-agents/tests/verify_039_memory_consolidation.py:121).

3. `consolidate_user_memories`는 후보 조회, threshold/mem_cfg 해석, dry-run preview, per-user saga, 집계 summary를 한 함수가 조율합니다: [jobs.py](/Users/anthony/Repository/github/{{GITHUB_ORG}}/my-agents/packages/api/src/api/batch/jobs.py:358). 이미 `_consolidate_one_user`가 있지만, snapshot commit → mem0 add → 원본 delete의 외부 저장소 saga 경계가 내부에 숨습니다: [jobs.py](/Users/anthony/Repository/github/{{GITHUB_ORG}}/my-agents/packages/api/src/api/batch/jobs.py:290). `MemoryConsolidationPlanner`, `MemoryConsolidationExecutor`, `MemorySnapshotRepository`, `MemoryBackendAdapter`로 나누는 게 맞습니다.

4. 파괴적 selector와 executor가 가족마다 흩어져 있습니다. `cleanup_sessions`는 그나마 후보 id를 한 번 만들고 dry-run/execute가 공유하지만: [jobs.py](/Users/anthony/Repository/github/{{GITHUB_ORG}}/my-agents/packages/api/src/api/batch/jobs.py:155), 토큰/승인/이력은 count/select 후 delete predicate를 다시 만듭니다: [jobs.py](/Users/anthony/Repository/github/{{GITHUB_ORG}}/my-agents/packages/api/src/api/batch/jobs.py:676), [jobs.py](/Users/anthony/Repository/github/{{GITHUB_ORG}}/my-agents/packages/api/src/api/batch/jobs.py:721), [jobs.py](/Users/anthony/Repository/github/{{GITHUB_ORG}}/my-agents/packages/api/src/api/batch/jobs.py:778). 공통 `DeletePlan(counts, ids_or_predicate, meta)`를 두되, mem0 orphan처럼 TOCTOU 방지를 위해 “한 문장 delete”가 필요한 경우는 예외로 남겨야 합니다.

5. `cleanup_test_users`는 이메일 패턴, keep-list, 마지막 super 보호, Casbin raw SQL purge, User delete, enforcer reload를 한 흐름에 둡니다: [jobs.py](/Users/anthony/Repository/github/{{GITHUB_ORG}}/my-agents/packages/api/src/api/batch/jobs.py:581). 삭제 트랜잭션과 post-commit enforcer reload 순서는 유지하되, candidate policy와 authz cleanup은 별도 모듈로 빼야 합니다.

**분할 설계**
- `batch/jobs.py`: 파사드. 기존 함수명, `_consolidate`, `_is_private_host`, `_protect_last_supers`, `is_delete_all_pattern`, `JOBS`, `default_mem_cfg`, `memory` 재수출 유지.
- `batch/jobs_registry.py`: `JOBS` 단일 출처. runner/CLI는 여기를 직접 import하도록 마지막 단계에서 전환: [runner.py](/Users/anthony/Repository/github/{{GITHUB_ORG}}/my-agents/packages/api/src/api/batch/runner.py:40), [__main__.py](/Users/anthony/Repository/github/{{GITHUB_ORG}}/my-agents/packages/api/src/api/batch/__main__.py:15).
- `batch/jobs_guards.py`: `is_delete_all_pattern`, `_is_private_host`, keep-list/last-super policy 같은 순수 guard. API validator도 여기로 이동.
- `batch/jobs_sessions.py`: session cleanup criteria, pending approval guard, delete plan.
- `batch/jobs_memory_consolidation.py`: consolidation planner/executor/LLM adapter.
- `batch/jobs_agents.py`, `batch/jobs_users.py`, `batch/jobs_retention.py`: A2A, user cleanup, token/approval/history 계열.
- `batch/jobs_checkpoint.py`, `batch/jobs_memory_reclaim.py`: 외부 위임 wrapper만.

서브패키지 `batch/jobs/`는 장기적으로 예쁘지만 지금은 손해가 큽니다. `api.batch.jobs`가 파일에서 패키지로 바뀌면 직접 import 테스트와 monkeypatch가 한 번에 흔들립니다. 평면 형제+파사드는 지저분한 재수출을 감수하는 대신 동작보존 리스크가 낮습니다.

**동작보존 함정**
- 모든 잡 시그니처는 `async def job(*, dry_run: bool, run_id=None) -> dict` 그대로여야 합니다. runner가 keyword-only로 호출합니다: [runner.py](/Users/anthony/Repository/github/{{GITHUB_ORG}}/my-agents/packages/api/src/api/batch/runner.py:55).
- `batch_routes.trigger` 기본값은 `dry_run=True`입니다. CLI `batch run`은 `--dry-run` 없으면 실행입니다. 이 차이를 리팩터 중 통일하면 동작 변경입니다: [batch_routes.py](/Users/anthony/Repository/github/{{GITHUB_ORG}}/my-agents/packages/api/src/api/batch_routes.py:127), [__main__.py](/Users/anthony/Repository/github/{{GITHUB_ORG}}/my-agents/packages/api/src/api/batch/__main__.py:26).
- 반환 dict shape가 UI와 BatchRun summary 계약입니다. `sample`은 라이브 응답엔 있고 감사행엔 scrub됩니다: [runner.py](/Users/anthony/Repository/github/{{GITHUB_ORG}}/my-agents/packages/api/src/api/batch/runner.py:16).
- `_pending_approval_clause`는 나이 절과 턴 절 모두에 AND로 붙어야 합니다. pending approval 세션 삭제는 resume 연속성을 깨뜨립니다: [jobs.py](/Users/anthony/Repository/github/{{GITHUB_ORG}}/my-agents/packages/api/src/api/batch/jobs.py:87).
- `cleanup_sessions`는 `Session.turns`가 진실원입니다. 메시지 행 수로 바꾸면 windowed-mode 고턴 세션을 지웁니다.
- memory consolidation dry-run은 “무변형”이지만 LLM preview는 호출합니다: [jobs.py](/Users/anthony/Repository/github/{{GITHUB_ORG}}/my-agents/packages/api/src/api/batch/jobs.py:384). 비용/외부 호출 시맨틱을 바꾸려면 별도 제품 결정입니다.
- mem0 add 실패 시 원본 삭제 금지, status=`degraded`는 보존해야 합니다: [jobs.py](/Users/anthony/Repository/github/{{GITHUB_ORG}}/my-agents/packages/api/src/api/batch/jobs.py:326).
- Casbin purge는 User delete와 같은 DB 트랜잭션, enforcer reload는 commit 이후입니다: [jobs.py](/Users/anthony/Repository/github/{{GITHUB_ORG}}/my-agents/packages/api/src/api/batch/jobs.py:640).
- mem0 orphan cleanup은 판정과 delete가 같은 SQL이어야 합니다. select ids 후 delete로 바꾸면 TOCTOU 회귀입니다.

**권장 순서**
1. `jobs_guards.py` 추출: `is_delete_all_pattern`, `_is_private_host`, `_protect_last_supers` 같은 순수 함수부터. 파사드 재수출 유지. 검증: `verify_050_destructive_cleanup.py`, `batch_routes.BatchConfigIn`.
2. `jobs_registry.py` 추가 후 `JOBS`만 재수출. runner/CLI/service/list_jobs 소비를 단계적으로 전환. 검증: `verify_038`, `verify_347_resource_gate`.
3. `cleanup_tokens`, `cleanup_approvals`, `cleanup_history`를 `jobs_retention.py`로 이동. 반환 shape 전후 스냅샷 비교. 검증: `verify_349`, `350`, `351`.
4. `cleanup_checkpoints`, `cleanup_memories` wrapper 이동. mem0 orphan은 내부 SQL 구조를 건드리지 말 것. 검증: `verify_352`.
5. `cleanup_a2a_agents`, `cleanup_test_users` 이동 후 selector/policy/execute 분해. 이 단계부터 적대 검증을 넣어야 합니다: 공개 endpoint, 예약 IP, keep-list whitespace/case, 마지막 super, Casbin dangling.
6. `cleanup_sessions` 이동 후 criteria builder와 executor 분해. 적대 검증: 나이∪턴 합집합, pending approval 양 절 제외, turns counter, disabled floor.
7. 마지막으로 memory consolidation 분해. 가장 위험합니다. 적대 검증은 구현 전후 모두 필요합니다: LLM 빈/미축소/과다 입력, add 실패, snapshot 후 delete, list~delete 사이 신규 기억 보존, `jobs_mod._consolidate` monkeypatch 호환.

Compounding은 read-only 요청 때문에 `.dev/retrospect` 작성과 커밋을 생략합니다.

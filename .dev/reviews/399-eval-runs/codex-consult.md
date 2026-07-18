# codex 자문 원문 — eval_runs.py 리팩터 (2026-07-19, 스펙 399 입력)

[단계 5 — Verification]  
참고 자산: 373 생산자-소비자 seam 검증, 381/398 외부 계약 두께 기준, 383/394 격리 대장 대조

Read-only로 실제 파일과 소비자만 확인했습니다. 수정·verify 실행은 하지 않았습니다.

**판정**
가장 큰 구조 결함은 `eval_runs.py`가 “runs 라우트 파일”이 아니라 eval 실행 미니 애플리케이션이라는 점입니다. 실행기, 자동 회귀, 접수 정책, 런 생성·스케줄링, HTTP DTO 조립, startup recovery가 한 파일에 같이 있습니다. 그래서 이미 15개 `eval_*` 형제로 분리됐는데도 [eval_runs.py](/Users/anthony/Repository/github/loveqoo/my-agents/packages/api/src/api/eval_runs.py:28)만 639줄로 남아 MI 최저가 된 겁니다.

P1: `trigger_auto_regression`은 분해보다 먼저 버전 핀 seam을 설계상 고정해야 합니다. 자동 런 행에는 `agent.active_version`을 박제하지만, 실제 background 실행은 [eval_runs.py:244](/Users/anthony/Repository/github/loveqoo/my-agents/packages/api/src/api/eval_runs.py:244)에서 `_execute_run(..., version=None)`으로 스폰됩니다. `eval_run_agent`는 `version=None`이면 현재 active를 다시 읽습니다([eval_runner.py](/Users/anthony/Repository/github/loveqoo/my-agents/packages/api/src/api/eval_runner.py:171)). 빠른 재오픈/롤백이 끼면 “박제된 버전”과 “실제로 평가한 버전”이 갈라질 수 있습니다. 수동 지정 평가 seam은 verify_373이 닫고 있지만, 자동 회귀 쪽은 같은 강도로 닫혀 있지 않습니다.

P1: `trigger_auto_regression` C13의 복잡도 원인은 한 함수가 후보 수집, 소유권 필터, env 생성, 버전 dedupe, admission, 비용 게이트, 행 생성, commit, spawn, 로깅을 모두 합니다([eval_runs.py](/Users/anthony/Repository/github/loveqoo/my-agents/packages/api/src/api/eval_runs.py:163)). 분해 방향은 “조건문 줄이기”가 아니라 자동 회귀 상태기계를 명명하는 쪽이어야 합니다.

P1: `_spawn_runs`는 DB 행 생성, env 차이, commit, detach를 3분기에서 반복합니다([eval_runs.py](/Users/anthony/Repository/github/loveqoo/my-agents/packages/api/src/api/eval_runs.py:396)). 여기서 202 계약의 핵심은 “running 행 commit 후 background detach”입니다. 추출 시 factory가 너무 똑똑해져 spawn 전에 실행하거나, commit 전 반환하는 회귀가 가장 위험합니다.

**분할 설계**
권장은 평면 형제 모듈 유지입니다. 이미 `eval_routes.py`가 “전 심볼 재수출 파사드” 계약을 문서화하고 있고([eval_routes.py](/Users/anthony/Repository/github/loveqoo/my-agents/packages/api/src/api/eval_routes.py:9)), main과 agents도 `eval_routes`를 소비합니다([main.py](/Users/anthony/Repository/github/loveqoo/my-agents/packages/api/src/api/main.py:77), [version_routes.py](/Users/anthony/Repository/github/loveqoo/my-agents/packages/api/src/api/agents/version_routes.py:74)). 따라서 `eval_routes` 파사드는 유지가 맞습니다.

추천 경계:

- `eval_execution.py`: `_execute_run`, `_execute_group`, 케이스 로딩, judge 해석, result persist, error persist. 우선은 함수형 추출. `EvalRunExecutor` 클래스는 세션 팩토리·runner 주입이 실제 테스트를 단순화할 때만.
- `eval_admission.py`: `_resolve_run_target`, `_admission_check`, `_assert_run_admission`, `_validate_compare_models`, `_resolve_pinned_version`. HTTP 예외를 유지하되 “판정”과 “반응”은 분리.
- `eval_scheduling.py` 또는 `eval_run_factory.py`: `_spawn_runs`, `RunSpec`, `create_run_rows`, `schedule_run_specs`. commit-before-spawn 계약을 여기에 박제.
- `eval_regression.py`: `trigger_auto_regression`, candidate selector, dedupe predicate, auto-run spec builder. 반드시 `version=opened_version`을 `_execute_run`에 넘기게 설계.
- `eval_recovery.py`: `sweep_zombie_runs`, `sweep_zombie_datasets`. main lifespan 소비가 있으므로 `eval_routes`에서 계속 재수출.

`eval_runs.py` 자체는 두 선택지가 있습니다. 외부 계약이 실질적으로 `eval_routes`에 모여 있으므로 최종 소멸도 가능하지만, 테스트들이 `from api import eval_routes as ER`로 private 심볼까지 호출합니다([verify_137](/Users/anthony/Repository/github/loveqoo/my-agents/tests/verify_137_eval_runner.py:30)). 1차 리팩터는 `eval_runs.py`를 얇은 compatibility facade로 남기고, 내부 구현은 새 형제에서 직접 import하는 편이 안전합니다. 두 번째 회전에서 `eval_runs.py` 소멸 여부를 표면 박제 결과로 판단하면 됩니다.

**동작보존 함정**
202 계약: [start_run](/Users/anthony/Repository/github/loveqoo/my-agents/packages/api/src/api/eval_runs.py:500)은 running `EvalRun`을 만들고 즉시 반환합니다. background는 요청 세션이 아니라 `SessionLocal`을 새로 엽니다. 리팩터 후에도 “행 commit → spawn → RunOut 반환” 순서를 깨면 폴링 클라이언트가 흔들립니다.

자원 예산 347: 비특권 비용 게이트는 advisory lock, 동시 running, case+llm_judge work 계산을 포함합니다([eval_guards.py](/Users/anthony/Repository/github/loveqoo/my-agents/packages/api/src/api/eval_guards.py:31)). 자동 경로는 HTTP 429/422를 조용한 skip으로 바꾸는 것만 달라야지, 판정식이 갈라지면 안 됩니다.

배포 게이트 372/373: verify_373의 핵심은 SQL 시드가 아니라 “실 지정 평가가 쓴 행을 게이트가 읽는다”입니다([verify_373](/Users/anthony/Repository/github/loveqoo/my-agents/tests/verify_373_eval_gate_e2e.py:1)). `agent_version`, `status=ok`, `score∈[0,1]`이 같은 축에 남아야 합니다.

좀비 스윕: main lifespan이 `eval_routes.sweep_zombie_runs/datasets`를 직접 호출합니다([main.py](/Users/anthony/Repository/github/loveqoo/my-agents/packages/api/src/api/main.py:75)). 이동해도 재수출은 필수입니다. 별도 운영 리스크로, backlog에는 다중 레플리카에서 부팅 스윕이 타 프로세스 running을 죽일 수 있다는 빚도 이미 보입니다.

이벤트 순서: `eval_runs.py`에는 `events.publish`가 없습니다. 현재 사용자 가시 이벤트는 DB 상태 폴링입니다. 따라서 보존 대상은 SSE 순서가 아니라 `running → case_results insert → ok/error + finished_at` commit 순서입니다.

**권장 순서**
1. 표면 박제: `rg`로 `eval_routes`, `eval_runs`, private 심볼 소비자를 고정하고 `eval_routes` 재수출 목록을 테스트로 박제.
2. `eval_recovery.py` 분리: 가장 독립적. main 호출과 `verify_137` sweep만 대조.
3. `eval_admission.py` 분리: 순수 판정 후보가 많고 347 게이트와 직접 연결.
4. `eval_scheduling.py` 분리: `RunSpec`으로 단일/비교/기본 런 생성 중복 제거. commit-before-spawn 단언 필요.
5. `eval_regression.py` 분리: 여기서 `opened_version`을 명시적으로 캡처해 `_execute_run(..., version=opened_version)`으로 넘기는 설계 변경을 포함.
6. `eval_execution.py` 분리: 마지막. judge, RAG/agent 분기, result persist, error persist가 몰려 있어 가장 위험합니다.

**표적 verify**
주력: `verify_241_auto_regression.py`, `verify_347_resource_gate.py`, `verify_372_eval_gate.py`, `verify_373_eval_gate_e2e.py`.

보조: `verify_137_eval_runner.py`는 `_execute_run`, `get_run`, sweep을 직접 찌르지만 현재 `KNOWN_DRIFT`에 격리되어 있습니다([run_suite.py](/Users/anthony/Repository/github/loveqoo/my-agents/tests/run_suite.py:54)). `verify_240/242/244`도 기격리 노후가 맞습니다([run_suite.py](/Users/anthony/Repository/github/loveqoo/my-agents/tests/run_suite.py:70)). 리팩터 회귀 판정에는 “현재 격리 실패와 같은가” 대조로 쓰고, 통과/실패 자체를 단독 신호로 쓰면 안 됩니다.

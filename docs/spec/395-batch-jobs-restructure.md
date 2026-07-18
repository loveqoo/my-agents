# 395 — batch/jobs.py 구조 개선(파괴 잡 가족 분할 + C급 분해)

> 상태: **완료** · 2026-07-18 (승인 후 P1~P7 실행 → codex 적대 리뷰 **발견 0건**)
> 발단: 복잡도 스냅샷 잔여 — 904줄(남은 2위)·C급 2·**전 잡이 파괴적 삭제/변형**(383 dry_run
> 계약의 본체). 방식: 392~394와 동일 4회전 — codex 자문
> (`.dev/reviews/395-batch-jobs/codex-consult.md`) + dry-run 패턴 리서치 → 승인 → 실행 → 적대.

## 구조 판단(codex)

- **batch/jobs/ 서브패키지 전환 금지** — api.batch.jobs가 파일→패키지로 바뀌면 직접 임포트
  테스트 10종과 monkeypatch(verify_039의 `jobs_mod._consolidate`)가 한꺼번에 흔들림.
  **평면 형제(batch/jobs_*.py) + jobs.py 파사드**(392~394 관례).
- JOBS 레지스트리는 파사드가 자연 소유(전 잡 함수를 어차피 임포트 — codex의 별도
  jobs_registry+소비자 단계 전환안보다 무전환·동작보존 우위. 자문 대비 의도적 단순화).
- Terraform식 plan/execute 전환·공통 DeletePlan·consolidation Planner/Executor 재설계는
  **OUT**(별도 스펙) — 파괴 경로의 의미 변경이라 동작보존 원칙과 충돌("if dry-run 수프"
  교정은 지금 없음, 리서치·codex 모두 예외 인정).

## 진단

1. batch_routes가 JOBS·is_delete_all_pattern만 필요한데 전 잡 구현을 임포트(가드와 실행 혼재).
2. `_consolidate`(C13): 프롬프트 조립+클라이언트 생성+동기 LLM 호출+파싱+dedupe 혼재.
3. `consolidate_user_memories`(C11): 후보 조회+설정 해석+dry-run preview+per-user saga+집계.
4. 파괴 selector/executor가 가족마다 산재(각자 관례 — 통일은 OUT).

## 처방(위험 오름차순 — codex 순서, 적대 검증 위치 포함)

- **P1** `jobs_guards.py`: 순수 가드 — is_delete_all_pattern·_is_private_host(+_A2A_PRIVATE_NETS)·
  _survives_keep_list(+_USER_CLEANUP_KEEP)·_protect_last_supers.
- **P2** `jobs_shared.py`: _get_config(전 잡 공유)·_TURN_CLEANUP_IDLE_GUARD 등 공유 상수.
- **P3** `jobs_retention.py`: cleanup_tokens·cleanup_approvals·cleanup_history·
  cleanup_checkpoints·cleanup_memories(위임 wrapper 포함, mem0 orphan **내부 SQL 무접촉** —
  판정=삭제 단일 SQL의 TOCTOU 계약).
- **P4** `jobs_agents.py`(cleanup_a2a_agents) + `jobs_users.py`(cleanup_test_users+casbin purge+
  enforcer reload — 트랜잭션/재로드 순서 보존). **여기부터 적대 검증 축**: 공개 endpoint·
  keep-list 공백/대소문자·최후 super·casbin dangling.
- **P5** `jobs_sessions.py`: cleanup_sessions+절 빌더(criteria/meta/labels). 적대: 나이∪턴
  합집합·pending approval 양 절 AND·turns 진실원.
- **P6** `jobs_memory_consolidation.py`(최고 위험·최후): _consolidate를
  _consolidation_messages/_call_consolidation_llm/_parse_consolidation_lines 순수 분해,
  consolidate_user_memories는 설정 해석·집계 추출로 ≤B. saga 경계(snapshot commit→mem0
  add→원본 delete·add 실패 시 삭제 금지·degraded)는 **무변경**.
- **P7** jobs.py 파사드화(전 심볼 재수출+JOBS) + 전후 검증 일괄.

## 동작보존 함정(codex 목록)

1. 잡 시그니처 `async def job(*, dry_run, run_id=None) -> dict` — runner 키워드 호출(383).
2. API trigger 기본 dry_run=True vs CLI `--dry-run` 없으면 실행 — **비대칭 유지**(통일=변경).
3. 반환 dict 셰이프=BatchRun·UI 계약(sample은 감사행에서 scrub — runner 몫).
4. _pending_approval_clause는 나이·턴 **양 절에 AND**.
5. cleanup_sessions의 진실원은 Session.turns(메시지 행 수 아님).
6. consolidation dry-run은 무변형이지만 LLM preview는 호출(비용 시맨틱 변경 금지).
7. mem0 add 실패→원본 삭제 금지·status=degraded.
8. casbin purge=User delete와 동일 tx, enforcer reload=commit 후.
9. mem0 orphan: 판정과 delete가 같은 SQL(TOCTOU).

## 완료 기준(수치) — 전부 달성(실측)

- [x] jobs.py 파사드 **73줄**(904→73) — 7형제 모듈(shared·guards·sessions·
      memory_consolidation·agents·users·retention), JOBS 레지스트리는 파사드 소유.
- [x] C급 2 → 0(전체 51→**49**), batch/jobs_* C급 0·MI 53.5~(전부 A).
- [x] JOBS 9종 (이름·함수명·시그니처) 전후 diff **0** 기계 확인.
- [x] 행동보존: metrics-fast 전판 + make test SUITE_OK + **suite 51/51** + 배치 verify **11종**
      (038·039·049·050·056·349·350·351·352·357·383) 전판 그린.
- [x] monkeypatch 소비자 갱신: verify_039·357 패치 대상을 정의 모듈(jobs_memory_consolidation)로
      (파사드 재수출 패치는 내부 호출에 안 먹음 — monkeypatch-is-consumer 3번째 적용).

## codex 적대 스팟 리뷰 결과 — **발견 0건**(P1/P2/P3 없음)

확인함(codex): 순수 이동 전 함수 HEAD 텍스트 동일·SQL/술어 동일·_consolidate 분해의 빈("")/실패
(None) 접힘 의미 동일·_run_consolidation 집계 동일·JOBS 동일 객체 소비·run_id 관통·monkeypatch
접근 실측·import 사이클 0·지연 임포트(..users·..authz) 유지. 4회전 수확 체감: P2 2→1→0→0.

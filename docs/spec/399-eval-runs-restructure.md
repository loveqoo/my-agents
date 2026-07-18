# 399 — eval_runs.py 구조 개선(실행 미니앱 해체 + 자동 회귀 버전 핀)

> 상태: **완료** · 2026-07-19 (승인 후 P1~P7 → codex 적대가 개선의 잔여 race 지적 → 완성형 봉합)
> 발단: 캠페인 잔여 최종 — 639줄·C급 1(trigger_auto_regression 13)·MI 35.9(잔여 최저).
> 방식: 9회전 — codex 자문(`.dev/reviews/399-eval-runs/codex-consult.md`) → 승인 → 실행 → 적대.

## 구조 판단(codex)

eval_runs.py는 "runs 라우트 파일"이 아니라 **eval 실행 미니 애플리케이션**(실행기·자동 회귀·
접수 정책·스케줄링·DTO 조립·startup recovery 동거) — 15형제 분할 후에도 MI 최저인 원인.
**평면 형제 5모듈 + eval_runs.py 얇은 호환 파사드 유지**(1차) — 외부 계약은 eval_routes
재수출 파사드에 모여 있고 테스트가 그 경유로 private 심볼까지 소비(398의 소멸 처방과 달리
계약 두께가 있음). 소멸 여부는 다음 회전에서 표면 박제로 재판단.

## 명시 개선 1건(codex P1 — 잠재 결함 수정, 승인 대상)

**자동 회귀 버전 핀**: trigger_auto_regression이 EvalRun 행에 `agent.active_version`을
박제하면서 실행은 `_execute_run(..., version=None)`으로 스폰 → eval_run_agent가 **실행 시점**
active를 다시 읽어, 빠른 재오픈/롤백이 끼면 "박제된 버전 ≠ 실제 평가한 버전"(372 "평가한
것==배포한 것" seam의 자동 회귀판 구멍, verify_373은 수동 지정 경로만 닫음).
수정: 활성화 시점 버전을 캡처해 `version=opened_version` 명시 전달. 검증: 전후 회귀 실행의
agent_version 귀속 실측 + verify_241.

## 처방(위험 오름차순 — codex 순서)

- **P1 표면 박제**: eval_routes 재수출 목록·private 소비자 rg 3단계(수집→판정→검증).
- **P2** `eval_recovery.py`: sweep_zombie_runs·sweep_zombie_datasets(main lifespan 소비 —
  eval_routes 재수출 유지).
- **P3** `eval_admission.py`: _resolve_run_target·_admission_check·_assert_run_admission·
  _validate_compare_models·_resolve_pinned_version(판정/반응 분리 구조 유지).
- **P4** `eval_scheduling.py`: _spawn_runs — 3분기 중복을 RunSpec+생성/스케줄 추출로,
  **commit-before-spawn 계약 박제**(202 계약의 핵심 — 행 commit → spawn → RunOut 반환).
- **P5** `eval_regression.py`: trigger_auto_regression(C13) — 후보 수집·dedupe 술어·자동 런
  스펙 빌더 분해 + **버전 핀 개선 적용**.
- **P6** `eval_execution.py`(최후·최고 위험): _execute_run·_execute_group — 케이스 로딩·judge
  해석·결과/오류 영속 추출. running→results insert→ok/error+finished_at commit 순서 동결.
- **P7** eval_runs.py 얇은 파사드화(라우트 3개+재수출).

**OUT**: 347 게이트 판정식 변경·202 계약 변경·스윕 시맨틱 변경·eval_routes 파사드 구조 변경.

## 동작보존 함정(codex 목록)

1. **202 계약**: running 행 commit → 배경 spawn(detach) → RunOut 반환 순서(추출된 factory가
   spawn을 앞당기거나 commit 전 반환하는 회귀가 최위험).
2. 347 자원 예산: 수동=HTTP 429/422 vs 자동=조용한 스킵 — **판정식은 단일**(반응만 분기).
3. 372/373 seam: agent_version·status=ok·score∈[0,1]이 같은 축 유지.
4. 좀비 스윕: main lifespan이 eval_routes 경유 호출 — 재수출 필수.
5. 이벤트는 SSE가 아니라 DB 폴링 — 보존 대상은 상태 commit 순서.
6. 자동 경로 게이트 사슬(소유권 필터→버전 dedupe→admission→비용 가드) 순서 보존.

## 완료 기준(수치) — 전부 달성(실측)

- [x] eval_runs.py **138줄**(639→138 — 라우트 3+재수출) + 5형제(execution 169·admission 160·
      scheduling 147·regression 140·recovery 48). C급 1→0(전체 47→**46**), 신규 MI 60.6~85.5.
- [x] **버전 핀 완성형**: 1차 수정(태스크가 active 캡처→실행에 명시 전달)에 codex 적대가 잔여
      race(태스크 실행 전 재오픈 시 이벤트 버전 미보장)를 지적 → 호출부(version_routes)가
      `opened_version=body.version`을 인자로 관통(이벤트 버전 고정, 미전달 폴백=active).
      verify_241 전후 그린.
- [x] 표면: eval_routes 파사드 8심볼 hasattr + codex rg(모두 ER 경유·monkeypatch 재할당 0).
- [x] 행동보존: metrics-fast 전판 + make test SUITE_OK + **suite 51/51(flaky 0)** + 표적 verify
      4종(241·347·372·373) virgin 그린. _start_auto_run은 ACTION_WHITELIST 등재(386 관례).

## codex 적대 스팟 리뷰 결과 — P1 1건(개선의 완성형 요구) → 봉합

- **P1**: 버전 핀이 "행 박제==실행 버전"은 고정했으나 "활성화 이벤트의 버전"은 미관통 —
  연속 오픈(v2→v3) race에서 v2 태스크가 v3 캡처. 이벤트 버전 인자 관통으로 완성.
- 확인함(codex): 202 계약 3분기 add→commit→spawn→validate 순서 동일·_execute_run 외곽 try
  범위 동일·게이트 사슬 순서 보존·active/지정 두 경로의 config 해석 수렴·지연 import 생존·
  import 사이클 0.

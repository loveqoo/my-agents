# 329 — 죽은 영역 감사 잔여 3건 제거

## 배경 / 동기

스펙 324(죽은 영역 감사)가 유력/관찰로 분류해 사용자 판단 대기로 남긴 3건을, 사용자 결정
(2026-07-13, 3건 모두 제거)에 따라 소거한다. 이로써 324 감사 축이 완전 마감된다.

## 결정 (사용자, 2026-07-13)

| 항목 | 결정 | 근거 |
|---|---|---|
| `POST /eval/generate-dataset` | **폐기(제거)** | UI 진입은 스펙 195에서 사용자 지적으로 이미 제거("자동 강제 완전 제거"), 'AI 출제'(143/301 append)가 역할 대체. 필요 시 git 이력에서 복원 |
| `Chunk.token_count` | **DROP(완전 제거)** | 쓰기 2곳·읽기 0. 값은 파생값(`len(t.split())`)이라 소실 무해(다운그레이드=default 0 재생성, lossy 명시) |
| `_harness088.tsx`+`_harness_088.html` | **삭제** | 파일 머리 주석 스스로 "커밋 안 함" 선언한 임시 하네스. 필요 시 재생성 |

## 제거 범위 (실측 기반 닫힌 집합)

### R1. generate-dataset 기계 일습
- `eval_authoring.py`: `_execute_generation`(123–176) + `generate_dataset` 라우트(178–207) + `GenerateIn` import.
- `eval_schemas.py`: `GenerateIn` 클래스.
- `eval_routes.py`: 재수출 3개(`_execute_generation`·`generate_dataset`·`GenerateIn`).
- `admin/src/api.ts`: `generateEvalDataset` 래퍼(호출 0).
- `tests/verify_142_golden_gen.py` **삭제** — 단, G1(`_parse_question` 단위 5검사)은 **살아있는 코드**
  (eval_golden — append/suggest 경로 공유)의 커버리지이므로 verify_329로 이전.
- `tests/browser/shot-eval-golden-142.mjs` **삭제** — 스펙 195에서 제거된 "컬렉션에서 생성" 버튼을
  누르는 스크립트(이미 실행 불능 = 그 자체가 죽은 영역).
- **보존**: `eval_golden.generate_golden_cases`(append 경로 사용 중)·`_active_jobs`/`_member_job_guard`/
  `_job_lock`(출제·수확 공유)·'AI 출제' 전체.

### R2. Chunk.token_count DROP
- `models.py:157` 필드 제거 · `rag.py:481,860` 쓰기 제거.
- 새 alembic 리비전(head=`55c79db3e710` 단일 확인 완료, down_revision으로 연결). 회고 177 패턴:
  손수 순번 금지(무작위 id)·헤더 그래프 검증(단일 head·중복 0·고아 0) 동반.
- **reload 함정**(learning): dev 서버가 --reload로 살아 있음 → **마이그레이션 파일을 완성본으로 먼저**
  쓰고, 그 다음 src 파일을 수정한다(저장 시 lifespan이 upgrade 실행 — 반쪽 적용 방지).

### R3. 하네스 088
- `admin/src/playground/_harness088.tsx` + `admin/_harness_088.html` 삭제.

## 완료 조건 (측정 가능)

1. `grep -r "generate.dataset\|GenerateIn\|generateEvalDataset\|token_count\|_harness088\|_harness_088"`이
   소스(packages/·admin/src/·tests/)에서 0건 (alembic 이력·docs 제외).
2. DB 실측: `chunks` 테이블에 `token_count` 컬럼 부재 + alembic 단일 head·현 DB가 그 head.
3. verify_329: `_parse_question` 단위(구 G1 이전) · 라우트 부재(404/라우트 테이블) · 스키마 부재 ·
   컬럼 부재 · 마이그레이션 그래프(단일 head·중복 0·고아 0) 전부 통과.
4. 기능 무회귀: RAG 인제스트 실왕복(청크 생성 정상 — token_count 없는 INSERT) + 'AI 출제' 경로 임포트
   무결 · `make lint format-check typecheck` · admin `tsc`+build 클린.
5. codex 적대 리뷰(제거물의 남은 소비자·여집합) P1/P2 0.

## OUT (이번에 안 함)

- verify 스위트 격리(321 대형 항목) · generate-dataset 복원 대비 리팩터(불필요 — git 이력이 복원점).

## 결과 (2026-07-13 실행)

- 3건 전부 제거 + 실행 중 여집합 2겹 추가 발견·동봉 제거:
  - **"생성 중…" 마커 화석 3곳**(142 계약의 소비자) — `_is_generating` 접두 분기·`sweep_zombie_datasets`
    생성 스윕 블록·`_assert_run_admission` description 보조판정(사용자가 설명에 그 문구만 넣어도 실행이
    409로 막히던 오탐 표면). 라이브 잔여 행 0 실측 후 제거. verify-eval-ux-193.mjs P3는 산 마커
    ("AI 출제 중…")로 교체.
  - **shot-markdown-088.mjs** — 삭제한 하네스의 소비자(codex P2).
- **codex P1(실결함)**: 마이그레이션이 `chunks`를 DROP — 실제 테이블은 `rag_chunks`. upgrade가
  실패했는데도 **init_db의 create_all 폴백이 warning만 남기고 head를 스탬프**해 라이브 DB에
  token_count가 잔존(조용한 우회). verify V4a도 같은 오타로 빈 결과 자명통과(false green).
  → 마이그레이션 정정(미공개 리비전이라 제자리 수정)+라이브 DB 수동 정합(ALTER DROP)+V4a에
  산 컬럼 동시 단언으로 자명통과 봉인. **init_db 폴백의 조용한 우회는 백로그 등재**(k8s 마이그레이션
  Job 분리와 합류).
- 검증: VERIFY329_OK 27/27(일회용 virgin DB — 폴백 경고 0 = 정정 마이그레이션 실적용 확인) ·
  라이브 DB rag_chunks 컬럼 부재+head 정합 · lint/format/mypy·tsc·build 클린 · 193 e2e 실패 4건은
  stash 재현으로 **기존 드리프트 확증**(내 회귀 아님, 백로그 등재).

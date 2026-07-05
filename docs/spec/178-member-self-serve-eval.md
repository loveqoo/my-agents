# 178 — 멤버 자율 평가 (본인 에이전트 한정, 소유 기반)

> 상태: **초안(검토 대기)**. AI 작성 · 인간 검토 후 승인 → 실행.

## 배경·목표
"에이전트를 노코드로 만들고 → 테스트하고 → 평가하는" 자율 루프를 일반 멤버에게 연다.
현재 **생성·테스트는 이미 멤버에게 열려 있고**(에이전트/컬렉션과 동일한 소유 기반, 스펙 112/114/147),
**평가만 관리자 전용**이다(순수 `require("eval","manage"/"run")`, 기본정책은 admin `(*,*)`뿐).

**목표**: 평가를 에이전트·컬렉션과 **동일한 소유 기반**으로 전환 — 멤버는 *본인 소유* 문제집·실행을
직접 만들고 돌리며, *본인이 쓸 수 있는* 에이전트만 평가 대상으로. 관리자는 전체(특권).

## 비목표(v1)
- 공개 등록/셀프사인업(별개 축).
- 유저 간 평가 데이터 공유·협업(v1은 소유자+관리자만 열람 — D1).
- 정교한 과금/크레딧 시스템(v1은 남용 방지 가드만 — D2).

## 현황 매핑 요지(조사 완료)
- **데이터 모델 준비됨**: `EvalDataset.owner_id`·`EvalRun.owner_id` 이미 존재(스펙 112 패턴).
  case/result는 부모 FK로 소유 상속 → **마이그레이션 불필요**.
- **인가는 순수 require()**: 소유 훅(may_manage/may_use_agent/owner_scope_filter) 미사용.
  `owner_of`는 생성 스탬프에만. list/get에 owner 필터 전무.
- **보안 구멍 2개**(개방 시 반드시 봉합):
  1. run 시작(eval_routes L356)·suggest-cases(L716)가 대상 `Agent`를 `session.get`만 —
     `may_use_agent` 미적용 → **멤버가 남의 private 에이전트를 평가 가능**(스펙 147 우회).
  2. list datasets/runs·get에 owner 필터 부재 → **멤버가 남의 문제집·성적표 전량 열람**.
- **비용**: 실행 1회 = `cases × (1 대상 + K judge) × models(≤6)`, 선형. 기존 가드는 동시성/중복뿐
  (per-dataset running 409, `_active_jobs` 락) — **유저별 총량 쿼터 없음**.
- **프론트**: eval이 `AdminShell.tsx`의 superuser 전용 "관리자" 그룹에 있음 → 서버·프론트 이중 게이트.

## 설계

### 1. 인가: require() → 소유 기반(컬렉션 패턴 = 읽기 공개·관리 소유자)
`_manage`/`_run_dep`(순수 require) 게이트를 **제거**하고, **컬렉션(rag.py)과 동일**하게
`current_principal` + `ownership.py` 술어로 전환한다(D1 확정 = 열람 공개·관리만 소유자, 단일 출처 drift-0):

| 엔드포인트 | 종류 | 변경 |
|---|---|---|
| GET datasets / runs / dataset{id} / run{id} / cases | **읽기** | `current_principal`만 — **전량 공개**(owner 필터 없음, 404-fold 없음). D1. |
| POST dataset / generate-dataset | 생성 | `current_principal` + `owner_id=owner_of(principal)` 스탬프(이미 있음). generate는 대상 컬렉션 읽기(공개) |
| PATCH/DELETE dataset | 관리 | `assert_may_manage(dataset, principal)` — 비소유 **404-fold** |
| POST/PATCH/DELETE case | 관리 | 부모 dataset에 `assert_may_manage`(케이스는 owner 없음, 계보 상속) |
| **POST runs(실행)** | 실행 | `current_principal` + 부모 dataset `assert_may_manage`(본인 문제집만 실행) + **대상 Agent `may_use_agent`**(구멍#1 봉합) + owner 스탬프 |
| **POST suggest-cases** | 관리 | 부모 dataset `assert_may_manage` + 대상 Agent `may_use_agent`(구멍#1) |
| GET helper-status | 읽기 | `current_principal`(단순 상태) |

→ `authz._DEFAULT_POLICIES`에 eval 정책 추가 **불필요**(require 게이트 자체를 제거). admin은
`is_privileged`로 관리 술어에서 특권 통과. **`eval:manage`/`eval:run` casbin 객체는 폐기**(사용처 소멸).

**D1 공개-읽기의 결과(문서화)**: 성적표(run/result)가 전량 공개이므로, **본인 private 에이전트를 평가하면
그 테스트 입출력이 모든 로그인 유저에게 열람된다**. 이는 버그가 아니라 D1의 의도된 귀결(컬렉션 공개-읽기와
동형) — UI에 "평가 결과는 모든 사용자에게 공개됩니다" 안내 문구로 소유자가 인지하게 한다.

### 2. 비용 가드 (멤버 자율 실행 — D2)
- 기존 유지: per-dataset running 409, `_active_jobs` 락(생성/출제 중 실행 금지).
- **신설**: 비특권 유저의 **동시 실행 수 상한**(예: 유저당 running 상태 run ≤ 2). 특권은 무제한.
- **신설**: 비특권 1회 실행의 **작업량 상한** — 상한 초과면 422(≤ 60).
  단일-run 입력 상한(cases 입력 4000자, assert 20, models 6)은 이미 있음 → 여기에 곱 상한만 추가.
- (총 누적 쿼터/일일 한도는 v1 비목표 — 필요 시 후속.)

**P4 — codex 적대 검증 반영(하드닝).** P1~P3 커밋 전 codex challenge로 "보장 목록의 여집합"을 검증,
비용 경계의 실제 결함 4건을 봉합(`verify_178` T6~T9로 각 벡터 회귀):
- **① `generate-dataset` 무가드**(fixed): 컬렉션→문제집 자동 생성이 배경 LLM을 무제한 킥 → 비특권
  **동시 배경작업 상한**(`_MEMBER_MAX_CONCURRENT_JOBS=2`) 신설. `_active_jobs`를 단일 진실원으로 통일,
  생성 시 **동기 등록**(create_task 전 창 봉인).
- **② `suggest-cases` 무가드 + 락 TOCTOU**(fixed): 락(`_active_jobs.add`)이 배경 태스크 안에 있어
  동시 요청이 중복 출제 → 락을 **엔드포인트에서 동기 획득**(체크와 add 사이 await 없음), 실패 시
  finally 대신 except에서 해제(누수 방지). 배경작업 상한 공유.
- **③ run 동시성 가드 TOCTOU**(fixed): `my_running` 확인과 insert 사이 락 없어 병렬 요청이 상한 우회
  → 유저별 **`pg_advisory_xact_lock`**로 확인+삽입 직렬화.
- **⑤ work가 judge 비용 누락**(fixed): 케이스당 `llm_judge` 최대 5개가 실 LLM 호출을 배증
  → work = `models × (cases + llm_judge 기준 수)`로 정직화(harness와 동일 카운트).
- **의도된 경계(수정 아님, 문서화)**: ④ 모델 매트릭스가 running 행 M개 생성 = 순차 실행+work 상한이라
  유계. ⑥ RAG 대상 collection 사용권 게이트 없음 = 컬렉션은 **읽기 공개** 정책이라 by-design(교차 private
  누출 없음). ⑦ 성적표 obs/details 공개 = **D1 선택**(공개 읽기) — you 쓸 수 있는 에이전트/공개 컬렉션만
  평가 가능하므로 교차유저 private 누출 없음, UI "결과 공개" 안내로 고지.

### 3. 프론트엔드
- `AdminShell.tsx`: eval을 superuser "관리자" 그룹에서 **일반 접근**으로 이동(Playground 옆 "도구" 또는
  상단). 노출 게이트만 완화 — 서버가 소유로 독립 강제하므로 안전.
- `EvalView`/`EvalMatrix`/`EvalTrend`: 목록이 owner-scoped라 자연히 본인 것만. `can_manage`로 편집/삭제
  버튼 게이트(에이전트/컬렉션 UI와 동형). 대상 에이전트 선택 드롭다운은 `may_use_agent` 통과분만
  (list_agents가 이미 필터).

## 결정(확정)
- **D1 = 열람 공개·관리만 소유자**(컬렉션 패턴). 문제집·성적표는 전 유저 열람, 생성/수정/삭제/실행은
  소유자만. → 위 §1 반영. 공개-읽기의 private-에이전트 노출 귀결은 문서화 + UI 안내.
- **D2 = 동시성 락 + 동시 run 상한 + 작업량 곱 상한**. → 위 §2 반영.

## RBAC/소유권 체크리스트 응답 (docs/spec/CLAUDE.md 트리거 — 유저별 데이터)
1. **입구 열거(닫힌 집합)**: 읽기(list/get datasets·runs·cases·results·helper-status) · 생성(dataset·
   case·run·generate·suggest) · 수정(patch dataset·case) · **삭제(delete dataset·case — 비가역)** ·
   실행(run 시작=부수 생성). *재진입/외부프로토콜 입구 없음*(eval은 A2A/resume 경로 없음, 내부 HTTP만).
2. **입구별 소유권**: (a) **읽기 = 공개(D1)** — owner 스코프 없음, 이는 의도. (b) 쓰기/실행: 소유자
   **덮어쓰기 금지**(owner_id는 생성 시 1회 스탬프, patch/run이 재스탬프 안 함). (c) 생성/부수생성(run):
   `owner_of(principal)` 1회 스탬프(이미 구현). (d) 비-SQL 저장소 없음(전부 Postgres FK, SELECT-WHERE 가능).
3. **단일 헬퍼**: `ownership.py`(may_manage/assert_may_manage/may_use_agent/owner_of/is_privileged) —
   에이전트/컬렉션과 공유(드리프트 0). eval 전용 판정 로직 신설 안 함.
4. **존재 비노출**: 읽기는 공개라 은닉 불요. **관리(patch/delete/run)**는 비소유 시 `assert_may_manage`가
   **404-fold**(403과 구분 안 함) — 열거 오라클 제거.
5. **검증 사다리 3런(비겹침)**: ① 단위 시맨틱(각 입구 소유 판정) ② 실 인프라 통합(seed 멤버 2명+실 DB로
   A가 B 문제집 실행/수정 거부, 공개 읽기 통과) ③ **적대 타자(deep-reasoner/codex)** = "보장 목록의 여집합"
   (특히 구멍#1 우회·owner 재스탬프·run이 대상 검사 우회 시도).
6. **자가-잠금 핀**: 소유자 본인은 자기 문제집 수정·실행·삭제가 *정상 통과*하는지 별도 확인(조임이
   본인 접근을 막지 않음).

## 검증(완료 조건 — 측정 가능)
- **관리 격리**: 멤버 B가 멤버 A의 dataset/case를 patch/delete/run **거부**(404-fold). (읽기는 공개=통과.)
- **구멍#1 봉합**: 멤버가 남의 private 에이전트를 run/suggest 대상 지정 → 거부(may_use_agent). run은
  본인 문제집만(부모 dataset assert_may_manage).
- **자가-잠금 핀**: 소유자는 본인 dataset 수정·실행·삭제 정상 통과.
- **관리자 특권**: admin은 전체 dataset/run 관리 유지(is_privileged).
- **비용 가드**: 동시 run 상한 초과 → 거부, 작업량(cases×models) 곱 상한 초과 → 422.
- **회귀**: 기존 eval 실행/채점/매트릭스(verify_137~143) admin 경로 무회귀.
- **브라우저**: 멤버 계정으로 평가 메뉴 노출 + 본인 것 관리 버튼·남의 것 열람만, 대상 드롭다운에 남의
  private 에이전트 부재. "결과 공개" 안내 문구 노출.
- 검증은 **타자**(서브에이전트/적대 검토) 우선 — 인가 경계라 적대 리뷰 필수.

## 단계(제안)
- **P1 백엔드 인가 전환**: require→소유 술어 이식 + 구멍 2개 봉합 + eval:manage/run 폐기. 격리 테스트. ✅
- **P2 비용 가드**: 동시 run 상한 + 작업량 곱 상한. ✅
- **P3 프론트**: 메뉴 이동 + can_manage 버튼 게이트. 브라우저 검증. ✅
- **P4 codex 하드닝**: 적대 검증 결함 ①②③⑤ 봉합(generate/suggest 가드·advisory 락·judge work). ✅
- (한 스펙, per-단계 커밋 — 177과 동형.)

## 실행 결과 (완료)
- **인가**: `eval_routes.py` require()→`current_principal`+`ownership.py` 소유 술어. 읽기 공개(D1),
  관리 `assert_may_manage` 404-fold, 실행·출제 `may_use_agent` 게이트(구멍#1). `can_manage` 응답 필드.
- **비용 가드**: 동시 run ≤2(advisory 락), work=`models×(cases+judges)`≤60, 동시 배경작업(생성·출제)≤2.
  admin(`is_privileged`) 전부 우회.
- **프론트**: 평가 메뉴 "관리자"→"도구"(일반 접근), `can_manage !== false` 버튼 게이트, "결과 공개" 안내.
- **검증**: `verify_178`(24/24 — 읽기공개·관리격리·구멍#1·자가잠금·admin특권·비용가드 4벡터), eval CRUD
  무회귀, 브라우저(메뉴 이동+안내 렌더). 적대 타자=**codex challenge**(결함 4건 포착→봉합).

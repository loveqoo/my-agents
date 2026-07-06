# 195 — 평가 케이스 등록 UX 개선 4건 (실사용 문의)

## 배경
케이스(문제) 등록이 번거롭다는 실사용 문의 4건:
1. 카드의 **'N개 기준' 배지**가 아래 assert 태그로 이미 개수를 알 수 있어 **중복**.
2. **근거 파일명(rag_source_contains)을 직접 타이핑** → 오타 위험. 등록된 파일에서 **고르게**.
3. **'문제 이름'을 매번 작성**하는 게 번거롭다 → 이름 개념을 **없애고**(내부 해시로 관리, 유저 비노출),
   질문으로 식별.
4. **AI 자동 출제**가 문제집 생성 시 자동으로 돌거나 버튼이 목록 하단에 숨음 → **드로어 상단 '시험 실행'
   옆에 'AI 출제' 버튼**(빈 문제집 + 원할 때만 클릭).

## 사용자 결정 (2026-07-06)
- 3: 질문 앞부분 자동저장이 아니라 **임의 해시로 관리 + 유저 비노출**(사용자 제안). 성적표에는 질문이 뜨게.
- 4: 상단 'AI 출제' 버튼 방식 승인(agent·rag 공통).

## 설계

### 1. 'N개 기준' 배지 제거 (프론트만)
케이스 카드에서 `<Tag>{c.asserts.length}개 기준</Tag>` 제거. 아래 assert 문장 태그가 개수를 이미 보임.

### 2. rag_source_contains → 파일명 AutoComplete (프론트, 기존 API 재사용)
- `DatasetDrawer`가 `dataset.collection_id`로 `listDocuments(cid)` 호출 → **파일명 목록** →
  `CaseForm` → `AssertEditor`에 prop 전달.
- `rag_source_contains` 입력을 Input → **AutoComplete**(목록 제안 + 자유입력 허용): 채점은 부분포함
  (contains)이라 파일명 일부도 유효 → 목록에서 고르되 직접 입력도 막지 않음(오타는 목록이 줄임).
- 목록 미확보(컬렉션 없음/구버전)면 기존 Input 폴백.

### 3. '문제 이름' 제거 → 내부 해시 (프론트 + 백엔드 소)
- **프론트**: `CaseForm`에서 이름 Input·state 제거. `onSave`는 name 미전송. 카드 헤더 = **질문(input)**.
- **백엔드**: `CaseIn.name`을 optional(기본 None) → 생성 시 없으면 **해시**(`secrets.token_hex(4)` →
  `case-xxxxxxxx`). update는 name 미전송 시 **기존 유지**(덮어쓰기 금지).
- **성적표**: 실행 시 `HarnessCase(name=c.input, …)`로 넘겨 `EvalCaseResult.case_name`=**질문**이 되게
  (DB `EvalCase.name`은 해시 내부 관리, 성적표엔 질문 표시). `CaseResultOut` 무변경(최소 변경).

### 4. AI 출제 버튼 상단 + rag 지원 (프론트 + 백엔드)
- **백엔드**: `suggest_cases`(현재 agent 전용)에 **rag 분기** — rag면 `dataset.collection_id`로
  `_execute_generation`(골든 생성)을 **기존 문제집에 append**(기존 케이스 수부터 `order_idx`). agent는
  기존 `_execute_suggestion`. 같은 소유자 게이트·비용 가드(`_member_job_guard`) 재사용.
- **프론트**: 드로어 상단('시험 실행' 옆)에 **'AI 출제' 버튼**. agent=선택 에이전트 대상, rag=고정 컬렉션
  대상. 기존 케이스 목록 하단의 AI 출제 버튼 제거(상단으로 일원화).
- **'컬렉션에서 생성'(자동 채움) UI 제거**(사용자 재요청 2026-07-06): 문제집 생성 시 AI가 자동으로 10개를
  채우는 경로를 없앤다 — 문제집은 **빈 채로** 만들고(새 문제집; rag는 모달에서 컬렉션 고정), 드로어 상단
  'AI 출제'로 원할 때만 채운다(자동 강제 완전 제거). `generate_dataset` **백엔드 엔드포인트는 유지**(API
  계약·테스트) — UI 진입만 제거.

## 검증 (사다리)
- **단위**: `CaseIn.name` 없으면 해시 생성·update 시 미전송이면 기존 name 보존. suggest rag 분기(append
  base order_idx, 소유자·비용가드).
- **e2e**: 카드 'N개 기준' 없음 · rag_source_contains AutoComplete(목록 옵션) · 이름칸 없음 · 카드/성적표
  질문 표시 · 상단 'AI 출제' 버튼. 무회귀 194 e2e.
- **무회귀**: tsc0 · 137 CRUD.

## RBAC 경계 (트리거 판정)
- **경계 스펙**(유저별 데이터 — 케이스·문제집 소유). 입구별:
  - 케이스 생성/수정: 기존 owner 스코프(`_assert_*owns`/dataset owner) **무변경** — name만 optional화.
  - AI 출제(rag 분기): **기존 `suggest_cases` 엔드포인트에 분기** 추가 → 그 소유자 게이트·404-fold·비용
    가드를 그대로 탄다(새 입구 아님). rag 분기도 dataset 소유 검증 후 실행.
  - name 해시: 표시/식별용, 소유권·존재비노출과 무관(볼 수 없는 문제집은 여전히 404).
- 새 쓰기 입구 0(기존 엔드포인트 분기·필드 optional화). 단일 헬퍼 유지.

## 경계
- '컬렉션에서 생성'(자동 채움) **UI 제거** — 빈 문제집 + 상단 'AI 출제'로 일원화(자동 강제 완전 제거).
  `generate_dataset` 엔드포인트 자체는 유지(계약·테스트). 초안에선 "유지(원하는 사람용)"였으나 사용자가
  자동 생성 자체를 불필요로 봄 → 제거로 정정.
- 파일명 AutoComplete는 자유입력 허용(contains 매칭 특성) — 목록은 오타를 줄이는 보조.

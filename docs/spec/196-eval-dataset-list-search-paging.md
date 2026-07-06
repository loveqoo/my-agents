# 196 — 평가 문제집 목록: 최근순 정렬 + 검색 + 페이징

## 배경 (실사용 요청)
평가 화면의 문제집 목록이 (1) **이름순**이라 방금 만든 게 어디 있는지 모르고, (2) **검색**이 없어 많아지면
못 찾고, (3) **페이징**이 없어 전부 한 번에 그린다. → 최근 생성순 정렬 + 서버 검색 + 페이징.

## 설계 (세션 목록 패턴 재사용 — 스펙 098·128)

### 백엔드
- **list_datasets 페이징화**: `q`(name·description ilike, `_ilike_literal` 이스케이프 — 와일드카드 오라클
  차단, 세션 098과 동일 헬퍼) · `limit=Query(20,1..100)` · `offset=Query(0,)` · **정렬 `created_at DESC,
  id DESC`**(최근순). 응답 `DatasetPageOut{items: list[DatasetOut], total, any_generating: bool}` —
  `any_generating`은 이 페이지에 진행 중 문제집이 있나(프론트 폴링 신호).
- **get_dataset 단건 추가**: `GET /datasets/{id}`(읽기 공개, 404-fold) → 열린 드로어 rebind용(폴링 시
  detail 최신화). `_dataset_out` 재사용.

### 프론트
- **목록 탭 → `PagedListShell`**(스펙 128 공용 엔진: 디바운스 서버검색·페이지네이션·오류): `scopeKey=
  'eval-datasets'` · `fetchPage=listEvalDatasets({q,limit,offset})→{items,total,extra:any_generating}` ·
  `columns=dsCols` · `onRowClick=setDetail` · `searchPlaceholder="문제집 이름·설명 검색"` · `leftSlot=
  새 문제집 버튼` · `refreshKey`(생성·삭제·폴링 트리거) · `onExtra=any_generating 수신`.
- **전체 `datasets` 상태 제거**(셸이 소유) → 파생 의존 재배선:
  - **generating 폴링**: `onExtra(any_generating)`가 true면 `refreshKey`를 2.5s마다 증가(다 끝나면 정지) —
    기존 "datasets.some(generating)" 대체.
  - **detail rebind**(스펙 193): 열린 detail이 generating이면 `getEvalDataset(detail.id)`로 2.5s 폴링해
    `setDetail` 갱신(생성/출제 종료·collection_id 반영). 기존 "datasets에서 find" 대체.
  - **runFilter 옵션**(실행 이력 탭 문제집 필터): 전체 datasets 대신 **runs에서 유도**(고유
    `dataset_id`→`dataset_name`) — 실행 이력 탭이니 runs 기반이 자연.
  - 생성/삭제 후 `loadDatasets()` → `refreshKey++`.

## 검증
- **단위**: list_datasets q 필터(부분일치·이스케이프)·created_at desc 순서·페이징(limit/offset·total)·
  any_generating. get_dataset 404-fold.
- **e2e**: 최근 만든 문제집이 맨 위 · 검색어로 필터 · 페이지 넘김 · 검색 중 generating 폴링/배지 유지 ·
  드로어 rebind. 무회귀 195 e2e.
- **무회귀**: tsc0 · 194/195 e2e.

## RBAC 경계 (트리거 판정)
- **비트리거 성격**: 목록은 읽기(전원 공개 — 스펙 178 D1). q/페이징은 표시 범위만, 소유권 판정 무변경
  (`_dataset_out`가 can_manage 계산 유지). get_dataset도 읽기 공개(볼 수 없는 행 없음 — 평가는 전체 공개).
  q는 `_ilike_literal`로 와일드카드 오라클 차단(주입/과매칭 방지). 새 쓰기 입구 0.

## 경계
- 정렬은 최근순 고정(사용자 요청) — 컬럼 정렬 토글은 범위 밖.
- 검색은 이름·설명만(케이스 내용 전문검색은 범위 밖).

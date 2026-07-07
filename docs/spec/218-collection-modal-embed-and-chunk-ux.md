# 스펙 218 — 컬렉션 생성 모달: 임베딩 모델 필터·라벨·청크 툴팁

## 배경 (사용자 실사용 지적 3건, 2026-07-07 — 모두 같은 컬렉션 생성 모달)

1. "mock 임베딩 모델이 아닌 다른 임베딩 모델이 있다면, 실제 임베딩 모델만 고를 수 있게 하자."
2. "'청크 크기', '청크 겹침'에 마우스 오버 시 정보를 제공." (크기엔 이미 (?) 툴팁, 겹침엔 없음)
3. "임베딩 모델 보여주는데 너무 모델명이 길다." — 라벨 `name — model_id`가 name==model_id일 때 중복 표기로 2배 길이·잘림.

## 변경

### 1. mock 임베딩 모델 필터 (견고한 신호 = provider.kind)
- **백엔드**: `ModelOut.provider_kind`(=provider.kind: local|mock|remote) 추가 + `model_to_out` 배선.
  하드코딩 이름("mock-embed") 대신 provider 종류로 판정(일반적·재사용 가능).
- **프론트 api.ts**: `Model.provider_kind: ProviderKind`.
- **CollectionsView CreateModal**: 실제(비-mock) 임베딩 모델이 하나라도 있으면 mock 제외
  (`selectable`). mock만 있으면(개발 초기) 그대로 노출해 생성이 막히지 않게 함. 프리셀렉트·옵션·
  placeholder 게이트 모두 `selectable` 기준.

### 2. 청크 겹침 (?) 툴팁
- 청크 크기와 동일 패턴으로 겹침에도 (?) Tooltip 추가("이웃 조각이 공유하는 글자 수 … 크기의 10~20%").
- 편집 모달은 청크가 읽기 전용(스펙 198)이라 대상 아님.

### 3. 모델 라벨 과다 길이
- `name === model_id`면 `— model_id` 생략(중복 제거). Select에 `popupMatchSelectWidth={false}`로 팝업은
  내용폭(스펙 215 패턴).

## 검증
- API `/models?kind=embedding`에 provider_kind(mlx=local, mock-embed=mock). 브라우저: 드롭다운에
  mlx만 노출(mock-embed 제외)·mlx 프리셀렉트·라벨 중복표기 0·청크 크기/겹침 둘 다 (?) 툴팁. tsc 0.

## OUT
- provider_kind는 표시 배지 등에도 재사용 가능하나 이번엔 필터만.
- mock-only 환경(실제 모델 0)은 mock 노출 유지(생성 가능성 보장).

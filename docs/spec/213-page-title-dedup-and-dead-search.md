# 스펙 213 — 페이지 제목 중복 제거 + 죽은 전역 검색 제거

## 배경 (사용자 실사용 지적 2026-07-07, 평가 스샷)

- 모든 메뉴에서 제목이 **두 번** 나온다: 상단 헤더(AdminShell `TITLES[view]`)와 각 화면의
  `<Page title>`가 같은 라벨을 중복 렌더. 사용자: "맨 위에만 남겨놓으면 될 것 같고, 다른 메뉴도 마찬가지."
- 상단 헤더 우측에 **배선 안 된 검색창**(`<Input placeholder="검색">`, value/onChange 없음)이 있다.
  사용자: "검색 기능 없는데 검색 UI는 왜 있는거죠?"

## 변경 (전역 — 컴포넌트 2곳 단일 수정이 전 메뉴 전파)

### A. Page 제목 제거 (admin/src/admin/shared.tsx)
- `Page`가 `title`을 h3로 렌더하던 것을 제거. 제목은 **상단 헤더가 단독 표시**(TITLES[view]가 진실원).
- `subtitle`·`actions`는 유지(부제는 화면 설명이라 남김). 래핑 조건 `(title||actions)` → `(subtitle||actions)`.
- `title` prop은 시그니처에 남기되 **무시**(14개 호출부 호환 — 점진 정리는 별도, 지금 churn 회피).
- 전 Page 제목이 메뉴 라벨과 일치함을 확인(전역 제거 안전) — 다른 제목을 넘기는 화면 0.

### B. 죽은 검색창 제거 (admin/src/admin/AdminShell.tsx)
- 헤더의 미배선 `<Input placeholder="검색">` 제거. `Input`·`SearchOutlined` import도 미사용 → 제거.
- 각 목록의 **자체 검색**(PagedListShell searchPlaceholder 등)은 실제 동작하므로 그대로.

## 완료 기준 (측정)
1. 브라우저 전 메뉴 순회: 라벨과 정확일치하는 h3가 **화면당 1개**(중복 0), 헤더 `placeholder="검색"` 0개.
2. tsc 0(미사용 import 제거 포함).

## OUT
- Page `title` prop 완전 제거(14 호출부 정리)는 별도 청소 — 지금은 무시로 무해.
- 실제 전역 검색 기능 구현(원한다면 별도 스펙).

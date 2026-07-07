# 스펙 224 — 능력 부여 [역할에게/특정 유저에게]를 Segmented→Tabs 통일

## 배경 (사용자 지적 2026-07-08)

유저 → 능력 부여 탭 안의 [역할에게 | 특정 유저에게]가 Segmented(알약)라 상위 [유저 목록 | 능력 부여]
Tabs(언더라인)와 스타일 불일치. "다른 탭과 동일한 스타일로."

## 판단

부여 대상(역할 전체 vs 특정 유저)이 바뀌면 아래 폼(역할 select vs 유저 select)과 부여 목록이 달라진다 →
"내용/도구 전환"이라 Tabs가 규칙(스펙 212·219)에 부합. 스펙 219(메모리 일치/유사도)와 동형.

## 변경 (admin/src/admin/views/UsersView.tsx)

- `<Segmented>` → `<Tabs>`(activeKey/onChange 스위처, 내용은 아래 조건부 렌더). onChange에서 grantSubject
  초기화 유지. 안내문은 탭 아래로(marginInlineStart 제거). 미사용 `Segmented` import 제거.

## 검증
- 브라우저: [역할에게/특정 유저에게] role=tab, 상위와 동일 언더라인, Segmented 잔재 0, 탭 전환 시 안내문
  갱신(이 유저에게만). tsc 0.

# 280 — mockData.ts 死데이터 배열 제거(스펙 305)

## 무엇을 했나
스펙 303이 "seed=실 DB 첫 설치 단일 출처, mockData 배열=死코드"로 정정한 것을 실제 제거로 마감.
`admin/src/admin/mockData.ts`(375→약 300줄)에서 死배열 3종(`BLOCKS`·`ADMIN_AGENTS`·`ADMIN_SESSIONS`)
+ 이들을 변형하던 IIFE 블록 + 死상수 `MCP_STATUS`를 걷어내고, 타입 14·live 상수 8은 원문 그대로 보존.

## 배운 것 / 복리 포인트

- **참조 0이 곧 死는 아니다 — 전이 사용(live 타입에 박힌 타입)을 봐야 안전**. `AgentCard`(Agent.card에
  사용)·`ToolApprovalOverride`(ToolPolicy에 사용)는 **직접 importer 0**이지만 live 타입 정의에 박혀 있어
  삭제하면 빌드가 깨진다. "grep 참조 수 0 → 死"로 기계 판정하면 이 둘을 오삭제한다. 반대로 死배열을
  *어노테이트*하는 타입(`Agent`·`Session`·`BlockCategory`…)은 외부 import도 되므로 **타입은 보존, 배열
  값만 제거**. 死/live 판정은 심볼 카운트가 아니라 **참조의 성격**(값 소비 vs 타입 골격 vs 어노테이션).
  → [[move-breaks-references-both-directions]] [[installed-guard-isnt-covering-guard]]

- **死배열과 그걸 변형하는 IIFE는 한 단위(HARD 블로커)**. 파일 말미 IIFE가 `ADMIN_AGENTS.forEach`·
  `BLOCKS.mcp.items.push`로 배열을 후처리했다. 배열만 지우고 IIFE를 남기면 ReferenceError/TS 에러 →
  **함께 제거해야 함**. 조사가 이 결합(H1)을 선식별해 조각 편집의 함정을 피함. 死코드 제거도 "무엇이
  그걸 만지나"를 먼저 세야 안전. → [[context-control-propagates-to-affordances]] 계열(연결된 것 함께 처리).

- **다중 영역 삭제는 조각 편집보다 "死부분 뺀 전체 재작성"이 안전**. 375줄에서 5개 흩어진 영역을 제거해야
  했는데, 조각 Edit은 IIFE 고아·경계 어긋남 위험이 크다. 파일 전체를 확보해 보존 부분(타입·상수)을 원문
  그대로 두고 死부분만 뺀 전체 Write가 한 번에 정합. → [[whole-fix-over-minimal-patch]]

- **죽은 흔적은 주석까지 따라간다**. `ADMIN_SESSIONS` 마지막 외부 참조는 코드가 아니라 AgentsView의
  *주석*("ADMIN_SESSIONS 제거…") 한 줄이었다. 死배열을 지웠으면 그 이름을 언급하는 주석도 정리해야
  "grep 참조 0"이 진짜 0이 된다(303의 "산출물/주석 언급≠참조"의 쌍 — 이번엔 제거 후 흔적 청소).

## 검증
- **정적(tsc)**: `npx tsc --noEmit` rc=0 — 보존 타입 14·상수 8 온전, 死배열/IIFE 제거 후 컴파일. H1(IIFE
  고아) 있었으면 여기서 잡힘.
- **빌드**: `vite build` ✓(7901 모듈, 3.14s) — 死코드 제거가 번들에 무회귀(청크 경고는 기존·무관).
- **참조 무결(grep)**: 제거 4심볼(BLOCKS·ADMIN_AGENTS·ADMIN_SESSIONS·MCP_STATUS) 전 저장소 외부
  참조 0 재확인(주석까지 청소 후). 제거가 살아있는 참조를 끊지 않음.
- **적대**: 순수 프론트 死코드 제거(파괴·경계·유저데이터 아님) → RBAC/codex 트리거 미해당. tsc/build가 정본 그물.

## 남은 것 / 주의
- 타입/상수 파일 분할(mockData.ts→types.ts 개명 등)은 OUT — 이번은 死코드 제거만. 구조 개편은 별도.
- 파일명이 여전히 `mockData.ts`이나 이제 mock 데이터가 없음(타입·상태맵만). 개명은 21 importer 갱신 동반이라 후속 후보.

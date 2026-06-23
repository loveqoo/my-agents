# 015 — 빌딩 블록 작성/편집 폼 (memory·embedding·permission)

상태: **완료**
날짜: 2026-06-24
브랜치: `feat/agent-service` — main 머지 금지
연동: [014 페르소나 작성 UI], BlocksView, `.dev/troubleshooting/004-dead-button-audit.md`

> 죽은 버튼 전수 감사(004) 결과, 페르소나(014)와 **같은 부류**의 빈틈이 3개 더 발견됨:
> memory/embedding/permission 카테고리는 작성·편집 폼이 통째로 없다.
> persona·mcp만 전용 폼이 있었음.

## 1. 진단
- `BlocksView.createCurrent`: 이 3종은 `createBlockItem(resource, {name:'새 항목'})` 빈 껍데기 생성.
  - **memory는 사실상 깨짐**: `MemoryTypeIn.key`가 필수인데 `key` 미전송 → 422 예상.
- Drawer "편집" 버튼: 이 3종은 하드코딩 `disabled` (활성화 경로 없음).
- 백엔드 CRUD는 3종 모두 완비(`blocks.py`). UI만 부재.

## 2. 목표 / 비범위
### 목표
- memory/embedding/permission를 **등록·편집**할 수 있는 폼 추가(페르소나 패턴 답습).
- 죽은 "새 항목"(껍데기) → 실제 작성 폼. 죽은 "편집"(disabled) → 편집 폼.
- 필드 스펙 기반 **단일 BlockForm**으로 3종 공용(DRY).

### 비범위
- VectorTable의 `rows`/`status`(동기화 관리값) 입력 — 폼에서 제외(서버 기본값).
- 실제 임베딩 동기화 파이프라인. MCP 폼(이미 구현). 감사의 다른 항목(세션 종료·검색·클립·연결테스트).

## 3. 필드 스펙
- **memory** (`memory-types`): `key`(필수·고유) · `name`(필수) · `scope`(선택) · `body`(설명, textarea)
- **embedding** (`vector-tables`): `name`(필수) · `model` · `source` · `dims`(숫자) · `body`(textarea)
- **permission** (`permissions`): `name`(필수) · `scope` · `approver`(셀렉트 user/admin) · `body`(textarea)

## 4. 변경
- `packages/api/src/api/blocks.py`: `/blocks` 집계 memory_items에 `"key": row.key` 추가(편집 prefill용). 그 외 백엔드 무변경.
- `admin/src/admin/views/BlocksView.tsx`:
  - 필드 스펙 `BLOCK_FORMS`(memory/embedding/permission) + 공용 `BlockForm` 모달.
  - `createCurrent`: 이 3종 → `BlockForm(create)` 오픈(껍데기 생성 제거).
  - Drawer "편집"(이 3종) → `BlockForm(edit, prefill)` 오픈(disabled 제거).
  - 저장 → `createBlockItem`/`updateBlockItem(resource, …)` + `loadBlocks()`.

## 5. 검증 (완료 조건)
- [x] `tsc --noEmit` 통과.
- [x] memory 등록(key 포함) → 목록 반영 → 편집 → 본문/필드 변경 저장 → 재조회 (E2E, admin.spec 155행).
- [x] embedding/permission 등록·편집 동작 — vectorTable 편집 시 rows/status 보존(P1 회귀) E2E(190행) + api.spec 015 추가.
- [x] codex GATE — P1/P2 0건 (P3 1건: MCP 상세 status 이중 렌더 → 수정 완료).
- [x] 전체 E2E 36 passed / 1 skip.

## 6. 검증 중 추가 발견·수정 (회귀 방지)
- **embedding 탭 전체 크래시 (실버그)**: status는 백엔드 자유 문자열인데 `VECTOR_STATUS[status].tag`/`MCP_STATUS[...]`를
  가드 없이 조회 → 맵에 없는 status 값(예: `syncing`)이 오면 DataTable이 통째로 언마운트(백지).
  → 폴백 헬퍼 `statusTag(map, status)` 도입(미존재 시 raw 문자열 default Tag). 컬럼/상세 드로어 전부 적용.
  → 학습: [.dev/learning/017-unmapped-status-crash.md].

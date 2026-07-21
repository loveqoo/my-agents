# 176 — 컬렉션 편집 버튼(별명·설명·청크) — 발견성 개선

## 배경 (개발자 피드백)
"RAG 별명을 수정하는 기능은 어디 있나요?" — 스펙 173에서 별명 편집을 *문서 관리 드로어* 맨 아래
"컬렉션 설정" 패널에 넣었더니 찾을 수 없었다. 행 클릭=문서 관리를 예상하지, 별명 편집이 거기 있을 거라
생각 못 함. 발견성 실패.

사용자 결정(AskUserQuestion): **행에 편집(연필) 버튼 추가** — 누르면 별명·설명·청크를 바로 고치는
작은 모달.

## 딜리버러블 (프론트만 — CollectionsView)
1. **EditModal 신설**: 별명·설명·청크(문서형만) 편집. 제목 "컬렉션 편집 · {name}". 저장=
   `updateCollection(id, {alias: alias.trim(), description, chunk_size, chunk_overlap})` → 토스트 →
   목록 새로고침. 식별이름·모델·차원은 불변이라 노출 안 함(안내 문구로 명시).
2. **행에 편집 아이콘**: 액션 컬럼에 연필(edit) 버튼 추가, `c.can_manage !== false`일 때만(소유자만 —
   삭제 버튼과 동일 게이트). `setEditFor(c)`로 EditModal 오픈.
3. **문서 관리 드로어에서 "컬렉션 설정" 패널 제거**: 편집을 EditModal로 일원화(두 곳 편집 혼란·드리프트
   제거). DocsDrawer는 이제 문서 업로드·목록만. 관련 상태(alias/description/chunk*/savingPolicy)·
   useEffect·savePolicy 제거.

## 안전성
- 백엔드·API 무변경(`updateCollection` 그대로, 소유자만 assert_may_manage — 172 verify로 확인된 축).
- EditModal은 can_manage 게이트로만 노출 → 비소유자는 편집 진입 자체가 없음(백엔드도 이중 방어).

## 검증
- tsc clean. 브라우저: 행 편집 버튼 클릭→모달 열림·별명 프리필·수정 저장→목록 반영·비우기 동작.
  문서 관리 드로어엔 "컬렉션 설정" 패널 없음(문서만).

## OUT
- 식별 이름(슬러그)·임베딩 모델·차원 편집(불변 — 별도 축). 별명 유일성 미강제.

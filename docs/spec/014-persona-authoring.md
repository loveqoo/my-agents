# 014 — 페르소나 등록/수정 UI

상태: **완료 (자율)**
날짜: 2026-06-24
브랜치: `feat/agent-service` — main 머지 금지
연동: [007 어드민 UI 연결], 빌딩 블록(BlocksView), 에이전트 폼(AgentsView)

> 사용자 보고: "페르소나를 등록/수정할 수 있는 메뉴가 없어."
> 백엔드 CRUD는 완비, **UI만 빠져 있음**. 페르소나 작성 UI를 추가한다.

## 1. 배경 / 진단

현재 아키텍처(이미 동작):
- 페르소나 = `name` + `tone` + `body`. 백엔드 CRUD(`blocks.py`) + `/blocks` 집계에 `body`·`tone` 포함. ✅
- 에이전트 폼은 페르소나를 **이름으로 드롭다운 선택** → 백엔드 `resolve_persona(name)`가 본문을 찾아 `agent.persona`(서빙용 해석 본문)에 저장 → 채팅이 시스템 프롬프트로 사용. ✅ (즉 **연동은 이미 됨**)

빠진 것(이번 버그):
- 빌딩 블록 persona 탭의 **"새 항목"** → `{ name: '새 항목' }` 빈 껍데기만 생성(이름/톤/본문 입력 폼 없음).
- 상세 Drawer의 **"편집"** 버튼(BlocksView.tsx) → `onClick` 없는 죽은 버튼.
- 결과: 페르소나를 의미있게 등록·수정 불가 → 드롭다운엔 시드 페르소나만 → 단순 에이전트 작성이 막힘.

## 2. 목표 / 비범위
### 목표
- 빌딩 블록 persona 탭에서 페르소나를 **등록**(이름·톤·본문)·**수정**·삭제.
- 새/수정한 페르소나가 에이전트 폼 드롭다운에 즉시 반영(getBlocks 재조회로 자동).
- 단순 에이전트 흐름 복구: 페르소나 작성 → 에이전트에서 선택 → 채팅에 본문 적용.

### 비범위
- memory/permission/embedding의 죽은 "편집" 버튼 — 시드 고정 카탈로그라 이번엔 손대지 않음(추후).
- 에이전트 폼에 자유 텍스트 시스템 프롬프트 입력 — 드롭다운 라이브러리 방식 유지(사용자 선택).
- 페르소나 본문 토큰/길이 검증, 버전관리 — 추후.

## 3. 변경
- `admin/src/api.ts`: `updateBlockItem(resource, id, body)` 추가 (현재 create/delete만 있음) → `PUT /{resource}/{id}`.
- `admin/src/admin/views/BlocksView.tsx`:
  - **PersonaForm 모달**: 이름(Input) · 톤(Input) · 본문(TextArea). 등록/편집 공용.
  - persona 탭 "새 항목" → 빈 껍데기 생성 대신 PersonaForm(create) 오픈.
  - Drawer "편집"(persona) → PersonaForm(edit, 기존 값 채움) 오픈.
  - 저장 → `createBlockItem('personas', …)` / `updateBlockItem('personas', id, …)` → `loadBlocks()`.
  - persona 상세 Drawer에 본문 표시(이미 `detail.body` 렌더 경로 존재 — 확인).

## 4. 검증 (결과)
- [x] UI: persona 등록(이름·톤·본문) → 목록/드롭다운 반영 (admin E2E).
- [x] UI: persona 편집(죽은 버튼 복구) → 본문 변경 저장 → 재조회 확인 (admin E2E).
- [x] 단순 에이전트: 새 페르소나 선택 → systemPrompt로 해석 + 채팅 말투 적용("냥옹") 확인 (API 수동 + E2E).
- [x] E2E: persona 등록→수정→삭제 + 작성 페르소나→단순 에이전트 systemPrompt 해석. 전체 32 passed / 1 skipped.
- [x] codex GATE — P1/P2 0건.

## 5. 추후
- memory/permission 편집 UI(시드 카탈로그 정책 결정 후).
- 페르소나 버전관리·미리보기.

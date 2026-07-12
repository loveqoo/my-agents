# 305 — mockData.ts 死데이터 배열 제거(타입·상수 보존)

## 배경
스펙 303에서 "seed는 실 DB 첫 설치 단일 출처, mockData.ts 데이터 배열은 死코드"로 정정. 이번에
그 死배열을 실제로 걷어낸다. `admin/src/admin/mockData.ts`(375줄)는 **타입/상수(21파일이 import)**와
**목 데이터 배열(아무도 렌더 안 함=死)**이 섞여 있음. 앱은 실 백엔드 API에서 데이터를 읽으므로 배열은
불필요. 조사: 서브에이전트(§검증 참고, 전 export 분류·import 그래프·결합 위험 전수).

## 제거/보존 분류(실측)

### 제거(死)
- **`BLOCKS`**(212–251) — 외부 참조 0.
- **`ADMIN_AGENTS`**(254–287, Agent[]) — 외부 참조 0.
- **`ADMIN_SESSIONS`**(338–343, Session[]) — live 참조 0(AgentsView.tsx:108의 *주석* 언급뿐).
- **후처리 IIFE 블록(350–374)** — `ADMIN_AGENTS.forEach`(351·357)·`BLOCKS.mcp.items`(367·371)를
  변형. **배열과 한 단위로 제거 필수**(안 지우면 ReferenceError/TS 에러 = HARD 블로커, H1).
- **`MCP_STATUS`**(295–299) — 死상수(전 저장소 참조 0). 나머지 status-map 6종과 대칭이라 조사에서
  "NEEDS DECISION"으로 뒀으나 **소비자 0 → 제거**(대칭보다 死코드 정리 우선; 필요 시 되살리기 쉬움).
- (선택) 헤더 주석 1–5(데모 데이터 서술) — 배열 제거 후 부정확 → 갱신/축소.

### 보존(live — importer 있음 또는 live 타입에 박힘)
- **타입 14종**: `AgentConfig`·`PipelineNode`·`ArtifactField`·`ArtifactSpec`·`VersionMeta`·`BlockItem`·
  `BlockCategory`·`ToolApprovalOverride`·`ToolPolicy`·`Agent`·`AgentCard`·`Session`·`Approval`·`StatusMeta`.
  - **주의(H5)**: `AgentCard`(Agent.card에 사용)·`ToolApprovalOverride`(ToolPolicy에 사용)는 **직접
    importer 0이지만 live 타입에 박혀 있어 보존**. 참조 0을 死로 오판하면 빌드 깨짐.
  - **주의(H4)**: `Agent`·`Session`·`BlockCategory`·`BlockItem`·`StatusMeta`는 死배열을 *어노테이트*
    하지만 외부 import도 됨 → **타입은 보존, 배열 값만 제거**.
- **live 상수 8종**: `SHORT_TERM_MEMORY`·`isOrchestratorImpl`·`VERSION_STATUS`·`SESSION_STATUS`·
  `VECTOR_STATUS`·`AGENT_STATUS`·`AGENT_SOURCE`·`AGENT_CONFORMANCE`.

## 제거 위험(조사)
- **H1(HARD)**: IIFE 블록(350–374)을 배열과 함께 제거하지 않으면 컴파일 에러 → 한 단위로 삭제.
- **H2**: mockData.ts는 최상단 import가 없음(`grep "^import"`=0) → 死배열 제거로 생기는 미사용 import 없음.
- **H3**: 배열 파생 상수 없음(`X = ADMIN_AGENTS.length` 류 부재) → 상수 안전.
- **H4/H5**: 위 보존 주의 참조.

## 실행 순서
1. 死 3배열 + IIFE 블록(350–374) + `MCP_STATUS` 제거, 헤더 주석 정리. 타입·live 상수 전부 보존.
2. AgentsView.tsx:108 死배열 언급 주석 정리(참조 흔적 제거).

## OUT
- 타입/상수 재배치(파일 분할) — 이번은 死코드 제거만. 구조 개편은 별도.
- 테스트 잔해 = 스펙 304(별도).

## 검증
- **정적(tsc)**: `tsc --noEmit` 0(보존 타입·상수 온전, 死배열/IIFE 제거 후 컴파일). H1(IIFE 고아) 잡힘.
- **빌드**: admin 빌드 통과(vite/tsc) — 死코드 제거가 번들·타입에 무회귀.
- **참조 무결(grep)**: 제거 심볼(BLOCKS·ADMIN_AGENTS·ADMIN_SESSIONS·MCP_STATUS) 전 저장소 외부 참조
  0 재확인(제거가 살아있는 참조를 끊지 않음 — learning: move-breaks-references-both-directions).
- **적대**: 순수 프론트 死코드 제거라 파괴·경계 아님 → RBAC/codex 트리거 미해당(tsc/build가 정본 그물).

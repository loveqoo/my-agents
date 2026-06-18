# 002 — 에이전트 서비스 초기 구축 루프 회고

날짜: 2026-06-19
지배 스펙: [docs/spec/001-system-overview.md](../../docs/spec/001-system-overview.md)
실행계획: [.dev/plan/001-minimal-hardcoded-agent.md](../plan/001-minimal-hardcoded-agent.md)

## 루프 개요
- **목표:** 에이전트 생성·관리 서비스의 초기 구축 — 시스템 전체 설계(001) + 첫 실행 증분(미니멀 하드코딩 에이전트).
- **단계 흐름:**
  - 1 Scaffolding — uv 워크스페이스 + `packages/agent` 1개
  - 2 Context — 씨앗 스펙(`docs/spec/CLAUDE.md`) 해석
  - 3 Planning — `docs/spec/001-system-overview.md`(질문 라운드로 결정 확정) + `.dev/plan/001`(실행계획)
  - 4 Execution — 로컬 MLX + LangGraph 단일 ReAct, CLI 순수 대화
  - 5 Verification — codex 비판 리뷰(P1 0, P2 3) → 3건 수정 → 실동작 재검증
  - 6 Compounding — 본 회고 + 학습 003/004

## 무엇이 잘못됐나 / 배운 것
- **재촉:** 매 턴 승인/커밋/다음으로 몰아감. → [[003]]
- **AskUserQuestion CJK 이스케이프 실패** 2회. → [[004]]
- **환경 미점검:** uv가 미설치라 실행 단계에서 막힘. 사전 환경 점검이 빨랐다.
- **사용자 제공 값도 검증:** MLX API 키 끝 `s` 누락으로 인증 실패 → 진단 후 정정.
- **codex review와 미추적 파일:** `codex review`는 git diff 기반이라 untracked 파일을 못 봄.
  → `codex exec -s read-only`로 파일을 직접 읽혀 해결.

## 잘된 것
- 단계마다 **사실 확인**: langchain-mcp-adapters / FastMCP / LangGraph A2A·MCP 엔드포인트 / MLX OpenAI 호환을 웹으로 근거 확인 후 스펙에 반영.
- **타자 비판 검증**(codex)로 stateless 대화 버그를 잡고 수정·재검증.
- **점진적 결정**: 큰 스펙을 질문 라운드로 쪼개 확정.

## 다음에 다르게 할 것
- 실행 진입 전에 **툴체인(uv 등) 가용성 선점검**.
- 사람 속도 존중(→ [[003]]), AskUserQuestion은 한글 그대로(→ [[004]]).

## 관련 기록
- [[003]] 재촉하지 말 것
- [[004]] AskUserQuestion CJK 직접 작성
- 이전 루프 회고: [001-project-initial-setup](./001-project-initial-setup.md)

# 011 — API 인증 (Bearer 토큰)

상태: **실행 중 (자율)**
날짜: 2026-06-23
브랜치: `feat/agent-service` — main 머지 금지
연동: [010 비밀 암호화](./010-secret-at-rest.md)

> API가 무인증(로컬)이라 누구나 에이전트·모델·세션을 읽고 조작 가능. **Bearer 토큰 인증**으로
> 보호한다. 개인 워크스페이스이므로 "인증=소유자 전체 접근"; 다중 사용자 RBAC(인가 세분화)는 추후.

## 1. 목표 / 비범위
### 목표
- 모든 도메인 API(`/blocks /models /agents /sessions /approvals` + chat)에 **`Authorization: Bearer <token>`** 요구. 없거나 틀리면 **401**.
- 토큰: env `API_AUTH_TOKEN` → 없으면 `.dev/.api_token`(생성·영속, gitignore).
- 어드민 UI가 모든 요청(fetch + SSE)에 토큰 첨부(`VITE_API_TOKEN`).
- E2E가 토큰 헤더로 통과.

### 비범위
- 다중 사용자/역할(RBAC)·로그인 세션·OAuth — 추후. 지금은 단일 공유 토큰=소유자.
- `mock_remote`(외부 에이전트 스탠드인)는 **API 토큰 비요구**(자체 인증 영역; chat 프록시는 에이전트 토큰을 보냄).
- `/docs /openapi.json`은 열어둠(개발 편의).

## 2. 설계
- `auth.py`: `require_auth` 의존성 — `Authorization` 헤더의 Bearer를 `API_AUTH_TOKEN`(또는 `.dev/.api_token`)과 상수시간 비교. 불일치/누락 → 401.
- `main.py`: 도메인 라우터에 `dependencies=[Depends(require_auth)]`. `mock_remote`·docs 제외. CORS preflight(OPTIONS)는 미들웨어가 처리하므로 영향 없음.
- UI(`api.ts`): 모든 요청 헤더에 `Authorization: Bearer ${VITE_API_TOKEN}`.
- 토큰 공유: 루트 `.env` `API_AUTH_TOKEN` = `admin/.env` `VITE_API_TOKEN`(개발 동일값). `.env.example`에 명시.
- E2E: Playwright api 프로젝트 `extraHTTPHeaders` + 브라우저 cleanup 요청 헤더.

## 3. 검증 (결과)
- [x] 무토큰/오토큰 → 401, 올바른 토큰 → 200 (스모크 + E2E).
- [x] UI가 `VITE_API_TOKEN`으로 정상 동작(전체 브라우저 E2E 통과).
- [x] mock_remote는 토큰 없이도 동작.
- [x] 전체 E2E 27 passed. codex GATE — **P1 수정**(`.dev/.api_token` gitignore) + P2 2건(빈 토큰 fail-closed, 원격 에러 본문 로그 비기록). 학습 [[015]].

## 추후
- 다중 사용자·RBAC(예: 관리자만 승인 큐 처리), 로그인/세션, 토큰 로테이션, 감사 로그.

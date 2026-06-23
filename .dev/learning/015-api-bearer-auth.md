# 015 — API Bearer 토큰 인증과 함정

날짜: 2026-06-23
맥락: [011 API 인증](../../docs/spec/011-api-auth.md), `auth.py`/`main.py`/`admin/src/api.ts`

## 패턴
- 도메인 라우터에 `dependencies=[Depends(require_auth)]`. `Authorization: Bearer`를 `API_AUTH_TOKEN`(env)→`.dev/.api_token`(생성·영속) 과 **상수시간 비교**(`secrets.compare_digest`).
- SPA: 서버 `API_AUTH_TOKEN` = UI `VITE_API_TOKEN` 동일값. UI는 모든 fetch+SSE에 헤더.
- 보호 제외: `mock_remote`(외부 에이전트 스탠드인, 자체 인증 영역), `/docs`.
- CORS preflight(OPTIONS)는 미들웨어가 처리 → 의존성과 충돌 없음.

## codex가 잡은 함정 (반영)
- **토큰 파일 gitignore 필수**: 생성형 비밀 파일(`.dev/.api_token`, `.dev/.secret_key`)을 반드시 ignore. 안 하면 라이브 토큰이 커밋됨.
- **빈 토큰 fail-closed**: env/파일 토큰이 공백이면 `Bearer `(빈 값)로 인증 통과 가능 → 공백이면 재생성, 빈 제시 토큰은 거부.
- **에러 로그 비밀 누출**: 원격 응답 본문은 보낸 Authorization을 **에코**할 수 있어 클라·로그 어디에도 본문을 남기지 않음(상태코드만).

## 교훈
인증은 **fail-closed**가 기본(공백/누락=거부). 생성형 비밀 파일은 만들자마자 gitignore. 비밀은 **에러/로그 경로로도** 새지 않게.

## 추후
다중 사용자·RBAC(예: 관리자만 승인 처리), 로그인/세션, 토큰 로테이션, 감사 로그.

## 관련
- [[014-secret-at-rest-fernet]] (비밀 암호화 저장)

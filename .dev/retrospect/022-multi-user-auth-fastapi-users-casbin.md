# 022 — 멀티유저 인증 + 오픈형 권한 (fastapi-users + Casbin)

지배 스펙: [docs/spec/031](../../docs/spec/031-multi-user-auth-and-pluggable-providers.md)
날짜: 2026-06-26 · 브랜치: `feat/agent-service` (main 머지 금지)

## 한 일

011의 단일 머신 토큰(=소유자 전체접근)을 멀티유저로 확장. 직접 구현 대신 **라이브러리 차용**:
- **fastapi-users**: 서버측 세션 쿠키(`CookieTransport` + `DatabaseStrategy` — `accesstoken` 행이
  불투명 토큰, 로그아웃 시 행 삭제 = 진짜 무효화). 비밀번호 Argon2(pwdlib).
- **PyCasbin + async SQLAlchemy adapter**: 오픈형 RBAC. 정책을 `rbac_model.conf`로 코드에서 분리 —
  호출부는 `enforce(sub,obj,act)` 고정, RBAC→ABAC/ReBAC 확장 시 모델 파일만 교체.
- **`current_principal`**: 세션쿠키 유저 OR 머신 Bearer 토큰(하위호환) 통합 게이트.
- Admin SPA: AuthGate(부팅 시 `/users/me` → 미인증이면 로그인 화면, 전역 401도 여기로) +
  LoginScreen + UsersView(유저/역할 관리). api.ts는 same-origin 쿠키 모드(`credentials:'include'`).

## 잘된 것

- **사용자 피드백으로 방향을 되돌린 게 정답이었다.** v1에서 나는 "fastapi-users 피하자"(자체구현)로
  결론냈는데, 사용자가 "오픈형·라이브러리 차용"을 요구 → 웹 1차 출처로 재조사하니 *서버측 세션쿠키 +
  Argon2 + 확장 seam을 한꺼번에 주는 유일한 라이브러리*가 fastapi-users였다. [[probe-deeper-before-concluding]]
  단정("이점 없음") 한 겹을 사용자가 밀어 깬 사례. 내 첫 결론을 의심했어야 했다.
- **검증을 타자에게 넘긴 게 값을 했다.** codex + 독립 서브에이전트 둘 다 SHIP을 냈고, **둘이 같은 MED를
  독립적으로 짚었다**(CORS `allow_credentials` 누락 → 크로스오리진 쿠키 로그인 무음 실패). 수렴 = 신뢰.
  자가검증만 했으면 same-origin 프록시로만 테스트해서 영영 못 봤을 구멍이다. [[loop-is-cross-project-practice]]
- **수치/상태로 끊어 검증**: curl 라운드트립(204/200/403/401 + Argon2 `$argon2id$` 접두 + 평문 누출 0)을
  단계별로 찍고, 브라우저는 Playwright+시스템Chrome 스샷 4장(로그인→셸→유저뷰→로그아웃)으로 눈 확인.
  [[verify-ui-in-browser-proactively]] — 사용자 스샷 안 기다리고 내가 먼저 캡처.

## 막힌 것 / 교훈

- **autogenerate가 남의 테이블을 drop하려 했다.** alembic이 DB에는 있고 우리 metadata엔 없는
  `mem0_memories`(mem0 런타임 관리)를 `drop_table`로 넣었다. 손으로 제거. → learning 033.
- **머신 토큰 빈값 단락의 함정.** 첫 머신토큰 테스트가 401이라 "하위호환 깨졌나?" 했는데, 실제론
  `.dev/.api_token` 파일이 없어 `TOK`가 빈 문자열 → `valid_machine_token`이 빈 토큰을 단락 거부한
  *정상 동작*이었다. 단정 전에 "내 입력이 빈 게 아닌가"를 먼저 의심해야 했다. [[probe-deeper-before-concluding]]
- **콘솔 404를 버그로 오해할 뻔.** 브라우저 콘솔 404는 `/favicon.ico`(브라우저 자동요청), 401 두 개는
  로그인 전/로그아웃 후 `getMe`(설계대로). "에러 로그 = 버그" 단정 말고 출처를 짚으니 전부 정상.

## 적용점(다음 작업 Context에서 상기)

- 라이브러리 차용 판단은 **요구 3종(이 경우 세션쿠키+Argon2+seam)을 한 번에 주는가**로 가른다.
  하나라도 자체구현이면 그 라이브러리의 이점이 깎인다.
- 인증/권한처럼 사이드가 깊은 변경은 **반드시 타자 2종(codex+서브에이전트) 병렬** — 수렴하면 채택,
  엇갈리면 한 겹 더. CORS 같은 배포-의존 구멍은 same-origin 로컬 테스트로 안 잡힌다.
- alembic autogenerate는 **남의 런타임 테이블(mem0 등)을 drop하지 않는지** upgrade/downgrade 둘 다 확인.

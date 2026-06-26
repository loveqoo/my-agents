# 031 — 멀티유저 인증 + 오픈형 권한 (라이브러리 차용: fastapi-users + Casbin)

상태: **구현 완료 (1차 — AI 작성·검증, 인간 브랜치 테스트 대기)** · v1(자체구현)에서 사용자 피드백 반영해 전면 개정
날짜: 2026-06-26
브랜치: `feat/agent-service` — **main 머지·push 금지**(사용자가 직접 브랜치 테스트)
지배 스펙: [011 API 인증](./011-api-auth.md)(단일 토큰=소유자 → 여기서 멀티유저로 확장),
[021 Playground userId UX](./021-playground-userid-ux.md)(userId=인증과 분리된 식별자 — 연결고리)
참고: `.dev/learning/015`(Bearer 인증 함정·fail-closed), `.dev/learning/014`(Fernet 비밀저장)

## 배경 / 문제 (사용자 지적)

> *"멀티 유저 기능을 제공해야 할 것 같아. 사용자 등록, 로그인, 권한 같은 거. 가장 관리하기 쉽고,
> 다른 서비스의 인증과 연동하기 쉬운지 파악하자. 예: LDAP를 추상 레이어로 나중에 쉽게 추가."*

피드백(방향 재조정):
> *"너무 한쪽으로 치우친 구체적인 인증/권한 체계보다는 **오픈된** 인증/권한 체계가 들어왔으면 해
> (그렇다고 너무 오픈, oauth? 구조는 아니야). 그리고 **직접 구현하기보다는 잘 만들어진 구조(라이브러리)
> 를 차용**했으면 해."*

- 현재 인증(011)은 **단일 공유 Bearer 토큰 = 소유자 전체 접근**. 유저 테이블 없음, RBAC 없음.
- 요구: (1) 등록·로그인·권한, (2) **오픈/확장형**(특정 역할·방식에 락인 안 됨), (3) **라이브러리 차용**
  (자체 구현 지양), (4) OAuth 위임처럼 **과하게 무겁진 않게**(앱 임베디드, 별도 IdP 서버 아님).

## 리서치 근거 (웹 1차 출처 — 2026-06-26, 추측 금지)

두 갈래 병렬 리서치, 1차 출처(GitHub/PyPI/공식문서)로 검증. v1의 "fastapi-users 피하라" 단정을
사용자 피드백에 따라 재검증 → **라이브러리 차용이 자체구현보다 fail-closed 리스크가 낮다**로 전환.

### 인증 = `fastapi-users` (≥15.0.2, 현 15.0.5 / 2026-03-27)
- **서버측 세션 쿠키**: `CookieTransport` + `DatabaseStrategy` → DB에 불투명 토큰 행, HttpOnly·Secure
  쿠키, 로그아웃 시 행 삭제 = **진짜 무효화**(JWT-in-cookie 아님). 후일 `RedisStrategy` 무변경 교체.
  (출처: fastapi-users.github.io/configuration/authentication)
- **Argon2 기본**(pwdlib) — passlib(2020 미유지·PEP594로 py3.13 `crypt` 제거로 깨짐) 안 씀. v13.0.0
  (2024-03-11)에서 passlib→pwdlib 전환. (출처: github releases, pypi pwdlib/passlib, peps.python.org/pep-0594)
- **확장 seam = 사용자가 원한 "오픈" 구조**: Transport+Strategy+UserManager 추상화. **LDAP=커스텀
  authentication backend, OIDC=내장 `httpx-oauth` 라우터로 drop-in** — Keycloak/Ory 같은 무거운 IdP
  위임 없이. (요구 (3)(4) 충족)
- **유지보수 모드(신기능 동결)** — README 자기선언. 단 우리 요구(register/login/logout/me + 세션)는
  **이미 완성·동결된 기능**, 보안 패치 유지(CVE-2025-68481 → v15.0.2 패치). 후속 toolkit은 예고만
  (미검증). → 로드맵이 아니라 *오늘 되는 것*으로 채택. **사용자 승인(2026-06-26).**
- SQLAlchemy async 기본 경로(`fastapi-users-db-sqlalchemy`), Pydantic v2(v15에서 v1 제거). 우리 스택 정합.
- RBAC 없음(active/verified/superuser 플래그만) → 인가는 아래가 담당.
- 대안 비교: **authx**(active이나 user framework 아님 → 비번해시·유저모델·등록흐름 직접구현 = 의도
  역행), fastapi-login(thin·세션무효화 없음), Starlette 세션(전부 자작), AuthLib(OAuth 전용=과함).

### 인가 = `PyCasbin` + `casbin-async-sqlalchemy-adapter`
- **정책을 코드에서 분리**(요구 (2) "오픈, 락인 아님"의 핵심): `model.conf`(PERM 메타모델)로 RBAC
  시작 → ABAC/ReBAC/도메인-RBAC로 확장해도 **호출부 `enforce(sub,obj,act)` 불변**. admin/member를
  코드에 하드코딩하지 않는다. (출처: casbin.apache.org/docs/supported-models, get-started)
- **임베디드 라이브러리**(별도 서버 아님) + **async Postgres** 정책 저장(우리 스택 정합). 정책이 우리
  DB(`casbin_rule`)에 산다. (출처: pypi casbin-async-sqlalchemy-adapter 1.17.0 / 2025-12-10)
- FastAPI 통합: per-route 의존성으로 `enforce`. 활발 유지(pycasbin 2.8.0 / 2026-02).
- 대안 전부 탈락: **oso=공식 deprecated**(Oso Cloud 유료 이전, 마지막 0.27.3/2024-01), py-abac/Vakt=
  stale+sync only+SQLAlchemy1.x, OpenFGA/Permify/SpiceDB=별도 Go 서버(요구 (4) 위반·너무 무거움).

## 결정 (사용자 승인 2026-06-26)

- **범위**: 설계 + **1차 로컬 인증 구현**(등록·로그인·세션·권한). LDAP/OIDC는 **seam만**(fastapi-users
  커스텀 backend / httpx-oauth)로 두고 미구현(나중에 drop-in).
- **인증**: **fastapi-users** — 서버측 세션 쿠키(CookieTransport+DatabaseStrategy) + Argon2(pwdlib).
- **권한**: **PyCasbin**(async SQLAlchemy adapter) — RBAC model부터, 정책 코드분리(확장형 "오픈").
- **하위호환**: 기존 머신 Bearer 토큰 유지(mock_remote·E2E·playground 무회귀).
- **로그인 식별자 = email**(fastapi-users 기본, username 미도입 — 1차 단순화). *(승인 2026-06-26)*
- **공개 등록 안 함 = 관리자만 유저 생성**: `register_router` 미마운트, admin 전용 생성 엔드포인트
  (UserManager.create, `require` 보호)만 제공. *(승인 2026-06-26)*
- **Casbin enforce 부착 = 민감 라우트만**(승인 처리·유저/역할 관리·모델 비밀), 나머지는 `current_principal`
  만(둘 다 통과). 전 라우트 즉시 권한게이팅 안 함. *(승인 2026-06-26)*

## 보안 안전성 (계승 원칙 — 015)

- **fail-closed**: 비번/세션 누락·만료 = 거부. fastapi-users 기본이 fail-closed(미인증 401).
- **비밀 비누출**: 해시만 저장(Argon2, 평문 금지), 쿠키는 DB에 토큰 행(불투명). 에러/로그에 자격·쿠키 비기록.
- **생성형 비밀 gitignore**: fastapi-users `SECRET`(토큰 서명·리셋용)은 생성 즉시 ignore(기존
  `API_AUTH_TOKEN`/`.dev/.api_token` 패턴 재사용 — env 우선, 없으면 생성·`.dev/` 영속·gitignore).
- **쿠키 보안**: `cookie_httponly=True`, `cookie_secure=True`, `cookie_samesite="lax"|"strict"`(same-origin
  → CSRF 1차 방어). 가능하면 `__Host-` 호환 이름.

## 변경 범위

### A. 의존성 — `packages/api/pyproject.toml`
- `fastapi-users[sqlalchemy]`(≥15.0.2), `casbin`, `casbin-async-sqlalchemy-adapter`. (pwdlib/argon2-cffi는
  fastapi-users가 끌어옴.) `uv`로 추가.

### B. 스키마 — `models.py` + alembic
- **`User`**(fastapi-users 규약, `SQLAlchemyBaseUserTableUUID` 상속): id(UUID), email(unique),
  hashed_password, is_active, is_superuser, is_verified + **확장 컬럼** `source`(String default `local` —
  local/ldap/oidc 구분), `display_name`(nullable), created_at.
- **`AccessToken`**(`SQLAlchemyBaseAccessTokenTableUUID`): DatabaseStrategy 세션 토큰 행(token PK,
  user_id FK, created_at). = 우리의 "auth_sessions". (채팅 `sessions`와 이름 충돌 회피 자동 해결.)
- **`casbin_rule`**: async adapter가 생성·관리(정책 `p` + role 할당 `g`). 직접 정의 불필요.
- **`Role`(`roles`) 카탈로그**(선택·가벼움): name(unique)·description — **UI 표시·관리용**(어떤 role이
  있나 나열). role 할당의 **진실 원천은 Casbin grouping policy**(`g, user, role`)지 이 테이블이 아니다.
  user_roles M:N 테이블은 **폐기**(Casbin이 대체) — v1 대비 단순화.

### C. fastapi-users 배선 — 신규 `packages/api/src/api/users.py`
- `UserManager`(`BaseUserManager[User, UUID]`) — `on_after_register` 훅에서 Casbin 기본 role(`member`)
  부여. `SECRET` 주입(B 보안).
- `get_user_db`(SQLAlchemyUserDatabase), `get_access_token_db`(SQLAlchemyAccessTokenDatabase).
- `auth_backend` = `AuthenticationBackend(name="cookie", transport=CookieTransport(...),
  get_strategy=DatabaseStrategy)`. **provider 확장점**: 후일 LDAP/OIDC backend를 이 리스트에 추가.
- `fastapi_users = FastAPIUsers[User, UUID](get_user_manager, [auth_backend])` → 의존성
  `current_active_user` 제공.

### D. 인가(Casbin) — 신규 `packages/api/src/api/authz.py`
- `model.conf`(RBAC: `request_definition r=sub,obj,act` / `role_definition g=_,_` /
  `matchers m = g(r.sub, p.sub) && r.obj==p.obj && r.act==p.act`). 파일로 두어 **정책=코드분리**.
- `AsyncEnforcer` + `casbin-async-sqlalchemy-adapter`(우리 async engine 재사용). 부팅 시 `load_policy`.
- **의존성 팩토리** `require(obj, act)` — `current_active_user`로 sub 도출 → `enforce(sub,obj,act)`
  실패 시 403, `is_superuser`는 우회. (v1의 `RoleChecker`를 Casbin enforce로 대체.)
- role 부여/회수 = enforcer `add_role_for_user`/`delete_role_for_user`(= grouping policy 갱신).
- 기본 정책 시드(부팅): `member`/`admin` role, admin은 전 obj 허용 등 최소 정책. 멱등.

### E. principal 통합 + 라우팅 — `main.py` / `auth.py`
- fastapi-users 라우터 마운트: `/auth`(login·logout — DatabaseStrategy 쿠키), `/users`(me·유저관리).
  **`register_router`는 마운트 안 함**(공개 등록 금지) → admin 전용 유저 생성 엔드포인트(`require` 보호,
  UserManager.create)로 대체.
- **통합 principal 의존성** `current_principal` — **세션 쿠키 유저(fastapi-users) OR 기존 머신 Bearer
  토큰(=superuser급 머신)** 둘 다 허용. 머신 토큰은 fastapi-users 밖이라 OR 분기로 흡수(하위호환).
- 도메인 라우터 **점진 전환**: 1차엔 기존 `require_auth`를 `current_principal`로 교체(둘 다 통과),
  민감 라우트(승인 처리·유저/역할 관리·모델 비밀)에 `Depends(require(obj, act))` 부착.
- **관리자 시드**: 첫 부팅 시 env(`ADMIN_EMAIL`/`ADMIN_PASSWORD`)로 superuser 생성(UserManager.create)
  + Casbin `admin` role 부여. 미설정이면 생성 안 함 + 경고 로그(fail-closed — 빈 관리자 자동생성 금지).
  `db.init_db` 시드 경로에 추가.

### F. Admin 프론트 — 로그인/로그아웃 + 유저·역할 관리
- 미인증 → **로그인 화면**(email/password). 세션 쿠키는 same-origin이라 fetch 자동 전송 → `api.ts`는
  토큰 헤더 불요(쿠키 모드). `VITE_API_TOKEN`은 머신/개발 폴백 유지. login은 fastapi-users의
  OAuth2 form(`username`=email, `password`).
- 401 → 로그인 화면. 헤더에 **로그아웃**(`POST /auth/logout`) + 현재 유저(`GET /users/me`) 표시.
- **유저·역할 관리 뷰**(admin 전용, `require` 보호): 유저 목록·활성토글·**Casbin role 부여/회수**.
  role 목록은 `roles` 카탈로그(B). antd.
- 1차 최소: 로그인/로그아웃/me + 유저목록·role부여. 비번리셋·이메일검증 UI는 후속.

### G. alembic
- User/AccessToken/casbin_rule/roles 테이블 마이그레이션. `roles` 카탈로그 + 기본 Casbin 정책 시드.

## 실행 단계 (순서)

1. **의존성**(A) 추가 → import 확인.
2. **스키마**(B) + alembic → 마이그레이션 적용 확인.
3. **fastapi-users 배선**(C) + **Casbin**(D) → 라우터 마운트(E) + 관리자 시드.
4. **라이브 라운드트립**: register→login(쿠키)→`/users/me` 200, 미인증 401, logout→401.
5. **권한**: member→`require(admin)` 라우트 403, admin/superuser→200.
6. **프론트**(F) → 브라우저 검증(로그인→보호화면→로그아웃, admin/member 권한 차이).
7. alembic·시드(G) 마무리.

## 검증 (측정 가능 · 자가검증 지양)

1. **인증 라운드트립**(라이브): register(또는 시드)→login→Set-Cookie→`GET /users/me` 200, 미인증 401.
   logout→토큰 행 삭제→이후 `/users/me` 401. (DatabaseStrategy 무효화 동작 확인.)
2. **권한(Casbin)**: member 유저가 `require(obj,act=admin)` 라우트 → **403**, admin/superuser → 200.
   `add_role_for_user`로 member→admin 승격 후 200(정책 반영).
3. **비밀 안전**: DB에 **평문 비번 없음**(Argon2 해시만 — `$argon2` 접두 확인), 쿠키 토큰은 `AccessToken`
   행(불투명), 에러/로그에 자격·쿠키 비노출. `SECRET` env→`.dev/` 영속·gitignore.
4. **하위호환 무회귀**: 기존 머신 Bearer 토큰으로 도메인 API·mock_remote·playground·E2E 정상.
5. **브라우저**: 미인증→로그인 화면, 로그인 후 보호 화면, 로그아웃, admin/member UI 권한 차이
   (Playwright + 시스템 Chrome, `tests/browser/`).
6. **서브에이전트/codex 비판 리뷰**: 쿠키 플래그(HttpOnly/Secure/SameSite)·세션 무효화·Casbin enforce
   누락 경로·머신토큰 OR 분기 누수·관리자 시드 fail-closed·정책 시드 멱등.

## 완료 조건

- [x] 의존성 3종(fastapi-users[sqlalchemy]·casbin·async adapter) + User/AccessToken/casbin_rule/roles + alembic
- [x] fastapi-users 배선(UserManager·DatabaseStrategy 쿠키 backend) + `/auth`·`/users` 라우터
- [x] Casbin `model.conf`(RBAC) + async adapter + `require(obj,act)` 의존성 + 기본 정책 시드(멱등)
- [x] `current_principal`(세션쿠키 OR 머신토큰) + 민감 라우트 admin 보호 + 관리자 시드(fail-closed)
- [x] Admin 로그인/로그아웃 + 유저·역할 관리(최소) 화면
- [x] 검증 1~5 라이브·브라우저 통과 + codex·서브에이전트 비판 리뷰 PASS(둘 다 SHIP; CORS allow_credentials·seed 경쟁·중복 member role 3건 즉시 반영)
- [ ] **main 머지 금지** — 사용자 브랜치 테스트 대기

## 범위 밖 (후속)

- **LDAP/OIDC 실구현** — seam만(fastapi-users 커스텀 backend / httpx-oauth). `ldap3` search-then-bind·
  LDAPS·빈비번거부·필터이스케이프, OIDC(iss/aud/JWKS/exp 검증)는 별도 스펙.
- **userId↔인증주체 전면 도출**(021 후속) — 1차엔 병존.
- **외부 IdP 위임** — 관리형 Keycloak/Authentik 전환은 규모 확대 시.
- **Casbin 고급 모델**(ABAC/ReBAC/멀티테넌트·도메인) — 1차는 RBAC. 정책 코드분리라 호출부 무변경 확장.
- **다중 워커 정책 reload watcher**(casbin-postgresql-watcher) — 1차 단일/소수 워커는 부팅 load로 충분.
- CSRF 토큰(SameSite 1차 방어), MFA, 비번 리셋·이메일 검증 UI, 세션 만료 청소 잡(1차 lazy).

# 052 — 유저 메모리 큐레이션에 유저 신원 표시 (raw UUID → 이메일)

## 배경 / 문제

메모리 관리 화면(스펙 030)의 **유저 메모리 탭**은 `listUserIds()`(`GET /sessions/users`)가 주는
**raw `user_id`(UUID)를 그대로 드롭다운 라벨**로 쓴다(`MemoryView.tsx` `label: u`). user_id는
인증 주체에서 도출된 `str(User.id)` UUID(스펙 032)라, 관리자가 *"누구의 메모리인지"* 식별할 수
없다. 선택 후 `UserMemoryPanel`의 설명문도 `<b>{userId}</b>`로 raw UUID만 보여준다.

사용자 보고: *"유저 메모리를 보고 수정하려는데 세션이름(=user_id)으로만 조회하니 어떤 유저인지
모르겠다."*

## 제약 (권한 결합 회피)

이메일·display_name은 `GET /admin/users`(`AdminUser`)에 있지만 이 라우트는
**`users:manage`(슈퍼유저 전용)**다. 반면 "메모리" 메뉴는 **모든 admin 콘솔 유저에게 노출**된다
(`AdminShell.tsx`: 유저/배치만 `is_superuser` 게이트, 메모리는 기본 노출). 따라서 프론트에서
`listUsers()`로 신원을 매핑하면 **비-슈퍼유저 관리자에게 메모리 화면이 403으로 깨진다**(메모리
큐레이션이 유저-관리 권한에 결합됨 — 잘못된 스코핑).

## 결정

메모리 화면 **전용**의, `users:manage`를 요구하지 않는 신원-보강 엔드포인트를 추가한다.
`GET /sessions/users`(Playground가 쓰는 `list[str]`, 스펙 021)는 **건드리지 않는다**(소비처 보호).

## 범위

### 백엔드 — `packages/api/src/api/memory_routes.py`
- `GET /memory/users` 신설 → `list[{user_id, email, display_name}]`.
  - 세션의 distinct `user_id`(최근 활동순 — `/sessions/users`와 동일 출처/정렬)를 뽑고,
    `User` 테이블을 파이썬 측에서 `{str(u.id): u}`로 매핑해 보강(문자열 user_id ↔ UUID 캐스팅
    회피, distinct 수가 적음). 등록 유저가 아니면 email·display_name = None(미등록 — graceful).
  - 메모리 라우터(`_auth`)에 마운트되어 있으므로 **추가 권한 의존 없음**. `users:manage` 불요.
  - 라우트 충돌 없음: `/users`(복수) ≠ 기존 `/user/{user_id}`(단수).

### 프론트 — `admin/src/api.ts`
- `interface MemoryUser { user_id; email: string|null; display_name: string|null }`
- `listMemoryUsers = () => j<MemoryUser[]>('/memory/users')`

### 프론트 — `admin/src/admin/views/MemoryView.tsx` (UserMemoryTab)
- `listUserIds` → `listMemoryUsers`. 라벨 = `display_name · email`(있으면), 미등록이면
  `(미등록) <uuid>`. value=user_id. 검색은 라벨(email+이름+short id) 전반.
- 선택된 유저의 신원 라벨을 `UserMemoryPanel`에 `label` prop으로 전달.

### 프론트 — `admin/src/admin/views/UserMemoryPanel.tsx`
- `label?: string` prop 추가. 설명문의 `<b>{userId}</b>` → `<b>{label ?? userId}</b>`,
  label이 있으면 raw `userId`는 흐린 monospace 보조로 병기(교정 대상 식별 + 기술적 정확성 동시).

## 검증 (완료 조건)
- [ ] `GET /memory/users`가 distinct user_id를 최근순으로, 등록 유저엔 email/display_name 붙여
      반환(라이브 asyncpg/HTTP로 확인). 미등록 user_id는 email=null로 graceful.
- [ ] `/sessions/users`(list[str]) 응답 형태 **불변**(Playground 회귀 없음).
- [ ] 권한: 비-슈퍼유저(=`users:manage` 없음) 토큰으로 `/memory/users` 200, `/admin/users` 403 —
      메모리 화면이 유저-관리 권한에 결합되지 않음을 실증.
- [ ] 브라우저(Playwright+시스템 Chrome): 유저 메모리 탭 드롭다운이 이메일을 보여주고, 선택 시
      패널 헤더가 이메일로 식별됨(스샷).
- [ ] 타자 검증: 서브에이전트/codex로 라우트 충돌·권한 결합·소비처(Playground) 회귀를 적대 점검.

## 메모
- 드롭다운 출처는 여전히 **세션 기반 user_id**(활동 있는 유저)다 — mem0에만 있고 세션이 정리된
  유저는 빠질 수 있으나(스펙 049/050 정리), 이 작업의 범위는 *식별 라벨링*이지 출처 변경이 아니다.
  필요 시 후속에서 mem0 user_id 열거를 출처로 승격 검토.

# 053 — 유저 메모리 역할 기반 스코핑 (본인 기본 + 어드민 타인)

상태: 승인 대기 → 실행
선행: [052](052-user-memory-identity-in-curation.md)(신원 보강 `/memory/users`),
031(fastapi-users + Casbin RBAC), 032(user_id를 principal에서 도출)

## 문제

유저 메모리 라우터는 general `_auth`만 걸려 있어 **인증된 누구나 임의 user_id의 메모리를
조회·교정**할 수 있다(`GET/PATCH/DELETE /memory/user/{user_id}`). 즉 일반 사용자도 남의
개인 사실을 열람·수정 가능 — 프라이버시 경계 부재. 052는 *신원 라벨*만 붙였을 뿐 *접근*은
안 막았다.

## 결정 (사용자 확인)

1. **본인 기본 + 어드민은 타인.** 비-어드민 사용자는 *자기* user_id 메모리만 조회·교정.
   어드민 롤은 드롭다운으로 임의 유저 선택(현재 큐레이션 UX 유지). 본인 것은 **읽기 전용이
   아니라 교정 가능**(질문 Q1: "맞음 — 본인 기본 + 어드민은 타인").
2. **"어드민 롤" = `memory:manage` 권한.** `require` 대신 principal 기반 인라인 판정:
   - 머신 Bearer 토큰(소유자) → 어드민 등가(하위호환 — curl·Playground 안 깨짐).
   - `is_superuser` → 우회 통과(부트스트랩 안전판, authz.py 패턴).
   - Casbin `enforce(str(user.id), "memory", "manage")` → `admin` 역할(`*,*`)이 통과.
   - 그 외(member) → 본인만.
   기본 정책 `("admin","*","*")`이 이미 `memory:manage`를 커버 → **새 시드 불요**.

`require("memory","manage")` 의존성을 *직접* 쓰지 않는 이유: 그건 `current_active_user`에
의존해 **머신 토큰을 401**로 막는다. 메모리 라우트는 쿠키 유저 + 머신 토큰 둘 다 받아야
하므로(`current_principal`), 둘을 함께 다루는 인라인 헬퍼로 판정한다.

## 설계

### 백엔드 (`memory_routes.py`)

권한 헬퍼:
```python
def _can_curate_others(principal) -> bool:
    if principal == "machine":      # 소유자 토큰 = 어드민 등가
        return True
    if getattr(principal, "is_superuser", False):
        return True
    return get_enforcer().enforce(str(principal.id), "memory", "manage")
```

소유권/권한 게이트(타 유저 접근 차단):
```python
def _assert_principal_may_access(principal, user_id: str) -> None:
    if _can_curate_others(principal):
        return
    own = None if principal == "machine" else str(principal.id)
    if user_id != own:
        raise HTTPException(403, "다른 유저의 메모리에 접근할 수 없습니다")
```

라우트 변경 — 모두 `principal = Depends(current_principal)` 주입:
- `GET /memory/users` → 응답을 **객체로 격상**(052는 bare list였고 소비자는 우리 프론트
  하나뿐이라 안전한 변경):
  ```
  { "can_curate_others": bool,
    "self": { user_id, email, display_name } | null,   # 머신=null(유저신원 없음)
    "users": [ {user_id, email, display_name}, ... ] }  # 어드민=전체, 비-어드민=[self]
  ```
  비-어드민은 `users=[self]`(메모리 없어도 항상 본인 1건 — 빈 패널이라도 봄). response_model로
  누출-안전(052 교훈) 유지.
- `GET /memory/user/{user_id}` · `PATCH …/{mem_id}` · `DELETE …/{mem_id}` →
  맨 앞에 `_assert_principal_may_access(principal, user_id)`. 기존 `_assert_user_owns`
  (mem_id가 그 user_id 소유인지)는 그대로 — 이건 principal-레벨, 저건 row-레벨, **둘 다 필요**.

### 프론트 (`api.ts`, `MemoryView.tsx`)

- `listMemoryUsers()` 반환형을 `MemoryUserList`(위 객체)로. `Me`에 `id` 포함 확인.
- `UserMemoryTab`: `can_curate_others`로 분기.
  - true(어드민/머신) → 현재 드롭다운(전체 `users`, 052 이메일 검색·식별).
  - false(일반) → 드롭다운 없이 `self`로 `UserMemoryPanel` 직접 렌더("내 기억" 헤더).
- `self`가 null이고 `can_curate_others`인 머신 경로는 드롭다운만(본인 패널 없음) — 자연스러움.

## 완료 조건 (측정 가능)

1. **비-어드민 격리(read)**: member 토큰/쿠키로 `GET /memory/user/{타인}` → **403**.
2. **비-어드민 본인 허용**: 같은 주체로 `GET /memory/user/{본인}` → 200.
3. **비-어드민 교정**: 본인 mem PATCH/DELETE 200; 타인 mem → 403.
4. **어드민 전체**: superuser/머신으로 임의 user_id → 200, `/memory/users.can_curate_others=true`,
   `users`=전체.
5. **`/memory/users` 형상**: 비-어드민 → `can_curate_others=false`, `users=[self]`;
   누출 없음(세 필드만).
6. **프론트**: 비-어드민 로그인 시 드롭다운 없이 본인 패널, 어드민은 드롭다운(브라우저샷).
7. **회귀**: `/sessions/users`(Playground) 불변, 052 신원 라벨 불변.
8. **타자 적대 리뷰**: 권한 우회(머신/superuser/casbin 경계)·row-vs-principal 가드 중복성·
   403 누출문구·response_model 누출.

## 검증 수단

- 단위: pytest로 4개 주체(member·superuser·casbin-admin·machine) × (self/other) 매트릭스.
- 브라우저: self-fixture로 member·super 두 계정 시드 → 각 로그인 후 유저 메모리 탭 캡처
  (member=드롭다운 없음·본인만, super=드롭다운). 종료 시 자동 삭제(스펙 050 Phase 3).
- 타자: 서브에이전트 적대 리뷰(완료조건 8).

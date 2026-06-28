# 043 — 유저 메모리 역할 스코핑: 두 직교 축 가드

스펙: `docs/spec/053-user-memory-role-scoping.md`
관련: [[042-user-memory-identity-scoped-enrichment-endpoint]](선행 052 신원 보강) ·
learning 054(이 회고의 일반화) · 050(연산 대칭) · 022/031(RBAC seam)

## 무엇을 / 왜

052에서 큐레이션 화면에 *신원 라벨*만 붙였는데, 정작 **접근**은 안 막혀 있었다 —
`/memory/user/{user_id}`(GET/PATCH/DELETE)가 general `_auth`만 걸려 **인증된 누구나 임의
user_id의 개인 메모리를 열람·수정** 가능했다(프라이버시 구멍). 사용자 요구:
"로그인한 본인 메모리만 기본, 어드민 롤은 타인도."

## 결정 (사용자 확인 2건)

1. 본인 기본 + 어드민은 타인(본인 것도 교정 가능, 읽기전용 아님).
2. "어드민 롤" = `memory:manage` 권한: 머신토큰(소유자)=어드민 등가, is_superuser=우회,
   Casbin `admin`(`*,*`)=enforce 통과. 기본정책이 이미 커버 → **새 시드 불요**.

`require("memory","manage")`를 직접 못 쓴 이유: 그건 `current_active_user`에 의존해
**머신 토큰을 401**로 막는다. 메모리 라우트는 쿠키 유저 + 머신 토큰 둘 다 받아야 하므로
(`current_principal`), 둘을 함께 다루는 인라인 헬퍼(`_can_curate_others`)로 판정했다.

## 핵심 설계 — 두 직교 축의 가드가 *합성*되어야 한다

- **주체×대상 축**(신규 `_assert_principal_may_access`): 비-어드민은 path `user_id`가
  자기 것일 때만 통과.
- **대상×행 축**(기존 `_assert_user_owns`): mem_id가 그 user_id의 기억에 속하는지.

둘 중 하나만으론 새는 자리:
- 주체 가드만 있으면 → member가 `DELETE /memory/user/{자기id}/{남의_mem_id}`로 path를
  자기로 *위조*해 남의 행을 지울 수 있다. 행 가드가 404로 막는다.
- 행 가드만 있으면(052 이전 상태) → 애초에 임의 user_id 열람이 열려 있다.
적대 타자가 정확히 이 path-spoof 합성을 점검 → 두 축이 함께 막음(PASS).

## capability는 권고, 강제는 서버

`GET /memory/users`가 `can_curate_others`를 내려 프론트의 드롭다운 노출을 정하지만,
**per-user 라우트는 이 플래그와 무관하게 독립적으로** `_assert_principal_may_access`를
재실행한다(defense in depth). 프론트를 무시하고 API를 직접 때려도 막힌다.

## 검증 사다리 (자가검증 지양 — 4 rung)

1. 단위: `verify_053`(인프라 불요, casbin enforce는 FakeEnforcer 주입) 14/14 — 주체 4종
   × self/other 매트릭스 + 누출-안전 필드.
2. 실인프라 통합: 실제 member 쿠키 로그인(curl 쿠키잡) → 타인 403·본인 200·
   `can_curate_others=false`·`users=[me]`. 머신 토큰=어드민 경로. _provision_super에
   `member` 모드 추가(비-super 시드).
3. UI 통합: 브라우저샷(self-fixture member+super) — member=드롭다운 0개·본인 패널,
   super=드롭다운 1개. 시각 확인까지.
4. 적대 타자(서브에이전트): 8점검(cross-read·path-spoof write·capability-vs-enforce·
   principal confusion·enforce fail-closed·누출·회귀·enumeration) 전부 PASS, 블로커 0,
   **fail-open 없음**(미초기화 enforcer는 RuntimeError→500=fail-closed).

## 배운 점 → learning 054

권한 가드는 한 축(주체)만 막으면 다른 축(행)에서 path 위조로 샌다 — **모든 직교 축에
가드를 두고 합성**해야 격리가 성립. 클라에 내린 capability는 UX 권고일 뿐, 강제는
모든 동사(GET/PATCH/DELETE)에서 서버가 독립적으로. 미초기화는 fail-closed인지 확인.

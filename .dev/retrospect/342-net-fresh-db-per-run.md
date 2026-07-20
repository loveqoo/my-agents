# 342 — 그물 fresh-DB-per-run 격리 하네스(스펙 414)

## 발단
세션 내내 `make test`가 **매 실행 다른 db 테스트를 red**로 냈다(137/140/141 → 124/130/131/158 …).
개별 격리(throwaway) 실행은 통과 → 공유 dev DB가 근본. [[net-runs-are-exclusive]]를 "규율"에서
"구조"로 옮기는 작업.

## 한 일
- `_throwaway_db.py`의 생성/부트스트랩/drop 로직을 `_dbharness.py`(`fresh_db()` 컨텍스트)로 추출(사본 0).
- `run_suite.py` db 그룹 전체를 `fresh_db(label="run")` 한 개로 감싸 — run당 virgin DB 1개(부트스트랩
  1회 상각), 45개 db 테스트를 그 DB env로 순차 실행, 그룹 끝나면 drop. dev DB 무접촉.
- 하네스가 노출한 결정적 red 4건을 자기완결로 수리(아래 교훈).

## 배운 것

### 1. 격리를 "구조"로 만들면 플레이크와 **암묵 의존**이 갈라진다
플레이크(124/130/131/137/140/141/158)는 공유 DB가 근본 → 격리 즉시 소멸. 하지만 같은 격리가
**결정적으로 red인** 4건을 드러냈다 — 공유 dev DB의 ambient 상태(부팅 테이블·부트스트랩 어드민)에
암묵 의존해 **그동안 우연히 통과**하던 테스트. "격리하면 플레이크만 사라진다"가 아니라, **격리는
숨어 있던 커플링을 결정적 실패로 승격**시킨다 — 그게 격리의 진짜 가치다(부채 가시화).

### 2. virgin 부트스트랩은 앱 **startup을 미러**해야 한다 — 단, startup만
`casbin_rule`은 alembic이 아니라 **앱 부팅 `init_authz()`**가 만든다. 부트스트랩이 init_db+seed만
하면 이 테이블이 없어 policy 쓰는 테스트가 "relation does not exist"로 죽는다. 해결=부트스트랩을
startup 순서(init_db → init_authz → seed)로 미러. **그러나 mem0 테이블은 startup이 아니라 런타임
lazy 생성**이라 부트스트랩에 안 넣는다 — 그 테이블을 쓰는 테스트가 **자기 setup서 확보**한다.
경계: "부팅 시 생기는 것"은 부트스트랩, "첫 사용 시 생기는 것"은 소비 테스트.

### 3. 연쇄 실패는 **첫 도미노**부터 — 잔재는 증상이다
verify_148이 "위반 ['v050 public', ...]"로 실패 → 범인은 verify_050이 남긴 에이전트. 근인은 148이
아니라 **050이 casbin 없음으로 중간 실패(생성 후 정리 전)해 잔재를 남긴 것**. init_authz 하나로
050이 완주·정리 → 148 연쇄 해소. 공유 run-DB에선 **한 테스트의 미완 정리가 다음 테스트를 오염**
시키므로, red 여러 개를 볼 땐 순서상 첫 실패부터 고친다(뒤엣것은 앞엣것의 증상일 수 있다).

### 4. seed는 유저 0행이 **정직한 virgin** — 유저는 테스트가 만든다
prod엔 `seed_admin()`이 ADMIN_EMAIL env로 부트스트랩 어드민을 만들지만, env 미설정이면 스킵.
virgin DB의 정직한 상태는 "유저 0행". keep-list가 보호하는 `admin@/alice@example.com`도, `_alive()`가
집던 live 유저도 전부 ambient였다. 유저 필요한 테스트는 **멱등 자가 생성**(있으면 no-op, 없으면
심고 정리) — dev DB 재실행과 virgin DB 양쪽서 안전.

### 5. 안전 테스트는 격리보다 **자기완결 수리** 우선
[[regression-net-quarantine-not-fix-all]]의 기본값은 "노출된 드리프트 명시 격리"지만, 삭제정리·
메모리고아는 **안전 테스트**라 격리 시 coverage가 조용히 준다. 결정적 실패(플레이크 아님)이고 수리가
싸므로 자기완결로 살렸다. 판단축: 플레이크면 격리, **결정적 실패 + 안전 테스트 + 싼 수리면 고친다**.

## 자산화 후보(관련)
[[net-runs-are-exclusive]] [[regression-net-quarantine-not-fix-all]] [[verification-ladder-three-rungs]]
[[whole-fix-over-minimal-patch]] [[compounding-vs-latent-axis]]

# 039 — 파괴적 데이터 정리 + 재생성 뿌리 차단 회고 (스펙 050)

마스터 044의 마지막 배치(배치6). 테스트가 쌓은 정크(#1 A2A·#11 세션·#13 유저)를 청소하고,
**정크를 매번 다시 만드는 뿌리**를 끊었다. 비가역·파괴 경로라 적대 리뷰를 두 번 받았다.

## 무엇을 했나 (2 Phase)
- **Phase 1(기능)**: `a2a-cleanup`·`user-cleanup` 배치 잡 + admin UI. learning 037 "파괴 노브엔 바닥"을
  3겹으로(패턴 NULL→disabled, `%`/빈→거부, keep-list, 마지막 super 보호).
- **Phase 2(즉시 1회 정리)**: **dry-run→사용자 검토 게이트→실행**. A2A 9 + 세션 9 cascade, 유저 5(좁은
  패턴 3회), 세션 130→3. 마지막 super 보호가 실제로 작동(admin@ 1개 생존).
- **Phase 3(재생성 뿌리)**: 공용 provisioner + probe/shot self-fixture화 + **가장 깊은 뿌리**(서버 env로
  verify032 재시드)를 config층에서 차단.

## 무엇이 어려웠나 / 무엇을 배웠나

### 1. 행을 지워도 발생원이 살아있으면 정크는 돌아온다 (→ learning 049)
Phase 2에서 verify032 유저를 지웠는데 **다시 생겼다**. `ps eww`로 추적하니 실행 중 api 서버의 env에
`ADMIN_EMAIL=verify032`가 박혀 있어 매 `--reload`마다 seed_admin이 재생성하고 있었다. 어떤 커밋 파일에도
없는 셸 `export`였다. **삭제(행)는 증상이고, 발생원(env)이 원인.** config층(`.env.example`/`.env`)을 고쳐
재발을 끊었다 — DB 행을 백번 지워도 발생원을 안 끄면 무의미했다. 이게 050이 "재생성 뿌리"를 명시 목표로
둔 이유이기도 하다(스펙 §1).

### 2. 파괴 헬퍼의 delete만 막고 create를 열어두면 대칭 위협이 샌다 (→ learning 050)
provisioner의 `delete`는 keep-list·prefix로 단단히 막았는데, 적대 리뷰가 `create`의 EXISTS 분기를 짚었다:
`create("alice@example.com")` → 실계정 alice를 **super로 승격**. is_superuser=True는 authz.require가 casbin을
통째로 우회하는 권한이라, "실계정 삭제 금지"와 "실계정 super 승격 금지"는 **같은 등급의 위협**이다. delete만
가드한 건 대칭 위협의 비대칭 방어였다. create에도 `_disposable` 가드를 걸어 대칭화했다.

### 3. 적대 리뷰는 글자대로 다 고치지 않는다 — 블래스트 반경으로 분류한다
2차 적대 리뷰가 7건(C1·H1·H2·M1·M2·M3·L1)을 올렸다. [[probe-deeper-before-concluding]]대로 코드와 대조해
**진짜 결함 3(C1·H1·H2)만 수정**, 나머지는 채무로 §7에 명시 기록했다. M1(last-super)은 admin@가 구조적으로
생존하므로 수용, L1(password argv)은 throwaway @example.com 크레덴셜(실비밀 아님)이라 수용. 036 회고의
"Low 지적 글자대로 고치다 버그 낼 뻔"과 같은 교훈 — 적대자의 가치는 *목록*이지 *처방*이 아니다.

## 검증 사다리 (3 rung 다)
- **단위 시맨틱**: provisioner 8/8 가드 케이스(정상 생성·삭제, 대소문자 정규화 멱등, alice@/admin@ 승격 거부,
  비-example 도메인 거부, keep-list 삭제 거부).
- **실인프라 통합(self-fixture)**: shot-batch-050이 라이브 fixture 경로로 완주(PROVISION_OK→샷→DELETED→residue 0).
- **적대 리뷰 2회**: Phase 2 출하 전 1회(BLOCKER 0) + Phase 3 헬퍼 1회(진짜 결함 3건 적발→수정).

## 자산화
- learning 049(재생성 소스 vs 행), 050(형제 연산 가드 갭). self-fixture는 045가 이미 명명(이번이 4번째 적용).
- 채무: §7에 산술적 last-super·SIGKILL 고아·mem0 미정리·서버 재기동 액션아이템 등 명시.

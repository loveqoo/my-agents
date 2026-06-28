# 050 — 파괴적 데이터 정리(dry-run) — #1 A2A 정크 · #11 세션 정크 · #13 유저 정크

마스터 044 배치6(마지막 기능 배치). 테스트가 쌓은 정크를 **dry-run→사용자 검토→실행**으로 청소하고,
**재생성 뿌리**(테스트가 매번 새 정크를 남김)를 self-fixture로 끊는다. 파괴적·비가역 → 적대 리뷰 필수.

## 결정 (사용자 합의 2026-06-28)
1. **표면**: 재사용 배치 잡 + admin UI **그리고** 즉시 1회 정리(둘 다).
2. **재생성 뿌리 차단**: 정크를 만드는 verify/shot 스크립트에 **자가정리** 추가(learning 045/049 self-fixture 전면화).
3. **유저 삭제**: 테스트 유저 5명 **전부** 삭제(verify032 포함) + 브라우저샷을 **self-fixture화**(자체 테스트 계정 생성→끝에 삭제).

## 라이브 현황 (2026-06-28 측정, 읽기 전용)
- **A2A(#1)**: 에이전트 12 = code 1·ui 2(데모, 보존) + **external 9**(전부 `agt_a2a_*` "Probe A2A *",
  endpoint=127.0.0.1:8142 또는 10.0.0.5:9999 = 루프백/사설 = 테스트 프로브). → 정크 9.
- **세션(#11)**: 130 = playground 126(turns 0~2)·실세션 4(A2A·web-chat·debug, turns 3+). → 049 `session-cleanup`로 청소.
- **유저(#13)**: 7 = 보존 2(admin@ 실 super, alice@ 데모) + **테스트 5**(verify032·admin041·member041·admin041i·admin042i).

## 정크 식별 규칙 (보수적·dry-run 게이트·learning 037 바닥)
파괴 작업은 **실행 지점에 바닥**을 깐다 — 규칙이 절대 전체로 번지지 않게.

### A2A 정리 잡 `a2a-cleanup`
- 대상: `source='external'` **AND** endpoint 호스트가 루프백/RFC1918 사설(127.* · localhost · ::1 · 10.* ·
  192.168.* · 172.16~31.*). 실 A2A 파트너는 공개 endpoint라 절대 안 걸린다.
- 바닥: `source` 비‑external(ui/code)은 **절대** 손대지 않음(규칙에 source 고정). endpoint 없으면(NULL) 제외.
- cascade: Agent 삭제 → 그 에이전트의 `sessions`(agent_pk FK ondelete CASCADE)·`agent_versions`도 DB가 정리.
  dry-run에 딸린 세션 수를 함께 표기(무엇이 같이 죽는지 정직히).

### 유저 정리 잡 `user-cleanup` (가장 비가역 → 바닥 3겹)
- 대상: 이메일이 **config 패턴**(`test_user_email_pattern`, SQL `LIKE`) 일치 AND **keep-list 제외**.
- 바닥(learning 037):
  1. 패턴 NULL → **disabled no-op**(명시 설정 전엔 절대 삭제 안 함). 패턴 `%`/빈문자 → **delete-all 가드로 거부**.
  2. **하드코딩 keep-list**(`admin@example.com` 부트스트랩, `alice@example.com` 데모)는 패턴 일치해도 제외.
  3. **마지막 슈퍼유저 보호** — 삭제 후 super가 0이 되면 그 super는 남긴다(잠금 방지).
- cascade·정합성: User 삭제 → `accesstoken`(user_id FK CASCADE). `sessions.user_id`는 plain String(FK 아님) →
  고아 문자열은 무해(049 정책상 곧 정리). **Casbin grouping/policy(`casbin_rule`)**의 그 유저 grant는
  dangling → 같은 트랜잭션에서 제거(learning: dangling 권한 누수 방지). mem0(user_id 축)는 별 저장소 →
  이번 범위 밖(debt §7).

### 세션 정리 `session-cleanup` (신규 잡 없음 — 049 재사용)
- 126 playground 정크는 049 잡의 `min_session_turns`로 청소(idle>IDLE_GUARD라 활성 보호 유지).

## 변경 파일 (계획)
- **`batch/jobs.py`**: `cleanup_a2a_agents`·`cleanup_test_users` 추가 + JOBS 등록(키 `a2a-cleanup`·`user-cleanup`).
  공통 dry-run/execute 형태(`{status, ...meta, would_delete, sample}` / `{status:ok, deleted}`) 유지.
- **`models.py` + alembic**: `BatchConfig.test_user_email_pattern: str|None`(default None) 추가.
- **`batch_routes.py`**: BatchConfigIn/Out에 `test_user_email_pattern` + 패턴 delete-all 가드(`%`/빈 거부).
- **`admin/src/api.ts` + `BatchView.tsx`**: 패턴 필드 + a2a-cleanup·user-cleanup dry-run/실행 패널(세션과 동형).
- **즉시 1회 정리**: 잡을 dry-run→**사용자 검토**→실행으로 운용(별 스크립트 불필요). A2A 9·세션 126·유저 5.
- **테스트 위생(Phase 3)**: A2A 프로브/유저를 만드는 verify·shot 스크립트에 try/finally 자가정리 추가.
  브라우저샷(shot-batch-038 등)은 전용 super 계정을 만들고 끝에 삭제(self-fixture).

## 검증 (자가 + 타자)
1. **잡 단위·통합(self-fixture)**: `a2a-cleanup`/`user-cleanup` 각각 — self-fixture(외부 프로브 에이전트·
   테스트 유저 prefix)로 시드 → dry-run would_delete 정확·sample, 실행 삭제·cascade(세션/accesstoken/casbin),
   바닥(패턴 NULL→disabled, `%`→거부, keep-list 보존, 마지막 super 보존), 멱등. **적응형 파괴안전**(비-fixture
   매치 시 실삭제 생략, 049 패턴).
2. **API ge/가드**: 패턴 `%`·빈 → 422. NULL 허용(비활성).
3. **프론트**: `tsc` 0. 브라우저: 신규 패널 렌더·dry-run 토스트(실행 버튼은 검토 후).
4. **즉시 정리 검토 게이트**: 실 삭제 전 dry-run 리스트를 사용자에게 제시(마스터 044 "사용자 검토" 준수).
5. **타자(적대 서브에이전트)**: 패턴이 전체 유저로 번지나? 마지막 super 삭제로 잠금? cascade가 실데이터(실
   세션·실 grant) 끌어가나? endpoint 파싱이 공개 호스트를 사설로 오판? keep-list 우회?
6. **회귀**: 049 `session-cleanup`·038 불변(verify_038/049 ALL PASS). 테스트 위생 후 정크 0 재생성 실증.

## 실행 결과 (2026-06-28)
- **Phase 2 (즉시 1회 정리, 검토 게이트 통과)**: dry-run 제시→사용자 "전부 실행" 승인 후 —
  A2A external 9 + cascade 세션 9, 테스트 유저 5(좁은 패턴 3회: verify%·admin04%·member04%),
  세션 130→3. 검증: admin@+alice@만 잔존, external 0, casbin dangling 0, **마지막 super 보호 유지**
  (super 1=admin@), config 비활성 복원. 5번(적대) BLOCKER 0.
- **Phase 3 (재생성 뿌리 차단)**: 공용 provisioner(`tests/_provision_super.py`) + probe_042 자가정리 +
  브라우저샷 11종 self-fixture화(`_fixture.mjs`) + **가장 깊은 뿌리**(dev 서버 env `ADMIN_EMAIL=verify032`
  매 --reload 재시드)를 `.env.example`/`.env` config층에서 차단.
- **Phase 3 적대 리뷰(2차)**: provisioner의 진짜 결함 3건 수정 — (H1) create EXISTS가 실계정을
  super 승격시키던 에스컬레이션 → create도 `_disposable` 가드(거부 exit2); (H2) `probe`/`verify` prefix가
  구분자 없어 `@corp.com` 실계정 삭제 가능 → **`@example.com`(RFC 예약 테스트 도메인) 게이트**;
  (C1) create=대소문자무시/delete=대소문자민감 비대칭 → 양쪽 `.strip().lower()` 정규화. 8/8 가드 테스트 통과.

## §7 빚·한계
- **마지막 super 보호는 *산술적*(count 기반)이다** — "삭제 후 super 0이면 남김"은 *어느* super가 남는지
  보장하지 않는다(learning 048 계보의 WHEN 축 잔여). 현 키워는 admin@가 비-던짐이라 구조적으로 항상
  생존하지만, 정체성 기반 보장(특정 부트스트랩 계정 핀)은 미구현.
- **provisioner SIGKILL 고아**(적대 M3 잔여): `-9`는 잡을 수 없어 `shotfix_*@example.com` super가 남을 수
  있음. 단 매 실행 랜덤이라 누적만·비자기증식, `user-cleanup` 잡으로 일괄 청소 가능. SIGHUP까지는 핸들러로 덮음.
- **probe_042 teardown 부분 실패**(적대 M2): 단일 commit이라 throw 시 롤백되나, commit 자체의 트랜지언트
  실패 시 던짐 super 잔류 가능. teardown 재시도·검증 카운트 미구현(테스트 전용이라 수용).
- **password argv 노출**(적대 L1): `ps`에서 create의 비밀번호 보임. 단 throwaway @example.com 테스트
  크레덴셜(실비밀 아님). stdin/env 전달은 미적용(수용).
- **probe_042 고정 PORT 8142**(적대 L3): 동시 2회 실행 시 포트 충돌(가용성 nit, 데이터 무손상).
- **mem0 user_id 축 미정리**: 삭제 유저의 mem0 메모리는 별 저장소라 이번 범위 밖(별도 정리 필요).
- **`sessions.user_id` 고아 문자열**: FK 아님(plain String)이라 삭제 유저의 세션 user_id는 잔류 — 무해하며
  049 정책으로 곧 청소.
- **실행 중 서버 상태**: verify032 삭제를 영구화하려면 실행 중 api 서버를 `export ADMIN_EMAIL=verify032`
  없는 셸에서 **재기동**해야 함(config는 고쳤으나 살아있는 프로세스 env는 못 바꿈). 사용자 액션 아이템.

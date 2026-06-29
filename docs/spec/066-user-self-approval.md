# 066 — 유저 self-승인: permission 기반 RBAC 3-way 승인 권한

## 배경 / 문제
현재 "승인"(HIL 게이트, spec 041)은 두 겹으로 거칠다:
1. **승인 주체가 admin 전용** — 위험 도구가 그래프를 멈추면 `Approval(pending)`이 생기고,
   resolve는 `authz.require("approvals","resolve")`(superuser/admin/머신)만. 채팅하는 본인은
   자기 세션 위험 행동도 스스로 승인 못 한다(admin 대기).
2. **action 종류/RBAC 구분이 0** — 모든 위험 도구가 같은 큐·같은 게이트로 간다.
   각 Approval은 이미 `permission`("data.delete")을 들고 있지만(`runtime.py:101` interrupt
   payload→`chat.py:650`), 이 값은 **승인 카드 표시용**일 뿐 **인가에 전혀 안 쓰인다**.
   그리고 Approval 행엔 **요청 주체(user_id)가 기록조차 안 된다** → self-승인 자체가 불가능.

"승인 필요" 판정도 RBAC가 아니라 `runtime.py:32` 하드코딩 dict `_APPROVAL_ACTIONS`
(`("local-tools","delete_record")→"data.delete"` 단일).

## 목표 (사용자 결정: RBAC/민감도 기반 3-way)
승인 권한을 **action의 `permission` + RBAC**로 분할한다:
- **admin/머신** → 무엇이든 승인.
- **owner**(요청 주체 본인) → 자기 것 중 **그 permission이 self-승인 허용된 것만**
  (`enforce(user, permission, "self_approve")`).
- **그 외**(민감 permission, 예: `data.delete`) → owner여도 **admin 필수**.
- 기본 정책 **fail-closed**: self-승인 허용 집합은 *비어 있음* — 명시적으로 정책에 넣은
  저위험 permission만 self-승인. `data.delete`는 admin 전용으로 남는다.

## 비목표
- "승인 필요" 판정 자체를 RBAC/빌딩블록으로 옮기기(`_APPROVAL_ACTIONS` 동적화) — 별개 작업.
  본 스펙은 *이미 표시된 permission*을 *승인 권한 인가*에 연결하는 데 한정.
- admin 화면 요청자 신원(email/이름) 라벨 — 추후(spec 052 패턴, over-coupling 주의 learning 053).
  v1은 user_id 보유까지, 라벨은 빚.
- 도구별 다중 동시 승인 — 기존 단일 interrupt 제약(041 §7) 유지.

## 위협 모델 (위험 도구 실행 인가를 넓히는 보안 경로 — 타자 적대 필수)
- T1 **교차 유저**: A가 B의 approval resolve → 거부(owner 일치만).
- T2 **NULL-owner 탈취**: 레거시/머신 발(user_id=NULL)을 일반 유저가 주장 → 거부.
  **owner 매칭은 `user_id is not None` 필수**(fail-closed).
- T3 **user_id 위조**: 비교는 *서버가 쥔* `current_principal` 대 *DB의 user_id*로만(요청 본문 무관).
- T4 **머신 토큰**: owner급 전체 접근(spec 011/031) → 전체 resolve 허용.
- T5 **TOCTOU**: 인가↔원자 UPDATE 경쟁 → 기존 `WHERE status='pending'` 원자 가드 유지(041).
- T6 **permission 위조/누락**: owner self-승인 판정은 *DB의 `approval.permission`*으로만 enforce
  (클라가 못 바꿈). permission이 빈 문자열/미등록이면 self_approve 정책에 매칭 안 됨 → admin 필수
  (fail-closed). 즉 **알 수 없는 권한은 self-승인 불가**.
- T7 **정책 부재 시 개방 금지**: enforce가 false/미초기화면 owner 분기는 **거부**로 닫힌다
  (member에 self_approve 정책 없으면 전부 admin 필수, 회귀로 핀).

## 설계
### D1 — 데이터 모델: `Approval.user_id`
- `Approval`에 `user_id: Mapped[str | None]`(String(80), nullable, default None) — 요청 주체
  auth User UUID(str). **NULL = 머신/레거시 = admin 전용**(owner-resolvable 아님).
- 비-FK 평문(코드베이스 user_id 축 관례, spec 032; `session_id`도 비-FK). 마이그레이션
  add column nullable, **백필 없음**(레거시 NULL = fail-closed). create_all 폴백이 fresh 커버.

### D2 — 승인 생성 시 요청 주체 기록 (단일 지점)
- `_create_approval(ctx, thread_id, payload, user_id)` 파라미터 추가 → `Approval(user_id=...)`.
- 호출부(`chat.py:572`)에서 이미 도출된 `user_id`(line 472: `str(principal.id)` 또는 머신=None) 전달.
- 단일 생성 경로 확인: A2A `_a2a_stream`=원격(로컬 미생성), 노출 `stream_local_reply`=HIL 미적용
  순수컴퓨트(spec 061) → 승인 생성은 main `chat()` 단일.

### D3 — resolve 인가: 3-way (`_assert_may_resolve`)
- `_require_admin` 블랭킷 제거. resolve에 `principal=Depends(current_principal)` 주입.
- approval **먼저 조회**(없으면 404) 후 `_may_resolve(approval, principal)`:
  1. `principal == "machine"` → 허용(T4).
  2. `User` and (`is_superuser` or `enforce(str(id),"approvals","resolve")`) → 허용(admin).
  3. `User` and `approval.user_id is not None` and `approval.user_id == str(id)`
     and `approval.permission` and `enforce(str(id), approval.permission, "self_approve")`
     → 허용(owner+RBAC, T1/T2/T3/T6).
  4. else → 403.
- **열거 오라클 차단(적대리뷰 Low#1)**: `_may_resolve` *앞에* 가시성 게이트 — 비-admin(`_own_scope`≠None)이
  *볼 수 없는* 행(자기 것 아님·NULL-owner)은 부재와 동일하게 **404**. 안 그러면 approval_id 추측으로
  404↔403을 갈라 타인 행 존재가 샌다(목록은 이미 스코핑돼 안 보이는데 resolve가 새는 격). 단 *자기*
  행이지만 권한 미달(민감 perm)은 **403** 유지(이미 자기 목록에 보여 존재는 알려진 상태).
- 이후 기존 원자적 조건부 UPDATE 그대로(T5·409 무회귀). 재개(`resume_approval`)는
  주체와 무관하게 동일(승인되면 도구 실행).

### D4 — Casbin 정책: `self_approve` act + 기본 fail-closed
- rbac_model.conf는 이미 `enforce(sub,obj,act)` 일반형 → **모델 파일 변경 불필요**(act 축 그대로).
- 기본 정책(멱등 시드): **self_approve 정책 0개**(self-승인 허용 집합 비어 있음 = fail-closed).
  `data.delete`는 어디에도 안 넣음 → 영구 admin 전용.
- member 역할 배선 확인: 일반 유저가 self_approve 정책의 sub로 매칭되려면 role 그룹이 필요.
  실행 단계에서 (a) 신규 유저 member role 할당 여부 확인, (b) 저위험 permission을 self로 열려면
  `(member, <perm>, self_approve)` 정책을 *명시 추가*해야 함을 문서화. v1 기본은 비움(저위험
  도구가 아직 없음 — data.delete 단일). **owner 분기는 인프라로 완성하되 기본 노출은 0**.

### D5 — list 스코핑: 본인 / 전체
- `list_approvals`에 `principal=Depends(current_principal)`.
  - 머신 or admin → 전체(현행).
  - 일반 User → `WHERE user_id == str(id)`(본인 것만, NULL-owner 숨김).
- 사이드바 배지(pendingCount)는 이 list 사용 → 유저별 자동 스코핑.

### D6 — 프론트(최소)
- 승인 메뉴 일반 메뉴 유지(일반 유저=자기 큐). owner+self_approve면 resolve 버튼 동작,
  민감 permission이면 서버 403(방어적 유지). (빚) admin 요청자 신원 라벨·"admin 필요" 배지 추후.

## 검증 사다리 (비겹침 — 보안 경로라 적대 codex 필수)
- **단위/라이브**(`verify_066_*`):
  - owner+self_approve 허용 permission → 200 + 재개 (정책 시드한 테스트 permission으로 owner 분기 실증).
  - owner지만 **민감 permission(data.delete)** → **403**(핵심: RBAC 구분 작동).
  - owner가 타인 것 → **404**(T1, 존재 은폐) / NULL-owner → **404**(T2, 존재 은폐) / permission 빈값·미등록 → 403(T6).
  - admin 전체 → 200 / 머신 전체 → 200(T4).
  - list 스코핑(A는 A것만·admin 전체) / 이중 resolve → 409(T5) / req body user_id·permission 무시(T3/T6).
  - 정책 부재 시 owner 분기 거부(T7).
- **브라우저**(`shot-user-approval-066`): 일반 유저가 self-허용 action은 본인 resolve, data.delete는
  버튼 막힘/403 표시.
- **적대 codex**: 권한 상승(위조 user_id/permission·NULL 탈취·교차유저·머신 의미·인가↔UPDATE 경쟁·
  정책 부재 개방·열거). installed-guard / verification-ladder / adversarial-before-destructive.

## 완료 조건
- [x] D1 `Approval.user_id` + 마이그레이션(백필 없음). — `models.py`, alembic `e1f2a3b4c5d6`(라이브 적용 확인).
- [x] D2 승인 생성이 요청 주체 기록(단일 지점). — `chat.py` `_create_approval(user_id)`.
- [x] D3 resolve 3-way(admin/머신·owner+self_approve·그 외 403), 민감 permission은 owner여도 admin 필수. — `approvals.py` `_may_resolve` + 가시성 404 게이트.
- [x] D4 self_approve act 인가 + 기본 fail-closed(data.delete admin 전용), member 배선 확인. — `authz.can_self_approve`, `_DEFAULT_POLICIES` self_approve 0개.
- [x] D5 list/배지 스코핑. — `list_approvals` `_own_scope`(라이브 L1~L3 실증).
- [x] D6 프론트 owner resolve 동작·메뉴 유지(무변경). — 기존 `httpError`+`message.error`가 403 detail 노출(브라우저 rung 실증).
- [x] 검증 4 rung(단위·라이브·브라우저·codex 적대), 특히 "owner+data.delete→403" 핀.
  - 단위 `verify_066_resolve_authz.py`(24/24), 라이브 `verify_066_live.py`(15/15), 브라우저 `shot-user-approval-066.mjs`(PASS), codex 적대 **VERDICT: PASS**(Low#1 열거 오라클 → 가시성 404 게이트로 수정·재검증).

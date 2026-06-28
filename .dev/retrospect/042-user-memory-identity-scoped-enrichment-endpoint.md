# 042 — 유저 메모리 큐레이션, 신원을 스코프 엔드포인트로 보강

스펙: `docs/spec/052-user-memory-identity-in-curation.md`
관련: [[051-agent-memory-scoping-cut-the-llm-write-channel]](선행 메모리 작업) ·
learning 053(이 회고의 일반화) · [[018? installed-guard]] 권한 결합 점검

## 무엇을 / 왜

증상: 어드민 "유저 메모리" 큐레이션 화면이 유저를 **raw UUID**(`276e5f67-…`)로만
라벨링한다. 관리자가 "누구의 메모리를 고치는지" 식별 불가. 유저 메모리(user_id 축)는
세션에서 파생된 user_id(스펙 032: 로그인 유저 UUID)로만 조회되기 때문.

수리: distinct user_id에 등록 유저 신원(email·display_name)을 붙이는 `GET /memory/users`를
**메모리 라우터에** 추가. 드롭다운 옵션·패널 헤더를 이메일(있으면 이름 병기)로 식별,
UUID는 보조 병기(dim). 미등록 user_id는 `(미등록) <uuid>` graceful fallback.

## 함정 — 편의상 고권한 엔드포인트 재사용

이메일은 이미 `/admin/users`(user_admin.py)에 있다. 프론트에서 `listUsers()`를 불러
user_id→email 매핑하면 "끝"처럼 보인다. **하지만** `/admin/users`는 `users:manage`
(슈퍼유저) 게이트다. 반면 어드민 콘솔 "메모리" 메뉴는 **모든** 어드민에게 열린다
(AdminShell.tsx에서 "유저"·"배치" 메뉴만 is_superuser 게이트). → 비-슈퍼유저
관리자에겐 그 호출이 403 → 드롭다운이 통째로 비고, 메모리 큐레이션이 *유저-관리 권한*에
조용히 결합된다. 기능의 권한 등급이 의도(`_auth`)보다 올라가 버린다.

처방: `/admin/users`를 건드리지 않고, 메모리 라우터(general `_auth`로 마운트)에
**필요한 것만 JOIN**하는 스코프 엔드포인트를 새로 둔다. email·display_name 외엔
반환 안 함 → response_model(`MemoryUserOut`)로 누출-안전을 *구조적*으로 강제
(hashed_password·is_superuser가 손수 dict에 실수로 늘어도 경계에서 잘림).

## 검증 사다리 (자가검증 지양)

- 단위/타입: backend import OK, `tsc --noEmit` exit 0, `curl` 200 + 정확히 3필드.
- 브라우저(타자 대신 실클라 1회 — learning 051): `shot-memory-users-052.mjs`,
  self-fixture super 시드(스펙 050 Phase 3). DROPDOWN_OPTIONS=`["admin@example.com"]`,
  PANEL_HEADER가 이메일+UUID(dim) 병기. LABEL/HEADER_HAS_EMAIL 둘 다 OK.
- 적대 타자(서브에이전트): 6점검(라우트충돌·권한결합·Playground회귀·매핑·null·프론트)
  전부 PASS, 블로킹 0. 비블로킹 2건 즉시 반영 → (1) 죽은 `optionFilterProp="label"`
  제거(filterOption 함수 있으면 antd가 무시), (2) `response_model` 추가로 누출-안전
  격상. 둘 다 재검증(200·정확3필드·tsc OK).

## 짚은 latent risk (현재 버그 아님)

매핑 `by_id = {str(u.id): u for u in users}`는 쓰기경로(chat.py `str(principal.id)`)와
읽기경로가 동일하게 `str(UUID)`(정규 소문자-하이픈)라서만 성립. 미래에 비-`str(UUID)`
소스(대문자·스펙021식 자유입력 user_id)가 들어오면 조용히 miss→"(미등록)". 잠재 결합.

## 배운 점 → learning 053

저권한 뷰를 고권한 소스의 *신원*으로 보강할 때, 편의상 고권한 엔드포인트를 재사용하면
기능의 권한 등급이 조용히 올라간다. 절단면은 "이 화면이 실제로 요구하는 최소 권한"에
긋고, 그 등급에서 *필요한 컬럼만* JOIN하는 스코프 엔드포인트를 새로 둔다.

# 273 — authz 스코프 + LIKE-escape 정본화 (스펙 298)

## 무엇을 했나
census(deep-reasoner 전수)로 랭크한 dedup 후보 중 **최저위험 2건**을 정본화:
- **A. LIKE-escape** (3중 바이트 동일: sessions `_like_escape`·eval_common `_ilike_literal`·mem0_backend
  인라인) → 신설 `sqlutil.like_escape(term)`(의존 0 순수 함수).
- **B. authz 스코프 트리오** (2중): `_agent_id_map`(동일)→`serializers.agent_id_map`,
  `_is_admin`((obj,act) 튜플만 차이)→`authz.is_admin_for(principal, obj, act)`, `_own_scope`(동일)→
  `authz.own_scope(principal, obj, act)`. 호출부가 자기 튜플 명시(sessions=`("sessions","read")`,
  approvals=`("approvals","resolve")`, chat=`("sessions","read")`) → **라우터 독립 보존, 골격만 단일화**.

## 배운 것 / 복리 포인트

- **"본문 공유 여부"가 dedup 판별의 정답**(retrospect 268 재확인). `_is_admin`은 시그니처가 같아 보이나
  본문이 (obj,act) 튜플 하나만 달랐다 — 그 차이를 *호출부가 넘기는 인자*로 뽑으니 "라우터 독립"(sessions.py
  옛 주석의 의도)이 그대로 보존되면서 골격이 단일화됐다. **주석의 의도("공유 안 함")를 액면 그대로 믿지
  말고 본문을 대조**하라 — 실제로는 파라미터화 가능한 중복이었다. → [[whole-fix-over-minimal-patch]]

- **크로스모듈 private import가 dedup 신호**. `rag→sessions._like_escape`·`chat→sessions._own_scope`처럼
  한 route 모듈의 `_private`을 다른 route가 끌어 쓰면, 그건 "이 헬퍼는 사실 공용인데 잘못된 집에 산다"는
  냄새다. 정본 홈(sqlutil/authz)으로 옮기면 절감(작음)보다 **경계 정합**이 진짜 이득. → [[structure-first-boundary-is-spec]]

- **놓친 시임 = 몽키패치만이 아니라 "모듈 속성 직접 참조"**(retrospect 270 monkeypatch-seam 확장).
  사전 시임 grep을 `monkeypatch|setattr|patch(`로만 걸어 **단위 verifier가 `S._is_admin(machine)`처럼
  심볼을 직접 호출**하는 걸 놓쳤다(verify_067/066). 심볼을 지우면 즉시 AttributeError. **시임 전수는
  "이 심볼 이름이 테스트에 문자열로 등장하나"로 넓게** 걸어야 한다(import·monkeypatch·직접호출 다 포함).
  수선은 정본 위치로 갱신(verify_067→`authz.is_admin_for(·,"sessions","read")`). → [[move-breaks-references-both-directions]]

- **적대 검증이 인접 잠복 결함을 덤으로 잡는다**(검증 사다리의 값). codex가 dedup 정합(여집합)을 확인하다
  `end_session`(mutating)이 read-scope를 쓰는 **기존 결함**을 짚었다 — 내 회귀는 아니나(pristine HEAD 동일,
  298은 시맨틱 보존), 스펙 209 F1이 feedback엔 넣은 write-scope를 end엔 안 넣은 잠복 불일치. **단순
  `_own_scope_write` 스왑 불가**(end는 machine 토큰 허용, write-scope는 `str(principal.id)`라 machine서
  깨짐) → machine-aware 설계 필요, 스펙 299로 분리(행위 변경이라 298 "행위 보존" 밖). 정직하게 이월.
  → [[use-codex-for-adversarial-verification]] [[adversarial-review-before-destructive-ship]]

## 검증 (사다리 3런)
- **단위/게이트**: metrics-fast 0(sqlutil.py 추가로 106 파일). 로컬 정의 0·크로스모듈 private import 0·
  LIKE-escape 원본은 sqlutil만.
- **실인프라 통합**: verify_066(승인 인가 3-way)·067(세션 스코프 M1/M2)·112(소유권)·147(가시성)·177(도구
  승인) PASS. 스위트 51/51(실패 0, flaky 1 재시도 통과).
- **적대(codex)**: 여집합 6축 — 핵심 호출부 튜플 라우터별 정확(sessions=read·approvals=resolve)·own_scope
  시맨틱 바이트 동일·`_own_scope_write`/`_may_resolve` 존치·mem0 strip 순서 보존·순환 import 0 확인.
  인접 발견(end_session)은 위 참조.

## 남은 것 (backlog)
- 스펙 299: `end_session` write-scope 정합(machine-aware) — codex 인접 발견.
- dedup 후속 C(eval llm_cfg)·D(eval `_execute_*` 배경작업, 최대 절감이나 락 lifecycle 위험).
- eval_* 내부 중복 미전수·stale verifier 일괄 갱신.

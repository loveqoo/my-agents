# 274 — end_session 쓰기 스코프 정합 (스펙 299)

## 무엇을 했나
스펙 298 codex 인접 발견을 정정: `POST /sessions/{id}/end`(mutating)가 읽기 스코프
(`own_scope(·,"sessions","read")`)를 유일 인가로 써서, `sessions:read` 운영자가 타인 세션을 종료할 수
있던 결함. `authz.own_scope_write(principal)` 신설(옛 sessions._own_scope_write 승격 + machine 분기)로
3개 write 라우트(end + feedback PUT/DELETE)를 정본화.

## 배운 것 / 복리 포인트

- **인접 발견을 좁게 고치지 말고 census부터**. codex는 `end_session` 하나만 짚었지만, 고치기 전에
  sessions.py write 라우트를 전수해 "같은 패턴이 또 있나"를 확인했다(feedback은 이미 정상, approvals
  resolve는 own_scope가 404-fold용이고 실제 게이트는 `_may_resolve`라 정상). **버그가 하나로 격리됨을
  측정으로 확인**한 뒤 고쳐야 "하나 고치고 옆에 남은 쌍둥이"를 안 만든다. → [[context-control-propagates-to-affordances]]

- **읽기/쓰기 스코프는 다른 권한 축**(스펙 209 F1 재확인). `own_scope`는 (obj,act)-read admin에게 무스코프를
  주지만, 쓰기는 그 read 권한이 넓히면 안 된다 — **읽기 권한이 쓰기를 넓히는 것 자체가 권한 상승**.
  end가 상태를 바꾸는데 read-scope를 쓴 게 정확히 그 함정. write-scope는 superuser/machine만 전체.
  → [[gate-on-intent-value-not-mutable-baseline]]

- **정본화(298)의 기계 치환이 잠복 버그를 "동결"했다 — 그게 오히려 발견을 도왔다**. 298이 모든
  `_own_scope(principal)`을 무차별 `own_scope(·,"sessions","read")`로 바꾸며 end의 read-scope를 그대로
  보존(회귀 0)했고, 그 정직한 보존 위에서 codex가 "이 write가 왜 read-scope?"를 깨끗이 짚었다. **정본화는
  버그를 고치지 않지만 드러나게 한다**(흩어진 복붙이면 이 한 곳만 보고 판단 못 함). → [[whole-fix-over-minimal-patch]]

- **machine 센티널이 스왑을 막는 실제 제약**. 옛 `_own_scope_write`는 `_require_user`(machine 배제) 뒤라
  `str(principal.id)`가 안전했지만, end는 machine을 허용해 그대로 못 썼다(str "machine"에 `.id` 없음).
  승격 시 **machine 분기(→None 전체)를 먼저** 넣어야 했다. 소비처가 하나 늘 때 그 소비처의 전제
  (machine 허용)가 헬퍼 전제(User 전용)와 어긋나는지 확인. → [[installed-guard-isnt-covering-guard]]

## 검증 (사다리 3런)
- **단위/게이트**: metrics-fast 0. verify_067_scope에 **M3 쓰기 스코프** 추가 — sessions:read 운영자가
  M2(read)=None(전체)이지만 M3(write)=str(id)(자기것)임을 대비 단언(=버그의 정확한 증명). machine/superuser
  =None·member=str(id)도. PASS.
- **실인프라 통합**: verify_067_live PASS — member 타인 end→404·status 무변경 실측·machine/superuser 전체
  end 유지. 스위트 51/51(실패 0, flaky 1 재시도 통과).
- **적대(codex)**: 여집합 7축 — machine/superuser/owner end 가능·운영자만 차단(과조임 아님)·feedback 무회귀
  (machine 분기가 _require_user 판정 안 흔듦)·읽기 라우트 read-scope 유지·approvals resolve 무변경 →
  **"여집합 공격 실패 — 결함 없음"**(codex가 직접 verify_067_scope 실행까지). machine=str "machine"만
  생성됨(auth.py) 확인=`.id` 접근 불가.

## 남은 것 (backlog)
- dedup 후속 C(eval llm_cfg)·D(eval `_execute_*` 배경작업).
- eval_* 내부 중복 미전수·stale verifier 일괄 갱신.

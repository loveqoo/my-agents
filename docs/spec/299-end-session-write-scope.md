# 299 — end_session 쓰기 스코프 정합 (읽기 권한이 쓰기를 넓히지 못하게)

## 배경

스펙 298 codex 적대 리뷰의 인접 발견. `POST /sessions/{id}/end`는 세션 상태를 `completed`로 바꾸는
**mutating route**인데 `authz.own_scope(principal, "sessions", "read")`(읽기 스코프)를 유일 인가로 쓴다.
스펙 209 F1이 feedback PUT/DELETE엔 `_own_scope_write`(superuser-only)를 넣어 "읽기 권한이 쓰기를
넓히면 안 된다"를 봉했으나, **end_session은 누락**됐다. 결과: `(role, sessions, read)` 정책이 부여된
"전체 세션 열람 운영자"가 **타인 세션을 종료**할 수 있다.

- **회귀 아님**: pristine HEAD도 end_session이 `_own_scope`(read)를 사용(298은 기계 치환으로 시맨틱 보존).
- **현재 미노출**: 기본 정책엔 sessions:read 시드가 없어 superuser만 admin-read → own=None이 정당. 잠복.
- **census**: sessions.py write 라우트 전수 — feedback PUT/DELETE는 이미 `_own_scope_write`(정상),
  end_session만 read-scope(버그). approvals resolve는 own_scope가 404-fold용이고 실제 쓰기 게이트는
  `_may_resolve`라 정상. **버그는 end_session 하나로 격리**.

## RBAC 경계 (체크리스트)

1. **입구 열거**: sessions 쓰기 입구 = feedback PUT·feedback DELETE·**end(비가역성은 아니나 상태 변경)**.
   전부 쓰기 스코프여야 함. 읽기 입구(list/get/messages/users)는 읽기 스코프 유지.
2. **입구별 소유권(쓰기)**: 쓰기는 **진짜 superuser 또는 machine 센티널만** 무스코프(전체), 그 외 User는
   자기 것만(SELECT-WHERE 융합 = `_get_session_or_404`의 own 인자). read 운영자는 스코프됨 → 타인 종료 차단.
3. **단일 헬퍼**: 읽기=`authz.own_scope(p,obj,act)`, 쓰기=`authz.own_scope_write(p)`(정본 승격, machine-aware).
4. **존재 비노출**: 스코프된 end가 타인 세션을 만나면 `_get_session_or_404`가 404(부재와 동일, 403 아님).

## 설계

**핵심 걸림돌**: end_session은 **machine 토큰(str principal)을 허용**한다(시스템이 세션 종료). 그런데 옛
sessions `_own_scope_write`는 `_require_user` 통과를 전제로 `str(principal.id)`를 써서 **machine(str)에서
`.id` AttributeError**로 깨진다(feedback은 `_require_user`로 machine을 먼저 배제해 무사). 따라서 단순
스왑 불가 → **machine-aware 쓰기 스코프**가 필요하다.

`authz.own_scope_write(principal) -> str | None` 신설(옛 sessions._own_scope_write 승격 + machine 분기):
```python
def own_scope_write(principal: Any) -> str | None:
    """**쓰기**용 소유 스코프(정본, 스펙 299). 읽기 권한이 쓰기를 넓히면 안 된다(209 F1):
    own_scope는 (obj,act)-read admin에게 무스코프를 주지만, 쓰기는 **진짜 superuser·machine 센티널만**
    무스코프(전체), 그 외 User는 자기 것만. machine=owner급 전체(011/031). read 운영자는 여기서 스코프됨."""
    if isinstance(principal, str):   # machine 센티널 = 전체(011/031)
        return None
    if getattr(principal, "is_superuser", False):
        return None
    return str(principal.id)
```
- read/write 스코프 짝을 authz.py에 나란히(298이 own_scope를 authz로 정본화한 것과 대칭 — 발견성).
- 소비: sessions `end_session`·feedback PUT/DELETE 3곳 모두 `authz.own_scope_write(principal)`. sessions
  로컬 `_own_scope_write` 제거. feedback은 `_require_user`(machine/익명 배제)를 **그대로 유지**(machine이
  피드백 못 남김은 별개 규칙) — machine 분기는 feedback 경로엔 무해(도달 안 함), end 경로에서만 발동.

## 목표 (측정 가능)

1. `authz.own_scope_write` 신설, sessions 로컬 `_own_scope_write` 정의 0. 3 write 라우트가 정본 사용.
2. **end_session 행위 변경(정정)**: sessions:read 운영자 → 자기 세션만 종료(타인 404). machine·superuser·
   owner·member는 **불변**(machine=전체·superuser=전체·owner=자기것·member=자기것).
3. **feedback 행위 불변**: `_require_user` 유지, 스코프 판정 동일(User만 도달 → machine 분기 무영향).

## 검증 (사다리 3런)

- **단위/게이트**: metrics-fast 0. verify_067_scope에 **M3 쓰기 스코프** 추가 — FakeEnforcer로 sessions:read
  운영자 모사해 `own_scope(·,"sessions","read")=None`(read=전체)이지만 `own_scope_write=str(id)`(write=자기것)
  대비 단언(=버그의 정확한 증명). machine→None·superuser→None·member→str(id)도.
- **실인프라 통합**: verify_067_live 유지(D4 T5 member 타인 end→404). 스위트 51/51.
- **적대(codex)**: 여집합 — (a) machine end 여전히 가능(None)? (b) superuser 전체 가능? (c) owner 자기것 가능?
  (d) sessions:read 운영자만 타인 종료 차단됐나(과도 조임 아님)? (e) feedback 경로 무회귀(machine 분기가
  User 판정 안 흔듦)? (f) 읽기 라우트는 read-scope 그대로(과잉 적용 아님)?

## OUT
- 쓰기 스코프에 enforcer(write perm) 상담 — 현재 어떤 자원도 sessions:write류 정책이 없어 YAGNI(superuser/
  machine-only 유지). 필요해지면 (obj,act) 파라미터화(own_scope와 대칭)로 확장.
- approvals resolve의 own_scope(404-fold) — 실제 쓰기 게이트는 `_may_resolve`라 정상, 무변경.
- dedup 후속 C/D(eval) — 별도.

# 298 — authz 스코프 + LIKE-escape 정본화 (저위험 dedup, 소유권 경계 불변)

## 배경

스펙 294~297 dedup 연작 후 census(deep-reasoner 전수)로 남은 **본문 공유 후보**를 랭크. 이 스펙은
**바이트 동일이거나 튜플 하나만 다른 최저위험 2건**(A·B)을 묶어 정본화한다. 절감보다 **크로스모듈
private import 냄새 제거**가 구조 이득(`rag→sessions._like_escape`, `chat→sessions._own_scope` —
route 모듈의 private을 다른 route가 끌어 씀).

## RBAC 경계 (체크리스트 트리거 — authz 술어를 만짐)

B는 `_is_admin`/`_own_scope`(소유 스코프 판정)를 건드리므로 소유권 경계 스펙이다. **핵심 불변식**:

- **판정 시맨틱 바이트 보존**: `_is_admin`은 `isinstance str→True`(machine)·`is_superuser→True`·
  `enforce(id, obj, act)` 3분기 구조가 동일하고 **유일 차이가 (obj,act) 튜플**
  (`("sessions","read")` vs `("approvals","resolve")`). 파라미터화 시 각 호출부가 **자기 튜플을 명시**로
  넘겨 "라우터 독립"(sessions.py:28 주석)을 그대로 보존 — 골격만 단일화, 정책 결정권은 호출부.
- **절대 병합 금지(존치)**: `sessions._own_scope_write`(superuser-only, 읽기권한이 쓰기 못 넓힘 =
  스펙 209 F1 보안경계, `is_superuser` 직접 사용해 `_is_admin` 무의존)·`approvals._may_resolve`
  (approvals 전용 승인자 판정, 대응물 없음). 본문·의미 실차이라 억지 dedup 아님.
- **존재 비노출·SELECT-WHERE 불변**: 이 스펙은 판정 *헬퍼의 홈*만 옮긴다. 각 라우터의 `own` 주입 →
  `_get_session_or_404(…, own)`·SELECT-WHERE·404-fold는 그대로. 스코프 값 자체 불변.

## 후보 (본문 대조 확정)

**A. LIKE-escape (3중 바이트 동일)**
- `sessions.py:115 _like_escape` · `eval_common.py:57 _ilike_literal` · `memory/mem0_backend.py:328`
  인라인 `esc = q.strip().replace("\\","\\\\").replace("%","\\%").replace("_","\\_")`.
- 차이: 없음(순수 문자열 함수). 홈 = **신설 `sqlutil.py`**(의존 0 — leaf backend가 route 모듈을
  import하지 않게). 크로스모듈 private import(`rag.py:42`) 제거.

**B. authz 스코프 트리오 (2중)**
- `_agent_id_map`(sessions:62·approvals:64 — 바이트 동일): Agent pk→외부 id 맵 = 직렬화 헬퍼.
  홈 = **`serializers.py`**(to_out 계열 소유자).
- `_is_admin`(sessions:25·approvals:24 — (obj,act) 튜플만 차이) → **`authz.is_admin_for(principal,
  obj, act) -> bool`**.
- `_own_scope`(sessions:39·approvals:57 — 바이트 동일, 로컬 `_is_admin` 의존) →
  **`authz.own_scope(principal, obj, act) -> str | None`** = `None if is_admin_for(...) else str(id)`.

## 목표 (측정 가능)

1. `sqlutil.like_escape` 신설, 3곳(sessions/eval_common/mem0_backend) 대체. `_like_escape`/
   `_ilike_literal` 정의·크로스모듈 import 0.
2. `authz.is_admin_for`·`authz.own_scope` 신설. sessions·approvals 로컬 `_is_admin`/`_own_scope` 정의 0.
   호출부가 자기 (obj,act) 튜플 명시: sessions=`("sessions","read")`, approvals=`("approvals","resolve")`,
   chat=`("sessions","read")`(resume 바인딩, 스펙 068 동형).
3. `serializers.agent_id_map` 신설, 로컬 `_agent_id_map` 정의 0.
4. **행위 보존**: `_own_scope_write`·`_may_resolve` 무변경. 세션/승인 소유 스코프·404-fold·존재 비노출
   전부 불변(측정: verify + 스위트 + codex).

## 검증 (사다리 3런)

- **단위/게이트**: `make metrics-fast`(ruff/format/xenon/MI/naming/mypy 0). import 정합·미사용 정리.
- **실인프라 통합**: 세션 소유(verify_067)·승인 소유(066/177)·가시성 147·소유권 112 + 스위트 51/51.
- **적대(codex)**: 여집합 — (a) 파라미터화가 (obj,act) 튜플을 라우터별로 정확히 보존했나(sessions=read,
  approvals=resolve 뒤바뀜 없나), (b) `own_scope` None/id 반환 시맨틱 바이트 동일한가, (c) `_own_scope_write`
  superuser-only 경계가 실수로 `own_scope`로 대체됐나, (d) machine 센티널(str) 분기 보존, (e) mem0
  `q.strip()` 순서(escape 전 strip) 보존.

## 인접 발견 (codex 적대 리뷰가 덤으로 적발 — 298 범위 밖, 이월)

- **`end_session`(sessions.py) mutating인데 read-scope**: `POST /{id}/end`가 `own_scope(·,"sessions",
  "read")`로 스코프 → `sessions:read` 운영자가 부여되면 **타인 세션 종료 가능**(스펙 209 F1 "읽기권한이
  쓰기 못 넓힘"이 feedback엔 적용됐지만 end엔 누락). **제 회귀 아님**(pristine HEAD도 `_own_scope`(read)
  사용, 298은 기계 치환으로 시맨틱 보존). 현재 기본 정책엔 sessions:read가 없어 미노출(superuser만
  admin)이나 잠복. **단순 `_own_scope_write` 스왑 불가** — end는 machine 토큰(str principal)을 허용하는데
  `_own_scope_write`는 `str(principal.id)`라 machine에서 깨짐(feedback은 `_require_user`로 machine 배제).
  → machine-aware write-scope 설계 필요, **스펙 299**로 분리(행위 변경이라 298 "행위 보존" 목표 밖).

## OUT
- `_own_scope_write`·`_may_resolve` 병합(보안경계·전용 판정) — 존치.
- 후보 C(eval llm_cfg)·D(eval 배경작업 스캐폴딩) — 절감 크나 락 lifecycle·사용자 문구 위험, **스펙 299+**로 분리.
- `end_session` write-scope 정합 — 위 인접 발견, 스펙 299.
- JSON 추출·`_State` TypedDict·pagination 관용구 — 억지 dedup(본문/알고리즘 상이), 제외.

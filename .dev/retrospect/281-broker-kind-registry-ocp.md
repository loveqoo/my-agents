# 281 — 브로커 kind 파싱 OCP 흡수(스펙 306)

## 무엇을 했나
구조 리뷰(182/183)가 남긴 "중간 우선" 항목. 브로커 cap_id 파싱 두 함수(`_kind_of`·`_cap_resource`)의
하드코딩 if-체인을 단일 kind 레지스트리(`_PREFIXED_KINDS`) 구동으로 흡수. 새 kind 추가 시 레지스트리
한 곳만 등록하면 두 파서가 파생 — `_cap_resource` 분기 누락 시 per-cap RBAC 리소스가 조용히 오추출되던
함정 봉인. 순수 리팩터라 **행위 바이트 동일**이 핵심 불변식.

## 배운 것 / 복리 포인트

- **중복이 균일하면 per-provider 추상보다 데이터 레지스트리가 옳다**. backlog 문안은 "provider 계약에
  `resource_of` 흡수"였지만, 5개 kind의 리소스 추출이 **전부 균일**(`{kind}:` 스트립)임을 실측하니
  per-provider 메서드는 5중복(과추상). 게다가 파싱은 context-free(a2a_server가 브로커 인스턴스 없이
  호출)라 provider 인스턴스에 못 매단다. **단일 `_PREFIXED_KINDS` 레지스트리 + `_strip_kind` 프리미티브**가
  OCP 봉인이자 중복 소거. 구조 지시("YAGNI는 구조 잡히기 전까지")대로 — 비균일 kind가 생기면 그때
  per-provider 오버라이드(트리거 미도래). → [[structure-first-boundary-is-spec]]

- **순수 리팩터의 완료조건 = "옛 구현과 바이트 동일"이고, 그건 옛 코드를 오라클로 박제해 대조**. "동작
  같겠지"가 아니라 verify_306이 **옛 if-체인을 그대로 재현한 `_old_kind_of`/`_old_cap_resource`**를
  품고, 표본×전 kind 곱집합으로 신·구 출력을 대조한다. 이 오라클 대조가 아니었으면 놓쳤을 엣지 하나를
  잡음(아래). authz-인접 리팩터는 "리소스 문자열이 바뀌면 인가가 넓어지거나 좁아진다" — 동일성이 곧
  안전. → [[verification-ladder-three-rungs]]

- **균일 규칙의 숨은 엣지: fallback은 스트립하면 안 된다**. 첫 구현은 `_cap_resource=return _strip_kind(cap_id,kind)`
  였는데, 옛 코드는 agent(fallback)에서 **스트립 안 하고 cap_id 전체 반환**. `_cap_resource("agent:x","agent")`가
  신=`"x"`·구=`"agent:x"`로 갈렸다(agent cap은 bare뿐이라 도달불가지만 바이트 동일 위반). `kind in
  _PREFIXED_KINDS`일 때만 스트립(agent는 레지스트리 밖이라 원본)으로 봉합 — **레지스트리가 "누가
  접두사를 갖나"의 단일 진실이라 이 게이트도 레지스트리에서 파생**(일관). 오라클 대조 테스트가 이걸 잡음.

- **드리프트 핀은 수동 리스트면 무력 — introspection이라야 진짜**. codex가 짚음: verify_306의 초안
  드리프트 핀이 수동 `ALL_KINDS`를 기준으로 비교해, 새 `CAP_KIND_FOO`를 추가하고 `_PREFIXED_KINDS`·
  `ALL_KINDS` 둘 다 안 고치면 못 잡는다(핀의 존재 이유 무력화). **모듈의 `CAP_KIND_*` 상수를
  introspect**(`vars(common)`)해 실제 kind 집합을 세도록 고침 → 새 상수만 추가해도 핀이 발화. "측정으로
  불변식을 지키되, 그 측정의 *기준*이 손으로 유지되면 같이 드리프트한다." → [[installed-guard-isnt-covering-guard]]

- **적대 리뷰가 '결함 없음'이어도 검증의 결함을 덤으로 잡는다**. codex는 행위 동일성 4축을 전부 "여집합
  공격 실패"로 확증했지만, 그 과정에서 드리프트 핀이 가짜라는 **테스트 자체의 구멍**을 발견. 코드가
  맞아도 그걸 지키는 그물이 헐거우면 미래에 샌다 — 적대자에게 코드뿐 아니라 "이 테스트가 정말 그걸
  보장하나"도 물을 것. → [[adversarial-review-before-destructive-ship]]

## 검증 (사다리 3런)
- **단위**: verify_306 105/105 — 라운드트립(전 접두사 kind)·**옛 if-체인 오라클 동치**(표본×전 kind)·
  introspection 드리프트 핀·agent bare 원본·cross-kind 격리·`agent:` 엣지 동일성.
- **게이트**: metrics-fast 0(ruff·mypy 106파일 — `_kind_of` str 반환 타입 무붕괴).
- **실인프라(rung 2)**: 브로커 verifier 066/104/105/111/112 PASS — 104/105/111은 **실 mem0 쓰기/읽기**,
  112는 **실 DB 소유권** 왕복(per-cap RBAC 경로 커버). 100/101/103은 pristine(306 stash) 동일 실패
  =기존 stale(그래프 타임라인)/인프라(mock MCP 미기동·RAG 시드 미인제스트) 부채, 내 변경 무관 확정.
- **적대(codex, read-only)**: 행위 동일성 4축 여집합 공격 실패 + 드리프트 핀 Low 지적→introspection 봉합.

## 남은 것 / 주의
- provider 계약 `matches`/`resource_of` 도입은 비균일 kind가 생기는 날의 트리거(현재 YAGNI).
- 기존 stale verifier 100/101/103(그래프 타임라인·mock MCP·RAG 시드)은 별개 부채 — backlog 일괄 갱신 후보.
- 전 실모델 스위트(make suite)는 미실행 — 파싱이 바이트 동일(오라클 대조)이고 실인프라 브로커 verifier가
  authz 경로를 커버해 rung 2 충족으로 판단(순수 리팩터, 10분 스위트 생략).

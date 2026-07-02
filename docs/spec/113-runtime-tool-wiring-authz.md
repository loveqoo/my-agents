# 113 — 런타임 tool 배선 인가 (spec 112 P0 후속)

## 배경 / 왜

codex 112 P0: 채팅 런타임(`chat._load_context`)이 agent config의 `mcps`/`vectorTables` **이름**으로
`McpServer`/`Collection`을 로드해 **복호화 크레덴셜**로 tool을 배선하는데, 여기에 RBAC/소유권 검사가
없다(브로커 밖 별개 경로, 112 이전부터 존재). 공격: member가 자기 에이전트 config에 `mcps=["victim-mcp"]`
를 넣고 채팅 → per-cap grant 없이 victim의 MCP 크레덴셜이 런타임에 쓰인다. 112에서 정직하게 OUT 처리
후 백로그 승격 — 이번에 닫는다. 사용자 승인: "1,2,3,4 모두 차례대로 루프"(상시).

## 설계

### 인가 주체 = **에이전트 작성자(agent.owner_id)**, 채팅 사용자 아님

112 교훈(소유권은 관리를 막지 사용을 막지 않는다)의 재적용: 채팅 사용자로 막으면 admin이 만든 공유
에이전트가 member 채팅에서 깨진다. 올바른 원칙은 **"에이전트는 그 작성자가 쓸 수 있는 자원까지만
쓸 수 있다"**(confused-deputy 차단) — 자원 참조를 config에 박은 주체가 그 자원에 대한 권한을 가졌어야
한다. 채팅 사용자의 권한은 브로커 per-cap(112 A)이 담당, 두 축 분리 유지.

### 게이트 지점 = `_load_context` 단일 관문

chat(582)·A2A chat(541)·resume(906) 셋 다 `_load_context`를 통과한다(단일 초크포인트, 체크리스트 §3
드리프트 0). MCP rows 루프와 RAG cols 루프에서 각 행을 술어로 거른다.

### 허용 규칙 (닫힌 집합 — 하나라도 참이면 배선)

1. **agent.owner_id IS NULL** → 신뢰 저작 맥락(레거시/admin/머신 생성) → 전부 배선. **무회귀 축**:
   오늘 모든 에이전트가 NULL-owned라 기존 동작 그대로.
2. **작성자가 특권** — casbin `(owner,'*','*')`(admin 역할) 또는 `User.is_superuser`(DB 1회 조회,
   세션 이미 있음) → 전부.
3. **자원이 작성자 소유** — `row.owner_id == agent.owner_id`.
4. **MCP published=True** — 명시 공개 플래그(시드 mock-mcp도 published=True → member 에이전트가 시드
   도구를 계속 쓸 수 있음). Collection에는 published 없음 → 규칙 3/5만.
5. **RBAC per-cap/kind** — `_rbac_check(enforcer, owner, kind, name)`(112 A와 동일 술어 재사용:
   `capability:mcp:{server}`(서버단위가 툴 덮음)·`capability:rag:{name}`·kind-레벨). admin이 특정
   자원만 member에 열어주는 레버가 브로커와 런타임 배선에 **일관**.

거부 행은 **조용히 skip + log.warning**(기존 "임베딩 provider 불완전 skip" 패턴과 동형 — 500 없이
graceful, 존재 비노출). authz 미초기화면 규칙 2/5 불가 → 1/3/4만(fail-closed).

### RBAC 체크리스트 답변

1. **입구 열거**: 런타임 배선 입구는 `_load_context` 하나(chat/a2a/resume 공유). 브로커 경로는 이미
   112 A가 게이트. 삭제 가드(`agents_referencing`)는 읽기 전용 참조 카운트라 대상 아님.
2. **입구별**: 배선=행 단위 술어(로드 후 필터 — 이름 IN 쿼리는 유지하되 반환 행을 술어로 거름).
   fetch-then-check 잔존 명시: 이름 목록 로드는 기존 코드 그대로, 필터가 추가 층(행 로드 자체는
   크레덴셜 미사용이라 오라클 아님).
3. **단일 헬퍼**: `ownership.agent_may_wire(row_owner, published, agent_owner, kind, name)` 1곳.
4. **존재 비노출**: 거부=skip(도구 미배선)이라 응답에 자원 존재가 드러나지 않음.
5. **3런**: 단위(술어 시맨틱) + 실 DB 통합(_load_context 직접 호출: NULL-owner 에이전트=전부·member
   에이전트가 남의/NULL 자원 참조=미배선·자기 것=배선·per-cap grant=배선·published=배선) + codex 적대.
6. **자가-잠금 핀**: 자기 소유 자원은 항상 배선(규칙 3)·NULL-owner 에이전트 무회귀(규칙 1) 별도 확인.

## codex 적대 검증 결과 (rung 3)

- **[P0] override 주입 confused-deputy** — 채팅 호출자가 `overrides.mcps`에 남의 비공개 MCP 이름을 넣으면
  게이트가 **작성자 권한**으로 판정해 배선됨. **봉합**: override 병합 전 `stored_mcps` 포착 → 저장본 자원은
  작성자 권한, **주입 자원은 호출자(`own`) 권한**으로 게이트(own=None=admin/내부는 특권). vectorTables는
  override 화이트리스트 밖이라 주입 불가(무영향).
- **[P2] non-UUID owner_id의 casbin role 충돌** — `owner_id="admin"`이면 UUID 검증 전 `enforce("admin",*,*)`
  가 기본 admin 정책과 매칭돼 특권 오판. **봉합**: `_wiring_owner_privileged`가 **UUID 검증을 casbin보다
  먼저**(owner_of는 UUID/None만 스탬프 → 비UUID는 즉시 비특권). 실 admin은 uuid→역할 상속으로 여전히 매칭.

## 비목표 (OUT)

- 저장 시점(config 작성 시) 검증 — 런타임 게이트가 진실원(저장 검증은 우회 가능: 저장 후 grant 회수
  등 시점 드리프트). UI 피커의 선택지 필터링은 별개 UX 후속.
- Collection에 published 플래그 추가 — 필요해지면 별개(오늘은 RBAC per-cap 레버로 충분).
- 채팅 사용자 축 게이팅 — 의도적으로 안 함(공유 에이전트 보존, 112 갈래).

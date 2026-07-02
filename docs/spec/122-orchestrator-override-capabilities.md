# 122 — 조율형 플레이그라운드 오버라이드에 capabilities 반영 (버그2)

## 배경 / 왜

사용자 버그: 조율형 에이전트에 MCP 설정 후 활성화 → 플레이그라운드 오버라이드를 열면 **설정한 MCP가
누락**. 원인은 런타임 이원화(learning 108): **조율형은 MCP를 `config.capabilities`(예: `mcp:서버`)로**
담고 브로커로 실행하는데, `OverridePanel`은 **직접형(default-ui)의 `mcps`/`memories` 필드만** 다룬다:

- `overrideDefaults(agent)`가 `agent.mcps`만 읽음 → 조율형은 비어 있어 오버라이드 패널에 **아무 MCP도
  안 뜸**.
- 백엔드 오버라이드 허용목록(`chat.py`)에도 `capabilities`가 없어, 설사 보여줘도 세션 오버라이드 불가.

런타임은 저장된 capabilities를 그대로 써서 **에이전트 자체는 정상 동작**하고, **오버라이드 화면에서만
누락**돼 보인다. 스펙 108이 편집 폼을 kind별로 갈랐는데(조율형=capabilities 피커, 직접형=직접 자원) 스펙
109가 오버라이드 패널엔 직접형만 이식하고 조율형 capabilities는 빠뜨린 틈이다.

## 설계

**백엔드 (`chat.py`)**
- 세션 오버라이드 허용목록 `allowed`에 `"capabilities"` 추가. 이후 `ctx["capabilities"] =
  cfg.get("capabilities", [])`가 오버라이드된 값을 읽어 `build_broker(principal, ctx["capabilities"])`로
  흐른다.
- **보안(confused-deputy, 스펙 113)**: 브로커는 `_permitted = allowlist ∩ RBAC(principal=호출자)`. 즉
  저장분이든 주입분이든 **capability는 항상 호출자 RBAC로 게이트**된다(브로커가 request principal 사용).
  주입해도 호출자 권한 없는 cap은 deny — mcps 경로의 stored-vs-injected 분기가 불필요(브로커가 이미
  호출자 스코프). 추가 게이트 없이 안전.

**프론트 (`OverridePanel.tsx` + `Playground.tsx` + `mockData.ts`)**
- `mockData.ts`: `isOrchestratorImpl(impl)`을 export(orchestrate/orchestrate_ranked). AgentsView의
  로컬 정의를 제거하고 import → **단일 소스**(드리프트 0).
- `Overrides`에 `capabilities: string[]` 추가. `overrideDefaults`는 `[...(a.capabilities ?? [])]`,
  `overridePayload`는 `sameSet` 비교로 변경 시만 전송(무회귀: 안 건드리면 저장분 유지).
- `OverridePanel`이 `agents`·`collections` prop을 받아 편집 폼과 **같은 capGroups**(다른 에이전트=
  code/external agentId, 도구=`mcp:name`, 문서=`rag:name`, 사용자 기억=`memory:user`/`memwrite:user`)를
  조립.
- 렌더: `isOrchestratorImpl(agent.impl)`이면 capGroups 피커를 `draft.capabilities`에 바인딩(직접형의
  mcps/memories 피커 대신 — 조율형은 직접 도구 미사용). 직접형이면 기존 mcps/memories 피커 유지.
- `Playground.tsx`: `listCollections()` 로드, `agents`·`collections`를 OverridePanel에 전달.

## 검증

- **브라우저(Playwright, 시스템 Chrome)**: 조율형 에이전트에 MCP capability 설정→활성화→플레이그라운드
  오버라이드 열기 → **설정한 MCP가 선택된 상태로 표시**되는지 스샷. 직접형은 기존 mcps 피커 유지(무회귀).
- **백엔드 단위/통합**: `_load_context`에 `overrides={"capabilities":[...]}` → `ctx["capabilities"]`가
  오버라이드 반영. 직접형/원격은 무영향. 오버라이드 미전송 시 저장분 유지.
- **적대(codex)**: capabilities 주입이 호출자 RBAC를 우회하나(브로커 principal 확인)·직접형에 capabilities
  누출 없나·overridePayload가 빈/동일 시 오전송 없나 등 여집합.

## 비목표 (OUT)

- 조율형에 직접 mcps/memories도 함께 오버라이드 — 런타임 미사용(learning 108), 혼란만. capabilities로 일원화.
- capabilities 카탈로그 밖(미등록) cap을 패널에 렌더 — 카탈로그 로드분만. 저장분은 오버라이드 미전송 시
  런타임이 그대로 사용(누락 없음).
- 편집 폼/오버라이드 폼 컴포넌트 통합 — 이번엔 capGroups 조립만 공유(리팩터는 후속).

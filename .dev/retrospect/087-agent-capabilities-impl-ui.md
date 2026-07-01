# 087 — 에이전트 편집 폼에 impl + capabilities 노출 (스펙 106)

## 무엇을 / 왜

능력 브로커(100–105)를 6개 provider까지 만들었지만 **UI에서 엮을 길이 없어** 코드/테스트로만
동작했다. 사용자 요청("설정 UI를 만들어야 테스트 하죠!")대로 편집 폼에 두 축을 채워, UI만으로
오케스트레이터 에이전트를 만들어 브로커를 엮게 했다:
- **실행 방식(impl) Select** — 에이전트를 오케스트레이터로 만드는 런타임 키 선택.
- **능력(capabilities) 피커** — kind별로 위임 가능 cap id를 고름.

## 한 일

- 백엔드: `GET /agent-impls`(신뢰 레지스트리 `list_agent_impls()` 노출, `/agents/{uuid}` 충돌 피해
  top-level `meta_router`), AgentOut에 `capabilities` 필드 + 직렬화 보강.
- 프론트: `AgentConfig`·`Agent`·`AgentFormData`에 impl/capabilities, `blankForm`·`configOf`·`initial`·
  `save` 4곳 배선, impl Select(키→친절 라벨 매핑, 미지 키 raw 폴백) + kind별 능력 피커(클라이언트 조립).
- 검증: 브라우저(실 Chrome) 10/10, 백엔드 왕복(impl+caps 저장→재조회 보존), 엔드포인트 인증.

## 잘된 것

- **능력 피커에 새 백엔드 카탈로그 엔드포인트가 불필요했다.** cap id가 `<kind>:<name>` 규약이라 폼이
  이미 로드하는 데이터(collections·mcps·agents)에서 순수 포매팅으로 조립 — 100–105가 쌓은 ID 네임스페이스가
  저작 계층에서 배당을 냈다(learning 106).
- **impl 목록을 레지스트리에서 끌어 drift 0.** agent-flow 스킬(099)이 새 flow를 등록하면 UI 드롭다운에
  자동 반영. UI는 표시(라벨)만.
- **브라우저 검증을 사용자 스샷 없이 내가 먼저** 돌려(Playwright+시스템 Chrome) 10개 단언+실화면 확인.

## 배운 것 / 함정

- **config 필드 왕복 완전성은 4지점의 교집합**(learning 106 핵심): 쓰기 스키마(AgentCreate)가 `capabilities`를
  101에서 이미 수용했고 직렬화는 `impl`은 보냈지만 `capabilities`는 **말없이 빠져 있었다** → 폼이 저장은
  해도 편집 재열기 때 사라지는 *비대칭 배선*. 필드명을 스키마+직렬화+폼 3파일에 grep해 4지점(write-schema∩
  serializer∩form의 configOf·save·initial) 다 있는지 확인해야 왕복이 닫힌다. 104의 "새 상태축→모든 팩토리"의
  config-필드판.
- **vite가 IPv6(`::1`)만 바인딩** → 브라우저 검증 시 `127.0.0.1:5173`은 ERR_CONNECTION_REFUSED,
  `localhost:5173`만 됨. shot 스크립트 `ADMIN_URL=http://localhost:5173`로 우회.
- **antd 라벨에 Tag를 중첩하면** `getByText(exact:true)`가 안 맞음(라벨 textContent에 태그 텍스트 포함) →
  정규식 부분매칭으로.

## 남은 것(OUT — 백로그)

- **엔드투엔드 스모크**: UI로 만든 오케스트레이터가 실제 대화에서 브로커 위임 노드(`broker_invoke:*`)를
  띄우는지. UI→config.capabilities 지속은 이번에 증명, config→build_broker 소비는 100–105가 증명 →
  체인은 이어졌으나 *한 화면에서* 잇는 스모크는 미실행(LLM 필요).
- MCP 툴 단위 granularity(`mcp:server/tool`), impl별 능력칸 조건부 표시.

## 검증 안 함(스킵 사유)

- **적대 codex 리뷰 스킵**: 순수 admin 설정 저작 UI라 RBAC/소유권 체크리스트 비발동(강제=백엔드 브로커,
  104/105서 이미 3런 검증). UI는 경계 아님 — 권한 없는 cap을 저작해도 브로커가 런타임에 deny-by-default로
  거부(거짓 부여 없음). 브라우저 10런+왕복+엔드포인트 인증으로 충분.

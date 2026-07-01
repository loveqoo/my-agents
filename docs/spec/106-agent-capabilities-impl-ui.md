# 106 — 에이전트 편집 폼에 impl(실행 방식) + capabilities(능력 목록) 노출

## 배경 / 왜

능력 브로커(100–105)를 만들었지만 **관리 UI에서 엮을 수단이 없다.** 에이전트를 오케스트레이터로
쓰려면 두 가지가 필요한데 편집 폼이 둘 다 안 보낸다:
- **impl**(실행 방식) — 에이전트를 오케스트레이터로 만드는 런타임 키(`orchestrate`·`orchestrate_ranked`).
  현재 폼은 impl을 안 보냄(085 H5 갭, 스펙 099/102 OUT).
- **capabilities**(능력 allowlist) — 그 오케스트레이터가 위임 허용된 cap id 목록. 저장 경로는 스펙 101에서
  `AgentConfig.capabilities`로 이미 열렸으나 UI 폼이 없다.

즉 브로커는 코드/테스트로만 동작하고 **사용자가 설정으로 엮어 테스트할 길이 없다.** 이 스펙이 그 UI를 채운다.

## 목표

관리 SPA 에이전트 편집 폼(`admin/src/admin/views/AgentsView.tsx`)에서:
1. **실행 방식(impl) 선택** — 등록된 런타임 중 고른다(+ "기본" = UI 에이전트).
2. **능력(capabilities) 선택** — 이 에이전트가 오케스트레이션에 쓸 cap id를 kind별로 고른다.
3. 저장/로드 배선(config ↔ form) — 백엔드 무변경(저장 스키마 이미 수용).

그러면 사용자가 UI만으로 오케스트레이터 에이전트를 만들어 브로커를 **엮고 테스트**할 수 있다.

## 설계

### 1. impl(실행 방식) Select
- **impl 목록 출처 = 신뢰 레지스트리**(drift 0): 백엔드 `list_agent_impls()`(runtime.py, 이미 존재)를
  얇은 엔드포인트 **`GET /agent-impls`**(관리자 인증)로 노출 → 새 flow(agent-flow 스킬 099) 등록 시 자동
  반영. UI는 키→친절 라벨을 매핑(`orchestrate`="첫 매치 위임"·`orchestrate_ranked`="랭킹 상위 조합"·
  `route`="조건 분기"·`plan_execute`="계획-실행"), 미지의 키는 raw로 표시(폴백).
- 폼에 "실행 방식" Select 추가: `기본(UI 에이전트)`(=impl 빈값) + 등록 impl들. 저장 시 빈값이면 config에
  `impl` 미포함(현행 default 동작 보존).
- **안전 경계 보존(스펙 085)**: impl은 레지스트리 *키*일 뿐(런타임 eval 없음). UI는 키를 고를 뿐 코드
  주입 아님. 미해결 키는 서빙이 정직히 거부(089) — UI는 저장만.

### 2. capabilities(능력 목록) 피커 — kind별, 클라이언트 조립
폼이 이미 가진 데이터로 조립(새 백엔드 카탈로그 엔드포인트 불요):
- **내 기억**: `memory:user`(읽기)·`memwrite:user`(쓰기) — 고정 2개 토글(라벨 "내 기억 읽기/쓰기").
- **문서 컬렉션(rag)**: `rag:<collection.name>` — 로드된 `collections`에서.
- **MCP 서버(mcp)**: `mcp:<server.name>`(서버 전체) — `blocks.mcp` 항목에서. **툴 단위 granularity
  (`mcp:server/tool`)는 후속**(서버 전체가 그 서버 툴을 덮음, 101 §3.3 — MVP는 서버 전체).
- **다른 에이전트(agent)**: `agt_<agent_id>` — 다른 에이전트 중 **원격(code/external=A2A)**만(로컬 UI
  에이전트는 A2A provider 대상 아님, `is_remote_source` 프론트 판정). 자기 자신 제외.
- UI: kind별 섹션에 Checkbox 목록(기존 memories/vectorTables/mcps 패턴 재사용). 선택된 cap id 배열이
  `form.capabilities`. 빈 배열이면 config에 빈 배열(=deny-by-default, 브로커가 발견 공집합).
- **안내**: capabilities는 오케스트레이터 impl(`orchestrate`·`orchestrate_ranked`)에서 쓰인다는 힌트 표시
  (다른 impl에선 무시됨 — 브로커는 주입되나 비-오케스트레이터 flow가 안 부름).

### 3. 배선(config ↔ form) — 백엔드 무변경
- `AgentFormData`에 `impl: string`·`capabilities: string[]` 추가.
- `AgentConfig`(저장 타입)에 `impl?`·`capabilities?` 추가(백엔드 `_load_context`가 이미 읽음).
- `configOf(a)`(edit 초기값), `save()`(config 조립), `blankForm`(기본값 impl=""·capabilities=[]) 3곳 배선.
- 서버 응답 Agent가 impl/capabilities를 노출하는지 확인 — 안 하면 GET /agents 직렬화에 추가(표시용, 관리자
  전용 — 089 F1처럼 채팅엔 노출 안 함).

## 검증

- **브라우저(Playwright, 직접)**: (a) 오케스트레이터 에이전트 생성 — impl=orchestrate 선택, capabilities에
  memory:user·rag:<col>·mcp:<server> 체크 → 저장 → 재열기 시 그대로 반영(초안 config 왕복). (b) impl 목록이
  레지스트리와 일치(orchestrate·orchestrate_ranked·route·plan_execute). (c) 기존 필드(model/persona/mcps)
  무회귀. 스크린샷 증거.
- **엔드투엔드 스모크(가능하면)**: 그렇게 만든 에이전트로 플레이그라운드 대화 1턴 → 브로커 위임 노드
  (`broker_invoke:*`)가 인스펙터 trace에 뜨는지(브로커가 UI 설정을 실제로 소비).
- **엔드포인트 단위**: `GET /agent-impls` 관리자 인증·목록이 `list_agent_impls()`와 일치(no-auth 401).
- 무회귀: 기존 에이전트 CRUD·직렬화 테스트.

## 비목표 (OUT)

- **MCP 툴 단위 granularity**(`mcp:server/tool`) — MVP는 서버 전체. 툴 목록 로드 + per-tool 체크는 후속.
- **capability 검색/유효성 실시간 검증** — 클라이언트 조립 목록에서 고르므로 유효 id만 선택됨(자유 입력 없음).
- **impl별 capabilities 조건부 표시** — MVP는 항상 표시 + 힌트. impl에 따라 숨김은 후속 UX.
- **런타임 동적 로딩·code/external 에이전트 생성** — 스펙 099/085 경계 유지.
- capabilities 편집 자체의 RBAC — 편집 폼은 이미 관리자 전용 라우트(강제는 백엔드 브로커 104/105).

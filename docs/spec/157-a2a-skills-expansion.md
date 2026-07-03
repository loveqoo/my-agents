# 157 — A2A skills 확장: 카드가 실제 능력을 광고 (실사용 #7)

## 요구 (사용자)
"A2A skills 확장: chat 외 기능(mcp, sub-agent call) 제공 + 테스트 수단." → 지금 A2A 카드는 `chat`
스킬 하나만 광고한다(a2a_server.py). 에이전트가 실제로 가진 능력(MCP 도구·서브에이전트 위임)을
A2A 스킬로 정직하게 광고하고, 그걸 확인·테스트할 수단을 붙인다.

## 지금 상태 (실측)
- `exposed_agent_card`는 skills=[{id:"chat", ...}] 고정. 에이전트가 MCP 도구 3개를 쓰든 서브에이전트
  2개를 위임하든 카드엔 안 보인다 — 외부 소비자가 이 에이전트 능력을 발견 못 한다.
- 능력 출처: `config.mcps`(직접형 — MCP 서버 이름들, 각 McpServer.enabled_tools+tools_meta),
  `config.capabilities`(조율형 allowlist — `mcp:server[/tool]`·`agent:agt_...`·`rag:coll`, broker.py 파싱).
- 실행은 message/send 하나(스킬별 RPC 없음 — A2A 표준). stream_local_reply가 에이전트를 통째 돌려
  MCP·위임을 이미 수행한다. 즉 **기능은 이미 도달 가능**하고, #7의 공백은 **발견(카드 광고)+표면**이다.

## 설계
### A. 카드 스킬 빌더 (a2a_server.py)
- `_agent_a2a_skills(agent, db)` → 카드 skills[] 구성:
  - 항상 `chat`(기존).
  - **MCP 도구**: `config.mcps`의 각 서버 + `config.capabilities`의 `mcp:server[/tool]`을 모아 McpServer
    로드 → enabled_tools마다 skill `{id:"mcp:server/tool", name:tool, description:tools_meta설명, tags:["mcp",server]}`.
    (server 전체 cap이면 enabled_tools 전부, `mcp:server/tool`이면 그 툴만.)
  - **서브에이전트 위임**: `config.capabilities`의 `agent:agt_...`(및 bare `agt_...`) → 대상 Agent 로드해
    skill `{id:"agent:agt_id", name:대상 alias/name, description:"위임", tags:["delegate"]}`.
  - **RAG**(부차): `rag:coll` → skill `{id:"rag:coll", tags:["rag"]}`(광고만, 선택).
  - 존재 안 하는 참조(dangling name)는 조용히 스킵(카드는 살아있는 능력만). 캡: 스킬 수 상한(예 50)으로
    거대 config 방어.
- 게이트 무영향: 카드는 공개(self-fetch 호환), 스킬 광고도 공개 메타(민감정보 아님 — 이름·설명만,
  auth/url 미포함). 노출 안 된 에이전트는 여전히 404(_load_exposed_agent 그대로).

### B. 테스트 수단 (플레이그라운드 — 155 위에)
- 155의 A2A 모드에 **"광고 스킬" 패널**: 활성 노출 에이전트의 카드를 fetch(GET well-known)해 skills[]를
  칩으로 표시(chat/mcp/delegate/rag 태그 구분). 외부 소비자가 보는 것과 동일한 걸 확인.
- 실행 테스트는 기존 A2A message/send(155)로 — 스킬을 유도하는 프롬프트를 보내면 에이전트가 그 MCP/
  위임을 실제로 태운다(트레이스는 A2A라 없음 — 155 경계 그대로).

## 검증 (2026-07-03 완료)
- verify_157 9/9: V1 MCP 스킬(chat+mcp tool+설명), V2 조율형 delegate/mcp/rag(위임=remote만), V3 dangling
  스킵, V4 미노출 404, V5 캡 50(61→50 실측), V6 민감정보 미노출, **V7 ui 미노출 서브에이전트 delegate
  미광고·이름 미누출**(High 봉인), **V8 stdio 서버 미광고**(Med1), **V9 빈 enabled→tools 스냅샷 광고**(Med2).
- e2e 6/6: 플레이그라운드 A2A 모드 광고 스킬 칩(web_search·echo·delete_record), 직접 복귀 시 배너 부재.

## codex 적대 리뷰 (High1/Med2/Low1 전부 반영)
- **High**: `agent:` 위임이 ui 미노출 서브에이전트 이름을 공개 카드에 누출(그 에이전트 노출 게이트 우회)
  + AgentProvider는 remote+endpoint만 위임(broker:236)하므로 거짓 능력. **수정**: 위임 스킬은
  `is_remote_source(source) and endpoint`인 remote(code/external)만 광고 → 누출·거짓 동시 봉인.
- **Med1**: MCP 스킬을 transport 무관 광고 → stdio·미지원은 런타임이 안 붙는데 카드는 광고. **수정**:
  http/streamable_http 서버만 광고(runtime.mcp_connection과 일치). down/SSRF 라이브 프로브는 카드마다
  하기 비싸 유예 — 카드=설정된 능력(지원 transport) 광고(경계 명시).
- **Med2**: `enabled_tools=[]`는 런타임서 "서버 전체"인데 카드는 아무것도 광고 안 함. **수정**:
  `enabled_tools or tools`(발견 스냅샷)로 광고 — 런타임 노출과 일치.
- **Low**: 같은 agent.id에서 exposed/능력 변경 시 칩 stale. **수정**: effect deps에 exposed·mcps·
  capabilities 시그니처 추가(un-expose/능력 변경 시 재조회).
- **경계(정직)**: tools_meta.description을 카드에 그대로(200자). MCP 발견 메타의 공개 도구 설명이라
  비밀 아님 — 단 discover가 토큰 섞인 설명을 저장하면 노출 가능(발견 메타 위생은 상류 책임).

## OUT
- 스킬별 독립 RPC(A2A 표준은 message/send 단일 — 스킬은 발견 메타). 스킬 단위 인가(카드는 광고,
  실행 인가는 기존 호출 게이트). A2A 카드 캐싱·라이브 도구 프로브(설정된 능력 광고에 그침).

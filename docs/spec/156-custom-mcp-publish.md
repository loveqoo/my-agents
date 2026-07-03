# 156 — 내부 MCP 외부 공개 + 커스텀(SDK) MCP (실사용 #4)

## 요구 (사용자)
"에이전트처럼 MCP도 만들어 공개." + "langgraph에서 mcp 만들어서 외부로 공개하는 프로토콜이 있습니다."
→ 우리 도구를 **진짜 MCP 엔드포인트로 서빙**해 외부 MCP 클라이언트/에이전트가 붙어 쓰게 한다.

## 지금 상태 (실측)
- McpServer는 **등록**만(외부/self-host 엔드포인트를 가리킴). `published`는 **카탈로그 플래그**일 뿐
  실제 외부 서빙 없음. 우리가 호스팅하는 MCP는 dev용 `mock_mcp`(`/_remote/mcp/`, FastMCP) 하나.
- 152 봉인: external+published 3입구 400·source 불변(재공개 세탁 방지).
- 에이전트는 A2A로 진짜 서빙(154). MCP엔 그 대응물(서빙)이 없다 — #4가 그 공백.

## 서빙 프리미티브 (확정)
`langchain_mcp_adapters.tools.to_fastmcp(langchain_tool) → FastMCP Tool` → `FastMCP(...).add_tool` →
`mcp.streamable_http_app()`를 경로에 mount → 실 streamable-HTTP MCP. mock_mcp가 이미 이 패턴.
= "langgraph에서 mcp 만들어 외부 공개"의 실체. 우리 도구를 to_fastmcp로 감싸 서빙한다.

## 설계 (에이전트 모델 미러)
### A. 커스텀(SDK) MCP = 우리가 코드로 정의·호스팅하는 도구 묶음
- 에이전트의 code(직접 코딩)·agent-flow 코드젠(099)에 대응. **신뢰 레지스트리** `agent/mcp_tools/`에
  코드로 도구를 정의(리뷰된 코드만 — 임의 UI Python 실행 금지, 099 신뢰 등록 철학 그대로).
- McpServer에 `source="custom"` 추가(local|external|custom). custom 행은 레지스트리 엔트리를 참조
  (`endpoint`=레지스트리 키). source 불변(152) 유지 — custom↔local↔external 세탁 금지.
- MVP: 시드 커스텀 MCP 1개(예: `calc-tools` — add/echo 결정적 도구)로 경로 실증(plan-execute-demo가
  커스텀 에이전트 실증한 것과 동형).

### B. 외부 공개 = published 커스텀/local MCP를 실 MCP 엔드포인트로 서빙
- 라우트 `/_served/mcp/{name}/` (또는 `/published/mcp/{name}/`) — published이고 source∈{custom,local}인
  MCP의 enabled_tools를 FastMCP로 서빙. **external은 서빙 불가**(152 봉인 — 재공개 금지 재확인).
- 마운트 방식 2안 검토(계획 승인 시 택1):
  - (B1) **동적 단일 마운트**: `/_served/mcp` 아래 이름별 라우팅, 요청 시 published 검사→해당 tools의
    FastMCP 앱 위임. lifespan/세션 매니저 처리 필요(mock_mcp처럼 stateless_http=True).
  - (B2) **published마다 앱 재구성**: 등록/publish 변경 시 서빙 레지스트리 갱신.
  - 기울기: B1(stateless) — mock_mcp와 동형, 재시작·핫스왑 단순.
- 인증: mock_remote/mock_mcp처럼 카드/discovery는 공개, 도구 호출은 라우트 인증(경계는 154 A2A
  서빙과 동형 — self-fetch 깨짐 방지 위해 카드 공개, 호출만 인증). **자격증명 위치가 API 경계**(129).
- 게이트(소유권 체크리스트): published 전환은 소유자/특권만(assert_may_manage), external 400,
  존재 비노출 404-fold. 서빙 라우트는 published=False면 404(노출 안 된 것 누출 금지).

### C. UI (에이전트 공개 미러)
- MCP 드로어에 "외부 공개(MCP 서빙)" 토글 — source∈{custom,local}만. 켜면 서빙 URL 표시(복사).
  external은 토글 숨김/비활성(재공개 불가 안내). 커스텀 MCP는 목록에 source 배지.

## 검증 (2026-07-03 완료)
- verify_156 9/9: V1 커스텀 행 source=custom, V2 publish 소유자/특권만·비소유 404, V3 **루프백**
  (MultiServerMCPClient로 우리 서빙 URL 접속→도구 목록+add(2,3)=5 실호출), V4 미공개 서빙 404,
  V5a external publish 400·V5b 정의 없는 custom 서빙 404, **V6 member의 source=custom 생성 400**(High 봉인).
- e2e 4/4(12 assert): 목록 커스텀 배지·드로어 공개 스위치·서빙 URL 노출·원복 실측(published False 복귀).
- codex High1/Med1/Low1 전부 반영(위 절). 서빙 라우트 lifespan(AsyncExitStack)·게이트·source 세탁 확인.

## codex 적대 리뷰 (2026-07-03 — High1/Med1/Low1 전부 반영)
- **High**: 기존 DB엔 calc-tools 미시드 + create가 source=custom 미차단 → member가 custom을 자가선언해
  서빙 레지스트리 이름 선점·공개 가능. **수정**: (a) create에서 source=custom **시스템 전용 400**,
  (b) create에서 **서빙 예약 이름(SERVED_MCPS) 400**(어떤 source로도 선점 금지 — 스쿼팅까지 차단),
  (c) custom 행은 seed의 멱등 reconcile만 생성(owner_id=None). update의 source 불변(152)이 custom 전환 차단.
- **Medium**: calc-tools 시드가 "빈 테이블만" → 기존 설치엔 기능 부재. **수정**: `_empty` 게이트 무관
  **매 부팅 멱등 reconcile**(SERVED_MCPS 이름에 행 없으면 system 소유로 insert).
- **Low(경계, 정직 기록)**: published custom MCP는 무인증 서빙(mock_mcp처럼 _auth 밖). **안전 불변식**:
  서빙 도구는 부수효과 없는 순수 도구만(`_SIDE_EFFECT_FREE_TOOLS` allowlist — 미등록 도구 서빙 시
  **부팅 실패**로 강제). HIL(delete_record류) 도구는 서빙 금지. 서명 토큰 인증은 OUT(후속).

## OUT
- UI에서 임의 Python 도구 작성(신뢰 레지스트리 코드젠만 — 099 철학). 다중 세션 stateful MCP.
- 서빙 사용량/레이트리밋·서명 토큰 인증(무인증 경계는 안전 불변식으로 봉쇄). 커스텀 MCP 도구 핫리로드.

## 확정 (사용자 승인 2026-07-03 — "우리가 외부 MCP 등록해 쓰는 것의 반대, 이미 다 쓰는 메커니즘")
- 마운트: **B1 동적 단일 마운트** `/_served/mcp` (stateless_http, mock_mcp 동형).
- source="custom" 신설(local|external|custom) — 우리가 코드로 정의·호스팅하는 서빙 가능 MCP. external 봉인.
- 서빙 도구는 **신뢰 in-code 레지스트리**(`served_mcp.py`)에서. UI Python 작성은 OUT(099 신뢰 등록 철학).
- 루프백 검증은 우리가 이미 쓰는 `MultiServerMCPClient`로 우리 서빙 URL에 붙어 확인(등록의 반대편 실증).

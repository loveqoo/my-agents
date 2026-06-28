# 054 — MCP 실연결 런타임 (HTTP/streamable, 합성 툴 제거)

> Planning. 사용자 지시: "MCP 기능 구현에 소홀했다 — 아마 하드코딩일 것."
> 서브에이전트 감사 결과 **구조(모델·CRUD·UI)는 실재, 런타임은 통째 가짜**(`runtime._CANNED`
> 하드코딩 문자열 반환, langchain-mcp-adapters 미통합)임을 확인. 이 스펙은 **런타임 실연결 한 층**을
> 채운다. 사용자 결정(AskUserQuestion, 2026-06-28): ① transport는 **HTTP(원격) 먼저**(stdio 유예),
> ② 모의 6개는 **실 mock MCP 서버로 대체**(spec 024 self-host 패턴), ③ 등록 도구목록은 **라이브 자동 탐색**.

관련: 스펙 007(런타임 §Phase2 유예 출처)·024(mock self-host)·042(net_guard SSRF)·041(HIL 게이트)·
010(secret at-rest)·013/045(연결테스트·liveness). learning 025(시드 drift)·026(mock=데이터+계약)·
039(drop-in=측정)·040(실인프라 rung)·044(가드 경계)·048(HIL 수명).

## 배경 — 무엇이 가짜인가

- `runtime.build_tools(mcp_pairs, calls_sink)`: (server, tool)마다 **합성 StructuredTool**을 만들어
  호출 시 `_CANNED.get(server, "ok (모의)")` 문자열을 반환하고 calls_sink에 트레이스만 남긴다.
  등록된 `McpServer.url`/`endpoint`는 **한 번도 닿지 않는다**(표시용 메타).
- `seed.MCP_SERVERS` 6행은 정적 카탈로그(tavily/gcal/gmail/notion/acme-weather/partner-crm) — 엔드포인트 미접촉.
- 등록(`POST /mcp-servers`)은 `tools`를 **수기 입력**으로 받는다(서버에 물어보지 않음).
- HIL 승인 게이트(041)·트레이스(calls_sink)·RAG 도구(037)는 **실재**이며 그대로 보존해야 한다.

## 범위 (이번 라운드)

**한다**: HTTP/streamable transport 실연결(`langchain-mcp-adapters` `MultiServerMCPClient`),
self-host 실 mock MCP 서버(`mcp` SDK `FastMCP`, `/_remote/mcp`), 라이브 도구 자동 탐색, auth at-rest,
SSRF 가드 재사용, 시드 양층 정합, 프론트 탐색 UX.

**안 한다(유예)**: stdio(로컬 서브프로세스) transport — 다음 라운드. 호스트 프로세스 spawn·생명주기
관리·보안 표면이 별개 작업. transport 필드는 유지하되 stdio는 등록 시 "미지원" 명시.

## 설계

### A. 의존성
- `packages/api/pyproject.toml`에 `langchain-mcp-adapters>=0.1`, `mcp>=1.0` 추가. `uv lock` 갱신.

### B. self-host 실 mock MCP 서버 (spec 024 패턴)
- `mock_remote.py`(또는 신규 `mock_mcp.py`)에 `FastMCP` 인스턴스 정의, **결정적 도구** 노출:
  - `web_search(query: str) -> str` — 입력 의존 결정적 결과(예: `f"[mcp] '{query}' 검색결과 3건..."`).
  - `echo(text: str) -> str` — 입력 그대로.
  - `delete_record(record_id: str) -> str` — **위험 도구**(HIL 게이트 대상). 부수효과 흉내.
- FastMCP의 streamable-http ASGI 앱을 FastAPI에 `/_remote/mcp`로 마운트(main.py). 인증 미검증(dev).
- 핵심: 반환은 `_CANNED`가 아니라 **서버가 실제로 계산한 값** — "실연결"의 측정 타깃(learning 039).

### C. 런타임 실연결 (`runtime.py`)
- `_CANNED` dict **삭제**. `build_tools`(합성)를 신규 async `build_mcp_tools(servers, calls_sink)`로 교체.
  - 입력 `servers`: `_load_context`가 해석한 dict 리스트 `{name, url, transport, enabled_tools, auth_token(복호화)}`.
  - `MultiServerMCPClient({name: {transport:"streamable_http", url, headers:{Authorization:...}}})` 구성
    → `await client.get_tools()` → `enabled_tools`로 필터.
  - 각 실 도구를 **래퍼로 감싼다**(세 계약 보존):
    1. **트레이스**: 호출 전후 calls_sink에 `{server, tool, status, ms, args, result}` 기록(기존 포맷 유지).
    2. **HIL 게이트(041)**: `(server, tool) ∈ _APPROVAL_ACTIONS`면 **실 도구 호출 이전에** `interrupt(...)`,
       거부 시 부수효과 0(실 도구 미호출). 승인 후에만 원 도구 실행 — 041 불변식을 실 도구 위에서 재성립.
    3. **graceful 실패**: 서버 다운·도구 오류·타임아웃은 잡아 status="error" + 문자열 반환(에이전트 크래시 금지,
       build_rag_tool과 동일 철학). 전체 작업 deadline은 `asyncio.timeout`으로(learning 046).
  - `_APPROVAL_ACTIONS` 키를 새 mock 도구로 갱신: `("<mock-server-name>", "delete_record"): "data.delete"`.
- SSRF: 연결 이전 `net_guard.guard_url(url)`(spec 042). loopback인 self-host mock은 `A2A_ALLOWED_HOSTS`로
  통과(이미 127.0.0.1 dev 허용). **빚**: allowlist 이름이 A2A 전용 — 공유 의미로 둘지 별도 env 둘지 §7.

### D. chat.py 배선
- `_load_context`: 현재 `ctx["mcp_pairs"]`(name,tool)만 → `ctx["mcp_servers"]`(위 dict 리스트)도 싣는다.
  `enabled_tools`/`url`/`transport`/`auth_token` 포함. auth_token은 저장값 복호화(마스킹값이면 None=헤더생략).
- 도구 빌드 지점(현 `runtime.build_tools(ctx["mcp_pairs"], ...)`)을 `await runtime.build_mcp_tools(ctx["mcp_servers"], ...)`로.
  RAG 도구 append·HIL checkpointer 부착 로직은 불변.

### E. 라이브 도구 자동 탐색 (013/045 패턴)
- 신규 `POST /mcp-servers/discover` (또는 `/test`): body `{url, transport, auth?}` → `guard_url` →
  `MultiServerMCPClient` 1회 연결 → 도구목록·상태 반환 `{ok, tools:[name...], error?}`. 부작용 없음(list만).
- 프론트 `BlocksView` McpForm: 수기 `tools` 입력 → **"연결 테스트" 버튼 → 자동 채움**으로 교체.
  실패 시 사유 표시. enabled_tools는 탐색된 tools에서 체크 선택.

### F. auth at-rest (spec 010)
- `McpServer`에 암호화 크리덴셜 보관. 기존 `auth`(스킴 라벨)는 유지하되 실제 토큰은 `auth_token`(암호화)로
  분리하거나, `auth`를 암호화 크리덴셜로 승격하고 응답에서 마스킹. (마이그레이션 최소안 택1 — Execution서 확정.)
- 저장: Fernet 암호화. 응답(GET): 마스킹(`••••`). 런타임: 복호화 → `Authorization: Bearer <token>` 헤더.
  마스킹/빈값이면 헤더 생략(a2a_client 규칙 동일). **응답에 평문 토큰 절대 노출 금지**(누출-안전).

### G. 시드 양층 정합 (learning 025)
- `seed.MCP_SERVERS`: 모의 6행 제거 → self-host mock MCP를 가리키는 **실 바인딩 1~2행**으로 대체
  (`url=http://127.0.0.1:8000/_remote/mcp`, transport=http, tools=탐색결과). 시드 에이전트
  (Research Assistant→tavily 등) 참조를 유효 서버명으로 재지정.
- 라이브 DB: 사용자 DB엔 옛 6행이 있음 → **멱등 reconcile**(idempotent reseed/마이그레이션)로 교체.
  소스만 고치면 drift(learning 025) — 라이브 적용까지 한 단위. 서버 재기동 포함(사용자 원격이라 내가 수행).

## 완료 조건 (측정 가능 — 자가검증 지양, 타자 우선)

1. `MultiServerMCPClient`가 self-host `/_remote/mcp`에 연결, `get_tools()`가 **≥2 실 도구** 반환(통합).
2. mock 서버 바인딩 에이전트 실행 → calls_sink에 **FastMCP가 실제 계산한 결과**가 기록되고, 그 결과에
   `"(모의)"`/`_CANNED` 문자열이 **없다**. (실연결의 결정적 증명 — learning 039)
3. `grep _CANNED`(runtime.py) = 0. 합성 경로 완전 제거.
4. `POST /mcp-servers/discover`: mock URL → 실 도구목록 반환; 사설대역 비-allowlist URL → SsrfBlocked 4xx.
5. HIL(041): 위험 실 도구(`delete_record`)가 **부수효과 이전 interrupt**, 거부 시 실 도구 미호출(probe green).
6. auth: GET 응답에 평문 토큰 없음(마스킹); 단위로 복호화→헤더 + 마스킹값→헤더생략 단언.
7. 시드 reconcile: 라이브 DB가 실 바인딩 MCP 서버 보유·옛 모의행 부재·시드 에이전트 참조 유효(불변식/델타, learning 034).
8. 프론트 탐색: 등록 폼에서 "연결 테스트→tools 자동채움" 브라우저샷 캡처(self-fixture, memory verify-ui).
9. `tsc` 통과 + 적대 타자 리뷰 블로커 0·fail-open 0(SSRF 경계·auth 누출·HIL 우회·부분실패·enabled_tools 강제).

## 실행 단계 (per-phase, 큰 단위는 내부 분할)

- **P1 (코어 실연결)**: A 의존성 + B self-host MCP + C runtime + D chat 배선 + SSRF. → 완료조건 1·2·3·5.
- **P2 (탐색 + 등록 UX)**: E discover 엔드포인트 + 프론트 + 브라우저샷. → 4·8.
- **P3 (auth·시드·검증·회고)**: F auth at-rest + G 시드 reconcile + 적대 리뷰 + 회고/자산화. → 6·7·9.

## 검증 (사다리 — learning 040)

1. **단위**(인프라 불요): 도구 래핑이 트레이스·HIL·enabled_tools 필터·auth 마스킹을 보존하는지(FakeClient 주입).
2. **실인프라 통합**: 라이브 서버 띄우고 실 등록→탐색→에이전트 실행→실 결과. 단위·적대가 못 보는 글루를 잡음(040).
3. **UI 통합**: 브라우저샷(self-fixture) — 탐색 자동채움 분기 시각 확인(memory verify-ui-in-browser).
4. **적대 타자**(서브에이전트/codex): SSRF(리다이렉트 재해석 044)·auth 누출·HIL 실도구 우회·부분실패 격리·
   enabled_tools 외 도구 비호출·미초기화 fail-closed. 자가검증 단정 금지.

## §7 빚·한계·비범위

- **stdio transport 유예** — 로컬 서브프로세스 MCP는 다음 라운드(호스트 보안·생명주기 별 작업).
- **SSRF allowlist 이름**: `A2A_ALLOWED_HOSTS`를 MCP outbound에도 재사용 → 공유 의미. 별 env로 가를지
  Execution서 결정(현 단계 빚으로 명시). 리바인딩 TOCTOU 한계는 042 §7 그대로 승계.
- **auth 스키마 최소 마이그레이션**: `auth` 승격 vs `auth_token` 신설은 Execution서 마이그레이션 비용으로 택1.
- **도구 입력 스키마**: 실 MCP 도구는 자체 JSON 스키마를 갖지만, 현 트레이스/HIL은 `query` 단일 인자 가정.
  MultiServerMCPClient가 주는 실 스키마를 그대로 쓰되, calls_sink args 기록은 범용 dict로 — 1라운드 범위.
- **라이브 reconcile는 비가역 가능성**: 옛 모의행 삭제 전 dry-run 검토(파괴적 정리 규칙, memory adversarial-review).

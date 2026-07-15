# 360 — 자체 served MCP는 SSRF 가드 예외 (리셋 후 web-fetch 502 봉합)

## 왜 (실물 확증 — 사용자 신고 + 근인 추적)

데이터 초기화 후 회사에서 web-fetch MCP "테스트"가 **502 Bad Gateway**. 근인 추적:

- web-fetch는 **우리 자체 served MCP**(스펙 201)로 `http://127.0.0.1:8000/_served/mcp/web-fetch/`에
  서빙된다(플랫폼이 자기 자신에 붙는 로컬 엔드포인트).
- MCP "테스트"(`blocks.py:566 test_mcp_tool`)는 `build_mcp_tools`로 그 URL에 연결해 도구를 나열한다.
  연결 전 `mcp_connection`(runtime.py:224)이 `net_guard.guard_url`로 SSRF 검사 → **127.0.0.1은 루프백이라
  차단**(allowlist에 없으면). 차단 시 서버 스킵 → tools=[] → `test_mcp_tool`이 502(blocks.py:594).
- 리셋이 근인: `allowed_hosts`는 마이그레이션 `d0e1f2a3b4c5`가 env `ALLOWED_HOSTS`로 **1회만** 시드.
  데이터 초기화로 행이 지워졌는데 마이그레이션은 재실행 안 되고 seed.py도 allowed_hosts를 안 넣어,
  127.0.0.1이 사라진 채 남는다(사용자 진단 정확).

## 설계 — 자체 served MCP는 SSRF 판정 대상이 아니다 (사용자 선택 A)

served MCP의 목적지는 **사용자 입력이 아니라 `served_url(name)`으로 플랫폼이 결정한 고정 로컬 URL**이다
(우리 앱이 자기 자신에 연결). SSRF(사용자가 내부망을 찌르는 것)가 아니므로 사용자 SSRF 가드를 태울
이유가 없다. 127.0.0.1을 사용자 allowlist에 넣는 방식(B)은 SSRF 표면을 넓히므로 기각 — 대신 자체 served
연결을 가드에서 **예외**한다.

- **예외 판정은 의도 신호로 타이트하게**: `name in SERVED_MCP_TOOLS`(플랫폼 코드 레지스트리) **그리고**
  `url == served_url(name)`(그 이름의 결정론적 served URL과 정확 일치)일 때만. 둘 다 만족해야 예외.
- **사용자 우회 불가**: served 이름(web-fetch·calc-tools)은 `McpServer.name` 유일 제약으로 이미 예약 —
  사용자가 그 이름으로 서버를 못 만든다. 다른 이름에 served URL을 박아도 `name in SERVED_MCP_TOOLS`가
  거짓이라 예외 안 됨. 정확 일치라 prefix/traversal 애매성 없음.
- **예외해도 목적지 안전**: 그 URL은 우리 served 마운트뿐이고, 미등록/미공개 이름은 마운트의 자체
  게이트(`_is_served`: published+source=custom+레지스트리)가 404로 막는다 — 예외는 SSRF 검사만 건너뛰지
  served 게이트는 그대로.
- **chokepoint 한 곳**: `mcp_connection`은 `build_mcp_tools`(그래프 preload)와 브로커 `McpProvider`가
  공유하는 단일 SSRF 관문 → 여기 예외를 넣으면 두 경로가 균일(드리프트 0, learning: policy-at-chokepoint).

## 완료 조건 (수치)

- **E1** `is_own_served_url(name, url)`: (web-fetch, served_url("web-fetch"))→True; 스푸핑
  ((myname, served_url("web-fetch"))·(web-fetch, "http://evil/..."))→False.
- **E2** allowed_hosts에 **127.0.0.1이 없어도** web-fetch served MCP 연결 성공(tools 나열, 502 없음) —
  실측(127.0.0.1 임시 제거 후 test_mcp_tool).
- **E3** 무회귀 — 외부(source=external) MCP·비-served 로컬은 여전히 guard_url 적용(사설/루프백 차단 유지);
  allowlist에 있는 dev mock 통과 무변경.
- **E4** codex 적대 검토(SSRF 경계) — 예외로 임의 내부 URL 연결 가능한 우회 여집합 확인.
- **E5** `make test` 씨앗 그물 SUITE_OK.

## 결과 (2026-07-15)

- `served_mcp.is_own_served_url` + `runtime.mcp_connection` 예외 착지. verify_360 E1/E2/E3 통과,
  E2는 127.0.0.1 임시 제거 후 calc-tools·web-fetch 둘 다 200 실측. 씨앗 그물 SUITE_OK(E5).
- **E4 codex 적대 검토(SSRF 경계) 결과: P0 우회 없음**. 4개 공격 모두 BLOCKED —
  ① served 이름 재사용(name 유일 제약 + seed reconcile이 source=custom·owner=None으로 선점 + blocks.py
  생성 게이트가 예약어·custom 차단), ② 문자열 정규화 우회(정확 파이썬 문자열 일치라 트레일링슬래시·
  대소문자·127.1·[::1]·8진/10진 IP·userinfo·IDN·기본포트 전부 불일치→guard_url로 폴백), ③ served
  마운트 자체 프록시/리다이렉트(calc=순수 산술, web-fetch=위키 ko/en 고정+리다이렉트 최종호스트
  wikipedia.org 검증, `_is_served` 게이트가 source=custom·published 요구), ④ 공유 호출부 6곳
  (build_mcp_tools·chat·chat_stream·chat_approval·eval_runner·broker) 모두 정확 일치라 임의 내부 URL
  불가. **방어심화 반영**: codex가 지적한 비-P0 갭(개명 경로에 예약어 검사 없음 — 시스템 served 행이
  지워진 틈에 사용자 행을 served 이름으로 개명 가능, 단 url 정확 일치 필요라 임의주소 불가)을
  `update_mcp_server` 개명 블록에 생성 게이트와 대칭인 `SERVED_MCPS` 검사로 봉합(blocks.py).

## OUT

- web-fetch 도구 **호출** 시 위키(en.wikipedia.org) 아웃바운드는 정상 SSRF 정책 대상(외부 호스트는
  allowlist 필요) — 이 스펙은 자체 served **연결**(테스트/나열)의 502만 봉합.
- allowed_hosts를 리셋 후 재시드하는 것(방식 B) — 채택 안 함(예외가 근본 해결·표면 안 넓힘).

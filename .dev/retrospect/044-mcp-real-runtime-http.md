# 044 — MCP 실연결 런타임: 가짜 한 층을 실 프로토콜로 갈아끼우다

스펙: `docs/spec/054-mcp-real-runtime-http.md`
관련: learning 055(이 회고의 일반화 — 새 아웃바운드 경로·의존성 기본값) ·
[[039-redirect-ssrf-on-new-outbound-path]] 류의 가드-경계 메타패턴(044/018/050) ·
learning 025(시드 drift 양층)·026(mock=데이터+계약)·039(drop-in=측정)·040(실인프라 rung)·
051(거짓 green=도구 충실성) · 스펙 024(self-host mock)·042(net_guard)·041(HIL)·010(secret at-rest).

## 무엇을 / 왜

사용자 지시: "MCP 기능 구현에 소홀했다 — 아마 하드코딩일 것." 감사 결과 **구조(모델·CRUD·UI)는
실재, 런타임은 통째 가짜**였다(`runtime._CANNED` 하드코딩 문자열 반환, langchain-mcp-adapters
미통합, 등록 URL 한 번도 안 닿음). 이 스펙은 **런타임 실연결 한 층**을 채웠다 — 3페이즈:
- **P1**(코어 실연결): `_CANNED` 폐기 → `MultiServerMCPClient` 실연결, self-host 실 mock MCP
  (`FastMCP` `/_remote/mcp`), 트레이스·HIL(041)·graceful 래퍼 보존.
- **P2**(탐색+UX): `POST /mcp-servers/discover` 라이브 자동탐색 + 프론트 "연결 테스트→자동채움".
- **P3**(auth·시드·검증·회고): auth at-rest(010) + 시드 양층 reconcile + 적대 리뷰 + 자산화.

## 결정 (Execution서 확정한 빚 2건)

1. **auth 스키마 — Option B(승격)**: 스펙은 "`auth`(스킴 라벨) 유지 + `auth_token` 신설" vs
   "`auth`를 암호화 크리덴셜로 승격" 택1을 Execution에 미뤘다. **승격**을 골랐다 — `auth`를
   스킴 라벨로 *읽는 코드가 아무 데도 없었고*, providers.py의 `api_key`(암호화 단일 컬럼)와
   대칭이라 더 깨끗했다. 컬럼 폭 String(120)→(400)(Fernet 암호문) 마이그레이션 1건.
2. **SSRF allowlist 이름**: `A2A_ALLOWED_HOSTS`를 MCP outbound에 재사용(공유 의미). 별 env로
   가르는 건 다음 라운드 빚으로 명시(§7 승계).

## 핵심 사건 — 적대 리뷰가 잡은 2개 (둘 다 happy-path 초록)

### H1. 리다이렉트-SSRF: 새 아웃바운드 경로가 가드를 자동 상속하지 않았다
`net_guard.guard_url`(042)은 **최초 URL의 해석 IP만** 검사한다. 그런데 새로 들인
`MultiServerMCPClient`(정확히는 그 밑의 httpx 클라이언트)는 `follow_redirects=True`가 기본 —
공인 URL이 `guard_url`을 통과한 뒤 **3xx로 사설/메타데이터 대역으로 재유도**되면, 가드는
이미 끝났고 **복호화된 Bearer 토큰까지 재전송**된다. 레포는 a2a_client/agent_card에서
`follow_redirects=False`로 이걸 막아왔지만, MCP라는 *새 경로*는 그 방어를 안 물려받았다.
→ `net_guard.mcp_http_client_factory`(follow_redirects=False, fail-closed) 신설 + runtime·
blocks.discover **두 outbound 지점**에 배선. 회귀가드는 "팩토리 존재"가 아니라 **클라이언트가
실제로 `follow_redirects is False`**를 단언(T8) — `installed-guard-isnt-covering-guard` 교훈대로.

### H2. dry-run 부정직: 리포트는 필터, apply는 무조건
reconcile의 `_apply`가 모든 version.config를 무조건 재작성+flag_modified 했는데, 리포트는
`vb!=va`인 것만 보여줬다 → **"보여준 것"과 "건드린 것"이 불일치**(dry-run이 거짓 안심).
→ `_apply`가 *plan이 담은 데이터만* 소비하도록: config는 before!=after일 때만, version은
plan의 `vers`(=실제 바뀌는 버전)만 `by_ver` dict로 골라 재작성. 리포트==apply 계약 복원.

부수로 발견: `NEW_TOOLS`가 seed와 reconcile에 **평행 리터럴**(drift 씨앗) → `mock_mcp.py`에
`MOCK_MCP_TOOLS` 단일 소스 신설, 둘 다 import.

## 검증 사다리 (4 rung — 자가검증 지양)

1. **단위(in-process)**: auth at-rest 18/18 — create→마스킹 응답, DB 암호문+복호 왕복,
   list/get/blocks 전수 마스킹 + 전역 평문 스캔, 마스킹-PUT 보존·신규-PUT 재암호·""-PUT 제거,
   런타임 배선(암호문→토큰/마스킹→None/빈값→None). ASGITransport라 실행 서버와 무관하게 새 코드 검증.
2. **실인프라 통합**: T1–T8 라이브 — self-host mock에 실연결(3도구), web_search/echo가 **서버
   실계산값**(`(모의)` 0), enabled_tools 필터, SSRF 스킵, graceful, transport 게이트, +T8 H1 회귀.
3. **UI 통합(브라우저샷)**: Playwright+시스템 Chrome, 로그인→빌딩블록→MCP 탭→외부 등록→인증
   스킴 Select "Bearer 토큰"→Input.Password+"Fernet 암호화" 안내 캡처. 모달 뒤 테이블에
   local-tools 1행(가짜 6행 사라짐)도 시각 확인.
4. **적대 타자**: 독립 리뷰어 2명이 H1·H2 적발 → 둘 다 수정·재검증.

## reconcile 적용 (비가역, dry-run 먼저)

라이브 DB는 옛 가짜 6행 보유 → `--apply` 전 dry-run 재확인(깨끗) → 적용(6행 삭제, local-tools
생성, 에이전트 3개+버전들 재매핑) → **멱등 재실행(변경 0)** 확인. 서버는 `--reload`라 코드
자동반영(verify가 delete_record 포함 3도구 받은 게 증거) — 수동 재기동 불요.

## 배운 것 → learning 055

핵심 일반화: **새 아웃바운드 경로/새 의존성은 기존 네트워크 가드를 자동 상속하지 않고, 오히려
위험한 기본값(follow_redirects=True)을 들고 들어온다.** 가드는 "설치됨"이 아니라 "이 경로에서
*실제로 켜졌는지*"를 단언해야 하고, 그 단언은 설정값 자체를 본다.

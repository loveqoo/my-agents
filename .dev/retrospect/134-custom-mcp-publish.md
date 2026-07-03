# 134 — 내부(커스텀) MCP 외부 공개 (스펙 156, 실사용 #4)

자율 루프 7건차(B 시리즈 마지막 직전). "우리가 외부 MCP를 등록해 쓰는 것의 **반대편**" — 우리가
코드로 정의한 MCP 도구를 진짜 MCP 엔드포인트로 서빙해 외부가 붙게 했다(에이전트 A2A 서빙의 MCP판).

## 무엇을 했나
- 서빙 프리미티브: LangChain `@tool` → `to_fastmcp` → `FastMCP(tools=[...], streamable_http)` →
  `/_served/mcp/{name}` 마운트(mock_mcp 동형). "langgraph에서 mcp 만들어 외부 공개"의 실체.
- 공개 가드: 요청마다 DB로 published + source=custom + 레지스트리 존재 확인, 아니면 404.
- source에 `custom` 신설(우리 코드 정의·호스팅). external은 서빙 불가(152 봉인 유지).
- UI: 커스텀 배지·서빙 URL 표시·publish 스위치, 편집 시 source 불변 보존.

## 배운 것 (상기용)
1. **범위 확인 ≠ 헷갈림, 하지만 사용자가 "이미 다 쓰는 메커니즘"이라 하면 과설계 신호다.** MCP 서빙은
   FastMCP(mock_mcp)로 이미 돌고 있었고 클라이언트(MultiServerMCPClient)도 이미 썼다. 신뢰 레지스트리
   코드젠 같은 큰 authoring 시스템을 상상했지만, 실제로 필요한 건 **기존 두 조각을 뒤집어 붙이는 것**
   뿐이었다. 사용자가 "반대로 하는 것"이라 지목하면 새 서브시스템이 아니라 **대칭 뒤집기**를 먼저 보라.
2. **provenance를 사용자가 자가선언하게 두면 게이트가 넓어진다(152의 MCP 재현).** source=custom을
   "우리가 정의한 것"의 표식으로 삼았는데, create가 그 값을 사용자 입력으로 받으면 아무나 custom을
   선언해 내부 레지스트리 이름을 선점·공개할 수 있다(codex High). **유래 표식은 시스템만 스탬프**해야
   한다 — custom은 seed reconcile만 생성(owner_id=None), 사용자 입구에선 400. [[installed-guard-isnt-covering-guard]]·
   spec 152 유래-불변 계열. 나아가 **예약 이름은 어떤 source로도 선점 금지**(스쿼팅 DoS까지).
3. **"빈 테이블만 시드"는 기존 설치에 새 기능을 안 실어준다.** calc-tools를 `_empty` 게이트 안에 두니
   신규 DB에만 생기고 기존 운영 DB엔 안 나타난다(codex Medium). 새 시드 로우는 **_empty 무관 멱등
   reconcile**로 매 부팅 보장해야 한다(그리고 그 reconcile이 유래 표식의 유일한 정당 생성 경로가 되어
   High 봉인과 합쳐진다 — 한 수정이 두 결함을 닫음).
4. **무인증 서빙면엔 안전 불변식을 코드로 박아라.** 서빙 라우트는 self-fetch 호환 위해 _auth 밖(mock_mcp·
   A2A 카드 관례) → published custom MCP는 무인증 공개 API다(codex Low 경계). 지금 도구는 무해하나
   부수효과 도구가 레지스트리에 들어가면 publish 플래그 하나가 무인증 실행면이 된다. → **서빙 도구
   allowlist(`_SIDE_EFFECT_FREE_TOOLS`)**, 미등록 도구 서빙 시 **부팅 실패**로 강제(무심코 위험 도구
   서빙을 컴파일타임에 차단). [[adversarial-review-before-destructive-ship]]·[[complement-attack-can-be-honest-boundary]].

## 삽질 (도구 운영)
- codex를 백그라운드 실행하니 stdin이 안 닫혀 `Reading additional input from stdin...`에서 10분+ 블록.
  프롬프트는 인자로 넘겼으니 stdin 불필요 → **`< /dev/null`로 재실행**해 해결. 백그라운드 codex는
  항상 stdin 리다이렉트. (다음에 같은 실수 안 하도록 기록)

## 검증
- verify_156 9/9(루프백 add(2,3)=5 실호출·공개 게이트·external 400·미공개 404·member custom 생성 400).
- e2e 4/4(12 assert): 커스텀 배지·공개 스위치·서빙 URL·원복 실측.
- codex High1/Med1/Low1 전부 반영·재검증.

# 295 — 도구 실행 실패 사유를 인스펙터에 표면화 (스펙 320)

## 무엇을 했나

도구 실행이 실패했을 때 인스펙터에서 **왜 실패했는지(사유)**를 볼 수 있게 했다. 실패 기록이 예외 타입만이
아니라 사람이 읽을 사유 문자열(`error` 필드, 마스킹+캡)을 싣고, 프론트 `ErrorReason` 컴포넌트가 직접
MCP·RAG·브로커 세 표면 모두에 그 사유를 렌더한다.

## 핵심 배운 것

### 1) 어댑터 swallow는 예외를 내지 않는다 — 단위 fake로 못 잡고 기능 rung만 잡음
스펙 초안은 "MCP 도구가 실패하면 `except`가 잡는다"를 전제했다. **틀렸다.** langchain-mcp-adapters는 MCP
`isError=True`를 `ToolException(_MCPToolExecutionError)`으로 만든 뒤 **tool.handle_tool_error로 삼켜
정상 문자열**("Error executing tool …")로 돌려준다 → `rt.ainvoke`가 예외를 안 내고, `status="ok"`로 오기록,
사유 소실. 단위 테스트는 "예외를 raise하는 StructuredTool"로 검증했는데 그건 **현실에 없는 경로**였다(초록이
거짓). **진짜 MCP 도구를 태운 브라우저 rung에서만** `status:"ok" + result:"Error executing tool…"`이 드러났다.
수정: `rt.handle_tool_error = False`로 삼킴을 꺼 예외를 우리 except로 전파. → learning "UI 검증은 기능으로"가
도구 실행 계층에서 재현. **적대 rung 이전에 기능 rung이 이미 설계 전제를 깼다** — happy-path 단위는 상상한
실패만 본다.

### 2) 형제 표면 비일관 — 직접 경로만 고치면 브로커가 샌다 (codex P1a)
직접 MCP 경로(`_wrap_mcp_tool`)만 `handle_tool_error=False`를 걸었더니, **브로커 MCP provider**
(`broker/providers/mcp.py invoke`)는 여전히 삼켜 `res.error=None`으로 실패가 조용히 사라졌다. 조율형/노드가
같은 MCP 도구를 부르면 성공처럼 보인다. codex가 정적 검토로 잡음. 스펙 319 "펜스를 파이프 도구 결과 전체에
걸어야 정합"과 **같은 형제-표면 클래스**. 두 경로가 같은 실패 표면화 규약을 공유하도록 provider.invoke도 동일
수정 + U7 브로커 회귀 단위.

### 3) 새 노출 표면은 마스킹도 넓혀야 (codex P1b)
사유를 표면화하면 **예외 메시지 자체가 새 누출 벡터**다. MCP 서버 예외는 라벨 없는 자격증명(URL userinfo
`scheme://user:pass@`·`Basic <blob>`)을 담을 수 있는데 공용 `_SECRET_RE`는 `sk-`/`Bearer`/라벨형만 잡았다.
`Basic\s+<base64>` + `(?<=://)user:pass(?=@)`(호스트 보존, userinfo 없는 URL은 `@` 없어 미매치) 추가.
공용 마스커라 result·resultPreview·메모리 진단까지 함께 강해짐. **사전 gap이지만 320이 그 표면을 증폭하니
같은 턴에 봉합**(전체 정합 > 최소 수선).

### 4) 테스트 인프라가 프로덕션 표면을 넓히면 오염 (codex P2)
실패 유발 도구 `failing_op`를 mock의 seed 카탈로그(`MOCK_MCP_TOOLS`)에 넣었더니, `local-tools`를 문 데모
에이전트가 "실패/오류" 질의만으로 의도 실패 도구를 호출해 오염될 뻔했다. 도구 정의(`@mcp.tool`)는 라이브
등록으로 남기되 **seed enabled 집합에서 빼고**, 브라우저 rung이 **전용 임시 MCP 서버**(mock URL·
`enabled_tools=[failing_op]`)를 만들어 hermetic하게 쓰고 teardown서 삭제. 테스트가 공용 상태를 안 건드림.
(초기엔 공용 `local-tools`를 rediscover+PUT enable로 오염시켰고 published 플래그까지 뒤집었다 → 리팩터로
격리 + DB 원복.)

### 5) 수단이 모델-facing 정보를 지우면 그것도 복원하라
`handle_tool_error=False`는 부작용으로 **모델이 보던 어댑터 상세 문자열을 지웠다**(모델은 이제 terse graceful
텍스트만 봄). 트레이스에만 사유를 넣으면 에이전트는 왜 실패했는지 몰라 적응/재시도를 못 한다. 모델-facing
text에도 사유를 실어(toolbox agent-call이 str(exc)를 싣는 선례와 동형) 인스펙터와 모델 양쪽이 같은 사유를 봄.

## 검증
- 단위(verify_320): U1~U8 — MCP 예외·성공무회귀·브로커 프레임·RAG 사유·마스킹·캡 + **U6/U6b 어댑터 swallow
  무력화** + **U7/U7b 브로커 경로** + **U8/U8b URL userinfo·Basic 마스킹·오탐방지**.
- 기능(브라우저): 전용 임시 서버+진짜 실패 도구→trace.error→인스펙터 "실패 사유" 렌더, 11/11 hermetic.
- 회귀: 054·319·041·100·101·294 전종·lint/type/tsc/build 클린.
- 적대(codex): P1a(브로커)·P1b(마스킹)·P2(seed) 수정, P3(요약칩 카운트)=백로그. 정적 검토(read-only 샌드박스
  라 uv 실행 불가—코드 경로 기반).

## 잔여
- codex P3: 메시지 요약 칩의 브로커 MCP 실패 카운트 누락(인스펙터 카드는 정합, 상단 칩만) → 백로그.
- verify_125 "E 정상" 실패는 **사전** stale fake — `memory.__init__:182 search(..., threshold=0.0)`(스펙 158)를
  `_FakeBackend.search()`가 미수용. 내 변경 무관(정규식이 TypeError 못 냄). stale verifier 일괄 갱신 대상.

관련: [[whole-fix-over-minimal-patch]] · [[ui-verification-must-be-functional]] · [[context-control-propagates-to-affordances]](형제 표면) · [[use-codex-for-adversarial-verification]] · 스펙 319(펜스 형제화)

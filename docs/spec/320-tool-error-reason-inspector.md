# 320 — 도구 실행 실패 사유를 인스펙터에 표면화

## 배경 / 동기

사용자 요구(2026-07-13): **도구 실행이 실패했을 때 인스펙터에서 에러 내용·사유를 볼 수 있어야 한다.**

현 상태 점검:
- 인스펙터는 실패를 **표시는 한다** — 빨간 아이콘(`Inspector.tsx:97 close-circle`)·"실패"/"검색 실패" 태그
  (`:287·389`). 하지만 **사유가 버려진다**:
  - **MCP 도구**(`runtime.py:148`): `text = f"도구 실행 실패(...): {type(exc).__name__}"` — 예외 **클래스명만**
    남기고 실제 메시지(`str(exc)`)를 버린다. "TimeoutError"는 보여도 "왜/어디서"가 없다.
  - **브로커·에이전트 도구**(`broker/core.py:48-49`): `if res.error: inv["error"] = True` — `res.error`(사유
    **문자열**, 예: "capability not found"·"대상 없음")를 **불리언 True로 뭉갠다**. 사유 소실.
  - 프론트는 `error`를 **불리언으로만** 읽어(`Inspector.tsx:287·389`) "실패" 태그만 낸다.
- 즉 "실패했다"는 보이는데 "왜 실패했나"가 안 보인다.

정밀 디버깅 통로(플레이그라운드) 원칙상 보여줄 수 있으면 보여준다 — 단 에러 메시지는 민감정보를 흘릴 수
있으므로(learning 092 "에러가 입력 샌다"·065 "사유는 중앙 경계서 surface"·089 값 allowlist) **마스킹+캡**
백스톱을 반드시 통과시킨다.

## 설계

### 1) 통일 `error` 필드 — 실패 기록에 sanitized 사유 문자열

실패한 모든 도구/브로커 호출 기록이 **사유 문자열**을 실은 `error` 필드를 갖는다(불리언 아님). 단일 스키마.

- **MCP 도구**(`runtime.py _wrap_mcp_tool`): `except`에서 `str(exc)`를 포착해 사유로. calls_sink 기록에
  `"error": _sanitize_preview(f"{etype}: {exc}", _ERR_CAP)`(etype=예외 타입, 앞 밑줄 제거—어댑터 내부
  클래스명 `_MCPToolExecutionError` 정돈). 모델-facing text에도 사유를 실어(에이전트가 실패 인지·적응).
  - **⚠ 핵심 함정(기능 rung이 잡음)**: MCP 도구 실패는 **파이썬 예외로 전파되지 않는다.**
    langchain-mcp-adapters가 MCP `isError=True`를 `ToolException(_MCPToolExecutionError)`으로 만든 뒤
    **tool.handle_tool_error로 삼켜 정상 문자열**("Error executing tool …")로 돌려준다 → `status="ok"`로
    오기록되고 사유 소실. 예외를 raise하는 단위 fake로는 이 경로가 안 잡혔고, **진짜 MCP 도구를 태운
    브라우저 rung에서만** 드러났다. 수정: `rt.handle_tool_error = False`로 어댑터 삼킴을 꺼 예외가 우리
    except로 전파되게 한다(전송/프로토콜 실패는 원래 ToolException 아니라 이미 전파 — 한 경로로 수렴).
- **브로커·에이전트 도구**(`broker/core.py _build_frame`): `inv["error"] = True` → `inv["error"] =
  _sanitize(res.error, cap=_ERR_CAP)`(사유 문자열 보존). `res.error`는 이미 사유 문자열(`InvokeResult.error`,
  스펙 318 `error="대상 없음"`). **후방호환**: 비어있지 않은 문자열은 truthy라 프론트 `b.error ? …` 태그
  분기 유지 + 사유 표시만 추가.
- **RAG 도구**(`runtime.py build_rag_tool`): `RagSearchError.tool_msg`가 이미 사람 사유("임베딩 실패: …"·
  "검색어가 비어 있습니다"). calls_sink 기록의 `error`에 그 사유를 싣는다(현 graceful 문자열과 같은 원천).
- **브로커 MCP provider**(`broker/providers/mcp.py invoke`, codex 320 P1a): 직접 경로만 고치면 **형제 표면
  비일관** — 조율형/브로커가 같은 MCP 도구를 부르면 어댑터 삼킴이 그대로라 `res.error=None`으로 실패가
  조용히 사라진다. provider.invoke도 `row.tool.handle_tool_error = False`로 끄고 except에서 `{etype}: {exc}`
  사유를 `res.error`에 싣는다(직접·브로커가 같은 실패 표면화 규약 — 스펙 319 펜스 형제화와 동형).

### 2) 보안 — 마스킹+캡 백스톱(사유가 새 표면)

- 사유는 반드시 `_sanitize`(비밀 마스킹, 스펙 125/211) 통과 + `_ERR_CAP`(500자) 절단. 에러 메시지에
  섞인 토큰·경로·입력값 누출 차단. 전문 스택트레이스는 **서버 로그**에만(클라엔 한 줄 사유, learning 092
  "크게 거부·좁게 공개").
- **마스킹 강화**(codex 320 P1b): MCP 서버 예외는 라벨 없는 자격증명(URL userinfo `scheme://user:pass@`·
  `Basic <blob>`)을 담을 수 있는데 기존 `_SECRET_RE`는 `sk-`/`Bearer`/라벨형만 잡았다. `_SECRET_RE`에
  `Basic\s+<base64>` + `(?<=://)user:pass(?=@)`(호스트/포트 보존, userinfo 없는 URL은 `@` 없어 미매치)를
  추가. 공용 마스커라 result·resultPreview·메모리 진단 등 모든 sanitized 표면이 함께 강해진다.

### 3) 프론트 인스펙터 — 사유 표시

- `Inspector.tsx` 도구/브로커 호출 렌더에서 `error`(문자열)가 있으면 **사유를 빨간 텍스트/Alert**로 표시
  (기존 "실패" 태그 옆·result 위). 두 렌더 지점(직접 calls_sink `:90~`·브로커 calls `:210~`) 모두 정합
  (형제 표면 승계). `error`가 문자열이 된 만큼 타입(`mockData.ts`)도 `error?: string`로.

### 4) 테스트 인프라 — 실패 유발 도구(codex 320 P2)

- 결정적 실패 도구 `failing_op`(mock_mcp.py `@mcp.tool`, `reason`으로 예외)를 등록하되 **seed 카탈로그
  (`MOCK_MCP_TOOLS`)에는 넣지 않는다** — seed enabled_tools에 들면 `local-tools`를 문 데모 에이전트가
  "실패/오류" 질의만으로 의도 실패 도구를 호출해 오염된다. 도구는 라이브 등록되므로, 브라우저 rung이
  **전용 임시 MCP 서버**(mock URL·`enabled_tools=[failing_op]`)를 만들어 hermetic하게 쓰고 teardown서 삭제.
- `mock_remote.py` 트리거("실패/에러/오류/fail"→failing_op)는 그 도구가 실제 바인딩된 턴에만 발화(무해).

## 범위 밖 (OUT)

- 전문 스택트레이스·재현 커맨드 UI(사유 한 줄+캡으로 충분; 전문은 서버 로그).
- 재시도 버튼·자동 복구.
- 에러 분류/그룹핑 통계.
- 성공 호출의 result 표시 변경(무회귀 — 이 스펙은 실패 경로만).
- **메시지 요약 칩의 브로커 MCP 실패 카운트**(codex 320 P3): 인스펙터 카드는 실패 사유를 표시하지만
  접힌 메시지 상단 칩의 "mcp 실패" 카운트는 직접 `trace.mcp`만 세고 `brokerCalls`의 non-rag 실패는 안 센다.
  320의 핵심(카드 표면화)은 충족 — 요약 칩 정합은 백로그 후속(`.dev/backlog.md`).

## 검증 (사다리 3런)

- **단위**: MCP 강제 실패 → calls_sink에 `error` 사유(마스킹·캡 단언)·예외 타입+메시지 병기. 브로커 실패
  (`InvokeResult(error=...)`) → `_build_frame`이 `error` 사유 문자열 보존(불리언 아님). RAG `RagSearchError`
  → 사유 전달. 비밀 마스킹 백스톱(사유에 토큰 넣어 마스킹 확인).
- **기능(브라우저)**: 실패하는 도구를 태운 채팅 → 인스펙터에 **사유 텍스트 표시**(외형 아닌 동작 —
  실제 실패 유발 후 사유 노출 단언). mock MCP에 실패 트리거 도구 활용/추가.
- **적대(codex)**: 사유에 비밀/입력값 넣어 마스킹·캡 우회 시도. 두 렌더 지점 비대칭(한쪽만 노출) 여부.

## 완료 조건

- MCP·RAG·에이전트/브로커 도구 실패 시 인스펙터에 **사람이 읽을 사유**가 뜬다(예외 타입만이 아니라 메시지).
- 사유는 마스킹+캡 통과(비밀 누출 0). 두 렌더 지점(직접·브로커) 정합.
- 성공 경로·기존 trace 무회귀. ruff/mypy/tsc/vite 클린. codex 적대 통과.

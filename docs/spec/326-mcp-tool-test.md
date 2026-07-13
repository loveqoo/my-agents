# 326 — MCP 도구 시험 (블록 상세에서 실호출)

## 배경 / 동기

사용자 요청(2026-07-13): "MCP 테스트하는 기능이 필요합니다." 연결·도구 목록 확인은 이미 있으나
(discover/rediscover, 스펙 151) **도구를 직접 호출해보는 시험 통로가 없다** — 메모리 "회상 시험"(084)·
컬렉션 "검색 시험"(072)은 있는데 MCP만 없다. 에이전트에 붙이기 전/문제 진단 시 도구가 실제로 도는지
인자 넣고 확인할 수 있어야 한다(playground-is-precision-debug-channel의 블록판).

사용자 결정 3: ①도구 **실호출까지**(연결 확인만 X) ②위치=**빌딩 블록 MCP 상세 드로어**(시험 패널
형제들과 같은 자리) ③승인 정책(HIL) 걸린 도구=**경고 후 허용**(관리 시험 통로, 명시 확인 필수).

## 설계

### 백엔드 — `POST /mcp-servers/{id}/test-tool`

- Body: `{tool: str, args: dict, confirm?: bool}`. 응답: `{ok, ms, result?, error?}`.
- **실행 경로는 `build_mcp_tools` 재사용**(새 연결 코드 금지) — net_guard(SSRF)·allowed_hosts·
  자격증명 복호·어댑터 swallow 해제(`handle_tool_error=False`)·실패 사유 마스킹+캡(스펙 320)이
  전부 그 경로에 이미 산다. 단일 서버 dict + `selected_tools=[f"{server}__{tool}"]`로 빌드 후
  해당 툴 `ainvoke(args)`, `calls_sink`에서 status/ms/error 회수.
- `enabled_tools`에 없는 도구=400. 연결 실패로 도구 0개=원인 그대로 502/400(조용한 스킵 금지 —
  322 footgun의 시험판이므로 여기선 실패를 말로).
- **승인 정책 도구 게이트(백엔드 강제)**: `tools_meta[tool].approval.required`면 `confirm=true`
  없이는 400("승인 정책이 걸린 도구 — 확인 후 재시도"). 프론트 경고만으로 두지 않는다.
- result는 `_sanitize_preview` + 캡(기존 마스커·_ERR_CAP 상수 재사용).
- 권한: 기존 blocks.py MCP 상세 라우트와 동일 게이트(관리 화면 동선).

### 프론트 — BlocksView MCP 상세 드로어 "도구 시험" 섹션

- 도구 Select(enabled_tools) → 인자 입력: `tools_meta.params`가 있으면 param별 Input(string),
  없으면 JSON textarea 폴백. 실행 버튼 → 결과 카드(성공=result 프리뷰+ms, 실패=사유 빨강 —
  Inspector ErrorReason과 같은 표현).
- 승인 정책 도구 선택 시: 경고 Alert("이 도구는 승인 정책이 걸려 있습니다 — 부수효과 주의") +
  Popconfirm 명시 확인 후 실행(confirm=true 전송).
- antd만(폼·Alert·Popconfirm·Tag) — 커스텀 금지.

## 범위 밖 (OUT)

- 채팅 경로 HIL 승인 플로우 변경 — 없음(시험 통로는 별도, 승인 게이트는 백엔드 confirm으로 대체).
- 서빙(custom) MCP의 외부 관점 시험(외부 클라이언트로 붙어보기) — served_url 실호출은 이 경로로
  이미 커버(custom도 served_url로 접속하므로 동일).
- 인자 스키마 고급 렌더(중첩 객체·배열 폼) — string+JSON 폴백까지만.

## 검증

- 단위: mock MCP로 성공(echo)·실패(failing_op → 사유 표면)·미허용 도구 400·승인 도구 confirm
  없이는 400/있으면 실행·마스킹(시크릿 패턴 인자 반향 시 결과 마스킹) — verify_326.
- 브라우저: 드로어에서 echo 실행→결과 렌더, failing_op→실패 사유 렌더, 승인 도구 경고+확인 플로우.
- 회귀: verify_151(재탐색)·211(정책)·156(서빙)·metrics-fast·tsc/build.

## 완료 조건

- 시험 API+드로어 UI로 echo 실호출 성공·failing_op 사유 확인(스크린샷).
- 승인 도구 백엔드 confirm 게이트 동작(단위 증명).
- 회귀 그린.

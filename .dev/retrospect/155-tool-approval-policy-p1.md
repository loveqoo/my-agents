# 155 — 도구 승인 정책 P1: 하드코딩→DB + 단일 리졸버 (스펙 177 P1)

## 맥락
개발자 지적: "기능에 권한 설정을 하기 어렵다." 승인이 필요한 도구가 코드 상수
`runtime._APPROVAL_ACTIONS`(한 줄, `(local-tools,delete_record)→data.delete`)에만 있어 관리자가 UI로
도구에 승인을 걸 수 없었다. 게다가 정책이 그래프-tools 경로(`_wrap_mcp_tool`)와 브로커 경로
(`McpProvider.approval_for`) 두 곳에서 각자 `_APPROVAL_ACTIONS`를 조회 — 소스는 같아도 소비처 둘.

## 한 것
- **단일 리졸버** `resolve_tool_approval(server, tool, tools_meta)`(runtime.py): tools_meta[tool].approval.
  required면 `mcp.{server}.{tool}`, 아니면 레거시 `_APPROVAL_ACTIONS` 폴백. 두 소비처가 이 함수 하나만
  호출(drift 0). `_wrap_mcp_tool`은 permission을 인자로 받게 시그니처 변경(내부 조회 제거), `build_mcp_tools`
  루프가 서버 dict의 tools_meta로 해석해 주입.
- **데이터로 이전**: 서버 dict 두 빌더(`chat._load_context`·`broker._server_dicts`)에 tools_meta 급전,
  `_McpBacking`이 tools_meta 슬롯 운반. schemas `_check_tools_meta`가 approval 키 정규화 보존(이전엔
  description/params만 남기고 버렸음 — 게이트키퍼였다). seed delete_record에 approval 추가.
- **관리자 UI**: BlocksView 편집 폼에 도구별 "승인 필요" 토글(McpToolInfo.approval, toolsDetail edit
  로드·저장 매핑·toggle 핸들러). 레거시 폴백으로 delete_record 무회귀.

## 배운 것
- **여러 소비처의 정책 조회는 리졸버 함수로 수렴시켜라(상수 공유로는 부족).** 상수를 공유해도 "어떻게
  해석하나"가 각 소비처에 흩어지면 데이터 소스(tools_meta)를 추가할 때 두 곳을 각각 고쳐야 한다. 함수
  하나로 접으면 소스 추가·우선순위·폴백이 한 곳 — 새 소비처도 그 함수만 부르면 자동 정합. [[verification-ladder-three-rungs]]
- **리팩터가 "데이터를 통째 교체"하는 지점은 새 필드를 조용히 파괴한다(적대 검토 P0).** rediscover가
  `obj.tools_meta = _tools_meta_from_details(details)`로 전체 교체하는데, 라이브 탐색 결과엔 approval이
  없다(그건 서버가 아는 게 아니라 **관리자 데이터**). → 재탐색 한 번에 관리자가 켠 승인이 소멸, 그 도구는
  레거시에 없으면 게이트 없이 부수효과 실행. **단위 테스트(리졸버 매트릭스)는 초록, reconcile 왕복만
  잡는 결함** — 정확히 검증 사다리의 통합 런. `prior`(기존 tools_meta) 이월 보존으로 봉합. 교훈:
  **탐색·동기화가 admin이 얹은 정책 데이터를 덮어쓰지 않는지**를 "라이브 소스가 모르는 필드" 기준으로
  점검하라(approval처럼 사람이 얹은 건 merge-preserve). [[adversarial-review-before-destructive-ship]]
- **리스크 낮추는 이전 = 신소스 우선 + 구소스 폴백(빅뱅 제거 아님).** `_APPROVAL_ACTIONS`를 지우지 않고
  리졸버가 tools_meta 우선·레거시 폴백. delete_record는 무회귀(기존 DB는 tools_meta에 approval 없어도
  레거시로 게이트), 신규 도구는 UI로 설정. verify_041(G7 정책맵 단언)도 그대로 초록.
- **시그니처 변경은 그 함수를 직접 부르는 테스트도 같이 고친다.** `_wrap_mcp_tool`에 permission 인자
  추가 → verify_092가 옛 3인자로 직접 호출 → 4인자(None)로 갱신. build_mcp_tools 경유 테스트(041)는
  무영향(호출부가 해석해 주입). [[move-breaks-references-both-directions]]
- **fail-closed 파생은 P1엔 안전하나 P2에 잠복 위험.** permission `mcp.{server}.{tool}`에 self_approve
  정책이 하나도 없어 항상 admin-only로 귀결(안전). 단 P2에서 approver="self"를 `mcp.*`에 연결하면
  server/tool 세그먼트 이스케이프 부재가 우회 표면이 됨 — P2 설계 시 명시(deep-reasoner 선제 경고).
- **검증 환경 드리프트 vs 코드 회귀를 diff 위치로 가른다.** verify_151이 400으로 죽었지만 실패 라인(전송
  가드 :518)이 내 diff(:339·:537)보다 위 → 내 코드 도달 전 발생 → 코드 무관. 원인은 이 dev DB만
  local-tools `url=None`(시드는 MOCK_MCP_URL 의도) 드리프트. 시드 의도로 복구하니 21/21. **"내 변경이
  깼나"는 실패 라인이 내 변경 라인 위/아래인지로 즉단**(스택트레이스 라인 vs git diff hunk).

## 검증
verify_177 13/13(리졸버 R1–R5 + reconcile 왕복 R6)·브라우저 3/3(토글·저장·재열기 영속)·종단
UI→DB→리졸버(echo가 UI 설정만으로 게이트, 하드코딩 0)·P0 통합(rediscover 왕복 승인 보존)·회귀
verify_041·092(17/17)·151(21/21).

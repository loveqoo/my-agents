"""MCP 도구 메타 상한 — 단일 출처(스펙 375, 캠페인 374 T1).

원격 유래 문자열(도구 이름·설명·파라미터)의 표시·저장 상한. **두 경계가 이 값을 공유해야
드리프트가 없다**:
  (1) 입력 검증 — `schemas.McpToolParam`/`McpToolInfo`/`McpServerIn._check_tools_meta`(위반 422),
  (2) 저장 정규화 — `blocks._tool_info`/`_tools_meta_from_details`(초과 절단·개수 컷).

이전에는 같은 숫자(500/30/100/120/80/40)가 두 파일에 복제돼 한쪽만 하드닝하면 입력 캡과 저장 캡이
조용히 어긋났다(codex 리뷰 P1). 여기 한 곳만 고친다 — 값 변경은 사용자 가시 한계라 승인 사항.

주의: MCP **서버 이름**(McpServerIn.name)의 120은 DB String(120) 제약이라 개념이 다르므로 여기서
합치지 않는다(도구 이름 캡과 우연히 같을 뿐).
"""

TOOL_NAME_CAP = 120  # 도구 이름
TOOL_DESC_CAP = 500  # 도구 설명
TOOL_PARAMS_CAP = 30  # 도구당 파라미터 수
PARAM_NAME_CAP = 80  # 파라미터 이름
PARAM_TYPE_CAP = 40  # 파라미터 타입 표기
TOOLS_META_CAP = 100  # 서버당 메타 저장 도구 수

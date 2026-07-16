# 375 — MCP 도구메타 캡 단일 출처 (캠페인 374 Tier 1-1)

## 왜

codex 리뷰 P1(그룹 B): MCP 도구 메타 상한 `500/30/100`(+ 이름 120·파라미터 이름 80·타입 40)이
`blocks.py`(저장 정규화)와 `schemas.py`(입력 검증)에 **각각 하드코딩**됨. 메인 대조 검증으로 실재
확인 — 공유 상수 없음. 한쪽만 하드닝하면 입력 캡(422)과 저장 절단 캡이 조용히 어긋난다(드리프트).

## 무엇

`mcp_tool_meta.py` 단일 출처 모듈에 6개 캡 상수를 모으고 두 소비자가 참조:
- `TOOL_NAME_CAP=120` · `TOOL_DESC_CAP=500` · `TOOL_PARAMS_CAP=30`
- `PARAM_NAME_CAP=80` · `PARAM_TYPE_CAP=40` · `TOOLS_META_CAP=100`

- **schemas.py**: `McpToolParam`/`McpToolInfo` `max_length`, `McpServerIn._check_tools_meta` 개수 컷·에러문.
- **blocks.py**: `_tool_info`(이름·설명·파라미터 절단), `_tools_meta_from_details`·discover 개수 컷.
- 인라인 매직넘버(`[:120]`/`[:80]`/`[:40]`)도 상수로 치환(whole-fix).

**값 불변** — 단일화만. 값 변경은 사용자 가시 한계라 승인 사항(product-limits). MCP **서버 이름**의
120(DB String(120))은 개념이 달라 병합하지 않음.

순환 위험 0 — `mcp_tool_meta`는 순수 상수(임포트 없음).

## 완료 조건 (동작 불변)

- 잔여 구 상수 참조 0 · ruff 통과.
- 캡 값 동일(120/500/30/80/40/100) · 101개 tools_meta 여전히 422 · 절단 동작 동일(스모크 실측).
- make test SUITE_OK · e2e 39/39(라이브 새 코드) · tsc 0(admin 무변경).

## 검증 결과 (2026-07-16 — done)

전부 초록: 잔여 참조 0·ruff·캡 스모크(101 거부·이름120·설명500 절단)·SUITE_OK·e2e 39/39.

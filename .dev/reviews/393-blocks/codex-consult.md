# codex 자문 원문 — blocks.py 리팩터 (2026-07-18, 스펙 393 입력)

**판단**
`api/blocks.py`를 패키지 `api/blocks/`로 바꾸기보다, 이 코드베이스에는 `chat_*` 선례처럼 **평면 형제 모듈 분할 + 기존 `blocks.py` 파사드 유지**가 맞습니다. `main.py`는 [blocks.router](packages/api/src/api/main.py:132)만 include하고, `agents/crud_routes.py`는 [assert_memory_names_exist](packages/api/src/api/agents/crud_routes.py:13)를 직접 import하며, verify들은 `api.blocks` 내부 심볼까지 직접 호출합니다. 패키지화는 import 해석 자체를 바꾸므로 리팩터 1차 목표인 동작보존과 충돌합니다.

**구조적 결함**
1. 라우터가 HTTP, 도메인 정책, 네트워크 클라이언트, presenter, 집계 query를 모두 소유합니다. 예: MCP discover는 SSRF guard, allowlist refresh, LangChain client 생성, timeout, 오류 DTO 변환을 [_live_discover](packages/api/src/api/blocks.py:488)에 묶고, `/blocks`는 네 모델 조회와 REST DTO와 다른 관리자 UI 표면 직렬화를 [한 함수](packages/api/src/api/blocks.py:862)에서 합니다.

2. C급 함수 중 `_tool_info`는 “외부 도구 스키마 파싱 + 타입 라벨 합성 + cap 적용 + fail-safe”가 섞였습니다. [314-356](packages/api/src/api/blocks.py:314). `tool_required_names()`, `param_type_label()`, `tool_param_summaries()`, `tool_info()` 순수함수로 쪼개고 cap 상수는 이미 있는 [mcp_tool_meta.py](packages/api/src/api/mcp_tool_meta.py:1)에 계속 둡니다.

3. `prompt_apply`는 라우트가 권한 필터, 대상 조회, active version 기준 선택, scratch 생성/갱신, pin freeze, 결과 집계를 모두 합니다. [150-210](packages/api/src/api/blocks.py:150). `PromptApplyCommand(session, principal, prompt, agent_ids)` 또는 `PromptAdoptionService`로 이동하고, 라우트는 `get_or_404`와 command 호출만 남기는 쪽이 낫습니다.

4. `update_mcp_server`는 source 불변, publish 게이트, tools_meta 보존, rename 가드, reserved name, auth patch, version commit이 한 트랜잭션에 직렬 배치되어 있습니다. [710-764](packages/api/src/api/blocks.py:710). `McpServerPatch` 파라미터 객체와 `McpUpdateCommand`로 나누되, `auth_in is None/마스킹/""/평문` 의미는 독립 함수로 고정해야 합니다.

5. `_assert_removed_tools_unreferenced`는 MCP 도구 capability 문자열 규칙을 blocks 내부에서 직접 스캔합니다. [555-578](packages/api/src/api/blocks.py:555). 삭제/rename 가드와 같은 가족이므로 `references.py` 쪽에 `agents_referencing_mcp_tools(server_name, removed_tools)`로 올리는 편이 맞습니다.

6. `_validate_tool_testable`은 작은 함수지만 정책 축이 큽니다: enabled 여부, transport/url, approval confirm이 섞여 있습니다. [617-631](packages/api/src/api/blocks.py:617). `ToolTestPolicy.from_server(obj).validate(tool, confirm)` 또는 순수 `validate_tool_test_request(snapshot, request)`로 빼면 `test_mcp_tool`이 실행 orchestration만 맡습니다.

**권장 분할 설계**
- `blocks.py`: 파사드. `router = APIRouter(tags=["blocks"])`, 내부에서 가족별 router를 `include_router(..., prefix="")`, 그리고 기존 직접 import 심볼 재수출.
- `blocks_prompts.py`: `/prompts*`, `PromptApplyCommand`.
- `blocks_memory_types.py`: `/memory-types*`, `assert_memory_names_exist`.
- `blocks_mcp.py`: `/mcp-servers*` 라우트.
- `blocks_mcp_discovery.py`: `_live_discover`, `_tool_info`, `_tools_meta_from_details`, test-tool 실행 보조.
- `blocks_presenters.py`: `mcp_to_out`, `_mcp_auth_masked`, `_mcp_served_url`, `/blocks` item presenter.
- `blocks_catalog.py`: `/blocks` 집계 query와 category별 item builder.
- `blocks_versions_routes.py`: `/block-versions*`.

트레이드오프: `blocks.py` 파사드는 당분간 F401 재수출이 지저분하지만, `from api import blocks as BL` 테스트들과 `from api.blocks import _tools_meta_from_details`를 즉시 살릴 수 있습니다. 패키지화는 장기적으로 이름 공간이 예쁘지만, 지금은 `api.blocks` 모듈 파일과 패키지명이 충돌해 import 리스크가 큽니다.

**동작보존 함정**
- 라우트 path는 prefix 없이 그대로여야 합니다: `/prompts`, `/memory-types`, `/mcp-servers`, `/mcp-servers/discover`, `/blocks`, `/block-versions/...`.
- memory-types 생성/삭제/개명 봉인 403은 그대로입니다. [233-243](packages/api/src/api/blocks.py:233), [251-276](packages/api/src/api/blocks.py:251).
- rediscover는 `tools_meta.approval.required`를 prior에서 이월해야 합니다. [_tools_meta_from_details](packages/api/src/api/blocks.py:359), verify도 이를 직접 핀합니다 [verify_177_tool_approval_resolver.py](tests/verify_177_tool_approval_resolver.py:110).
- MCP auth는 응답 마스킹, masked PUT 보존, `""` 제거, 평문 암호화 계약을 보존해야 합니다. [381-383](packages/api/src/api/blocks.py:381), [749-759](packages/api/src/api/blocks.py:749).
- 참조 가드는 삭제와 rename 모두 409입니다. verify_093이 함수 직접 호출로 핀합니다. [tests/verify_093_delete_reference_guard.py](tests/verify_093_delete_reference_guard.py:247), [314-345](tests/verify_093_delete_reference_guard.py:314).
- `/blocks`는 REST DTO와 달리 `enabledTools`, `toolsMeta`, `usedBy`, `chunkSize`, `chunkOverlap`, `can_manage`, `served_url`가 섞인 관리자 UI 계약입니다. [928-952](packages/api/src/api/blocks.py:928), 프론트도 그대로 소비합니다 [BlocksView.tsx](admin/src/admin/views/BlocksView.tsx:982).
- 블록 버저닝은 `record_block_version` + commit 충돌 409 흐름을 유지해야 합니다. unique race는 [BlockVersion 제약](packages/api/src/api/models/blocks.py:42)과 [record_block_version](packages/api/src/api/block_versions.py:93)에 걸려 있습니다.

**권장 순서**
1. `blocks_presenters.py`와 `blocks_mcp_discovery.py`로 순수/저위험 함수 이동. 파사드에서 `_tool_info`, `_tools_meta_from_details`, `mcp_to_out` 재수출.
2. `blocks_versions_routes.py` 이동. 경로 단순하고 공유 상태 적음.
3. `blocks_memory_types.py` 이동. 403 봉인과 `assert_memory_names_exist` 재수출만 주의.
4. `blocks_prompts.py` 이동 후 `PromptApplyCommand` 도입.
5. `blocks_mcp.py` 이동 후 `McpUpdateCommand`, `ToolTestPolicy`, removed-tool reference helper 도입.
6. 마지막에 `blocks_catalog.py`로 `/blocks` 집계 분리. 프론트 camelCase 계약 때문에 가장 늦게.

검증은 리팩터 전후 전판 원칙이면 최소 `verify_151`, `verify_326`, `verify_177_tool_approval_resolver`, `verify_093`, `verify_152`, `verify_156`, 그리고 `/blocks` 프론트 소비 smoke가 필요합니다. 이번 턴에서는 read-only 조건과 샌드박스 때문에 radon 재측정은 실패했습니다: `uv`가 `~/.cache/uv` 초기화 권한에서 막혔습니다.

Compounding은 파일 수정 금지 요청 때문에 `.dev/retrospect` 작성과 커밋을 생략했습니다.

# 서브에이전트 심층 분석(codex 샌드박스 실패 시 자체 분석 폴백)

[단계 5 — Verification] read-only로만 확인했습니다. `codex exec`는 1회 실행했고 지시대로 재시도하지 않았습니다. 로그: `WARNING: proceeding, even though we could not create PATH aliases: Operation not permitted (os error 1)` / `Error: failed to initialize in-process app-server client: Operation not permitted (os error 1)`. 파일 수정과 테스트 실행은 하지 않았습니다.

**1. 구조적 결함**
1. `blocks.py`는 라우터가 아니라 미니 애플리케이션입니다. `router = APIRouter(tags=["blocks"])` 하나에 `/prompts`, `/memory-types`, `/mcp-servers`, `/blocks`, `/block-versions`가 전부 붙어 있고 [blocks.py](packages/api/src/api/blocks.py:57), `main.py`는 이 단일 router만 include합니다 [main.py](packages/api/src/api/main.py:132). 가족 혼재 때문에 MCP 변경 리스크가 prompt/memory/version까지 같이 걸립니다.

2. MCP 영역은 라이브 I/O, 보안 정책, 저장 병합, 응답 직렬화가 한 덩어리입니다. `_live_discover`는 SSRF guard, allowed-host refresh, LangChain client, timeout, 예외 변환을 모두 수행합니다 [blocks.py](packages/api/src/api/blocks.py:488). `rediscover_mcp_server`는 권한, 복호화, 라이브 탐색, 삭제 참조 가드, `tools_meta` merge-preserve, enabled 교집합, 버전 기록을 한 함수에 묶습니다 [blocks.py](packages/api/src/api/blocks.py:581).

3. C급 함수 분해 방향:
   - `_tool_info`: 스키마 추출, required 추출, 타입 문자열화, cap 적용, fail-safe가 섞여 있습니다 [blocks.py](packages/api/src/api/blocks.py:314). `extract_required`, `summarize_param`, `tool_to_info` 순수 함수로 쪼개는 게 맞습니다.
   - `prompt_apply`: 라우터 함수 안에서 lazy import, 에이전트 재조회, scratch 버전 생성, pin freeze, 결과 집계까지 합니다 [blocks.py](packages/api/src/api/blocks.py:150). `PromptApplyCommand` 또는 `apply_prompt_to_agents(session, principal, prompt, ids)`로 빼야 합니다.
   - `update_mcp_server`: source/publish/name/auth/tools_meta/version/commit 정책이 직렬 if-chain입니다 [blocks.py](packages/api/src/api/blocks.py:710). `McpUpdatePatch` 파라미터 객체와 `validate_source`, `validate_publish`, `validate_rename`, `apply_auth_update` 추출이 적절합니다.
   - `_assert_removed_tools_unreferenced`: 제거 계산과 Agent config 스캔, 메시지 생성이 붙어 있습니다 [blocks.py](packages/api/src/api/blocks.py:555). `removed_enabled_tools` + `agents_referencing_mcp_tools`로 분리하고 `references.py` 계열로 옮기는 편이 자연스럽습니다.
   - `_validate_tool_testable`: 활성 도구, transport/url, approval confirm을 한 validator에 넣습니다 [blocks.py](packages/api/src/api/blocks.py:617). 예외 status/detail은 보존하되 predicate를 나누는 게 좋습니다.

4. 내부 helper가 사실상 public API입니다. `agents/crud_routes.py`가 `assert_memory_names_exist`를 직접 import합니다 [crud_routes.py](packages/api/src/api/agents/crud_routes.py:13). 테스트도 `api.blocks as BL`로 `_tool_info`, `rediscover_mcp_server`, `update_mcp_server`, `test_mcp_tool`을 직접 호출합니다 [verify_151](tests/verify_151_mcp_tool_detail.py:28), [verify_326](tests/verify_326_mcp_tool_test.py:28). 분할 시 재수출 없이는 테스트/소비자가 깨집니다.

5. `/blocks` 집계는 별도 read-model인데 CRUD 파일 안에 손조립 dict로 있습니다 [blocks.py](packages/api/src/api/blocks.py:862). 특히 MCP는 `enabledTools`, `toolsMeta`, `served_url`, `can_manage`처럼 REST DTO와 다른 표면을 만듭니다 [blocks.py](packages/api/src/api/blocks.py:928). 리팩터 중 필드명 실수 가능성이 큽니다.

**2. 리팩토링 설계**
권장 경계는 `api.blocks` 패키지화입니다. `api/blocks/__init__.py`가 facade가 되고, 내부를 `router.py`, `prompts.py`, `memory_types.py`, `mcp_servers.py`, `aggregate.py`, `versions.py`, `mcp_discovery.py`, `mcp_serializers.py`, `mcp_validation.py`, `prompt_commands.py`로 나눕니다. `__init__.py`는 `router`, `assert_memory_names_exist`, `_tools_meta_from_details`, `_tool_info`, 기존 라우트 함수명을 한동안 재수출합니다. 트레이드오프는 파일→패키지 전환 diff가 크다는 점입니다. 대신 `main.py`의 `blocks.router`와 기존 테스트 import를 보존할 수 있습니다.

라우터는 FastAPI 관례대로 가족별 `APIRouter`를 만들고 facade router가 include합니다. prefix는 붙이지 말고 각 기존 path를 그대로 유지합니다. 예: `prompts.router`는 `/prompts`, `mcp_servers.router`는 `/mcp-servers`, `aggregate.router`는 `/blocks`. 트레이드오프는 라우트 정의가 흩어지지만 path 소유권이 명확해집니다.

MCP는 Command 패턴을 제한적으로 씁니다. `RediscoverMcpServerCommand`는 `load -> authorize -> discover -> guard_removed_tools -> merge -> version -> commit` 순서를 명시하고, `UpdateMcpServerCommand`는 `McpUpdatePatch`를 받아 검증과 적용을 분리합니다. 트레이드오프는 클래스가 늘지만 현재 C급 함수의 정책 순서가 테스트 가능한 계약으로 드러납니다.

순수 helper는 먼저 빼도 됩니다. `_tool_info`, `_tools_meta_from_details`는 이미 `mcp_tool_meta.py`와 스키마 cap을 공유하므로 `mcp_tool_meta.py` 또는 `blocks/mcp_tool_details.py`로 옮기고 facade에서 재수출합니다. `tests/verify_177_tool_approval_resolver.py`는 `_tools_meta_from_details`를 직접 import합니다 [verify_177](tests/verify_177_tool_approval_resolver.py:12), 그래서 재수출 기간이 필요합니다.

**3. 동작보존 함정**
- `main.py`의 include 지점은 `blocks.router` 하나입니다. facade router가 모든 기존 path를 같은 순서/충돌 없이 포함해야 합니다 [main.py](packages/api/src/api/main.py:132).
- `memory-types`는 생성 403, 삭제 403, 이름/키 변경 403, 설명 수정 200입니다 [blocks.py](packages/api/src/api/blocks.py:233), [verify_387](tests/verify_387_memory_identity.py:244).
- MCP auth는 생성/목록/단건/집계 모두 마스킹, masked PUT은 보존, `auth=""`는 제거입니다 [blocks.py](packages/api/src/api/blocks.py:381), [verify_054](tests/verify_054_mcp_auth_at_rest.py:102).
- rediscover는 `tools_meta`의 관리자 승인 정책을 보존하고, `enabled_tools`는 새 tools와의 교집합이어야 합니다 [blocks.py](packages/api/src/api/blocks.py:601), [verify_151](tests/verify_151_mcp_tool_detail.py:120).
- 삭제/rename/rediscover 제거는 참조 중이면 409입니다 [blocks.py](packages/api/src/api/blocks.py:744), [verify_093](tests/verify_093_delete_reference_guard.py:314).
- non-custom publish는 create/update/publish 모두 400이고 끄기는 허용입니다 [blocks.py](packages/api/src/api/blocks.py:468), [verify_211](tests/verify_211_mcp_shared_use.py:111).
- `source`는 생성 후 불변입니다 [blocks.py](packages/api/src/api/blocks.py:720), [verify_152](tests/verify_152_no_reexport.py:193).
- block versioning은 prompt/MCP 수정과 rediscover에 걸려 있고, race 실패는 409로 집계됩니다 [blocks.py](packages/api/src/api/blocks.py:760), [verify_369](tests/verify_369_block_versioning.py:213).

**4. 권장 순서**
1. 순수 함수 이동: `_tool_info`, `_tools_meta_from_details`, `_mcp_auth_masked`, `_mcp_served_url`, `_audit_json`, `mcp_to_out`를 새 모듈로 빼고 `api.blocks`에서 재수출.
2. `/blocks` 집계만 `aggregate.py`로 이동. 경로/필드명 고정 테스트를 먼저 핀합니다.
3. `memory_types.py` 분리. 봉인 라우트라 상태코드 계약만 보존하면 상대적으로 낮은 위험입니다.
4. `prompts.py` + `prompt_commands.py` 분리. `prompt_apply`는 command로 옮기되 라우트 함수명은 facade 재수출.
5. MCP read/write 라우터 분리 후 `_live_discover`, rediscover, test-tool 순으로 command화. 여기서 전후 전체 관련 verifier를 돌려야 합니다.
6. 마지막에 `blocks.py` 파일을 패키지 facade로 전환하고 직접 import 소비자를 점진적으로 새 모듈 import로 옮깁니다.

검증은 전후 모두 최소 `verify_151`, `verify_326`, `verify_054_mcp_auth_at_rest`, `verify_093_delete_reference_guard`, `verify_387_memory_identity`, `verify_369_block_versioning`, `verify_211_mcp_shared_use`, `verify_152_no_reexport`, 그리고 `/blocks` e2e를 권합니다. 이번 턴에서는 read-only 지시 때문에 실행하지 않았습니다.


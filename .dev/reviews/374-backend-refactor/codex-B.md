[단계 5 — Verification]

## packages/api/src/api/blocks.py
[blocks.py:143] (P2) `prompt_apply`가 라우트 안에서 권한 필터·버전 선택·핀 고정·스크래치 생성·응답 집계를 모두 처리하고 내부 import까지 수행함 → `PromptAdoptionService` 같은 도메인 서비스로 버전 생성 로직을 빼고 라우트는 입력/권한/응답만 맡기기  
[blocks.py:273] (P1) 도구 메타 상한 `_TOOL_DESC_CAP/_TOOL_PARAMS_CAP/_TOOLS_META_CAP`가 라우트 파일에 있고 `schemas.py`에도 숫자 500/30/100이 별도 하드코딩되어 드리프트 위험이 있음 → `mcp_tool_meta.py` 같은 공용 정책 모듈로 상한과 정규화 DTO를 단일화하기  
[blocks.py:348] (P2) `_mcp_served_url`이 응답 직렬화 중 `served_mcp`와 `os.environ`을 직접 읽어 HTTP 표시 정책과 런타임 환경 조회가 라우트 serializer에 누출됨 → base URL/provider를 주입받는 `McpServerPresenter`로 분리하기  
[blocks.py:450] (P2) `_live_discover`가 SSRF 가드·allowlist refresh·MCP client 생성·timeout·오류 DTO 변환을 한 함수에 묶어 네트워크 경계를 라우트 파일에 박아둠 → `McpDiscoveryClient` 인터페이스로 빼고 라우트는 HTTP 예외 매핑만 수행하기  
[blocks.py:825] (P2) `get_blocks`가 모든 에이전트와 4종 블록을 직접 조회한 뒤 카테고리별 dict 직렬화와 usedBy 계산을 수작업으로 반복함 → 카테고리별 query/presenter와 usage count 집계 서비스를 분리하기  

## packages/api/src/api/models.py
[models.py:34] (P2) `RAG_EMBED_DIMS`가 모델 import 시점에 환경변수를 읽어 SQLAlchemy metadata 구성과 런타임 설정을 결합함 → 설정 모듈에서 명시적으로 산출한 값을 모델 factory/metadata 구성 단계에 주입하기  
[models.py:45] (P2) 한 파일에 블록, RAG, provider/model, MCP, agent, session, approval, auth, batch, SSRF, eval 테이블이 모두 공존해 bounded context 경계가 없음 → `models/blocks.py`, `models/rag.py`, `models/agents.py`, `models/auth.py`, `models/eval.py`로 쪼개되 같은 `Base`만 공유하기  
[models.py:279] (P2) `McpServer.tools/enabled_tools/tools_meta`가 raw JSONB list/dict로 저장되어 승인 정책·도구 메타 구조를 DB 모델이 보장하지 못함 → 최소한 typed value object 검증 계층 또는 별도 `mcp_tools` 테이블로 구조 경계를 세우기  
[models.py:338] (P2) `Agent.config`와 `AgentVersion.config`가 raw JSONB dict라 스키마의 `AgentConfig` 규칙과 저장 진실원이 분리됨 → config normalization을 persistence 전용 함수로 단일화하고 모델 주변 저장 경로가 반드시 통과하게 만들기  
[models.py:510] (P2) fastapi-users 테이블 import와 `User/AccessToken/Role`이 도메인 모델 파일 중간에 섞여 auth 인프라가 전체 도메인 metadata 모듈에 결합됨 → auth 모델 모듈로 분리하고 루트 metadata import에서 조립하기  

## packages/api/src/api/schemas.py
[schemas.py:39] (P2) 한 스키마 파일에 블록/RAG/MCP/provider/model/agent/session/chat/auth/admin DTO가 모두 들어 있어 API 계약 변경의 blast radius가 과도함 → 라우터 또는 bounded context별 `schemas/*.py`로 분리하고 공통 `AuditOut`만 공유하기  
[schemas.py:333] (P1) `McpToolInfo`의 max_length 120/500/30과 `McpServerIn._check_tools_meta`의 100개 제한이 `blocks.py`의 MCP 메타 상한과 중복됨 → 상한 상수와 정규화 로직을 공용 MCP schema/policy 모듈로 이동하기  
[schemas.py:539] (P2) `AgentConfig`가 에이전트 기본 설정, broker capability, 승인 정책, artifact form, pipeline nodes, RAG threshold를 한 클래스에 모두 끌어안음 → `AgentModelConfig`, `AgentToolConfig`, `AgentArtifactConfig`, `AgentPipelineConfig`, `AgentRagConfig`로 중첩 모델화하기  
[schemas.py:619] (P2) `artifactSpec`와 `nodes` 검증이 API DTO 내부에서 dict 조작과 의미 일부 정규화를 수행해 런타임 normalize와 책임이 겹침 → Pydantic nested model 또는 별도 config normalizer로 옮겨 API/seed/runtime이 같은 함수를 쓰게 하기  
[schemas.py:877] (P3) `RegisterExternalAgentIn` 주석이 deprecated라고 밝히지만 스키마는 여전히 공개 DTO로 유지되어 신규 `ConnectAgentIn`과 계약 표면이 중복됨 → 호환 계층으로 격리하거나 제거 일정이 있는 legacy schemas 모듈로 분리하기  

## 이 그룹 TOP 3
1. (P1) MCP 도구 메타 상한/정규화 단일화 — 라우트와 스키마가 같은 보안·저장 한계를 따로 들고 있어 다음 하드닝에서 드리프트가 가장 쉽게 생김  
2. (P2) `blocks.py`의 MCP discovery/test/presentation 분리 — 네트워크 보안 경계와 HTTP 라우트가 결합돼 테스트 대역과 변경 대역이 같이 커짐  
3. (P2) `schemas.py`의 `AgentConfig` 분해 — agent 설정 확장축이 계속 붙는 중심 객체라 현재 형태는 새 기능마다 검증·저장·런타임 책임이 한 클래스에 누적됨  


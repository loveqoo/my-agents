# 378 — schemas.py → 도메인 패키지 분할 (캠페인 374 Tier 2)

## 왜

codex 리뷰 P2(그룹 B): 단일 `schemas.py`(1054줄·76클래스)에 블록/RAG/MCP/provider/model/agent/
session/chat/auth/admin DTO가 모두 있어 계약 변경의 blast radius가 과도. 도메인별 편집이 한 파일을
관통한다.

## 무엇

`schemas.py` → `schemas/` 패키지로 **verbatim 슬라이싱**(전사 오류 0). 9개 도메인 모듈:

| 모듈 | 클래스 |
|---|---|
| base | AuditOut, ORM, _require_non_blank |
| blocks | Prompt*/MemoryType* (8) |
| collections | Collection*/Document*/ReindexIn/SearchHit (14) |
| memory | MemorySearch*/MemoryHit/MemoryPage* (6) |
| mcp | McpToolParam/McpToolInfo/McpServer*/McpDiscover*/McpToolTest* (9) |
| registry | Provider*/Model*/AvailableModel* (9) |
| agents | AgentConfig/Agent*/VersionOut/Connect*/Register* (10) |
| sessions | Session*/Message*/Approval*/Chat*/Feedback* (11) |
| admin | User*/Role*/Policy*/AdminUserOut (8) |

- `__init__.py`가 **명시적 re-export** — `from api.schemas import X`는 **기존 그대로**(임포터 무변경).
- 도메인 간 참조는 AuditOut 상속(base)뿐 — 나머지는 모듈 내부. Forward-ref 문자열 없어 model_rebuild 불요.
- `pyproject.toml` per-file-ignore(N815 camelCase 필드)를 `schemas.py` → `schemas/*.py` 글롭으로 갱신.

**동작 불변** — 클래스 76개 그대로, 이름·필드·검증 동일. 순수 이동.

## 완료 조건 (동작 불변)

- 클래스 수 76 보존(측정) · 누락 re-export 0 · 앱 import OK · 상속 무결(McpServerOut 필드) · ruff 통과.
- make test SUITE_OK · e2e 39/39.

## 검증 결과 (2026-07-16 — done)

전부 초록: 76클래스 보존·re-export 누락 0·app import OK·McpServerOut 상속 필드 확인·ruff·SUITE_OK·
e2e 39/39. 편집 blast radius가 도메인 단위로 축소(1054줄 단일 → 9모듈).

# 151 — MCP 도구 상세 정보 (실사용 버그 #2)

## 문제 (사용자 보고 2026-07-03)
MCP 등록에서 하위 툴의 메타정보(이름·설명·파라미터)가 노출되지 않고, MCP 기능을 들여다보는
화면이 없다. 현재 discover는 langchain 도구 객체에서 **이름만** 뽑고 설명·args 스키마를 버린다.

## 설계
- **discover 확장**: `McpDiscoverResult.toolsDetail` 추가 — 도구별 `{name, description,
  params: [{name, type, required}]}` (langchain tool의 description + args 스키마에서 파생).
  기존 `tools`(이름 목록)는 유지(하위 호환 — enabled_tools 체계 불변).
- **저장**: `McpServer.tools_meta`(JSONB, name→{description, params}) 신설 — 탐색 시점 스냅샷.
  등록/편집 폼이 discover 결과의 toolsDetail을 함께 저장. 마이그레이션 1건(컬럼 추가, 변환 없음).
- **상세 드로어(기능 화면)**: MCP 상세에서 도구를 태그 나열 대신 **도구 카드**로 — 이름·활성
  여부·설명·파라미터 표(이름/타입/필수). tools_meta 없는 도구는 이름만(기존 데이터 grandfather).
  외부(http) MCP엔 "도구 정보 새로 탐색" 버튼 — discover 재실행 → tools/tools_meta 갱신 저장
  (enabled_tools의 기존 선택은 교집합 보존).
- **시드**: local-tools(자기 서비스 mock MCP)의 tools_meta를 mock_mcp 도구 정의에서 시드 —
  신규 설치에서 바로 상세가 보이게.

## 검증 (2026-07-04 완료)
- verify_151 21/21: 파생 순수 함수(캡 3종·anyOf 타입 합성·fail-safe)·discover 라이브(설명+필수
  파라미터)·rediscover(메타 채움·enabled 교집합)·저장 라운드트립(None=미변경)·직접 저장 경계
  검증기 거부 5종·재탐색 참조 가드 409/해제 후 통과.
- e2e 8/8×2(재현 안정성): 도구 카드 3장·web_search 설명+query/string/필수·재탐색 토스트·등록 폼
  회귀. e2e 함정 기록: 상세 드로어는 커스텀(antd Drawer 아님)·antd6 Modal 클래스 구조 변화.
- codex: High 1(직접 저장 경로 tools_meta 무검증 → McpServerIn 검증기: 100개/설명500/params30/
  타입 강제)·Medium 1(재탐색이 참조 중 툴 능력을 조용히 제거 → 제거 도구를 capabilities로 참조하는
  에이전트 있으면 409 — 093 operation-symmetry의 재탐색판)·Low 1(프론트 Array.isArray 방어) →
  3건 수정. SSRF(allowlist 재검사·redirect 차단)·권한(관리 게이트)은 방어 확인.

## OUT
- 도구 단위 실행 시험(파라미터 넣고 호출) — 후속(플레이그라운드 축).
- stdio transport 라이브 탐색(기존 유예 유지).

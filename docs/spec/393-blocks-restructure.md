# 393 — blocks.py 구조 개선(가족 분할 + C급 함수 패턴 분해)

> 상태: **완료** · 2026-07-18 (승인 후 P1~P5 실행 → codex 적대 리뷰 P2×2 → 1건 봉합·1건 정직 경계)
> 발단: 복잡도 스냅샷의 다음 1순위 — blocks.py 995줄·**MI 21.6(문턱 20 최근접)**·C급 5개.
> 방식: 스펙 392와 동일 — codex 자문(`.dev/reviews/393-blocks/codex-consult.md` + 서브에이전트
> 분석 `subagent-analysis.md`) + FastAPI 대형 앱 라우터 관례 리서치 → 승인 → 실행 → 적대 리뷰.

## 진단(두 자문 합치)

1. **미니 애플리케이션**: 단일 router에 5경로 가족(`/prompts`·`/memory-types`·`/mcp-servers`·
   `/blocks`·`/block-versions`) — MCP 변경 리스크가 전 가족에 전파.
2. **C급 5개**: _tool_info 15(스키마 파싱+라벨+cap+fail-safe 혼재)·prompt_apply 14(권한+조회+
   scratch+freeze+집계)·update_mcp_server 14(7정책 직렬 if-chain)·_assert_removed_tools_
   unreferenced 12(참조 스캔이 blocks 안에)·_validate_tool_testable 11(3정책 축).
3. **내부 헬퍼가 사실상 공개 API**: agents/crud_routes가 assert_memory_names_exist,
   verify_151/326/177/093이 내부 심볼 직접 호출 — 재수출 없인 깨짐.
4. `/blocks` 집계는 REST DTO와 다른 관리자 UI 계약(camelCase enabledTools·toolsMeta·usedBy…)을
   손조립 — 필드명 실수 위험 최대 지점.

## 구조 판단(codex 명시 판정 채택)

**패키지(api/blocks/)화 아님** — 평면 형제 모듈 분할 + `blocks.py` 파사드 유지(chat_* 선례와 동형).
패키지화는 import 해석을 바꿔 동작보존 목표와 충돌(모듈↔패키지명 충돌 리스크).
가족별 APIRouter를 파사드 router가 prefix 없이 include(기존 path 불변, FastAPI Bigger
Applications 관례).

## 처방(위험 오름차순 — codex 권장 순서)

- **P1 순수/저위험 이동**: `blocks_presenters.py`(mcp_to_out·_mcp_auth_masked·_mcp_served_url·
  _audit_json) + `blocks_mcp_discovery.py`(_live_discover·_tool_info 분해: tool_required_names/
  param_type_label/tool_param_summaries 순수함수·_tools_meta_from_details) — 파사드 재수출.
- **P2 라우트 가족 이동(저위험→고위험)**: `/block-versions` → `blocks_versions_routes.py`,
  `/memory-types`(403 봉인 + assert_memory_names_exist) → `blocks_memory_types.py`.
- **P3 prompts + Command**: `blocks_prompts.py` — prompt_apply를 `PromptApplyCommand`로
  (라우트는 get_or_404 + command 호출만).
- **P4 MCP + Command/정책 분해**: `blocks_mcp.py` — update_mcp_server를 `McpServerPatch`
  파라미터 객체 + 정책 검증 함수들로(auth None/masked/""/평문 의미는 독립 함수 고정),
  _validate_tool_testable → 순수 정책 함수, _assert_removed_tools_unreferenced →
  references.py로 상향(`agents_referencing_mcp_tools`).
- **P5 집계 분리(마지막 — 프론트 계약)**: `blocks_catalog.py` — /blocks 집계·카테고리 빌더.
  camelCase 필드명 계약 때문에 최후순.

**OUT**: /blocks 응답 스키마 변경(관리자 UI 계약 동결)·mcp_tool_meta.py 캡 상수 이동(현 위치 유지).

## 동작보존 함정(자문 합본 — 각 단계 회귀 확인 대상)

1. 라우트 path prefix 없이 불변(main.py는 blocks.router 하나만 include).
2. memory-types 생성·삭제·개명 403 봉인(스펙 387), 설명 수정은 200.
3. rediscover merge-preserve: tools_meta.approval을 prior에서 이월·enabled_tools는 새 tools와
   교집합(verify_177 직접 핀).
4. MCP auth 4계약: 응답 마스킹·masked PUT 보존·`""`=제거·평문=암호화 저장.
5. 참조 가드: 삭제·rename·rediscover 제거 모두 409(verify_093 함수 직접 호출 핀).
6. non-custom publish 400(끄기는 허용)·source 생성 후 불변.
7. 블록 버저닝: record_block_version + commit race 409.
8. /blocks 집계 camelCase 필드(enabledTools·toolsMeta·usedBy·chunkSize·chunkOverlap·
   can_manage·served_url) — BlocksView.tsx가 그대로 소비.

## 완료 기준(수치) — 전부 달성(실측)

- [x] blocks.py 파사드 **92줄**(995→92) — 8개 형제 모듈(shared·presenters·mcp_discovery·
      prompts·memory_types·mcp·catalog·versions_routes).
- [x] 구 C급 5개 전부 소멸 — blocks_* C급 **0**, 최고 CC B(9). 저장소 전체 C급 61→**56**.
- [x] MI: 파사드 100.0 · 신규 모듈 45.8~89.7(전부 A, 기존 21.6 초과).
- [x] 라우트 표면 불변: 전후 (method, path, status_code, name) 24개 집합 diff **0**
      (FastAPI 신버전 지연 include `_IncludedRouter`는 original_router 재귀 순회로 박제).
- [x] 행동보존: metrics-fast 전판 + make test SUITE_OK + **suite 51/51** + 표적 verify
      151(21)·326(7)·177·344(12)·369·211·387(22 — 403 봉인) 전부 virgin 격리/인프로세스 그린.
      verify_054의 blocks.py 소스검사 경로는 blocks_mcp_discovery.py로 정직 갱신.

## codex 적대 스팟 리뷰 결과 — P1 0건, P2 2건

- **P2 봉합**: 상향한 `agents_referencing_mcp_tools`의 `set(caps)`가 오염/레거시 config의
  unhashable 값에서 TypeError 500(구 any-in은 무시) → 문자열 필터 집합화로 의미 보존.
- **P2/P3 정직 경계**: 파사드는 옛 모듈이 지나가며 임포트한 이름(select·McpServer 등)까지는
  재수출하지 않음 — repo 전수 실측 소비자 0(codex 확인), 파사드 주석에 경계 명시.
- 확인함(codex): PromptApplyCommand 순서 동일·auth 패치 의미 동일·update 검증 순서 동일·
  discover/{id} 라우트 매칭 무충돌·import 사이클 0·_tool_info 분해 구조 동일.

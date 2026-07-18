# 397 — runtime.py 구조 개선(도구·트레이스 가족 분할 + C급 5개 분해)

> 상태: **완료** · 2026-07-19 (승인 후 P1~P6 실행 → codex 적대 P1 0·P2 1 봉합)
> 발단: 캠페인(392~396) 후 3관왕 잔여 1위 — 738줄(최대)·C급 5(전 47 중 최다)·MI 31.5(최저).
> 방식: 6회전 — codex 자문(`.dev/reviews/397-runtime/codex-consult.md`) → 승인 → 실행 → 적대.

## 구조 판단(codex)

runtime.py는 이미 파사드 성격이다(말미의 RAG 재수출 — 스펙 380 선례, 소비자 13모듈+테스트가
`runtime.X` 속성 접근). 정답은 **기능별 평면 4형제 + runtime.py 재수출 파사드 유지**(소비자
재배선 금지). 캠페인 확립 패턴 그대로.

## 처방(위험 오름차순 — codex 순서)

- **P1 표면 박제**: runtime의 공개+private 소비 심볼 스냅샷(기계 검증), monkeypatch 선그렙.
- **P2** `runtime_trace.py`: is_tool_message·_msg_role·_summarize_*·_timeline_*·build_graph_path·
  estimate_tokens·assemble_trace. C급 2 분해: _summarize_messages_delta(11)→제거메시지 분리·
  프리뷰 추출, _summarize_node_update(11)→dispatch만 남김(_summarize_delta_value 기활용).
- **P3** `runtime_agent_tools.py`: _wrap_agent_tool·build_agent_tools.
- **P4** `runtime_trace_safety.py`: _content_text·_sink_from·_sanitize_preview·_SENSITIVE_KEY·
  캡 상수군·_redact_args·_cap. **_redact_args(13)는 보안 계약 — mapping/sequence/scalar 3분해만**
  (상수군과 동일 모듈 유지). rag_runtime의 runtime 지연 import를 이 모듈로 하강(순환 위험 축소).
- **P5** `runtime_mcp.py`: _safe_name·_APPROVAL_ACTIONS·resolve_tool_approval(13 —
  base/override/normalize 3분해, 우선순위 표면화)·_TOOL_TIMEOUT_S·_wrap_mcp_tool·mcp_connection·
  selected_for_server·도구 사양 캐시(371 D1)·build_mcp_tools(17 — 이동 후에만 내부 분해).
- **P6** runtime.py 파사드 축소(RAG 재수출 유지 + 전 소비 심볼 재수출).

**OUT**: 승인 우선순위·마스킹/캡 수치·캐시 키/락·타임아웃 값 일절 변경 금지. 명시 개선 0건
(전부 순수 이동+함수 분해 — dataclass류 계약 변경 없음).

## 동작보존 함정(codex 목록)

1. 승인 우선순위 동결: tools_meta 기본 > 레거시 _APPROVAL_ACTIONS 폴백 > tool_policy 오버라이드
   (브로커 McpProvider가 같은 리졸버 공유 — 드리프트 0 계약).
2. 도구 사양 캐시: 키 (name, version or 0, auth_fp)·락 double-check·stats — wrapper/calls_sink는
   캐시 금지(371 D1). pending 계산→refresh 순서(콜드 스냅샷 가드 — 371 실측 버그 재발 금지).
3. _sink_from의 config 우선/클로저 폴백(그래프 캐시 트레이스 격리의 핵심).
4. _wrap_mcp_tool 예외 경로 한 계약: handle_tool_error=False·asyncio.timeout·마스킹된 사유·
   status=error·모델-facing 실패 문자열.
5. 마스킹 계약(086/087/092/320): 키-blocklist(args) vs 값-allowlist(node delta) polarity 차이
   보존, sanitize-before-cap, budgeted 캡, fail-closed 예외.
6. verify_191은 runtime.search_collections를 패치하지만 구현은 rag_runtime을 직접 참조 —
   **기격리(노후)라 이번 표적에서 제외**(수선은 별도 스펙, 회고 324 격리 대조 적용).

## 완료 기준(수치) — 전부 달성(실측)

- [x] runtime.py 파사드 **75줄**(738→75, RAG 재수출 포함) + 4형제(mcp 386·trace 236·
      trace_safety 139·agent_tools 46).
- [x] C급 5 전부 소멸(runtime_* C급 0, 전체 47→**42**): build_mcp_tools 17→연결준비+서버별
      래핑 추출, resolve_tool_approval 13→기본/오버라이드 추출(우선순위 함수 경계 표면화),
      _redact_args 13→scalar 분리만(보안 계약), 요약 2종 11→프리뷰/dispatch 추출.
- [x] 소비 표면: 21종 hasattr 기계 검증(비소비 4건은 타패키지·부재단언·텍스트 판정),
      codex AST 재계수 제품+테스트 31종 누락 0. rag_runtime 안전 헬퍼 의존 2곳 하강.
- [x] 행동보존: metrics-fast 전판 + make test SUITE_OK + **suite 51/51** + 표적 verify 9종
      (177·087·092·262·320·086 인프로세스 + 041·101·371 virgin 격리) 전판 그린.

## codex 적대 스팟 리뷰 결과 — P1 0건, P2 1건

- **P2 봉합**: verify_054의 runtime.py 물리 파일 소스 검사 → runtime_mcp.py로 경로 갱신
  (소스-텍스트 단언=분할 소비자의 4번째 재현 — 054는 기격리지만 정직 갱신).
- 확인함(codex): resolve_tool_approval **300조합 진리표 대조 mismatch 0**·_redact_scalar 예외
  범위 보존·extend/append 시맨틱 동일·pending 값-동등 판정 동일·build 예외 흐름 동일·
  monkeypatch 소비자 0·파사드 50심볼 hasattr 통과·import 사이클 0.

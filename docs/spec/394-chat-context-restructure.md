# 394 — chat_context.py 구조 개선(리졸버 가족 분할 + C급 분해)

> 상태: **완료** · 2026-07-18 (승인 후 P1~P6 실행 → codex 적대 리뷰 P1/P2 0·P3 1 정리)
> 발단: 복잡도 스냅샷 잔여 1순위 — 812줄·**MI 23.85(문턱 근접 2위)**·C급 5(전체 56 중).
> 방식: 392·393과 동일 3회전 — codex 자문(`.dev/reviews/394-chat-context/codex-consult.md`) +
> 패턴 리서치(빌더 vs 함수 파이프라인) → 승인 → 실행 → 적대 리뷰.

## 구조 판단(codex + 리서치 합치)

- **374 T2의 "typed builder"는 기각(과추상)** — 당시 문제의식(dict ctx)은 스펙 382의 ChatContext
  DTO 전환으로 이미 해소. 빌더는 "패턴이 복잡도를 더하면 물러서라"(리서치)의 정확한 사례.
  필요한 것은 fluent builder가 아니라 **순서가 드러나는 얇은 오케스트레이터**.
- **ChatContext는 chat_context.py에 잔류**(타입 허브) — 형제 9곳이 직접 임포트, 이동은 표면
  회귀만 늘림. chat_context.py는 타입+파사드(재수출)가 된다.

## 진단

1. `_load_context`(C11)가 **순서 계약을 암묵 지역변수로 소유** — 버전→노드ref→오버라이드→풀
   재파생→pins→모델→MCP/RAG→세션의 직렬 결합(순서 변경=동작 변경).
2. `_resolve_mcp_servers`(C18, 최위험) — row 조회+pin overlay+auth 복호+유효 버전+런타임
   projection+tool filter 정책이 한 함수.
3. `derive_pipeline_pool`(C14) — 순수 파생처럼 보이나 DB 열고 cfg를 mutate(순수/DB 분리 필요).
4. 모델 해석 규칙 3벌 산재(_resolve_model/_chat_model_cfg/resolve_agent_mem_cfg) — 단,
   "오버라이드 미존재=400 vs 저장 미존재=기본 폴백" 차이는 의도 계약이라 보존.
5. `_merge_node_overrides`(C12)는 순수하나 verify_317이 직접 임포트 — 재수출 필수.

## 처방(위험 오름차순 — codex 권장 순서)

- **P1** `chat_context_overrides.py`: _NODE_OVERRIDE_FIELDS·_node_patch_fields·
  _merge_node_overrides(노드별 병합 추출로 ≤B)·_apply_overrides·_coerce_history_depth·
  _filter_capabilities. verify_317이 표면을 즉시 잡음.
- **P2** `chat_context_versions.py`(_resolve_version_and_prompt·_resolve_exec_pins·
  _resolve_prompt_provenance) + `chat_context_sessions.py`(_resolve_session) +
  `chat_context_rag.py`(_rag_collection_entry·_resolve_rag).
- **P3** `chat_context_models.py`: _pinned_model_cfg·_chat_model_cfg·_resolve_node_models·
  _resolve_model(레지스트리 조회 추출로 ≤B)·_resolve_mem_cfg·resolve_agent_mem_cfg.
  400 vs 폴백 차이를 docstring·검증으로 핀.
- **P4** `chat_context_pool.py`: 순수 파생(_derive_pool(nodes, servers, cols) — DB 무접촉)과
  DB wrapper(derive_pipeline_pool — 이름·mutate 계약 유지) 분리.
- **P5** `chat_context_mcp.py`: 서버 projection(_mcp_server_projection)·tool filter
  (_resolve_tool_filter) 분해 — 캐시 지문 재료라 **최후순**.
- **P6** `chat_context_loader.py`: _load_context 이동 — cfg 준비 단계(버전+노드ref+오버라이드+풀)
  추출로 ≤B, chat_context.py는 타입+파사드로 종결.

**OUT**: ChatContext 필드/의미 변경(스펙 371 지문·_build_turn_runtime 소비 동결)·모델 해석
규칙 3벌의 통합(의도 차이 있는 계약 — 별도 스펙 감).

## 동작보존 함정(codex 목록)

1. 노드 ref 해석은 **오버라이드 병합 전**(순서 바뀌면 세션 패치가 ref 원본에 먹음).
2. 풀 재파생은 오버라이드 뒤·모델/MCP/RAG 해석 전(폼 밖 입구 복구 계약).
3. `exec_version = pinned or active` **뒤에** pins 읽기(승인 재개·trace 버전 승계).
4. own 소유권 접기(타인/NULL/추측 → 새 세션·오라클 0)·NUL 위생 fold.
5. 승인 재개가 같은 _load_context로 세션 재발견(chat_approval 193) — 시그니처 불변.
6. 그래프 캐시 지문 재료(model_cfg·mcp_servers의 name/version/auth·tool_names·tool_policy·
   rag_collections·rag_min_scores·ephemeral) — projection 필드명/값 의미 변경 금지.
7. 오버라이드 모델 미등록 400 vs 저장 모델 미등록 기본 폴백(의도 비대칭).

## 완료 기준(수치) — 전부 달성(실측)

- [x] chat_context.py 파사드 **54줄**(812→54) — 9개 형제 모듈(types·overrides·versions·
      sessions·rag·models·pool·mcp·loader). 실행상 조정: 파사드↔로더 순환 회피로 ChatContext를
      chat_context_types.py로 하강(재수출로 소비자 표면 무변경 — 392 chat_graph_build 선례).
- [x] 구 C급 5 전부 소멸 — chat_context_* C급 **0**(최고 B), 전체 C급 56→**51**.
      _projection_content의 or-체인 C(12)도 pin/head 분리로 해소.
- [x] MI: 파사드 100 계열·신규 모듈 55.6~(전부 A, 기존 23.85 초과).
- [x] 형제 소비자 9곳 import 무변경(rg 실측) + verify_317 그린 + ChatContext 바이트 동등
      (codex 확인).
- [x] 행동보존: metrics-fast 전판 + make test SUITE_OK + **suite 51/51** + verify_371(캐시
      지문)·387(22)·388(22) virgin 격리 그린.

## codex 적대 스팟 리뷰 결과 — P1/P2 0건, P3 1건

- **P3 정리**: verify_122의 소스 문자열 단언(`allowed = {`)이 분할로 깨짐 → 값 단언
  (_OVERRIDE_ALLOWED 포함 검사)으로 갱신. 단 이 테스트는 **이미 KNOWN_DRIFT 격리**였고
  통합 B1의 400은 HEAD 재현(모델 없는 에이전트+오버라이드 → 스펙 290 거절 조건이 None==None
  매칭)으로 기존 드리프트 확정 — 격리 사유를 실측으로 정밀화.
- 확인함(codex): resolve_agent_mem_cfg 조회 동일·_merge_one_node 의미 동일·cfg.update 4키
  동일·400 순서 보존·remote 판정 단일·빈 dict pin 경로 동일·임포트 그래프 types 최하위.

# 396 — chat.py 구조 개선(턴 가족 분할 + C급 분해, 메인 SSE 경로)

> 상태: **완료** · 2026-07-19 (승인 후 P1~P5 실행 → codex 적대 리뷰 **발견 0건** 2연속)
> 발단: 복잡도 캠페인 마지막 대형 파일 — 1,147줄(최대)·C급 2·**핵심 채팅 경로**(POST /chat SSE).
> 방식: 5회전 — codex 자문(`.dev/reviews/396-chat/codex-consult.md`) → 승인 → 실행 → 적대.

## 구조 판단(codex — 백로그 전제 재검증 2번째)

- **374 "chat→ChatTurnService(큰 클래스)"는 기각** — 당시 전제(ctx dict·거대 stream 모듈)는
  382(ChatContext DTO)·392(chat_stream 해체)가 해소. 메인 /chat은 SSE 프레임·trace·persist·
  detached memory·checkpoint retention·HIL을 동시에 계약으로 갖고 있어 큰 클래스는 새
  god-object가 된다. **평면 형제+파사드+순수 이동**(확립 패턴)을 적용하고, `chat()` 얇게
  만들기는 최후 단계에서 **작은 runner 필요성만 재판정**.

## 진단

1. `_build_turn_runtime`(C15) — 회상·창 프록시·도구·브로커·프롬프트 seed·**캐시 적중/미스**·
   buildMs 계측이 한 함수, dict 반환(캐시 hit 시 tools 재사용+per-turn calls_sink 주입 계약이
   숨어 있음 — 순수 이동 중 깨지기 쉬운 지점).
2. `chat()` 라우트가 턴 라이프사이클 전체를 소유(진입 권한→로드→분기→시드→astream→오류→
   interrupt 디스패치→finalize→checkpoint release). `interrupts` 리스트가 finally의 paused
   판정까지 관통.
3. `_final_frames`(C13) — trace 조립·persist·message_id·detached memory task·memoryPending·
   프레임 순서를 한 함수가 결정("조금 정리"가 바로 UI 스피너/저장 보장을 깨는 지점).
4. interrupt 프레임 가족은 모양이 비슷하나 **계약이 다름**(ask/form=영속O, approval=영속X) —
   공통화가 오히려 위험(공통화는 OUT).

## 처방(위험 오름차순 — codex 순서)

- **P1 소비자 박제**: `from api.chat import`/`getsource(chat.*)` 소비자 20곳 rg 박제(스펙 부록),
  chat() 본문의 소스-텍스트 단언(057 기격리·058) 실측 확인.
- **P2** `chat_final.py`: _bg_memory_add·_final_frames·_BG_MEMORY_TASKS·타임아웃 상수 —
  스펙 314 계약(done 후 trailing memory 이벤트·client abort에도 태스크 보장) 소유.
- **P3** `chat_sse_frames.py`: _stream_text·_ingest_update·_artifact_wait_trace·_ask_frames·
  _form_frames·_pending_approval_trace·_approval_frames·_interrupt_frames(가족 단위 순수 이동,
  ask/form/approval 계약 차이 보존).
- **P4** `chat_turn_runtime.py`: _memory_inputs·_build_turn_runtime·_resolve_graph_entry·
  _turn_config·_seed_and_sent + 그래프 캐시(_GRAPH_CACHE·stats) 정의 이동. **명시 개선 1건**:
  turn dict → `ChatTurnRuntime` dataclass(필드 1:1, 소비자=이동 가족 내부뿐 — codex 권고,
  mypy 안전망). C급 2개는 여기서 분해(캐시 적중/미스 경로·트레이스 조립 추출).
- **P5** chat.py = router+chat()+파사드. chat() 내부 제너레이터를 `run_chat_turn()`으로 하강
  검토 — 작은 runner 도입 여부는 이 시점 재판정(필수 아님).

**OUT**: 프레임 가족 공통화(계약 상이)·큰 ChatTurnService·SSE 프레임/trace 필드 변경 일절.

## 동작보존 함정(codex 목록)

1. **SSE 순서 동결**: session → text/artifact → message_id(persist 뒤) → trace → done →
   (trailing) memory. 프론트 파서(api.ts·Playground)가 순서 전제.
2. memoryPending은 **live trace 전용**(영속 trace 미포함).
3. done 직후 client abort에도 memory task는 이미 떠 있어야(verify_314가 직접 핀).
4. `interrupts` 리스트=checkpoint release의 paused 판정 재료(스코프 은닉 금지).
5. 캐시 hit: tools 재사용+per-turn calls_sink는 config 주입(371 D3) — 트레이스 격리 계약.
6. ask/form=assistant 영속+trace+done vs approval=미영속+pending trace(계약 비대칭 유지).
7. 소스-텍스트 단언: 057(기격리·기존 드리프트)·058은 이동 후 실측, 깨지면 값 단언 갱신.

## 완료 기준(수치) — 전부 달성(실측)

- [x] chat.py **391줄**(1,147→391 — 파사드+router+진입 헬퍼 2+chat()) + 3형제(turn_runtime 384·
      sse_frames 360·final 192).
- [x] C급 2→0: _build_turn_runtime 15→**B(10)**(_turn_tools+_graph_for_turn 추출),
      _final_frames 13→**B(9)**(_memory_kickoff+_spawn_memory_task+_trailing_memory_frame 추출).
      전체 C급 49→**47**(캠페인 5회전 누적 **61→47**). MI 신규 전부 A(53~69).
- [x] ChatTurnRuntime dataclass(명시 개선) — 구 dict 키 15종 1:1, 소비자(chat_trace 15곳 포함)
      전량 속성 접근 전환, 잔존 dict 접근 0(codex rg 실측).
- [x] 소비자 20곳 import 무변경·verify_058 소스 단언 문자열 chat()에 잔존(codex 실측).
- [x] 행동보존: metrics-fast 전판 + make test SUITE_OK + **suite 51/51** + 표적 verify
      371(캐시)·314(비동기 기억)·101(HIL 왕복)·237·383 그린 + **실채팅 SSE 프레임 순서 실측**
      `session→text→message_id→trace→done→memory` 정확(라이브 서버).
      (242는 KNOWN_DRIFT 기격리라 제외 — 스펙 계획의 오기재 정정.)

## codex 적대 스팟 리뷰 결과 — **발견 0건**(2연속, 5회전 P2 추이 2→1→0→0→0)

확인함(codex): dataclass 1:1·캐시 hit 계약(stats 증가·tools 재사용·mcp/rag 0ms)·그래프 3분기와
저장/축출 동일·done 전 태스크 스폰·shield/취소 재전파·interrupts 클로저 관통·verify_058 문자열
잔존·import 사이클 0(TYPE_CHECKING뿐)·파사드 표면 누락 0(추가는 ChatTurnRuntime뿐).

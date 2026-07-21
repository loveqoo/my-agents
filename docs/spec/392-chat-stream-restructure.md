# 392 — chat_stream.py 구조 개선(책임 분리 + out-param 제거)

> 상태: **완료** · 2026-07-18 (승인 후 P1~P4 실행 → codex 적대 리뷰 P2×2·P3×1 전부 봉합)
> 발단: 복잡도 스냅샷(리뷰 재료 2026-07-18)에서 chat_stream.py가 이번 주 최대 성장(+260줄, 스펙 388)
> 지점으로 지목. 개발자 지시: "codex에게 문의하고, 파이썬 리팩토링·디자인패턴을 습득해 개선."
> 입력: codex read-only 자문(전문 `.dev/reviews/392-chat-stream/codex-review.md`) + 패턴 리서치
> (PEP 525 · Introduce Parameter Object · Replace Function with Command · 순환 import 해소).

## 진단(codex + 자체 측정 합치)

1. **out-param `state: dict`** — async generator가 값을 반환 못 하는 PEP 525 제약의 우회.
   "스트림 소진 후 dict를 읽어라"는 시간 순서가 타입에 없어 취소·조기 반환에 취약. (최우선)
2. **`_serve_chunks` 인자 10개** — 응집도 붕괴 신호(스트리밍+interrupt+영속+기억이 한 함수).
3. **책임 4개 혼재** — 설정 오류 SSE / 연결 힌트 / 원격 A2A 중계 / 로컬 A2A 서빙이 한 모듈.
4. **지연 import 순환** — chat.py 파사드 재수출 ↔ chat_stream·chat_approval의 역방향 지연 import
   (`resolve_agent_runtime`·`_rag_tools_for`가 chat.py에 남아 생긴 순환).

## 처방(위험 오름차순 4단계 — codex 권장 순서 채택)

- **P1 순수 이동(위험 최소)**: `_config_error_stream`·`_model_error_hint`·`_CONN_ERR_MARKERS` →
  `chat_sse_errors.py`, `_a2a_stream` → `chat_a2a_proxy.py`. chat.py 파사드 재수출 계약 유지.
- **P2 파라미터 객체 + Command 클래스**: 로컬 A2A 서빙(`stream_local_reply`+`_serve_*` 6종)을
  `chat_a2a_serve.py`로 이동하며 **Replace Function with Command** 적용 — 헬퍼들이 인자로 나르던
  공통 문맥(ctx·user_id·thread_id·has_ckpt…)을 dataclass 필드로 흡수(`_ServeTurn` 류).
  `_serve_chunks` 인자 10→（self）로. 이 단계는 out-param 유지(계약 불변).
- **P3 out-param 제거(계약 변경 — 이번 스펙의 핵심)**: 반환을 `(context_id, gen, state)` →
  결과 객체로. Command 클래스가 스트림과 최종 상태를 함께 소유하고, 소비자(a2a_server)는
  스트림 소진 후 `turn.outcome`(Completed | ApprovalRequired | Failed)을 읽는다.
  a2a_server의 state 소비 2곳(message/send·message/stream) 동시 갱신.
- **P4 순환 제거**: `resolve_agent_runtime`·`_rag_tools_for`를 `chat_graph_build.py`로 하강,
  chat_stream(2곳)·chat_approval(1곳)의 지연 import 제거. chat.py는 재수출만.

**OUT(이번 스펙 제외)**: 메인 chat 스트림과의 공통 runner 추출(codex 6단계) — interrupt·기억·SSE
프레이밍 계약이 서로 다르므로 중복이 선명해진 뒤 별도 스펙으로.

## 동작보존 함정(codex 6건 — 각 단계에서 회귀 확인 대상)

1. SSE 프레이밍 이원 규약: 원격 중계는 SSE 프레임 직접 생산, 로컬 서빙은 raw text만(감싸기는 a2a_server).
2. GeneratorExit 경계: 서빙 기억 저장은 스트림 종료 후 인라인(중간 이탈 시 생략이 **정직한 계약**) —
   메인 chat의 detached task와 다르며, 이번에 "고치지" 않는다(변경=동작 변화).
3. interrupt 턴 미영속 계약(재개가 전체 턴을 영속).
4. ephemeral → 체크포인터 미부착·interrupt는 error 안내로 접기.
5. contextId 세션 연속성·own=userId 접힘·channel="a2a" 스탬프.
6. a2a_server 승인 브리지: send→input-required Task, stream→final status event.

## 완료 기준(수치) — 전부 달성(실측)

- [x] chat_stream.py **소멸** — chat_sse_errors(57줄)·chat_a2a_proxy(83)·chat_a2a_serve(338)·
      chat_graph_build(146) 4모듈로 분리. chat.py 1,262→1,147줄·MI 24.9→**30.8**.
- [x] `stream_local_reply` CC 16 → LocalServeTurn.chunks **B(10)**·prepare_serve_turn B(8) 등
      서빙 경로 전 함수 ≤B. 신규 모듈 MI 52~89(전부 A).
- [x] 서빙 경로 함수 인자 최대 **5개**(_build_serve_graph) — 옛 10개는 self 필드로 흡수.
- [x] 역방향 지연 import **0건** — 실측은 스펙 가정(3곳)보다 많은 **5곳**이었음(chat_approval에
      _MemoryRecallProxy·_graph_fingerprint 2곳 추가 발견) → 4심볼 전부 chat_graph_build로 하강.
- [x] mutable out-param 0건 — `serve_state` grep 0.
- [x] 행동보존: metrics-fast 전판 + make test SUITE_OK + **suite 51/51** + verify_061/059/081(unit)
      + verify_387 22/22·verify_388 22/22(virgin 격리 서버, codex 봉합 후 재확정).
      057 C5 실패는 변경 전(HEAD)에도 실패하던 기존 드리프트로 판정(git show 대조).

## codex 적대 스팟 리뷰 결과(P3 완료 조건) — P1 0건

- **P2** chunks() 재호출 가능(옛 one-shot generator보다 넓은 계약 — 영속·Approval 중복 위험)
  → `_started` 가드로 1회용 잠금(재호출 RuntimeError).
- **P2** verify_061 `_FakeTurn`의 outcome이 일반 속성 None → premature-read 회귀가 거짓 초록
  → 실물과 동일한 fail-loud 프로퍼티로 미러.
- **P3** prepare 순서 변화(impl/model 검사가 도구·회상 뒤로 밀림 — "설정 실패 즉시 반환" 관측
  순서 훼손) → `_resolve_serve_impl`을 prepare 선두로 복원.
- 확인함: relay(turn=None) 경로·부분 소진 시 outcome 미접근·interrupt 텍스트 처리·임포트
  그래프 단방향·이동 심볼 사용처 — 전부 무결.

리뷰 원문: `.dev/reviews/392-chat-stream/codex-review.md`(사전 자문) + 적대 리뷰는 세션 기록.

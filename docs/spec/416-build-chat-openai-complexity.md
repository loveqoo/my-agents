# 416 — build_chat_openai 복잡도 분해(CC 31 E → 게이트 통과)

> 상태: **완료**(CC 31→15·게이트 통과·verify_411 24/24·410 14/14 무회귀) · 2026-07-20 · 발단: `make complexity`(xenon 상한 절대 C) 유일 실패 —
> `model.py:46 build_chat_openai`가 **CC 31(E)**. 스펙 411에서 wire 기반 파라미터 배선이 한 함수에
> 누적된 선재 부채(내가 이번 세션 만진 파일 아님). 나머지 함수·MI는 전부 게이트 통과.

## 설계 — 동작 보존 추출(extract-body-keep-wrapper, learning 126)
공개 `build_chat_openai`는 얇은 오케스트레이터로 남기고, 두 덩어리를 model.py 내 private 헬퍼로 뺀다
(단일 소비자라 크로스모듈 분리는 안 함 — YAGNI, [[structure-first-boundary-is-spec]]):

1. **`_resolve_wire_params(caps, params, cfg_params, default_temperature) -> (top_kwargs, extra_body,
   disable_streaming)`** — PARAMS 루프 + bool/number 분기 + wire 라우팅(top/extra_body/disable_streaming)
   + temperature 명시 판정(기존 default_temperature 계약) + chat_template_kwargs 래핑. 복잡도의 대부분.
2. **`_pool_key(...)` + `_pool_get`/`_pool_remember`** — loop_id 게이팅·키 구성(파라미터 전량 반영)·
   LRU 축출.

공개 함수 골격: 미설정 검사 → `_resolve_wire_params` → `_pool_key`+`_pool_get` → ReasoningChatOpenAI
생성 → `_pool_remember` → 반환.

## 불변식(refactor-wholesale-replace-destroys-new-fields, learning 155 — 조용한 누락 금지)
추출이 **어떤 분기도 빠뜨리면 안 된다**. 보존 목록:
- temperature 미명시 시 default_temperature 존중(스펙 077 흡수), bool 아닌 int/float만 명시로 간주.
- max_tokens None/≤0 → 서버 기본(안 보냄, continue).
- number None → 스킵.
- chat_template_kwargs 비어있지 않을 때만 extra_body에 래핑.
- 풀 키 = (loop_id, base_url, api_key 지문8, model_id, top_kwargs json, extra_body json, disable_streaming).
- loop_id None(동기 컨텍스트) → 풀 미사용. LRU = 삽입순 최고령 축출, 상한 64.
- ReasoningChatOpenAI(스펙 410) 유지 — base가 버리는 reasoning_content 복원.

## 검증(logic-surgery-needs-live-roundtrip, retrospect 167 · measure-complexity-first, 222) — 달성
- [x] `make complexity` 그린 — build_chat_openai **31(E)→15(C)**, _resolve_wire_params 16(C)·풀 헬퍼 A. xenon rc=0.
- [x] verify_411 24/24·verify_410 14/14 무회귀 — 실 배선 보존.
- [x] 실채팅 왕복(dev 서버) 200·텍스트 프레임 수신.
- [x] make test 91/0/0(verify_043이 416 INDEX 누락 선제 포착 → 줄 추가 후 그린) · lint · mypy 그린.

## OUT
- 게이트 통과 C 등급 함수들(mock_remote·rag_ingest·net_guard 등)은 상한 이내라 무손. 별건.

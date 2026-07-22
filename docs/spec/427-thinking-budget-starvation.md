# 스펙 427 — 사고 모드 토큰 예산 굶김(finish_reason=length) 표면화 + 사고 바닥

## 문제(재현·근인)

atom-spark(vLLM+Qwen3.6)에서 **Thinking 모드만 켜고 max_tokens를 작게** 두면, 사고(reasoning)와
답(answer)이 **하나의 max_tokens 예산을 공유**한다. 사고가 길면 답이 시작되기 전에 예산이 소진돼
서버가 `finish_reason=length`로 스트림을 끊고, 사용자에겐 **본문이 없거나 잘린 응답**만 남는다.
사용자 보고: "top_k 설정이 없어서 thinking 모드만 사용하다가 응답이 없이 length로 끝났습니다."

**근인은 두 겹이다.**
1. (일반) 어떤 이유로든 `finish_reason=length`로 끊긴 응답을 **사용자에게 아무도 알리지 않는다**
   — 잘림이 침묵한다.
2. (특정) 사고 모드는 답까지 갈 예산을 사고가 먼저 먹을 수 있는데, **작은 max_tokens가 그대로 전송**
   된다 — 사고 함정.

## 불변식(메커니즘 이전에)

- **A의 불변식**: "잘림은 절대 침묵하지 않는다." finish_reason=length는 원인(사고·긴 답·작은 예산)
  무관하게 사용자에게 표면화된다 — 모든 케이스를 덮는 안전망.
- **B1의 함정 제거**: 사고 모드가 켜졌고 max_tokens가 **명시적으로 바닥(8192) 미만으로 설정**됐으면,
  그 요청에 한해 바닥값으로 올린다 — 사고가 답을 굶기는 특정 경로를 없앤다. **저장값은 무변경**,
  **세션당 1회 토스트**로 알린다(침묵 오버라이드가 아닌 "고지된 조정").

### B3(사고 길이 캡)은 폐기 — 증거 기반

atom-spark vLLM 담당 에이전트 리포트로 확정: 이 vLLM+Qwen3.6 조합엔 **사고 예산 캡이 존재하지 않는다**
(`reasoning_max_tokens`·`max_reasoning_tokens`·`thinking_budget` 전부 무시, chat_template.jinja에 예산
로직 0). 유일한 레버 = `enable_thinking`(2진 스위치) + 전체 `max_tokens`. 따라서 사고 길이를 직접
제한하는 B3은 이 스택에서 불가능 → 추구하지 않는다.

## 결정

- **A**(모든 케이스 안전망): 채팅 astream 루프에서 `finish_reason=length`를 캡처 → trace에 `truncated`
  플래그로 표면화 → FE가 경고 토스트("응답이 최대 토큰에서 잘렸습니다 — max_tokens를 늘리세요").
- **B1**(사고 바닥): `_resolve_wire_params`(배선 해석 단일 지점)에서 사고 ON + `0 < 유효 max_tokens < 8192`
  이면 그 전송에 한해 max_tokens=8192로 대체. trace에 `thinkingBudgetApplied` 필드 → FE가 세션당 1회
  토스트.
  - **바닥=8192**, **세션당 1회 토스트**: 사용자 승인 완료(제품 가시 수치 — [[product-limits-need-explicit-approval]]).
  - **미설정(mt=0)은 제외**: 0은 "서버 기본"(안 보냄)이고 서버 기본은 보통 문맥 전체라 크다 — 8192로
    올리면 오히려 서버 기본을 깎는다. 명시적으로 작게 설정한 경우만 바닥을 올린다.

## 구현

### `packages/agent/src/agent/model.py`
- `THINKING_MAX_TOKENS_FLOOR = 8192`.
- `thinking_budget_applied(caps, params, cfg_params) -> int | None`: 순수. `resolve_effective("enable_thinking", …)`
  가 True이고 `resolve_number("max_tokens", …)`이 `0 < mt < FLOOR`이면 FLOOR, else None.
- `_resolve_wire_params`: 루프 뒤 `bump = thinking_budget_applied(…); if bump: top_kwargs["max_tokens"] = bump`.
  단일 지점이라 chat·eval·a2a 전 경로에 균일 적용.

### `packages/api/src/api/chat.py`
- astream 루프에서 메시지 청크의 `response_metadata.get("finish_reason") == "length"`를 추적 → `truncated`
  플래그를 `_final_frames`로 전달.

### `packages/api/src/api/chat_final.py`
- `_final_frames`가 `truncated` 수신 → trace에 `truncated=True`.
- `thinking_budget_applied(ctx.model_cfg 능력/params)` 계산 → trace에 `thinkingBudgetApplied=N`.
  (노드형은 노드별 예산이라 이 필드는 주 모델 기준 best-effort. **bump 자체는 노드 경로도 균일 적용**.)

### `admin/src/api.ts` + 플레이그라운드
- `onTrace` 소비부에서 `trace.truncated` → `message.warning`(잘림 고지), `trace.thinkingBudgetApplied` →
  세션당 1회 토스트(클라이언트 dedup).
- 새 프레임 타입·콜백 없이 **기존 trace 이벤트에 필드 두 개** 추가(드리프트 최소).

## top_k 동봉

이번 커밋에 미커밋 top_k 추가(capabilities.py 서술자 1줄 + model.py 0/미설정 가드)를 함께 싣는다 —
vLLM 담당 에이전트가 추천한 표면이고, 사고 굶김 완화의 튜닝 축과 같은 맥락(같은 스택 파라미터).

## 완료 조건(측정) — 결과

1. **단위 ✅**: `verify_411_model_params.py` 28/28. U4e 추가: (사고ON,512)→8192 / (사고ON,0)→None /
   (사고OFF,512)→None / `_resolve_wire_params`가 사고ON+512에서 top_kwargs["max_tokens"]==8192.
2. **서버 계약 ✅**(`tests/verify_427_budget.py` — 라이브 vLLM qwen36, 신선 nonce):
   - B1: `thinkingBudgetApplied==8192`, 답 본문 395자(굶김 해소), `truncated` 없음.
   - A: `truncated==True`(사고OFF+mt16 긴 답 → finish_reason=length), `thinkingBudgetApplied` 없음.
3. **FE 토스트 렌더 ✅**(`tests/browser/verify-427-budget-toast.mjs`): 사고 바닥 토스트("최대 토큰을
   8192로 적용합니다") 렌더 + 답 완결 캡처. B1은 모델 무관이라 기본 모델서도 렌더.
4. **tsc 0 ✅**.

## OUT(경계 명시)

- 노드형 per-node 사고 예산의 토스트 정밀 반영(bump는 적용, 토스트는 주 모델 기준).
- 사고 길이 자체 캡(B3 — 스택 미지원, 폐기).
- **MLX(qwen3.6-35b/8045)의 finish_reason=length 표면화는 미검증**: MLX는 max_tokens를 vLLM처럼
  하드캡하지 않아 A(잘림)가 재현되지 않는다. A 코드는 서버가 보고하는 finish_reason을 그대로
  표면화할 뿐(모델별 특례 없음) — vLLM에서 확정. MLX 잘림 표면화는 별개 모델서버 특성으로 경계 밖.
- A의 FE 잘림 경고 토스트: 브라우저 오버라이드 모델 셀렉트가 가상화라 vLLM 지정이 불안정 →
  브라우저 독립 렌더 캡처는 B1로 대표(동일 onTrace→message 경로), A는 서버 계약(verify_427)으로 검증.

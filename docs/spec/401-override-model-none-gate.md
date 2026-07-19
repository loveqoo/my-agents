# 401 — 오버라이드 모델 거절 게이트의 None==None 오폭 수리(스펙 290 보완)

> 상태: **완료** · 2026-07-19 (승인 후 P1~P2 + codex 스팟 리뷰 반영)
> 발단: 스펙 400 재활 중 발견·보고(verify_122가 픽스처에 모델 명시로 우회 중).

## 버그(실측)

`chat_context_models._resolve_model`의 스펙 290 거절 게이트:

```python
if overrides and overrides.get("model") == model_name:
    raise HTTPException(400, f"오버라이드 모델 '{model_name}' 미등록…")
```

**모델 미지정 에이전트**(config에 model 없음 → `model_name=None`)에 임의 오버라이드 dict가 오면
`overrides.get("model")`도 None → **None==None 매칭**으로 "오버라이드 모델 'None' 미등록" 400.
두 경로 모두 오폭:
- ① overrides에 model 키 자체가 없음(예 `{"capabilities": [...]}`) — 400의 이유가 없음.
- ② overrides={"model": None}(JSON null) — 명시 이름이 아니므로 기본 폴백이 정직.

스펙 290의 의도(learning 092)는 "**명시로 이름 댄** 오버라이드 모델이 미등록이면 시끄럽게 거절,
미지정은 기본 폴백" — 선언-but-broken만 거절하고 미선언은 폴백하는 구분이 무너진 것.

## 처방

- **P1 게이트 수리(1줄)**: 소유 판정에 실명 요구 —
  `if overrides and overrides.get("model") and overrides.get("model") == model_name:`
  (None·빈 문자열은 "명시 이름"이 아님 → 기본 폴백 경로. 저장 config의 미지정/빈값과 동형.)
- **P2 회귀 핀(verify_122 확장 — 이 게이트의 기존 유일 접점)**: 3축
  1. 모델 미지정 에이전트 + model 키 없는 오버라이드 → 400 없이 기본(mock-llm) 해석.
  2. 모델 미지정 에이전트 + overrides={"model": None} → 동일 폴백.
  3. 명시 미등록 이름(`{"model": "없는모델401"}`) → **400 유지**(290 본 계약 무회귀).
  검증 후 122 픽스처의 모델 명시 우회 주석을 "수리됨(스펙 401)"으로 갱신.

## 완료 기준(수치) — 전부 달성(실측)

- [x] verify_122(B6 4축 포함) virgin 그린 10/10.
- [x] make test SUITE_OK + metrics-fast 전판.
- [x] codex 스팟 적대 리뷰: **P1 없음**(명시 미등록 이름의 400 전 경로 유지 — cfg.update 병합·pins·
      호출부 단일 입구 확인). P2=빈 문자열 `""` 경계(전 400→폴백) — 승인 축("빈값=미선언, 저장
      config와 동형")대로 동작 유지하되 **B6d로 명시 핀**(미문서 경계의 정직화).

## OUT

- 저장 config의 미등록 모델 graceful 폴백 재설계(기존 docstring이 백로그로 명시 — 유지).
- 게이트 메시지·표면 변경.

# 417 — 노드형 세부 탭 모델 파라미터 오버라이드 숨김

> 상태: **완료** · 2026-07-20 · 발단: 구남님 "노드형 에이전트 수정에서 세부 탭에서 모델 메타값
> 설정은 이상하다. 노드마다 셋팅했으니까." 방향=숨김(구남님 선택). tsc0·브라우저 SHOT417_OK.

## 진단 — 표면 짝 불일치(retrospect 238)
노드형(pipeline)은 **에이전트-레벨 모델 *선택*을 이미 숨긴다**(AgentForm.tsx:566 `isPipeline ? null`,
"모델·프롬프트도 노드마다"). 각 노드가 자기 모델을 고른다(NodeListEditor). 그런데 세부 탭(단계 ③)의
**모델 *파라미터* 오버라이드**(CapabilitySettings "모델 설정 오버라이드")는 안 숨긴다 — **선택할 수도
없는 모델의 파라미터**를 노출. 표면(모델 선택)은 숨겼는데 짝(모델 파라미터)이 재등장한 것
([[hidden-value-reappears-in-summary]] 계열, 스펙 263이 요약 카드에선 이미 처리).

기술적으로 에이전트-레벨 modelParams는 캐스케이드 뿌리(모델기본→**에이전트**→노드→세션, 스펙 409)라
"모든 노드 공통 기본값"으로 작동은 한다. 하지만 모델 선택 없이 노출돼 혼란(구남님 지적). 직접·조율·
산출물형은 에이전트 모델을 보여주므로 파라미터 오버라이드가 정합 — **노드형만** 어긋난다.

## 설계 — 숨김 + 함정 차단
1. **세부 탭 패널 숨김**: "모델 설정 오버라이드" Field를 `!isPipeline`로 게이팅. **단기 기억은 유지** —
   모델 독립(대화 창 깊이 숫자)이라 에이전트-레벨 기본값이 정합(노드형 상속 원천, 스펙 271/238).
2. **저장 시 modelParams 제거**(retrospect 238 핵심): `finalizeForm`의 노드형 분기에 `modelParams: {}`.
   패널만 숨기고 form 값이 남으면 캐스케이드로 **전 노드에 조용히 적용**된다(숨긴 값의 비가시 적용).
   AgentsView는 빈 modelParams를 저장에서 제외(167행)하므로 = 미저장. 레거시 값도 다음 저장서 청소.
3. **요약(단계 ④)**: 스펙 263이 이미 "모델·프롬프트: 노드마다 설정"으로 대체 — 무변경(정렬됨).

## 검증(ui-verification-must-be-functional, verify-ui-in-browser-proactively) — 달성
- [x] 노드형 편집 → 세부 "모델 설정 오버라이드" **없음**(hasOverride=0)·단기 기억 **있음**(hasShortTerm=1).
      실 브라우저(research-pipeline-demo, tests/browser/shot-417) + 스샷 육안.
- [x] 직접형(personal-secretary) 세부 "모델 설정 오버라이드" **있음**(hasOverride=1, 무회귀).
- [x] 저장 strip: finalizeForm 노드형 분기 `modelParams: {}` — AgentsView가 빈 modelParams를 저장서
      제외(167행)하므로 미저장·레거시 청소. 코드 확인(1줄 방어, retrospect 238).
- [x] tsc 0 · 노드별 CapabilitySettings(NodeListEditor)는 무변경(각 노드 파라미터 유지).

## OUT
- 단기 기억의 노드형 처리(모델 독립이라 유지 — 사용자 미지적, 별건).
- 캐스케이드 백엔드 로직 무변경(에이전트 층이 비면 자연히 노드 층만 적용).

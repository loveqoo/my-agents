# 419 — 노드형 플레이그라운드 오버라이드 세부 탭 세션 모델 설정 숨김

> 상태: **완료**(tsc0·브라우저 SHOT419_OK) · 2026-07-20 · 발단: 개발자 "노드형 에이전트의 플레이그라운드
> 오버라이드 할 때, 세부탭에서 모델 설정을 중복으로 하고 있오. 이미 노드별로 하고 있는데." 방향=숨김(417 일관).

## 진단 — 417의 자매 표면 누락(single-source-sweep)
스펙 417은 **AgentForm**(에이전트 편집) 세부 탭의 노드형 모델 파라미터를 숨겼으나, **플레이그라운드
OverridePanel**이라는 자매 표면은 안 봤다([[retrospect 261 single-source-sweep]] — 진실원 바꾸면 소비
표면 전수). 노드형 오버라이드 탭은 `[노드][세부]`(OverridePanel:395):
- '노드' 탭: NodeListEditor — per-node 모델·파라미터 오버라이드.
- '세부' 탭(step 1, 471~491): ShortTermMemory + `CapabilitySettings` "모델 설정(이 대화 · 전 노드 공통)".

세부 탭의 "전 노드 공통"은 캐스케이드 세션층(스펙 411 codex가 복원 — 노드층 위를 덮음)이라 기술적으론
per-node와 다른 층이지만, 사용자 눈엔 "모델 설정 두 군데"라 혼란(개발자 지적). 417과 같은 규칙 적용:
노드형은 모델 설정을 노드가 소유(노드 탭)로 일원화.

## 설계 — 숨김 + 세션 modelParams 미전송
1. **세부 탭 CapabilitySettings 제거**(노드형 step 1): "모델 설정(전 노드 공통)" Field 삭제, ShortTerm
   Memory는 유지(모델 독립 — 노드 상속 원천값, 417과 동일 판정).
2. **페이로드 게이트**(retrospect 238 — 숨김의 짝은 데이터): `buildOverridePayload`에서 노드형
   (`applied.nodes` 존재)이면 세션 `modelParams`를 **전송 안 함**. 컨트롤을 숨겨 draft가 안 변해도
   명시 차단(세션층이 노드를 되덮는 걸 UI 뿐 아니라 계약에서도 막음).

## 검증(ui-verification-must-be-functional) — 달성(tests/browser/shot-419)
- [x] 노드형 오버라이드 세부 탭 "모델 설정" **없음**(hasModelSetting=0)·단기 기억 **있음**(hasShortTerm=2)·
      노드 탭 무변경. 직접형 세부 "모델 설정" **있음**(hasModelSetting=3, 무회귀). SHOT419_OK.
- [x] payload 게이트: `buildOverridePayload`가 `!applied.nodes`일 때만 modelParams 전송(노드형 미전송).
- [x] tsc 0.

## OUT
- 캐스케이드 백엔드 세션층 로직 무변경(노드형이 modelParams를 안 보내면 자연히 노드층까지만 적용).
- 조율형·산출물형 오버라이드 세부 탭(모델 컨텍스트 보유 — 417과 동일하게 무변경).

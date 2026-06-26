# 019 — 플레이그라운드 모델 배지 정직화 (회고)

스펙: [028](../../docs/spec/028-playground-honest-model-badge.md)
날짜: 2026-06-26
연결: [[probe-deeper-before-concluding]], [[029-same-origin-proxy-collapses-cross-origin-class]],
[[030-verify-ui-in-a-real-browser]]

## 무엇을 했나

플레이그라운드 picker/헤더가 모든 에이전트의 `agent.model`을 실행 모델인 양 표시했다.
code 에이전트(Doc Translator)는 `model="qwen3.6-35b"`로 박혀 있지만 실제론 원격 엔드포인트
(dev=mock)로 bypass → 배지가 거짓. `source`별로 갈라 ui=모델명 / code="코드 정의" /
external="외부 A2A"로 정직하게. 표시만, 라우팅·백엔드 무변경(`DebugChat.tsx` 한 파일).

## 아팠던 것 — 측정이 사용자 보고와 어긋났을 때

사용자 보고는 *"Doc Translator 모델이 qwen인데 mock이 응답… 다른 에이전트도 마찬가지"*.
내 라이브 측정은 **ui=진짜 qwen, code만 mock**이라 "다른 에이전트도 마찬가지"와 어긋났다.
[[probe-deeper-before-concluding]] 그대로: 단정하지 않고 **양쪽을 다 제시**(측정 + 표시 결함
가설)하고 사용자에게 의도를 물었다. 사용자는 옵션 "표시를 정직하게"를 골랐다 — 즉 보고의
핵심은 *동작 버그*가 아니라 **배지가 거짓말**이라는 것이었고, "다른 에이전트도 마찬가지"는
*같은 거짓 배지 패턴이 picker 전체에 반복*된다는 뜻이었다. 측정을 의심하되 버리지 않고
**해석을 사용자에게 위임**한 게 정답이었다.

## 잘된 것 — 화면을 진짜 브라우저로 직접 확인

가장 큰 수확은 **검증 방식**이다. 그동안 화면 변경을 사용자 스샷에 의존했는데, 이번엔
Playwright + 시스템 Chrome(`channel:'chrome'`, 브라우저 다운로드 0)으로 admin을 띄워
**BEFORE(qwen 파란 배지) → AFTER("코드 정의" 중립 pill)**를 내가 직접 캡처했다. 사용자가
보낸 스샷과 BEFORE가 픽셀 수준으로 일치 → 재현·수정·검증 루프가 사람 의존 없이 닫혔다.
재사용 가능한 하니스(`tests/browser/shot-playground.mjs`)로 남겼다.

- 결합 관점([[029-...]]의 변주): 증상(특정 에이전트)이 아니라 **배지가 source를 무시하는
  결합**을 끊었다 — 헬퍼 하나로 세 source를 가르니 두 표시 지점이 자동 일관.

## 다음에

- **UI 수정·확인은 기본적으로 브라우저로 직접 본다**([[030-verify-ui-in-a-real-browser]]).
  사용자에게 스샷을 요청하기 전에 내가 먼저 찍는다. 라우팅이 state면 메뉴 클릭으로 진입.
- 측정이 사용자 보고와 어긋나면 **어느 한쪽으로 단정하지 말고 둘 다 제시 + 의도 질의**.

# 347 — 노드형 플레이그라운드 오버라이드 세션 모델 설정 숨김(스펙 419)

## 발단
구남님: "노드형 에이전트의 플레이그라운드 오버라이드 할 때, 세부탭에서 모델 설정을 중복으로 하고
있오. 이미 노드별로 하고 있는데." 스펙 417 바로 다음 턴에 **같은 부류를 자매 표면에서** 또 지적.

## 진단 — 417을 한 표면만 고쳤다(single-source-sweep 반쪽)
417은 AgentForm(에이전트 편집) 세부 탭만 고쳤다. 같은 논리가 적용될 **플레이그라운드 OverridePanel**은
안 봤다. 노드형 오버라이드 세부 탭에 "모델 설정(전 노드 공통)"(세션 캐스케이드층)이 남아, 노드 탭의
per-node 설정과 나란히 "모델 설정 두 군데"가 됐다.

## 배운 것

### 1. 사용자 지적은 "패턴"이지 "인스턴스"가 아니다 — 첫 지적에 자매 표면을 함께 쓸었어야
417을 고칠 때 "노드형 모델 설정 중복"이라는 **패턴**을 이미 알았다. 그런데 AgentForm 한 곳만
고치고 끝냈다. 같은 데이터(modelParams)가 노드형에서 노출되는 표면은 grep으로 전수했어야
([[retrospect 261 single-source-sweep]]). 사용자가 다음 턴에 OverridePanel을 또 짚은 것 = 내가
패턴을 인스턴스로 축소한 대가. **지적이 "이 화면"이어도 고칠 땐 "이 데이터의 모든 화면"으로 넓혀라.**

### 2. codex가 "복원"한 표면도 제품 오너 앞에선 재심 대상
스펙 411 codex P1이 이 세션-modelParams 표면을 "잃어버린 캐스케이드 세션층"이라며 복원했다. 기술적
으론 맞다(세션층이 노드층을 이김). 하지만 제품 오너(구남님)에겐 혼란이었다. **codex의 완결성 논리
(모든 층을 UI로)와 사용자의 인지 단순성이 충돌할 땐 사용자가 최종심** — 트레이드오프(전 노드 일괄
조정 편의 상실)를 명시하고 사용자가 결정하게 했다(숨김 선택).

### 3. 숨김의 짝은 UI + 계약 둘 다(238) — 컨트롤 제거로 안 끝난다
세부 탭 CapabilitySettings만 지우면 draft.modelParams가 안 변해 자연히 미전송이지만, **명시 게이트**
(`buildOverridePayload`가 `!applied.nodes`일 때만 modelParams 전송)를 더했다. "컨트롤 없으니 값도
안 감"에 기대지 말고 계약에서도 세션층이 노드를 되덮는 걸 막아야([[align-all-consumer-surfaces]]),
레거시·경로변이에도 안전.

### 4. 플레이그라운드 위저드 검증은 컴포넌트별 관용구 편차가 크다
콤보(AgentCombo)=`.ant-avatar` 담은 상단 버튼·Steps 이동은 라벨 클릭 아니라 "다음" 버튼·오버라이드는
top 드로어(닫기=aria-label "오버라이드 닫기"). 4회 헛디뎠다. AgentForm(417)과 다른 화면이라 관용구를
새로 읽어야 했다([[retrospect 233 nearest-sibling-idiom]] — 화면마다 네비게이션을 먼저 실측).

## 자산화 후보(관련)
[[single-source-sweep]] [[align-all-consumer-surfaces]] [[codex-design-limit-third-verdict]]
[[read-navigation-idiom-first]] [[verify-ui-in-browser-proactively]]

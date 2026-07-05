# 166 — AgentsView.tsx(2128줄) 분해 Phase A

**스펙**: docs/spec/185 · **관련**: 182(god component 지목)·184(useAsyncData 토대)·165(폼시드 훅 부적합)

## 무엇을 했나
2128줄 god component에서 서브컴포넌트 8개를 `views/agents/`로 파일 분리 → 747줄. deep-reasoner로 정밀
매핑 후 fast-worker에 기계적 이동 위임, 메인이 tsc+브라우저로 검증. 순수 이동(행동 보존).

## 무엇이 잘못됐고 무엇을 배웠나

### 1. 분해의 실질은 대개 "로직 수술"이 아니라 "파일 분리"다
2128줄이라 겁났으나, 정밀 매핑하니 서브컴포넌트가 **이미 prop-driven 함수 경계로 분리**돼 있었다 —
얽힘은 공유 타입·콜백 시그니처·순환참조 위험뿐. 즉 대부분은 옮기고 import만 고치는 저위험 작업.
"god component 분해"를 큰 수술로 오해하면 착수를 미루는데, **먼저 매핑하면 위험의 실제 크기가 드러난다**.

- **처방**: 대형 파일 분해 전 정밀 매핑(deep-reasoner)으로 "수술 vs 이동" 비율을 먼저 재라. prop-driven
  자기완결 컴포넌트는 이동(tsc가 그물), 상태/이펙트 얽힘만 수술(브라우저 필요). 겁먹고 미루지 말 것.

### 2. 서브에이전트 "완료"는 가설 — tsc 초록도 브라우저로 확증
fast-worker가 "tsc 0"으로 마감했고 실제 0이었으나, tsc는 **순환 import를 통과시킨다**(런타임에만
터짐). PersonaStaleNote를 독립 모듈로 뺀 게 순환 방지의 핵심이었는데, 그게 지켜졌는지는 tsc가 아니라
**브라우저 로드(pageerror 0)**로만 확증된다. 스샷으로 3 드로어·폼이 실제 렌더됨을 눈으로 확인.

- **처방**: 파일 분리형 리팩터는 tsc(import 오류)+브라우저(순환·런타임) **둘 다**. tsc 초록을 완료로
  읽지 말 것. [[reverify-before-destructive-delete]]의 자매 — 위임 결과는 지점 재검증.

### 3. 내 검증 하네스가 붉을 때, 앱이 아니라 하네스를 의심하라 (또)
드로어 텍스트 읽기가 4번 실패(`.ant-drawer-open`·`:visible`·`.ant-drawer-content`)했으나 **스샷은 드로어가
멀쩡히 열림을 보여줬다**. 정체: `shared.Drawer`가 antd 아닌 **커스텀**(className·role 없음, 닫힘=translateX
off-screen). 앱은 정상, 셀렉터가 틀렸다. 각 드로어 고유 라벨을 Playwright 가시성으로 판정해 해결
(off-screen 드로어를 Playwright가 hidden 처리하는 성질 이용).

- **처방**: 기능 체크는 초록인데 특정 assert만 붉고 **스샷은 정상**이면, 코드가 아니라 셀렉터를 의심.
  특히 커스텀 컴포넌트는 antd 클래스 가정 금물 — 구현을 grep해 실제 DOM/고유 텍스트로 판정.
  [[fix-harness-not-code]](회고 165)의 재확인 — 이번엔 "성공=토스트0 논증"이 아니라 "스샷=열림" 대조.

## 복리 포인트
- god component 분해 = 정밀매핑→위임→tsc+브라우저 검증 파이프라인 확립(다음 대형 파일에 재사용).
- Phase B(useAgents)는 payoff<위험으로 보류 판단 — "구조 이득이 위험을 정당화하나"를 매번 재는 규율.
- 커스텀 Drawer 셀렉터 함정 기록 → 이후 드로어 검증은 고유 라벨 가시성으로.

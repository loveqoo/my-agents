# 348 — 모델 파라미터 층 정책 단일화(스펙 420)

## 발단
417(AgentForm)→419(OverridePanel) 같은 부류 실수 2연타. 개발자 커피챗: "반복되면 구조적 문제.
원천 차단 안 하면 또 발생." + "미래의 당신이 히스토리 기억하고 예외 피할 거라 예상하냐(=아니다)."
→ 증상(표면 5곳 땜질) 말고 **뿌리**(캐스케이드 층×유형 매트릭스가 각 표면·BE에 복붙)를 구조로 봉인.

## 한 일
- FE: 정책 함수 단일화 + `ModelParamsField`(유일한 문, raw CapabilitySettings 내부화) → 3표면 라우팅.
- BE: 정책 대칭 함수 + `_resolve_model`·`_resolve_node_models` 관문 게이팅 + **ctx.temperature 병렬
  통로 봉인** + Agent/AgentVersion.config **ORM @validates** 저장 관문.
- verify_420(계약 핀) 22/22 + codex 적대 4라운드.

## 배운 것

### 1. "정책을 한 곳에 모은다"보다 "**틀린 길을 없앤다**"가 amnesiac-proof
1차 설계는 "정책 함수 한 곳, 표면들이 참조"였다. 개발자이 한 단계 위로 밀었다 — 참조하는 걸
**기억해야** 성립하면 같은 실수가 재발한다. 그래서 raw `CapabilitySettings`를 아예 export에서 빼
**손에 잡히는 유일한 도구가 ModelParamsField**가 되게 했다. 새 표면을 짜는 "기억 0" 코더가 옳은 걸
집을 수밖에 없다([[design-for-amnesiac-future-actor]]). **경계는 타입처럼 미래 구현을 안내하는 복리
자산**이라는 개발자 프레이밍의 실체.

### 2. 가드 지점 ≠ 부수효과 지점 — 병렬 통로를 놓쳤다(codex P1②)
modelParams 캐스케이드를 관문에서 다 막았다고 믿었으나, codex가 **temperature가 별 채널**
(`ctx.temperature`→run_params→build_chat_openai 호출자 params가 모델 cfg를 이김)로 4입구+노드에
새는 실우회를 짚었다. [[installed-guard-isnt-covering-guard]] 그대로. 다행히 4입구가 전부
`ctx.temperature` 하나로 run_params를 만들어 **한 곳(ctx.temperature=None for pipeline)** 봉인으로
끝. "내가 막은 값이 다른 이름/축으로 같은 목적지에 도달하나"를 codex 없이 못 봤다.

### 3. "N개 사이트에 strip 뿌리기"는 그 자체가 안티패턴 — 관문을 찾아라
clone 놓침→codex→고침→adopt·프롬프트채택 놓침→codex→… **라우트마다 strip 호출**은 "모든 사이트를
기억해야" 하는, 정확히 이 스펙이 없애려던 병이다. 진짜 답은 config가 DB에 쓰이는 **단일 불가피 관문
= ORM @validates**(속성 대입). 이걸로 4곳 뿌리기·pydantic validator를 전부 **삭제**(엔트로피↓)하고 한
곳으로 수렴. codex가 사이트를 두 번 더 찾은 게 "뿌리기는 틀렸다"의 증거였다([[policy-at-the-chokepoint]]).

### 4. 관문의 정확한 계약을 **과장하지 마라**(codex 재검 P2)
@validates를 "모든 저장 경로·우회 불가·미래 신설"이라 적었더니 codex가 "Core update/raw SQL은
우회"라 정정. 과장 주석은 미래 코더가 "Core update도 안전"이라 오인하게 만드는 [[design-for-amnesiac
-future-actor]]의 역함정. 정확히 "ORM 속성 대입 관문(런타임이 우회 방어, 절대 DB 불변식 아님)"으로
좁히고 잔여를 명시([[complement-attack-can-be-honest-boundary]]). **경계를 공고히 = 경계를 정직히.**

### 5. 계약 핀 테스트는 "음성+양성+레거시+관문" 넷을 다 박아야
verify_420이 처음엔 음성(agent/session 미적용)만 있어 codex가 "node 층 양성 없음"을 지적. 최종은
①정책 매트릭스 ②ORM 관문(add로 저장 차단) ③해석 관문(음성 both 경로) ④**node 양성**(노드 자기
temperature 생존) ⑤**레거시 dirty 행**(raw SQL 우회 주입→런타임이 ctx.temperature None) ⑥비노드형
무회귀. ORM이 dirty 저장을 막으니 레거시 재현은 raw SQL로 우회해야 했다(관문이 세지면 테스트 셋업이
바뀐다).

## 자산화 후보(관련)
[[design-for-amnesiac-future-actor]] [[structure-first-boundary-is-spec]] [[whole-fix-over-minimal-patch]]
[[installed-guard-isnt-covering-guard]] [[policy-at-the-chokepoint]] [[single-source-sweep]]
[[use-codex-for-adversarial-verification]] [[complement-attack-can-be-honest-boundary]]

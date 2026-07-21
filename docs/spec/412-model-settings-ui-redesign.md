# 412 — 모델 능력·파라미터 설정 UI 재설계

> 상태: **완료** · 2026-07-20 · 모델폼 재설계 브라우저 확인(능력/파라미터 2블록 분리) + tsc 0 + FE 빌드 · verify_411 24/24 무회귀
> 발단: 개발자 "서버가 할 수 있는 것을 표현한 건 좋았는데 UI가 안 깔끔하다. 예전 UI 개편처럼 외부
> 사례 공부하며 유저 인지·개념 경계·컴포넌트 조합을 다시." → 411까지 기능은 됐으나 능력(사실)과
> 파라미터(값)가 한 평면에 뒤섞여 경계가 흐림(스트리밍 지원 vs 스트리밍 기본값이 겹쳐 보임).
> **조사(서브에이전트, 외부 사례+디자인 문헌)** 근거로 재설계. 방법론=[[design-focus-before-layout]]
> (①집중 대상 ②가림 ③배치·표준 문헌 선행), [[beauty-equals-trust]].

## 인지 경계(핵심)
- **능력(capability)=서버가 할 수 있는 사실(불변)** → 정적 시각 언어(Tag/선언 Switch). "정적인 걸
  인터랙티브처럼 보이지 않게"(조사 정설).
- **파라미터(param)=요청마다 조정하는 값(가변)** → Form control(Slider↔InputNumber·Switch).
- 두 개념을 **다른 블록·다른 헤더·다른 스타일**로 분리 — 겹침 소멸.

## 설계 — 두 화면, 각자 다르게

### A. 모델 폼(ProviderModelView CapsEditor) — 선언 + 기본값
- **① 능력 선언 블록**(상단, 구분 헤더 "서버가 할 수 있는 것"): 능력 3종을 `Switch`(관리자 선언)+
  상태 `Tag`(지원=solid/미지원=회색). 명백히 사실 언어.
- **② 파라미터 기본값 블록**(하단, "요청 파라미터 기본값"): number는 `Slider`↔`InputNumber` 동기화
  (대략=슬라이더·정밀=숫자, antd 공식 조합), bool은 `Switch`. 핵심(temperature·max_tokens·stream·
  thinking)만 펼치고 top_p·repetition_penalty는 `Collapse` "고급"(2단까지만 — NN/G).

### B. 오버라이드 화면(CapabilitySettings — 에이전트·노드·세션) — 상속/오버라이드
- **프리셋 `Segmented`**(정밀/균형/창의/직접): 개별 이해 없이 파라미터 일괄 세팅(LM Studio 방식).
  정밀=temp 0.2·top_p 0.9, 균형=기본, 창의=temp 1.2, 직접=수동. 프리셋 선택=modelParams 일괄 반영.
- **상속/오버라이드 표현**(VS Code 정본): 상속값을 `placeholder`(흐림, "모델 기본 0.7"), 값 넣으면
  "오버라이드" `Tag` + "기본으로 되돌리기" `Button link`(키 삭제=상속 복귀). number는 InputNumber
  (Slider는 상속-비움 표현이 어려워 오버라이드 화면은 InputNumber 위주).
- **게이트**: 능력 off인 bool 파라미터(thinking/stream)는 **disabled + 사유 툴팁**("이 서버는 thinking
  미지원"). disabled 툴팁은 wrapper로 hover 확보(조사 함정). 능력 undefined(미조회)면 낙관적 허용.
- **고급 `Collapse`**: 핵심 외 파라미터 접기.

## 구현
- **P1 서술자 프리셋**: PARAMS는 그대로. 프리셋은 FE 상수(param key→value 번들, 정밀/균형/창의) —
  값 축은 서술자에 의존. `descriptors_public`에 group(기본/고급) 힌트 추가(어떤 파라미터를 고급으로
  접을지 백엔드 정본): ParamDescriptor에 `advanced: bool` 필드(temperature·max_tokens·stream·thinking=
  기본, top_p·repetition_penalty=고급).
- **P2 CapsEditor(모델 폼)**: 능력 선언 블록(Switch+Tag) + 파라미터 기본값 블록(Slider↔InputNumber·
  Collapse 고급). 저장은 기존 updateModel(capabilities+params) 유지.
- **P3 CapabilitySettings(오버라이드)**: 프리셋 Segmented + 상속 placeholder + 오버라이드 Tag + 되돌리기
  link + 게이트 disabled+툴팁 + Collapse 고급. bool은 상속/켬/끔 3상 유지(오버라이드 의미).
- **P4 공통 컴포넌트 정리**: 재사용 조각(ParamNumberField=Slider+InputNumber, ParamOverrideRow=
  placeholder+override tag+reset) 추출해 모델폼·오버라이드가 공유(사본 금지, 회고 261).

## OUT
- effort/budget형 thinking(우리 MLX는 binary) — 서술자 kind 확장으로 후속(조사 확인: reasoning 컨트롤
  타입이 모델마다 다름).
- 파라미터 간 배타 안내(temperature↔top_p 동시 조정 주의) — 툴팁 후속.
- 사용자 정의 프리셋 저장(LM Studio Preset 수준) — 후속.

## 완료 기준
- [x] 모델 폼: 능력(Switch+Tag 선언)과 파라미터(Slider+InputNumber)가 다른 블록·헤더로 분리·겹침 0(브라우저 확인).
- [x] number 파라미터 Slider↔InputNumber 동기화(공유 ParamNumberField).
- [x] 오버라이드 화면: 프리셋 Segmented(정밀/균형/창의/직접)·상속 placeholder·오버라이드 Tag·되돌리기 link.
- [x] 능력 off 파라미터 disabled+사유 툴팁(disabled는 span wrapper로 hover 확보 — 조사 함정 회피).
- [x] 고급(top_p·repetition_penalty) Collapse 접힘·기본은 핵심(temperature·max_tokens·stream·thinking)만.
- [x] tsc 0 + FE 빌드 + 모델폼 브라우저 스샷 + verify_411 24/24 무회귀. (오버라이드 화면 시각은 공유
      컴포넌트+빌드로 담보, 사용자 실사용 리뷰로 다듬음.)

## OUT(추가)
- 노드형 thinking 다단계 분리(ThoughtChain) — 별도 스펙 413(개발자 질문, 412 후). 현재 노드 사고는
  단일 Think 패널에 통합 렌더(노드 태그 없음).

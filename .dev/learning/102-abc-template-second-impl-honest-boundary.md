# 102 — 전략은 impl로 갈라 공통 조상(ABC 템플릿)에 불변식을 소유시켜라 / 둘째 구현이 추상을 *측정*한다 / 여집합 공격은 "정직한 경계"가 답이다

교체 가능한 방식(오케스트레이션 전략 등)을 열 때 **어디에 변주점을 두느냐**가 불변식 보존을 가른다.

## 전략 = 각각의 impl + 공통 조상 ABC 템플릿 메서드

- **플로우 안 `if`로 전략을 가르지 마라**(분기 폭증·불변식이 분기마다 재작성됨). 대신 **전략 = 각각의
  구현(impl)** 으로 갈라 기존 선택 메커니즘(`config["impl"]`)을 재사용한다(새 config 필드 = 088 함정).
- **불변식은 공통 조상(ABC)이 소유한다**: 골격·채널 격리·HIL·정책 재검증을 `build_graph`에 확정하고,
  자식이 채우는 **유일한 구멍**을 `@abstractmethod` 하나(`select`)로 좁힌다. 자식은 상속으로 불변식을
  **뺄 수 없다**(구조적 Protocol이 아니라 *구체 ABC 템플릿*이라 골격이 실제 코드로 강제됨). 조상이
  `describe`/`build_graph`를 구현하므로 `CustomAgent` Protocol 자동 적합 → conformance(089) 무회귀.
- **드리프트 0은 주장 말고 측정**: 자식의 `get_graph().nodes`가 조상 노드집합과 동일함을 단언. "골격을
  못 뺀다"가 실측이 된다.
- **변주점(select)은 모듈 순수 함수로**(`rank_candidates`류) — 실 LLM 없이 결정성 단위 단언(099 규약).

## 둘째 구현이 추상 무누수를 *측정*한다(039/085 재적용)

추상 경계가 새지 않는다는 건 **둘째 구현이 나올 때까지 주장일 뿐**이다. 그래서 첫날 두 전략을 함께
낸다: ① 기존 동작을 행위보존 리팩터로 조상에 태우고(impl 키 유지), ② 진짜 다른 전략을 신규로. 둘이
`select` 한 줄만 다르고 나머지 전부 공유되면 그때 추상 경계가 실증된다(하나만 있으면 조상은 그 하나에
과적합됐는지 알 수 없다).

## codex 여집합 공격이 성공하면 "고쳐라"가 아니라 "정직하게 경계로 다뤄라"가 답일 수 있다

적대 리뷰가 "보장 목록의 여집합"을 파고들어 성공했을 때, 그게 항상 코드 결함인 건 아니다 — **미문서
경계**일 수 있다. 예: 다중 순차 위임 중 뒤쪽 cap이 interrupt하면 LangGraph가 노드를 처음부터 재실행
→ 앞선 read-only cap 재호출. 이건 **안전 위반이 아니다**(승인-게이트 부수효과는 여전히 exactly-once —
interrupt-before-sideeffect가 그 cap엔 그대로). 하지만 코드·주석·하네스가 그 경계를 침묵하면 codex
말대로 "정직하게 다루지 않는" 것. 답은 세 가지를 **함께**:
1. **경계를 코드 주석에 명시**(무엇이 재실행되고 무엇이 exactly-once인지).
2. **안전 불변식을 테스트로 실측**(H10: 혼합 위임서 gated cap pre=0/post=1, 순서 무관하게 견고).
3. 스펙 OUT/회고에 후속 난제로 기록.
→ 100의 "codex 설계한계 = 제3판정(기각도 수용도 아닌 명시화)"의 확장: 여집합 공격 성공도 명시화로 접는다.

## Python은 override를 못 막는다 → 정적 강제 + 저작시점 게이트로 겹쳐 막아라

"자식이 골격을 재정의하면 안 된다"는 런타임으로 강제 불가(Python 상속은 재정의 허용). 대신:
- `@final`(typing) — 타입체커·리뷰가 override를 잡음(자기문서화 + 정적 강제).
- 스킬 수용 게이트 — 저작 시점에 "자식이 build_graph/describe 재정의 안 했나" 검사.
- 계약(select 반환)은 조상 delegate가 `chosen ⊆ candidates` 교집합으로 **구조 강제**("고르는 자이지
  만드는 자 아님"). 하류(broker.invoke) 재검증에만 기대지 않고 한 겹 더 — 단일 지점(드리프트 0).

## 부수

- discover(전체 substring) vs rank(토큰 겹침) 필터 마찰: 다중 후보 시나리오는 query=`" "`로 전량 매치
  시켜 넓은 후보군 확보 후 select 직접 검증. 안전 단언은 discover 순서 무관하게 세워 견고화.
- 순환 import: flows 모듈을 최초 import로 직접 부르면 부트스트랩이 초기화 중 걸림 → `agent.runtime`
  먼저 import(모든 verify 규약).

[abc-template-method, strategy-as-impl, common-ancestor-owns-invariant, only-hole-abstractmethod, drift-zero-measured, second-impl-measures-abstraction, behavior-preserving-refactor, complement-attack-is-honest-boundary, gated-side-effect-exactly-once, document-boundary-not-silent, final-static-enforcement, python-cant-block-override, chosen-subset-candidates-guard, chooser-not-maker, codex-design-limit-third-verdict, discover-substring-vs-rank-token, adversarial-codex, probe-deeper]

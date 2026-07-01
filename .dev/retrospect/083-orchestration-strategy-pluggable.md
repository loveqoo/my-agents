# 083 — 전략 교체형 오케스트레이션: 공통 조상(ABC 템플릿) + 첫 출하 2전략

- 스펙: `docs/spec/102-orchestration-strategy-pluggable.md`
- 관련 학습: [102](../learning/102-abc-template-second-impl-honest-boundary.md), 100·101(브로커·HIL), 039·085(2nd-impl 측정), 099(순수함수 규약)

## 무엇을 했나

브로커(100·101) 위 데모 `orchestrate`는 `discover(limit=1)` 첫 매치 단일 위임 = 오케스트레이션이
아니었다. 이를 **에이전트 소유자가 고르는 전략**으로 열되, 플랫폼이 하나로 못박지 않았다:

- **전략 = 각각의 impl**(플로우 안 `if` 아님·새 config 필드 없이 `config["impl"]` 재사용 → 088 함정 회피).
- **공통 조상 = ABC 템플릿 메서드**: `OrchestrationAgentBase`가 골격(analyze→delegate→synthesize)·
  채널 격리[100]·HIL[101]·정책 재검증을 **소유**(드리프트 0). 자식이 채우는 **유일한 구멍은 `select`**.
  `describe`/`build_graph` 구현으로 `CustomAgent` Protocol 자동 적합 → 089 conformance 무회귀.
- **select = 모듈 순수 함수**(`rank_candidates` 겹침 점수·id tie-break) → 실 LLM 없이 결정성 단위 단언(099).
- **첫 출하 2전략**: ① 현 `OrchestrateAgent` → `FirstMatchOrchestrateAgent`(행위보존 리팩터, impl 키
  `orchestrate` 유지), ② `RankedOrchestrateAgent`(impl `orchestrate_ranked`, DISCOVER_LIMIT=10·TOP_K=3).
- **다중 위임 = 순차 fold**(병렬+interrupt 멱등은 별개 난제로 후속). agent-flow 스킬에 전략 분기(D7).

## 잘된 것

- **드리프트 0을 측정으로 증명**: 두 자식의 `get_graph().nodes`가 조상 노드집합 `{analyze,delegate,
  synthesize}`와 동일함을 단언(U4). "자식은 골격을 못 뺀다"는 주장이 아니라 실측이 됐다.
- **2nd-impl로 추상 무누수 *측정***(039/085 재적용): 추상화가 새지 않는다는 건 둘째 구현이 나올 때까지
  주장일 뿐 — 그래서 첫날 두 전략을 함께 냈다. FirstMatch/Ranked가 `select` 한 줄만 다르고 나머지
  전부 공유됨이 추상 경계를 실증했다.
- **RBAC 체크리스트 상속으로 만족**: 새 유저데이터 입구 0(invoke가 정책 소유). 자식은 정책을 못 건드림.
  체크리스트를 새로 돌릴 필요 없이 "왜 상속으로 만족하나"만 스펙에 답하면 됐다.

## codex 적대 리뷰(rung ③) — 5건 정직 분류

- **[P1] 다중 위임 + 중간 interrupt + resume 재실행** → **여집합 공격 성공(실결함 아닌 정직성 갭)**:
  뒤쪽 cap이 interrupt하면 LangGraph가 delegate 노드를 처음부터 재실행 → 앞선 read-only cap 재호출.
  codex 왈 "코드/주석/하네스가 정직하게 경계로 다루지 않는다". 판정=**승인-게이트 부수효과는 여전히
  exactly-once(안전 불변식 유지)**이나 read-only 중복은 미문서. 조치=delegate 주석에 경계 명시 +
  **H10 테스트로 안전 불변식 실측**(혼합 위임서 delete_record pre=0/post=1, discover 순서 무관 견고).
  → 여집합 공격은 "고쳐라"가 아니라 "정직하게 경계로 다뤄라"가 답인 부류(100의 3판정 확장).
- **[P2] override 홀(build_graph/describe 재정의)** → `@final` 정적 강제(Python 런타임은 상속 재정의
  못 막음 → 타입체커·리뷰+스킬 수용 게이트로 저작 시점 봉합).
- **[P2] select 계약 위반(임의 Capability 지어냄)** → 조상 delegate가 `chosen ⊆ candidates` 교집합
  (id 기준 canonical 복원)으로 **구조 강제**("고르는 자이지 만드는 자 아님"). broker.invoke 재검증에만
  기대지 않고 한 겹 더.
- **[설계한계] `## 능력:` 라벨 스푸핑** → codex도 G1(SystemMessage 격리) 견고 확인. 데이터 채널 내부
  attribution 표식일 뿐 신뢰 경계 아님 → fold_results docstring에 명시(100의 명시화 패턴).
- **[FALSE-POSITIVE] ABC 강제 미흡** → 이미 fail-closed(get_agent_impl try/except가 추상 인스턴스화
  TypeError를 잡아 None). 조치 없음.

## 아팠던 것 / 재현 함정

- **discover 부분문자열 필터 vs rank 토큰 필터 마찰**: discover는 전체 쿼리 substring, rank는 토큰
  겹침. 다중 후보 시나리오는 query=`" "`(→ extract_query "" → discover "" 전량 매치)로 넓은 후보군을
  얻은 뒤 select를 직접 검증. H10 안전 단언은 discover 순서에 무관하게 세워 견고화.
- **순환 import 아티팩트**: orchestrate를 *최초* import로 직접 부르면 부트스트랩이 초기화 중 걸림.
  모든 verify는 `agent.runtime`을 먼저 import(부트스트랩 완료 후 flows)해야 함 — 기존 규약, 내 변경 무관.

## 다음 후보

- admin UI에서 impl 선택 노출(085 H5) — 사용자가 UI로 orchestrate/orchestrate_ranked 고르기(현재 OUT).
- 데이터 채널 내부 attribution 강화(구조화 출력) — 라벨 스푸핑 설계한계 후속.
- 노드 간 멱등 재개(선행 위임 결과 캐시) — 다중 interrupt 난제(스펙 101/102 OUT 연장).

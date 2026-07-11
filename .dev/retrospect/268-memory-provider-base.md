# 268 — 메모리 provider 공통 조상 (스펙 293)

## 무엇을 했나

사용자가 provider 6개를 보고 "공통 조상 만들면 반복 줄겠다" 지적. 실측으로 **범위를 좁혀** 확정:
6개 전부가 아니라 **메모리 3형제**만(Agent/Mcp/Rag는 계약만 공유·내부 상이=억지 상속 OUT).
`MemoryAxisProvider(ABC)` 신설 — 골격 6메서드 중 4개(`__init__`·`_cap`·`candidates`·`load`·
`describe`·`node_label`)를 조상이 `@final` 소유, 자식은 유일 구멍 `invoke`·`approval_for`만.
파서 3갈래(`_parse_mem/memwrite/memedit`)를 기존 `_cap_resource`로 단일화. memory.py 436→396줄.

## 잘된 것

- **사용자 직감을 실측으로 "정밀화"해 돌려준 것.** "6개"는 절반만 맞았다 — Agent/Mcp/Rag는 공유
  헬퍼 `_cap`이 0개(grep)라 조상=빈 껍데기가 될 참이었다. 그냥 "네" 하고 6개를 묶었으면 억지
  상속을 만들었을 것. 겹쳐 *보이는* 것과 진짜 중복을 가르는 건 시그니처가 아니라 **본문 공유
  여부**(memory 3형제는 candidates/load 로직이 KIND·파서만 다른 동형, 나머지 셋은 조회 자체가 상이).
- **선례가 설계를 대신 잡아줬다.** OrchestrationAgentBase(ABC+템플릿 메서드+`@final`)가 이미 있어
  "골격 조상 소유·구멍만 자식·재정의 봉인" 패턴을 그대로 이식. 새 패턴을 발명하지 않고 코드베이스의
  기존 어휘를 재사용 = 리뷰·이해 비용 0.
- **codex가 리팩터 특유의 미묘한 버그를 잡았다(aliasing).** 리팩터 전 `_cap`은 매 호출 새 dict
  literal이었는데, 클래스 속성 `INPUT_SCHEMA`로 빼면서 **공유 참조**가 됐다 — describe 반환 schema를
  변조하면 다음 호출이 오염(정상 경로엔 안 나오지만 "바이트 동일" 계약 위반). deepcopy로 매 호출
  사본 = 리팩터 전 동작 정확 재현. "상수를 클래스 속성으로 올릴 때 가변 객체는 공유돼 aliasing"은
  리팩터의 정형 함정 — 봉합 후 격리 단언으로 실증.

## 배운 것

- **중복 제거의 판별자는 "본문이 같은가"지 "시그니처가 같은가"가 아니다.** Protocol이 시그니처를
  강제하면 6개가 다 같아 보이지만, 상속으로 줄일 수 있는 건 *본문 공유*가 있을 때뿐. 시그니처 반복은
  Protocol이 이미 처리하므로 조상으로 더 못 줄인다(Agent/Mcp/Rag). 억지 상속 판별 = 조상에 올릴
  구현이 있나(공유 헬퍼·동형 로직) vs 선언만 있나.
- **불변 의도 클래스 속성 dict는 `ClassVar[dict]`로 표기**(ruff RUF012) — 인스턴스 필드 오해·가변
  기본값 함정을 타입으로 차단. 그리고 그 dict를 *반환*할 땐 사본(위 aliasing).
- **조상이 소유하는 전 메서드에 `@final`을 빠짐없이** — describe/candidates/load엔 붙였는데
  node_label을 빠뜨렸다(codex 지적). 봉인은 "일부"가 아니라 "골격 전체"여야 우회 틈이 없다.

## 다음에 적용

- provider에 새 축(예: memory의 team 축)을 더할 때 `MemoryAxisProvider` 상속 + 클래스 속성 5개 +
  invoke/approval_for만 = 저마찰 확장.
- 상수→클래스 속성 승격 리팩터는 "가변 객체 공유(aliasing)"를 기본 점검 항목으로.

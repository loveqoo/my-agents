# 269 — 브로커 provider 조립 분리 (스펙 294)

## 무엇을 했나

사용자가 스펙 293(메모리 조상)에 이어 **DI/다형성을 서비스 전반**으로 넓혀 물었다("provider만
아니다. 부모 인스턴스로 제어하는 이점"). 실측으로 **유일·정확한 위반**을 찾았다: `PolicyScopedBroker`가
6 provider를 `__init__`에서 직접 생성 = "조립+소비" 겸직. 같은 코드베이스가 agent(`_REGISTRY`)·memory
backend(`_BACKENDS`)는 이미 생성을 감추는데 **provider만 예외**였다(증거: broker가 `self._session_factory`를
저장만 하고 한 번도 안 읽음 = 안 쓰는 DB 팩토리를 쥔 조립 관심사 누출).

`composition.py` 신설 — `BrokerContext`(frozen dataclass = provider 생성 규약) + `build_providers`
(구체 6종을 아는 **유일한 함수**). broker `__init__`은 `providers: list[_CapabilityProvider]`를
**주입받고** 구체를 0개 안다. 두 조립 호출부(build_broker·chat_approval)가 build_providers 경유.
verify 테스트 55곳(61 호출)을 순수 주입으로 재배선. 새 seam 증명 테스트(verify_294) 추가.

## 잘된 것

- **"바꿀 것 없다"를 사용자 한 번 더 밀자 되짚어 진짜 결함을 찾았다.** 1차 답은 "DB DI 이미 대칭,
  손댈 것 없음"이었는데 — 그건 *잎(leaf) 수준*만 봤다. 사용자가 원칙("구조 상세를 감춰라")을 재차 대자
  *조립점이 소비자에 박힌* 더 큰 층을 봤다. probe-deeper: 내 측정이 사용자 지적과 어긋나면 측정을
  의심하라(단정 전 한 겹 더). 안전망 55곳 churn을 감수하는 갈림길은 **사용자에게 물어** 결정(AskUser).
- **자기 코드베이스의 더 나은 부분이 설계를 대신 잡아줬다.** agent `_REGISTRY`·backend `_BACKENDS`가
  이미 "생성 은닉" 선례라, 그 비대칭(provider만 예외)이 곧 결함의 좌표이자 해법의 형태였다. 새 패턴
  발명 0 — 있는 어휘를 provider에 이식.
- **런타임 가변 레지스트리를 의도적으로 안 만든 게 정직한 절제.** agent는 사용자 플러그인이라 register()가
  *요구사항*이지만, provider는 플랫폼 내부 고정 집합 = 그 구동자가 없다. 조립 함수 한 줄이면 개방-폐쇄
  충족. "패턴을 흉내내면 카고컬트"를 스펙 OUT에 명시. 구조는 잡되 기계는 최소.
- **게이트 사다리 3런이 또 비겹침으로 작동.** metrics-fast(mypy 0)·주입 seam 단위(verify_294)·실인프라
  통합(104 anti-leak/105/111/101/112/117 + 스위트 51/51)·codex 적대(6축 SAFE, file:line 근거).
  특히 codex가 "조립 이동이 anti-leak·delegation·tool_policy·rag_min_scores 배선을 조용히 끊었나"를
  코드 경로로 물리 대조 = 행위 보존의 여집합 확인.

## 배운 것

- **DI의 결함은 "잎이 뭘 받나"가 아니라 "누가 조립을 아나"에 있다.** 각 provider가 서로 다른 인자를
  받는 건 좋은 DI(각자 필요한 것만) — 결함은 *소비자(broker)가 그 생성자들을 아는 것*. 조립 표면을
  타입(`BrokerContext`)으로 못박으면 그게 곧 스펙(경계=규약). 상속 축(293 본문 공유)과 DI 축(294
  조립 은닉)은 **별개** — 293이 "메모리 묶었으니 MCP도"가 아니었던 이유.
- **구조 리팩터의 진짜 블래스트 반경은 테스트 seam이다.** 순수 주입은 소스 3파일이지만 안전망 55곳이
  현재 seam(session_factory/user_id 직접 주입)에 의존했다 — 이걸 Execution 직전 실측으로 드러내
  설계 변경이 아닌 실행 결과임을 밝히고 사용자 결정을 받았다. 안전망 재배선은 값 누락(user_id anti-leak)
  위험이라 **전후 카운트 측정**(61=61)+**verify가 곧 검증**(104가 user_id 스코프를 단언하니 누락 시 적색).
- **기계 변환 스크립트는 값 안의 괄호·top-level 콤마에서 깨진다.** `session_factory=_raise_factory()`
  (값에 괄호)·`lambda k, name=None`(top-level 콤마)가 naive split을 깬다 — depth+문자열 인식 스캔으로
  "top-level 첫 ctx-kwarg 인덱스"만 찾아 원문 그대로 임베드(재분할 없음)가 안전. import 주입은 멀티라인
  `import (` 블록 안에 넣으면 SyntaxError — 블록 내 항목으로 추가해야.

## 다음에 적용

- 새 능력 소스는 `build_providers`에 한 줄 + `_CapabilityProvider` 구현 = broker 무변경(개방-폐쇄).
  런타임 플러그인 요구가 생기면 그 때 레지스트리로 승격(driver 생긴 뒤).
- 순수 주입 seam이 생겼으니 broker 정책·디스패치 로직은 가짜 provider로 격리 단위 테스트 가능(verify_294 패턴).
- 낡은 verify(100·103·130·131)는 pristine HEAD 동일 실패로 차등 확정 — 스펙 294 무관, 백로그 이월.

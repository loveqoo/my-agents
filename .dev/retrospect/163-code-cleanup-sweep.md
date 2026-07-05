# 163 — 코드 정리 훑기(죽은 코드·오너십 통합·중복·재발방지)

**스펙**: docs/spec/182 · **관련**: 068/069(소유권)·112(오너십 단위)·오케스트레이션(deep-reasoner 위임)

## 무엇을 했나
"코드 정리를 좀" → deep-reasoner 2개(프론트/백엔드 병렬) + 기계 스캔(tsc noUnusedLocals·pyflakes)으로
전체 훑기. 결과: 소스는 매우 깨끗, 정리감은 죽은 코드 소수 + 중복 1곳. 적용: 프론트 죽은 API 8개+
컴포넌트 1개+import 2개, 백엔드 죽은 함수 3개, 오너십 단일 규칙 통합(chat._next_owner→ownership.
next_owner), ApprovalsView 카드 중복 추출, tsconfig noUnusedLocals. tsc 0·verify_068/112 통과·시각 회귀 0.

## 무엇이 잘못됐고 무엇을 배웠나

### 1. 서브에이전트의 "삭제 안전(참조 0)"은 가설이지 판정이 아니다 — 삭제 직전 재검증 (핵심)
백엔드 에이전트가 "죽음, tests 포함 참조 0"이라던 7개 중 **3개가 실제로 테스트가 쓰고 있었다**
(`may_use`=verify_112·`_reset_cache`=verify_040·`_set_allowed_hosts_for_test`=verify_060/063). 그대로
믿고 지웠으면 테스트 3개가 깨졌다. 삭제 직전 각 대상을 tests 포함 전 저장소로 재-grep해 전부 걸러냈다.

- **처방**: 파괴적 행동(삭제) 직전에 **행동 지점에서** 각 대상을 재검증하라 — 특히 **테스트 디렉터리
  사용**을. 에이전트(그리고 ruff 같은 도구)는 테스트 전반 grep이 불안정하다. "안전"은 넘겨받은 가설로
  취급하고 내 손으로 확인. [[adversarial-review-before-destructive-ship]]·[[probe-deeper-before-concluding]].

### 2. 심볼 삭제는 들어오는 참조를 깬다 — 지우기 전 inbound를 봐라
`chat._next_owner`를 지웠더니 `verify_068_owner.py`가 그걸 import해 **테스트가 import 에러**로 죽었다.
"src에서 호출되나"만 봤으면 놓쳤다 — 지울 심볼 이름 자체를 전 저장소로 grep해 test import를 잡았다.

- **처방**: 삭제/이동은 **나가는 참조가 아니라 들어오는 참조**를 깬다. 심볼을 없애기 전 그 이름을 전
  저장소(tests·docs 포함)로 grep하고, 이동이면 소비처를 새 위치로 재배선. [[move-breaks-references-both-directions]].

### 3. "거의 같은" 중복은 경계에서 갈린다 — 통합 시 진리표를 diff하라
`ownership.next_owner`(죽음)와 `chat._next_owner`(사용)를 통합하는데, 둘은 `owner==""`(빈 문자열)
에서만 달랐다: next_owner는 ""를 미소유로 봐 새 소유자 부여, _next_owner는 ""를 기존 소유자로 봐
보존(이전 거부, fail-closed). 보안상 **fail-closed(_next_owner)가 정본** — 그 의미로 통합하고 경계
케이스를 verify_112·068에 고정. dead였던 next_owner의 "" 미소유 취급은 잠재 구멍이었다.

- **처방**: 중복 로직을 합칠 때 "거의 같다"에 속지 말고 **진리표를 나란히** 두라 — 숨은 경계 divergence
  가 보안이면 그게 통합의 핵심 결정이다(안전한 쪽을 정본·경계 테스트로 봉인). [[gate-on-intent-value-not-mutable-baseline]].

## 복리 포인트
- 잘 관리된 레포에선 "생산성 훑기"의 raw 수확은 작다 — 진짜 가치는 **추상화 드리프트**(ownership이
  "단일 출처"라면서 chat이 사본을 씀) 발견. 죽은 코드 양보다 방치된 계층 신호를 본다.
- tsconfig noUnusedLocals를 켜 재발을 **장치화**(Scaffolding "같은 실수는 훅으로"). 앞으로 미사용
  import는 tsc가 막는다.
- 병렬 deep-reasoner 위임으로 메인 컨텍스트 절약 — 단, 산출은 **검증 대상 가설**로 받아 재확인(위 1·2).

# 104 — per-user 소유 자원은 능력 이름이 아니라 실행 주체에 묶어라 / 새 상태 축은 모든 배선 지점을 센다

능력 브로커에 메모리 provider(첫 per-user 개인 데이터)를 붙이며 두 가지가 굳었다.

## 1. 공유 카탈로그와 per-user 자원은 능력 식별 방식이 반대다

브로커의 앞선 세 kind(agent·mcp·rag)는 **주인 없는 공유 카탈로그**였다. 자원이 누구 것도 아니라
cap_id에 대상을 박아도(`rag:회사문서`) 누구에게 노출되든 같은 데이터 — 그래서 정책은
`에이전트 allowlist ∩ kind-RBAC` 한 겹으로 충분했고, learning 100은 "Agent엔 owner가 없어
per-cap·per-user를 못 막는다"를 **입도 한계**(우회 아님)로 기록했다.

**per-user 자원(메모리)엔 같은 방식이 치명적이다.** cap_id에 대상 user를 박으면(`memory:앨리스`),
그 능력을 allowlist에 넣은 에이전트를 **밥이 실행하면 밥이 앨리스 기억을 읽는다** — 능력 이름이
소유자와 실행자를 분리해버려 교차 유출이 열린다.

**정공법: 능력 이름에 대상을 박지 마라. 소유자를 런타임 실행 주체(principal)에서 도출하라.**
능력은 `memory:user` 하나뿐 — "지금 실행하는 주체 *자신의* 기억". user_id는 `build_broker`가
`str(principal.id)`로 뽑아 provider에 주입하고, 검색 스코프는 **오직** `{"user_id": self._user_id}`
(cap_id·args의 어떤 필드도 이걸 지정·덮어쓸 수 없다). 이러면 **이름으로 남을 가리킬 방법 자체가
없어져** 교차 유출이 *구조적으로* 불가능하다 — 런타임 검사에 기대지 않고 표현 불가능성으로 막는다.

부수 효과: **어드민 에스컬레이션도 자동 차단**. superuser가 실행해도 user_id=자기 id라 자기 기억만.
브로커 능력은 대상 인자를 애초에 안 받으니 "남의 기억을 위임으로" 경로가 존재하지 않는다. 어드민의
타인 큐레이션은 URL에 대상 user_id를 받는 *별도* 경로(memory_routes, 053)로 남는다.

**적용:** per-user/테넌트 자원을 능력·도구·엔드포인트로 노출할 때 첫 질문 — "대상 소유자가 *식별자에*
담기나, *실행 주체에서* 도출되나?" 담기면 A의 토큰으로 B 자원을 가리킬 여지가 생긴다. 도출되면
그 여지가 사라진다. 공유 카탈로그면 전자도 되지만, 소유가 있으면 후자여야 한다.

## 2. 새 상태 축을 배선하면, 그 축을 쓰는 *모든* 팩토리를 세라

user_id라는 새 상태를 브로커에 흘리며 request-time 팩토리(`build_broker`)는 고쳤는데 **resume-time
팩토리(`_build_resume_broker`)를 놓쳤다.** 승인 interrupt가 걸린 멀티턴에서 재개 시 user_id가
주입 안 돼 `memory:user`가 사라졌다(fail-closed지만 자기 기억 접근이 재개서 깨지는 회귀). codex가
request/resume 두 경로의 **대칭성**을 보고 짚었다.

happy-path(단일 턴)엔 안 보인다 — 같은 능력을 만드는 팩토리가 둘인데 하나만 새 인자를 받으면,
그 인자가 필요 없는 흐름에선 티가 안 나고 필요한 흐름(resume+memory)에서만 터진다. 이건 RBAC
체크리스트 §1(입구 열거)의 **배선판**이다: 새 생성자 인자를 더하면 그 객체를 만드는 *모든* 지점을
닫힌 집합으로 세라(build + resume + 테스트 픽스처). learning 069·070의 "모든 입구에 소유권"이
데이터 입구였다면, 이건 *생성 입구*판.

**적용:** 공유 생성자에 인자를 추가할 때 `grep`으로 그 클래스의 *모든* 호출처를 세고, 각각이 새
인자를 옳게 넘기는지 확인. "하나 고쳤다"는 "다 고쳤다"가 아니다(learning 070 "주 경로 하나만 보면
샌다"의 배선판).

## 적용 요약
- per-user 자원 능력: 소유자를 식별자 아닌 실행 주체에서 도출(표현 불가능성 > 런타임 검사).
- 자원 경계(limit·길이)는 공유 지점에(learning 103) — 여기선 `recall_probe`가 084 이래의 limit 방어점.
- 새 상태 축 배선: 그 객체를 만드는 모든 팩토리를 닫힌 집합으로 세라(request+resume+fixture).
- codex 여집합: cap_id·args·principal 세 각도 anti-leak 전부 공격 실패(오탐) + 배선 누락 1건(실결함).

관련: 스펙 104 · retrospect [[085-capability-broker-memory-provider]] · learning 100·101·102·103 ·
[[complement-attack-can-be-honest-boundary]] · [[move-breaks-references-both-directions]](대칭 배선).

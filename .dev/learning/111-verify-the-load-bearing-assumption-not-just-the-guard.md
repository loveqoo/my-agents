# 111 — 가드가 초록이어도 그 가드가 안전한 *이유*(하중 가정)는 따로 검증해야

## 맥락

브로커 memedit(메모리 수정/삭제) 능력 추가. 소유권 검사(`user_owns`) 후 update/delete를 하는 코드.
verify_111의 교차유저 거부·404-fold·anti-leak 테스트가 전부 초록. 하지만 codex 적대 검증이 한 겹 더
파고들어 **가드가 안전한 이유가 미검증**임을 드러냄.

## 배운 것

### 1. 가드의 초록은 가드의 *전제*를 검증하지 않는다

`user_owns(user_id, mem_id)` 확인 후 `delete(mem_id)`(scope 없는 전역 호출)를 한다. 교차유저 거부
테스트는 초록이다 — 남의 mem_id는 user_owns가 false를 주니까. 그런데 codex가 물었다: **확인과 삭제가
원자적이지 않은데, 확인 후 실제 삭제 전에 그 mem_id가 다른 유저 행으로 해석되면?** 이건 테스트가 못
잡는다 — 테스트는 "남의 id는 거부됨"만 보지, "확인한 행과 삭제되는 행이 동일함"을 보장하는 *전제*는 안
본다.

그 전제(하중 가정)는 두 가지였다: (1) mem_id = 전역 유일 UUID, (2) 기억 소유자 불변. 이 둘이 참이라
check-then-act가 안전하다. **하지만 어디에도 안 적혀 있었다.** 자가검증이었으면 "교차유저 거부 초록"에
만족하고 넘어갔을 것이다. 가드가 초록인 것과, 그 가드가 *왜* 안전한지가 명시·검증된 것은 다르다.

교훈: 방어를 짤 때 "이 방어는 무엇을 가정하는가? 그 가정이 깨지면?"을 명시적으로 답하라. 특히
**check-then-act**(확인과 실행이 분리된 모든 패턴)는 "확인한 것 == 실행되는 것"의 전제를 적어라.

### 2. 정직화 = 가정 명시 + 안전 불변식 테스트 + OUT 기록 (셋 다)

codex의 [P1]은 새 안전 위반이 아니었다: 기존 HTTP 라우트도 같은 check-then-act이고, mem0 API엔
scope-bound 원자 mutation이 없어 재구조화도 불가. 즉 "고칠 결함"이 아니라 **정직한 경계**([[complement-attack-can-be-honest-boundary]]). 처리:
- **가정을 코드 주석에 명시**(왜 안전한지 + 깨는 백엔드는 fail-closed로 scope 원자 mutation 제공해야).
- **안전 불변식 테스트**로 못 박기(교차유저 거부 = verify_111이 실증).
- **OUT 기록**(scope-bound 원자화는 mem0 API 한계로 별개).

셋 중 하나만 하면 부족하다 — 주석만이면 회귀 못 잡고, 테스트만이면 *왜 안전한지*가 안 남고, OUT 없으면
"덜 짠 것"과 "의도적 경계"가 구분 안 된다.

### 3. codex exec 출력 라우팅 함정

`codex exec`(비-TUI)의 최종 agent_message가 stdout에 안 실리는 경우가 있다(`--json`도 3이벤트만 잡히는
불안정). **포그라운드 + `2>&1` 병합 + 넉넉한 타임아웃(540s, Bash timeout 570000)**으로 실행해야 verbatim
findings를 안정적으로 얻는다. 백그라운드 nohup + stdout 리다이렉트는 빈 파일이 되기 쉬움.

## 적용

방어(특히 check-then-act·소유권 가드)를 짜면 그 **하중 가정을 명시**하고, 가정이 깨지는 조건과 그때의
동작(fail-closed)을 적어라. 적대 타자에게 "이 가드가 안전한 *이유*를 무너뜨려봐"를 시켜라(가드 자체가
아니라). 여집합 공격이 성공해도 안전위반 아니면 정직화 3종세트. 관련:
[[verification-ladder-three-rungs]], [[complement-attack-can-be-honest-boundary]],
[[installed-guard-isnt-covering-guard]], [[110-links-proven-is-not-chain-proven]].

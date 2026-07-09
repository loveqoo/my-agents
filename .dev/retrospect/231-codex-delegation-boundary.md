# 231 — codex 적대 리뷰: 로컬 위임 경계의 브로커/본경로 불일치 (스펙 256)

## 맥락

로컬 에이전트 위임(256)은 권한 경계·순환·인프로세스 실행이 얽힌 보안 민감 변경이라 검증 사다리
3런 중 마지막(적대 타자)로 codex를 태웠다. `git diff 2114833..HEAD`에 보장 목록 5개를 주고
"여집합을 공격하라"고 요청. 4건 발견(P1 1·P2 3) → 전부 코드 대조로 검증 후 3건 수정·1건 종속 소멸.

## 무엇이 잘못됐나 — 한 문장

**같은 자원(에이전트)을 만지는 두 입구(chat 본경로 vs 브로커 위임 경로)가 사용 게이트를
공유하지 않아, 새 경로(브로커)만 `may_use_agent`가 빠진 채 남의 private 에이전트를 실행·탐지할 수
있었다.** — 체크리스트 §1 "입구 열거(닫힌 집합)"가 정확히 경고한 형태: 주 경로 하나만 보면 샌다.

## 배운 것 (복리 포인트)

1. **새 provider가 기존 자원을 새 경로로 노출하면, 그 자원의 *기존 게이트 전수*를 옮겨와야 한다.**
   256은 A2A(원격) 코드를 "행위 보존"으로 이관하며 로컬 분기를 얹었는데, 원격 A2A 경로도 애초
   `may_use_agent`가 없었다(external은 항상 허용이라 우연히 안전, private code는 잠복). 로컬은
   eval_run_agent로 **실제 실행**까지 가므로 잠복이 실동 결함으로 승격. → 이관/확장 시 "원본이
   무회귀"만 보지 말고 "원본에 *있었어야 할* 게이트"를 대조(원본의 부재를 계승하지 말 것).

2. **재개(resume)는 원 턴의 컨텍스트를 *전부* 재구성해야 한다 — 하나 빠지면 그 축만 조용히 무방비.**
   `_build_resume_broker`는 RBAC(user_id)·메모리(user_id)는 복원했는데 principal 객체와
   delegation_chain은 안 넘겼다. 새 축(체인)이 생기면 재개 경로도 같은 축을 복원했는지 별도 점검.
   특히 `build_broker(None)`이 `str(principal.id)`에서 즉시 크래시 = 승인된 위임이 조용히 미실행
   (approved-but-not-executed = 거부 방향 오류, 116/171에서 반복 학습한 그 패턴).

3. **순환 방지(방문 집합)는 깊이만 막는다 — 너비는 별개 축.** "재귀 막았나?"에 방문 집합으로 답했지만
   codex가 짚은 건 팬아웃 곱(분기^깊이). 순환=0이어도 비용 폭주=가능. 안전(무한루프)과 비용(폭주)은
   다른 상한이 필요(공유 카운터 예산). 사용자의 "재귀 막았나?"를 좁게 받으면 너비를 놓친다.

4. **검증자 검증 = codex 발견도 코드로 재확인.** 4건 전부 file:line을 열어 대조 — P2#1은
   `build_broker` line 1250 `str(principal.id)`가 principal=None에서 무조건 크래시함을 확인해
   "도달 가능·실동 크래시"로 승격, P2#3(resultPreview)은 codex 자신이 "P1을 먼저 닫으라"고 해서
   P1 종속으로 판정(별도 수정 불요). 발견을 그대로 티켓화하지 않고 종속 관계까지 정리.

5. **회색 판정 기록**(complement-attack-can-be-honest-boundary 적용): P2 breadth는 안전 위반이
   아니라 비용 상한 부재였다 — 팀 한정 신뢰 도메인이라 "정직한 경계"로 문서화 후 얇은 예산으로
   봉합(과투자 금지). P1은 명백 안전 위반(본경로 불일치)이라 즉시 수정. 둘을 같은 톤으로 다루지 않음.

## 처방(재발 방지)

- **입구 정합 규칙**: 자원 X를 만지는 provider/경로를 추가하면, X의 소유권 게이트를 그 provider의
  candidates/load(읽기)·invoke(쓰기/실행)에 동일 술어로 심는다. 게이트는 `may_use_agent` 한 헬퍼로
  단일화(드리프트 0, 체크리스트 §3).
- **재개 컨텍스트 체크리스트**: 새 실행 축(chain·budget·principal 객체)을 추가하면 chat 신규 경로와
  resume 경로 **양쪽**에 배선했는지 grep으로 대조(대칭 강제).

관련: [[verification-ladder-three-rungs]] [[gate-on-intent-value-not-mutable-baseline]]
[[sync-wholesale-replace-drops-admin-fields]] [[complement-attack-can-be-honest-boundary]]
[[installed-guard-isnt-covering-guard]] — "설치≠전체 덮음"의 위임판(본경로 설치·브로커 미덮음).

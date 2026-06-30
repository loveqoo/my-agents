# 073 — 커스텀 에이전트 공통 인터페이스 준수 3상태 분류

스펙: `docs/spec/089-custom-agent-interface-conformance.md`
관련 learning: 092(이번), [[index-layer-for-context-recall]], [[installed-guard-isnt-covering-guard]]=082,
[[adversarial-review-before-destructive-ship]], [[probe-deeper-before-concluding]],
[[verification-ladder-three-rungs]], learning 088(새 인터페이스 필드는 모든 입구서 다뤄야)
선행: spec 085(in-process 런타임 인터페이스 — `CustomAgent` Protocol·신뢰 레지스트리)

## 무엇을 했나

085가 `@runtime_checkable CustomAgent` Protocol을 *선언*했지만 resolve 시점에 isinstance를 한 번도
*쓰지 않았다*(갭). 089는 그 갭을 닫고, 에이전트를 **conforming / non_conforming / config_error**
3상태로 분류해 API(`AgentOut.conformance`)·UI(목록·디테일 배지)에 표면화했다.

- `get_agent_impl`에 isinstance 게이트(부적합·`cls()` 던짐→None, fail-closed).
- `classify_runtime(source, impl)` 단일 헬퍼 — 디스패치(`resolve_agent_runtime`)와 직렬화(`agent_to_out`)가
  *같은 게이트*를 공유(파생값·저장 안 함, 드리프트 0).
- 채팅 config_error 거부 경로(default 폴백 만회 *없음*) + 3상태 배지(설정실패 빨강 강조).

## 무엇이 어긋났고 무엇을 배웠나

### 1. 첫 초안은 "graceful 폴백 + 비준수 분류" — 사용자가 교정3로 뒤집었다

내 2상태 초안은 미해결 impl을 DefaultUiAgent로 *조용히* 폴백시키고 "non_conforming"으로 칠했다.
사용자: "등록 실수를 default 에이전트로 리턴해서 만회 또는 폴백하는 것은 문제가 있습니다. 그래서 이는
에이전트 설정 실패로 보고자 하는 것입니다." → **선언했으나 미해결**을 *정당한 다른 종류*(원격 A2A)와
섞으면 안 된다. config_error를 직교 상태로 카브아웃하고 **런타임이 서빙을 거부**하게 했다. 폴백은
편의처럼 보이지만 *설정 실패를 가린다*(learning 092 핵심).

### 2. 미선언 vs 선언-but-broken을 호출측이 *키 선언 여부*로 가른다

`get_agent_impl`의 None은 "미선언"과 "선언했으나 부적합"을 구분 못 한다(둘 다 None). 이 구분(폴백 vs
설정 실패)을 게이트 함수가 아니라 *호출측*이 `impl` 키 선언 여부로 판정하게 분리했다 — 게이트는
"적합 인스턴스 or None"만, 정책(폴백할지 거부할지)은 resolve/classify가. 관심사 분리가 단일 헬퍼
공유를 가능케 했다.

### 3. codex F1 — "정직한 통보"가 정보노출 채널이었다 (자가검증이 못 본 것)

config_error SSE를 "정직하게" 만들려고 미해결 impl 키를 메시지에 실었다(`'does_not_exist'을 찾을 수
없습니다`). 주석엔 "레지스트리 키일 뿐 비밀 아님"이라 적었다 — 그런데 **config_error의 impl은 정의상
레지스트리 키가 *아니다***(관리자가 임의 저장한 값, 합의 B). codex: 채팅 클라이언트는 관리자보다 권한이
낮을 수 있고(GET /agents의 impl은 인증 관리자 전용), 임의 저장값이 토큰류면 새어나간다. → 클라이언트
메시지 일반화·구체 키는 서버 로그에만. **내 자가 주석이 틀린 전제("키일 뿐")를 단언**했고, 적대 타자가
그 전제의 반례(임의 저장값)를 짚었다. learning 092로 일반화.

### 4. codex F2/F3/F4 — 정직화 1·수용 2

- F2(준수 라벨 과대주장): tooltip을 "구조적 적합(Protocol 게이트)·행위는 런타임 몫"으로 정직화
  (learning 091의 over-claim 금지 — 플래그는 구조적까지만).
- F3(`cls()` 직렬화마다 인스턴스화): **수용** — 신뢰 레지스트리만 등록(085 경계)이라 생성자 cheap·pure
  전제. 비순수·고비용 생성자 등장 시 분류 캐시 층(후속).
- F4(unknown source→로컬 conforming): **수용** — source는 내부 닫힌 enum. 열리면 fail-closed.

## 검증

3런(비겹침): ① `verify_089` 단위(C/G/R/S) ② 같은 파일 H1–H4 실인프라 통합(미해결 impl 저장→config_error
→채팅 시 설정-실패 SSE·default 응답 *없음*·시드 code/external 전부 non_conforming) ③ 적대 codex 4건.
verify_085·041 무회귀, admin tsc 0, 브라우저 샷으로 3상태 배지·거부 Alert 시각 확인.

## 다음에 적용할 것

- **폴백은 설정 실패를 가린다** — 미선언(default OK)과 선언-but-broken(거부)을 가르고, 후자는 크게 거부.
- **에러 메시지가 입력값을 반영하면 그 값을 에러 청중에게 노출하는 것** — 청중 권한 ≤ 값 권한일 때만 안전.
- 자가 주석의 "X일 뿐(=안전)" 단언은 *반례 한 겹*을 적대 타자에 시켜라(probe deeper).

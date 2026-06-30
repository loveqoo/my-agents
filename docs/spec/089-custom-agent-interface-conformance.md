# 089 — 커스텀 에이전트 공통 인터페이스 준수 분류 (3상태)

> 보고(#1): "커스텀 에이전트도 두 가지 타입으로 나뉜다 — 우리의 공통 인터페이스를 *지키는가/아닌가*."
> 교정 1: "레지스트리에서는 공통 인터페이스를 준수하지 않아도 등록이 가능하다." 교정 2: "A2A로 등록한 것은 준수하지 않는다고 봐야 한다."
> 교정 3(핵심): "등록/설정 실수를 default 에이전트로 만회·폴백하는 것은 문제다 — 이는 **에이전트 설정 실패**로 본다." → 그래서 분류는 2분기가 아니라 **3상태**(준수 / 비준수(A2A) / 설정 실패)다.
> 관련: spec 085(`CustomAgent` Protocol·신뢰 레지스트리·graceful 폴백 — 본 스펙이 그 *폴백을 일부 교정*), learning 088(새 인터페이스 필드는 모든 입구 배선까지 죽은 것)·060(단일 술어로 드리프트 0)·091(정직한 표시·over-claim 금지).
> 축 합의: **B = in-process 런타임 Protocol 축**(A2A 카드 계약 축 아님). #4(웹 작성 그래프)의 개념적 선행. 저장 정책 합의: **저장은 허용·"설정 실패"로 표시 + 런타임 거부**(저장시점 거부 아님).

## 배경 — 측정한 현황

스펙 085가 공통 인터페이스 `CustomAgent`(`@runtime_checkable Protocol`, `runtime.py:47`)를 들였지만, "이 에이전트가 그 인터페이스를 *준수하는가*"는 **1급 개념이 아니다** — 이름의 enum·플래그가 없고, 매 실행시 `resolve_agent_runtime`(`chat.py:45`)이 합성하는 **암묵 판정**으로만 존재한다. 측정으로 드러난 사실:

- **등록 ≠ 준수 (교정 1, 코드 확인)**: `register_agent(key, cls)`는 **무검증 저장**(`runtime.py:88`). `get_agent_impl`은 `cls()`를 돌려줄 뿐 **`isinstance(_, CustomAgent)`를 검사하지 않는다**(`runtime.py:93-101`). `@runtime_checkable`이 *선언만* 돼 있고 resolve 시점에 안 쓰인다 → Protocol 미구현 클래스도 통과해, 플랫폼이 `describe()`/`build_graph()`를 부를 때 비로소 깨진다.
- **폴백이 설정 실수를 가린다 (교정 3, 코드 확인 — 본 스펙의 발화점)**: `resolve_agent_runtime`는 `return get_agent_impl(ctx.get("impl")) or DefaultUiAgent()`. 즉 작성자가 `impl="my_custom"`을 *선언했는데* 그게 미등록/미구현이면 **조용히 `DefaultUiAgent`로 만회**한다 → 잘못된 설정이 "기본 에이전트로 잘 도는 것"처럼 보여 **설정 실패가 은폐**된다.
- **A2A 등록 = 비준수 (교정 2, 코드 확인)**: code·external은 원격(`_is_remote`=True, `chat.py:36`)이라 in-process 런타임이 없어 `resolve→None`. A2A 프로토콜은 지키지만 우리 공통 in-process 인터페이스는 미대상(085 명시). **이건 *실패*가 아니라 *정당한 다른 종류*다** — 설정 실패와 구분해야 한다.
- **분류가 사용자에게 안 보임**: admin SPA 전체에 `impl`·준수 여부 렌더 0건(`agents.py:148` 주석 "SPA 미배선"). 리스트·디테일은 `source` 3종만 표시(`AgentsView.tsx:863/872`).

## 결정 (사용자 합의)

- **분류를 1급화 — 3상태로.** 암묵 판정을 명시적 **준수(conforming) / 비준수(non_conforming) / 설정 실패(config_error)** 분류로 끌어올려 API·UI에 표면화한다. 산출물은 *구분 그 자체*이지 impl 선택 피커가 아니다(피커는 비목표).
- **폴백 마스킹 금지 — 설정 실패는 설정 실패로 (교정 3).** impl을 *선언했는데* 미등록/미구현이면 `DefaultUiAgent`로 폴백해 만회하지 않는다. 런타임은 **서빙을 거부**(명확한 에러)하고 분류는 **설정 실패**로 표면화한다. **단 impl 미선언(None)은 설정 실패가 아니라 정상 default** — 평범한 ui 에이전트는 `DefaultUiAgent`가 정당한 런타임이다(이 폴백만 085에서 유지).
- **저장은 허용·표시로 잡는다 (합의 B).** create/update는 미해결 impl이어도 **저장을 막지 않는다**. 대신 분류가 "설정 실패"로 뜨고(목록·디테일), 실제 채팅 시 런타임이 거부한다. (저장시점 거부는 비목표 — 작성 중간 상태·후배포 impl을 막지 않기 위해.)
- **판정은 source 라벨이 아니라 실제 게이트로.** 오늘은 우연히 `ui↔준수`로 일치하지만, 등록이 준수를 강제하지 않고(교정 1) #4의 ui-source 작성 그래프가 비준수일 수 있으므로 `isinstance(_, CustomAgent)`+resolve 게이트로 판정해야 #4까지 정직하게 흐른다.
- **파생, 비저장.** 분류는 (source, impl, 레지스트리)에서 언제든 파생되는 값이라 **컬럼에 저장하지 않는다**(레지스트리 변경 시 stale 드리프트 방지). 마이그레이션 0.

## 3상태 정의 (게이트)

`impl = config["impl"]` 기준. 단일 헬퍼 `classify_runtime(source, impl)`:

| 상태 | 조건 | 런타임 동작 | 의미 |
|---|---|---|---|
| **준수** `conforming` | impl 미선언(None/"") **또는** impl 적중 + `isinstance(cls(), CustomAgent)` | 정상 서빙(default 또는 커스텀 그래프) | 공통 인터페이스 준수 |
| **비준수** `non_conforming` | source ∈ {code, external} (A2A 원격) | A2A 경로 서빙(resolve→None→`_a2a_stream`) | 정당한 *다른 종류* — 실패 아님 |
| **설정 실패** `config_error` | impl **선언**했으나 미등록 **또는** isinstance 실패 | **서빙 거부**(폴백 없음, 명확한 에러) | 고쳐야 할 깨진 설정 |

**정직성 한 줄(스펙 명시 필수)**: 이 분류는 **구조적 준수**(Protocol 메서드 보유 = `isinstance`)까지만 단언한다. **계약적 준수**(`build_graph` 결과 그래프가 `astream`·interrupt/resume 계약을 실제로 지키는가)는 *행위*라 정적 검사 불가 — verify_041이 *실행으로* 증명하는 몫이고, 플래그는 그걸 보장하지 않는다(no over-claim, learning 091).

## 설계 (scope=분류 + 표면화 + 폴백 교정)

### 1. 단일 분류 헬퍼 + isinstance 갭 봉합 + 폴백 교정 (learning 060 드리프트 0)

- **`get_agent_impl`에 isinstance 게이트 추가**(`runtime.py:93`): `cls()` 인스턴스가 `isinstance(_, CustomAgent)`를 통과할 때만 반환, 아니면 None. `cls()` 생성이 던져도 None(try/except, fail-closed). → 등록만 되고 Protocol 미구현인 클래스(085 갭)가 이제 *조용히 통과 못 한다*.
- **`resolve_agent_runtime` 폴백 교정**(`chat.py:45`, 교정 3): 로컬 분기를 셋으로 가른다 —
  - impl 미선언 → `DefaultUiAgent()` (정상 default, 085 폴백 유지).
  - impl 선언 + `get_agent_impl(impl)` 적중 → 그 인스턴스.
  - impl 선언 + None(미등록/미구현) → **`AgentConfigError` raise**(no `or DefaultUiAgent()`). 채팅 핸들러가 잡아 SSE 에러 프레임으로 정직히 통보(비밀 누출 0 — 메시지는 impl 키만, 시크릿 없음).
- **`classify_runtime(source, impl) -> Literal["conforming","non_conforming","config_error"]` 신설**(위치: `agent/runtime.py` — Protocol·레지스트리 최저층). 위 표 구현. resolve와 *같은 레지스트리 lookup·같은 `_is_remote` 술어*를 공유(드리프트 0; `_is_remote`는 현재 `chat.py:36` → runtime으로 내리거나 classify가 호출, 실행 시 결정).
- **두 소비자가 한 헬퍼를 쓴다**: 런타임 디스패치(`resolve_agent_runtime`)와 직렬화(`agent_to_out`). 술어가 갈리면 086류 "겉도는 죽은 상태" 재발 → 단일 출처(learning 060·088).
- **현재 데이터 무영향**: 시드 ui 에이전트는 impl 미선언(→default) 또는 `plan_execute`(적합)뿐이라 config_error 0. 폴백 교정은 *잘못 선언된* 경우에만 작동.

### 2. API 노출 (read)

- **`AgentOut`에 `conformance: "conforming" | "non_conforming" | "config_error"` 추가**(`schemas.py:331`). `agent_to_out`(`serializers.py`)이 `classify_runtime(agent.source, (agent.config or {}).get("impl"))`로 파생. 입구는 list(`agents.py:94`)·get(`:99`)·create(`:110`)·update(`:136`) 전부 `agent_to_out`을 거치므로 한 곳 배선으로 닫힘(learning 088 "모든 입구"). *(필드명·3값 enum 모양은 리뷰서 조정 가능 — 핵심은 3상태 구분.)*
- 채팅 거부 경로: config_error 에이전트로 채팅 시 `AgentConfigError`→명확한 에러 응답("에이전트 설정 실패: 선언한 구현 '{impl}'을(를) 찾을 수 없음"). default로 가린 가짜 정상 응답 0.

### 3. UI 표면화

- **리스트·디테일에 3상태 배지**: `AgentsView.tsx` 리스트 컬럼(`:1346` 부근, `source` 옆)과 detail 헤더에 `conformance` → 준수(success)·비준수(neutral)·**설정 실패(error/red)** 태그(antd `Tag`, 색은 theme.css 토큰). 설정 실패는 *눈에 띄게* 표시해 작성자가 고치게 한다.
- 라벨 메타는 `mockData.ts`의 `AGENT_SOURCE`와 같은 패턴으로 상수화(자유문자열 하드코딩 맵 회피 — learning 017).

### 4. #4 선행 배선

- 분류 게이트(`classify_runtime` + `isinstance` + 폴백 교정)가 **단일 진입점**이 되므로, #4가 웹 작성 그래프를 들일 때 그 그래프도 같은 게이트를 통과해 준수/설정 실패로 분류된다(미해결이면 폴백으로 가려지지 않고 설정 실패로 노출). #4는 별도 스펙.

## RBAC/소유권 체크리스트 — 적용 여부

**트리거 객관 판정**: 이 스펙은 *파생 분류 + 표시 + 런타임 폴백 교정*이다 — `user_id`/테넌트 컬럼을 새로 읽거나 `_own_scope`/`_visible_or_404`/`_assert_*owns` 헬퍼를 건드리지 않는다. 분류는 전역(source+impl+신뢰 레지스트리)에서 파생되는 표시값, 새 소유경계 0. → **RBAC 체크리스트 미적용**(085와 동형, 사유: 새 소유경계 0). 단 §보안경계 무회귀(검증 ③)와 에러 메시지 비밀누출 0은 별도 단언.

## 검증 사다리 (3런 — 비겹침)

- **① 단위(verify_089, 순수)**: `classify_runtime` 매트릭스 — impl-없음→conforming, 적합 impl(plan_execute)→conforming, code/external→non_conforming, **미등록 키→config_error**, **등록됐으나 Protocol 미구현 스텁→config_error**(교정 1 갭 핀), **`cls()` 던짐→config_error**(fail-closed); `get_agent_impl` isinstance 게이트(비적합→None); **`resolve_agent_runtime`: impl-없음→DefaultUiAgent, 미해결 impl→raise(`DefaultUiAgent` 폴백 *안 함*을 단언 — 교정 3 핵심 핀)**; 디스패치·직렬화가 *같은 헬퍼* 호출.
- **② 실인프라 통합(in-process ASGI + 실 DB seed)**: 시드 ui·code·external의 `GET /agents`·`/{id}` `conformance`가 표대로(ui→conforming, code/external→non_conforming); ui 생성→conforming; **미해결 impl 픽스처 에이전트→`conformance=config_error`이고 그 에이전트로 채팅 시 설정-실패 에러(default 응답 *아님*)** — 폴백 마스킹이 사라졌음을 단언. verify_041·085 무회귀.
- **③ 적대 codex(read-only)**: 폴백 마스킹 잔존(미해결 impl이 어딘가서 여전히 `DefaultUiAgent`로 새는가), 분류 정직성(구조적 vs 계약적 over-claim), 갭(isinstance 누락 입구·`cls()` 예외 비포착), 드리프트(디스패치/직렬화 술어 단일성), source-라벨 하드코딩 회귀(#4에서 깨지나), 085 §보안경계/SSRF 무회귀, **config_error 에러 메시지 비밀누출 0**.

## 완료 체크
- [x] `get_agent_impl` isinstance 게이트(비적합·예외→None, fail-closed) — `runtime.py`
- [x] `resolve_agent_runtime` 폴백 교정(impl-선언-미해결→raise, impl-없음만 default) — `chat.py`
- [x] `classify_runtime(source, impl)` 단일 헬퍼(레지스트리·`_is_remote` 단일 출처) — `runtime.py`
- [x] `AgentOut.conformance` 3상태 + `agent_to_out` 파생(모든 입구 한 곳) — `schemas.py`·`serializers.py`
- [x] 채팅 config_error 거부 경로(명확 에러·비밀 0) — `chat.py`
- [x] 리스트·디테일 3상태 배지(상수 라벨, 설정실패 강조) — `AgentsView.tsx`·`mockData.ts`
- [x] 단위 + 실인프라 통합 + 적대 codex 그린, verify_041·085 무회귀, tsc 0

## 검증 결과
- **① 단위·② 실인프라 통합**: `verify_089_conformance.py` ALL GREEN(C 매트릭스 9·G isinstance 게이트 5·R 폴백교정 8·S 디스패치↔분류 일관 9 + H1–H4 통합 — 미해결 impl 저장 허용→`config_error`→채팅 시 설정-실패 SSE이고 default 응답 *없음*, 시드 code/external 전부 `non_conforming`). `verify_085`·`verify_041` 무회귀, admin tsc 0, 브라우저 샷(`shot-conformance-089.mjs`)으로 목록 3상태 배지·디테일 거부 Alert 시각 확인.
- **③ 적대 codex(read-only)** 4건:
  - **F1(Medium, 수정)**: config_error SSE/A2A-노출 에러가 `config["impl"]` 원문을 반영 — impl은 관리자 임의 저장값(합의 B)이라 레지스트리 키임이 증명 안 되고 채팅 클라이언트는 관리자보다 권한이 낮을 수 있음. → 클라이언트 메시지 일반화(impl 미반영), 구체 키는 서버 로그에만(`chat.py`). H3가 *미노출*을 단언하도록 뒤집음.
  - **F2(Medium, 수정)**: "준수" 라벨이 구조적 isinstance 게이트보다 강하게 읽힘(행위 보장 함의). → tooltip을 "구조적 적합(Protocol 게이트) · 행위는 런타임 몫"으로 정직화(`mockData.ts`).
  - **F3(Medium, 수용)**: 분류가 `cls()`를 실인스턴스화 → 직렬화(목록)마다 생성자 실행, 부작용/일시실패가 `config_error`로 뒤집힐 수 있음. **수용** — 신뢰 레지스트리 코드만 등록(085 경계), 생성자는 cheap·pure 전제. 비순수·고비용 생성자가 등장하면 분류 캐시 층 도입(후속).
  - **F4(Low, 수용)**: unknown/future source가 비원격→로컬 conforming로 떨어짐. **수용** — `source`는 내부 닫힌 enum(ui/code/external, 생성·connect 시점에만 설정). 열리면 fail-closed로 전환.

## 비목표
- **저장 시점 거부** — create/update는 미해결 impl이어도 저장 허용(합의 B). 작성 중간·후배포 impl을 막지 않음. 잡는 건 표시 + 런타임 거부.
- **impl 선택 피커/드롭다운** — 어떤 impl을 *고르는가*는 별개(이 스펙은 *구분*만). #4 또는 후속.
- **계약적(행위) 준수 정적 검증** — astream/interrupt 계약은 verify_041/런타임 몫. 플래그는 구조적까지만.
- **분류 영속 컬럼·마이그레이션** — 파생값이라 저장 안 함(드리프트 회피).
- **비신뢰/업로드 코드 샌드박싱** — 신뢰 레지스트리 로딩만(085 비목표 승계).
- **원격 code/external을 in-process로 재편입** — 비준수로 분류될 뿐, A2A 경로 무변경.

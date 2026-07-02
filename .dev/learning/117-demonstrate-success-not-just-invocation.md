# 117 — "고리가 돌았다"와 "협업이 성공했다"는 다르다 / opt-in 정책값도 write-schema를 관통해야

스펙 117(A2A 협업 실증 + 위임 승인 게이트)에서 배운 것.

## 1. 노드가 실행됨(invocation) ≠ 협업이 성공함(collaboration succeeded)

verify_100 H4는 external 위임을 채팅으로 돌려 `delegate` 노드가 생김을 확인했지만, 원격 endpoint가
**도달 불가(에러 프레임)**여서 "위임이 일어남"만 봤지 "다른 에이전트의 답이 실제로 돌아와 종합에
도달함"은 보지 못했다 — 그런데 노드 타임라인은 **성공/실패 무관하게** 남으므로(broker.invoke가 에러
결과도 프레임으로 기록) 노드 존재만 단언하면 **실패한 협업도 초록**이다. 진짜 실증은 원격 호출을
**결정적으로 성공시켜**(a2a_stream 패치로 실제 프레임 반환) ①대상 kind 노드 존재 ②원격이 **정확히
1회** 호출됨 ③**사용자 질의가 원격에 도달**(이음매) ④종합이 발화 — 넷을 함께 봐야 한다. "링크별
초록≠체인 증명"(learning 110)의 한 겹 더: **체인이 돌았음 ≠ 체인이 성공했음**. 성공 경로를 결정적으로
재현하지 않으면 happy-path 초록이 실은 error-path 초록일 수 있다.

## 2. 정책을 결정하는 config 값은 반드시 write-schema(스키마)를 관통해 보존돼야 한다

A2A 위임 승인 게이트를 대상 Agent의 `config.requires_approval` opt-in으로 뒀는데, 그 필드를
`AgentConfig` 스키마에 **추가하지 않으면** create/update의 `config.model_dump()`가 **조용히 드롭**한다 →
게이트가 영구 비활성(브로커는 항상 None). 테스트가 DB에 직접 시드하면 이 드롭을 **못 잡는다**(초록) —
learning 101 "seed-bypasses-write-schema"의 재발. **정책 소스가 되는 config 값은 반드시 API
라운드트립(create→저장→read)으로 보존을 실측**하고, 스키마에 필드를 명시한다. 브로커가 read하는 모든
config 키는 write-schema에 대응 필드가 있어야 한다(읽는 곳과 쓰는 곳의 스키마 정합).

## 3. opt-in 기본값은 무회귀의 열쇠 — 부재/거짓 = 기존 동작

승인 게이트를 "항상"으로 두면 조율형의 상시 위임이 매번 막혀 흐름이 깨진다. **대상별 opt-in
불리언(기본 False)**으로 두면 명시적으로 켠 것만 게이트되고 나머지는 현동작 보존(무회귀). MCP의
`_APPROVAL_ACTIONS`(툴 단위 opt-in)의 에이전트 단위 형제 — "부수효과 게이트는 대상이 스스로 켠다".

## 4. 시그니처를 넓힐 땐 이미 있는 값을 넘겨라(재조회 말고)

approval_for가 대상 행의 config를 읽어야 하는데 sync 함수라 DB를 다시 못 딴다 → 해법은 캐시/재조회가
아니라 **invoke가 이미 받는 row를 approval_for에도 넘기는 시그니처 통일**(`(row, cap_id, args)`). 호출부가
바로 앞에서 resolve한 값을 재활용. 부수: 정규화 헬퍼(`_a2a_text`)를 approval_for·invoke가 **공유**해
"승인한 것==전송되는 것"을 (현재 args 한정) 보장.

## 5. "승인==전송" 등식은 재실행 간 args 안정을 전제 — 경계를 좁혀 문서화

정규화 헬퍼 공유는 *현재 args*의 드리프트만 닫는다. 재개 재실행마다 args를 새로 만드는 호출자에겐
승인 payload(X)와 전송(Y)이 갈릴 수 있다(codex). 기본 orchestrate 경로는 `state["query"]`(스펙 116 pending
커밋)라 안정 → **보장은 그 경로로 좁혀 문서화**하고, 일반 보장이 필요하면 승인 payload에 args
스냅샷/해시를 바인딩(후속). 넓게 주장하지 말고 실제 성립 범위로 좁혀라(learning 116 ④ 계열).

## 적용
- 체인 실증은 "노드 존재"가 아니라 **성공 경로를 결정적으로 재현**(원격 성공·호출횟수·이음매·산출).
- 브로커/런타임이 read하는 config 키는 write-schema에 필드 추가 + **API 라운드트립 보존 실측**(seed 우회 금지).
- 부수효과 게이트는 대상별 opt-in(기본 off=무회귀).
- sync 콜백이 이미-resolve된 값을 필요로 하면 재조회 말고 시그니처로 넘긴다.
- "승인==실행" 등식은 성립 범위(결정적 args 경로)로 좁혀 문서화.

관련: [[node-boundary-is-the-commit-and-idempotency-unit]] · [[unforgeable-boundary-needs-both-sides-clean]] ·
[[verification-ladder-three-rungs]]

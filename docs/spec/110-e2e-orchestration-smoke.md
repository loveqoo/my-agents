# 110 — 엔드투엔드 오케스트레이션 시연 (스펙 106 잔여)

## 배경 / 왜

능력 브로커(100–105)와 UI(106–109)를 다 만들었지만 **한 번에 이어 돌린 적이 없다.** 각 고리는
증명됐다: UI→config.capabilities 지속(106 왕복), config→build_broker 소비(chat.py 644),
build_broker→orchestrate delegate→broker.invoke(102). 하지만 *실제 채팅 1턴이 이 체인을 통과해
브로커가 정말 일을 넘기는지*는 미실측(백로그 "106 잔여"). 사용자 선택: "조율형이 실제로 일
넘기는지 확인".

## 핵심 사실 (코드 근거)

- orchestrate 플로우(`flows/orchestrate.py`): `analyze`(결정적)→`delegate`(**broker.discover→invoke**,
  LLM 무관)→`synthesize`(LLM은 최종 종합만). 즉 **위임은 LLM과 독립** — mock-llm으로도 위임이 일어난다.
- 관측(`chat.py` 763): `build_broker_scoped.invocations`가 trace에 `broker_invoke:<kind>:<...>` 노드로
  합류. 위임이 있으면 이 노드가 뜨고, 없으면 빈다(무영향).

→ mock-llm으로 채팅 1턴을 돌려 trace에 `broker_invoke:*`가 뜨면 전 구간이 증명된다(결정적·반복 가능).

## 목표

- **결정적 E2E 테스트**(`tests/verify_110_e2e_orchestrate.py`): UI 저장 경로와 동일한 config로
  조율형 에이전트를 만들고(impl=`orchestrate`, capabilities=[관측 가능한 cap 1개]), 채팅 엔드포인트로
  1턴을 돌려 **trace에 `broker_invoke:*` 노드가 존재**함을 assert. 라이브 모델 불필요(mock-llm).
- **관측 가능한 cap 선택**: 결정적이고 시드가 쉬운 것 — 우선순위 `memory:user`(테스트 유저 기억 1건
  시드) 또는 `rag:<collection>`(docs_kb 청크 존재). discover가 그 cap을 고르도록 질의에 cap 키워드 포함.
- **무위임 대조**: 능력 0개 조율형은 `broker_invoke` 노드가 **안 뜸**(deny-by-default) — 위양성 배제.

## 검증

- 위 E2E 테스트 통과(broker_invoke 노드 존재 + 응답 완료). 무위임 대조(노드 부재).
- 가능하면 **브라우저 시연**: 플레이그라운드에서 조율형 에이전트로 대화 → 인스펙터 trace에
  `broker_invoke:*` 노드가 뜨는 스크린샷(사용자 눈으로 확인용). 라이브(qwen) 또는 mock-llm.
- 기존 무회귀: 100–105 broker 테스트.

## 비목표 (OUT)

- 새 기능 없음 — 순수 시연/검증(체인은 이미 구현·부분 검증됨).
- 다중 위임·랭킹 전략 심화(102에서 검증). 여기선 단일 위임 1턴으로 체인 관통만.
- Ralph 루프 — 1회 시연이면 충분(백로그 명시).

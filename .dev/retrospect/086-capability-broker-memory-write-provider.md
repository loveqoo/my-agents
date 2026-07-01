# 086 — 능력 브로커 kind 확장: Memory **write** provider (첫 부수효과·승인 게이트)

스펙 105. 능력 브로커에 다섯 번째 provider(kind=memwrite, 유저 장기 기억 저장)를 붙였다. 앞선 넷
(agent·mcp·rag·memory)에서 실제로 부수효과를 낸 건 mcp의 위험 툴뿐이었고 그마저 조건부였다.
memwrite는 **항상 부수효과(쓰기)**라, 두 게이트(정책+승인) 중 **승인 게이트가 처음으로 상시 발화**한다.
게다가 과거 자동쓰기가 교차유저 누출(스펙 051·learning 031)이라, "왜 이번 쓰기는 안전한가"를 구조로
못박아야 했다.

## 무엇을 했나

- `MemoryWriteProvider`(kind=memwrite, cap=`memwrite:user`)를 broker.py에 추가. MemoryProvider(104) 거울.
- **두 구조적 방어를 겹쳤다**:
  1. **쓰기 축=user_id(자기)만·principal 바인딩**(104 재사용) — `{"user_id": self._user_id}`에만 쓴다.
     agent_id 금지(051 누출 축). user_id는 cap_id·args가 아니라 principal 도출값 → 남의 기억에 쓸 방법
     구조적 부재. 자기 스코프 쓰기는 정의상 교차유저 누출 불가.
  2. **승인 게이트**(learning 031의 정답) — `approval_for` **항상 non-None**(읽기와 정반대). 브로커가
     `memory.add`(부수효과) *이전* interrupt로 멈추고 승인돼야 저장. reject→무저장 / approve→정확히 1회.
- **읽기≠쓰기 별도 권한**: kind 분리(`capability:memwrite` ≠ `capability:memory`) — 최소권한.
- **소유자 self-승인 기본**(사용자 결정): `_DEFAULT_POLICIES`에 `("member","memory.write","self_approve")`.
  자기 기억 쓰기는 소유자 승인이 옳은 민감도 등급(admin이 남의 개인 기억 승인은 부적절). `data.delete`는
  여전히 admin(민감도 구분 유지).
- **저장=승인 원문**(infer=False), 승인 payload에 사실 마스킹 없이 노출(승인하려면 봐야).
- 검증 3런: verify_105(단위 FakeMemAdd + **최소 1노드 graph 승인 왕복**[LLM 불요] + 실 mem0 쓰기→읽기
  왕복·교차유저 격리 + self-approve 정책 시드) + 무회귀(066/084/100–104) + codex.

## 잘된 것

- **learning 031이 처방한 구조가 그대로 맞았다**: "기억해줘를 프롬프트 금지보다 우선하는 LLM은 프롬프트
  아닌 구조로 막아라" → 브로커 승인 게이트가 정확히 그 구조. 회고가 다음 작업 Context에서 설계를 *직접*
  결정했다(복리).
- **부수효과 게이트를 LLM 없이 결정적으로 검증**: broker.invoke를 감싼 최소 1노드 StateGraph +
  MemorySaver로 reject=무저장/approve=1회저장/interrupt-전-무저장을 실측. 풀 orchestrate+mock LLM(101 H
  방식)보다 싸고 결정적. **게이트 메커니즘 테스트에 전체 플로우가 필요 없다** — 게이트를 부르는 최소
  하네스면 충분.
- **두 게이트 분리(103)가 또 벌었다**: 읽기(104)는 방어1만, 쓰기(105)는 방어1+2. 확장이 조합으로 떨어짐.

## codex 적대 리뷰 — 3판정 (P0/P1 없음, P2 2건)

- **[P2 실결함] 승인·저장 사실 길이 무제한** — 거대 text가 승인 DB(JSONB)·응답·저장 기억 무제한 점유
  (103·104 P2 동형 교차입구 갭). → `_memwrite_text` 공유 헬퍼로 4000자 상한. **approval_for·invoke가
  같은 헬퍼로 잘라 "승인한 것 == 저장되는 것"**(길이도 일치 — 승인-저장 드리프트 0).
- **[P2 미문서 경계] admin의 타인 memory-write 승인 열람/결정** — codex가 privacy 노출로 짚음. 판정:
  **admin은 이미 053(`memory:manage`)로 임의 유저 기억 전체 접근 권한 보유** → 승인 뷰에서 사실을 보는
  것이 admin 권한을 넓히지 **않는다**(새 노출 아님). 안전 불변식(저장 스코프=승인자 무관 요청자 user_id,
  교차유저 쓰기 0)은 유지·검증됨. → 비목표에 경계 명시 + 후속(owner-only resolve/마스킹) 기록. **privacy
  finding 판정의 핵심 질문**: "이게 그 주체가 *다른 경로로 이미 가진* 권한을 넓히나?" 안 넓히면 새 결함
  아닌 기존 경계.

## 아쉬웠던 것 / 다음

- self-승인 기본을 열지 admin-only로 둘지는 사용자에게 물어야 하는 결정이었다(보안 트레이드오프) —
  AskUserQuestion으로 outcome을 보여주고 결정받았다. 정책 민감도 등급은 도메인 판단이라 자가결정 대신 확인.
- 다음: memory **수정/삭제** 능력은 대상 mem_id 소유권 검증(053 `_assert_user_owns`)이 add와 달리 선행
  필요(add는 자기 스코프 생성이라 대상 없음, update/delete는 대상 행 소유 확인). per-cap·per-user 인가
  일반화(백로그 Phase 2 b)로.

관련: learning 105 · learning 031(구조로 막아라)·100·104 · [[complement-attack-can-be-honest-boundary]] · 스펙 105.

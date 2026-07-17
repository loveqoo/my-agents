# 388 — A2A 서빙 v2: contextId 세션 연속성(P1) + 승인 브리지(P2)

> 상태: 초안(AI 작성 → 인간 검토). 발단: 387 후속 문답("A2A로 유저 특정+세션 대화+승인 가능한가?")
> — 채팅 API로는 전부 되지만 A2A 표준 입구는 절반. 스펙 061 §6이 미룬 것을 채운다.
> 참고: 061(서빙 v1)·057(contextId 채택)·068(세션 소유권)·387(유저 정체성)·346(체크포인트 수명)

## 목표

외부 시스템이 **A2A 표준만으로** 우리 에이전트를 완전한 부품으로 쓰게 한다:
유저 특정(387 완료) + **대화 이어가기(P1)** + **승인 왕복(P2)**.

## 용어 층위(388 문답에서 확정)

contextId(A2A 와이어 표준) ↔ sessionId(우리 REST/DB) ↔ thread_id(LangGraph 내부, 턴별).
번역은 경계 어댑터 한 곳에서만 — v2는 서버 측 contextId↔session 번역기를 놓는 일.

## P1 — contextId 세션 연속성 + 영속

**설계 원칙: 발명 없음, 기존 부품 배선.** 우리 클라이언트는 이미 자기 세션 id를 contextId로
보낸다(chat_stream.py:87, 스펙 057) — 서버도 같은 규약으로 대칭을 완성한다.

1. **contextId = 우리 session_id 재사용**(서버 발급·클라 에코 — A2A 표준 모델 그대로).
   - 요청에 contextId 없음 → `_resolve_session(None)` 새 세션(lazy) → 응답 Message에
     `contextId` 포함.
   - 있음 → `_resolve_session(contextId)` 재개 — **에이전트 스코프**(타 에이전트 세션 안 섞임)·
     매칭 실패=새 세션(부재와 구별 불가, 068 열거 오라클 제거 그대로).
2. **소유권(RBAC 체크리스트 답)**:
   - 입구: A2A JSON-RPC(message/send·stream) 한 곳(+기존 chat API는 무변경).
   - 1차 방어 = session_id 자체가 추측 불가(`sess-`+128bit). 내부 채팅과 동일 수준.
   - 2차 = **userId 바인딩**: 생성 시 세션에 metadata.userId 스탬프(387 대칭), 재개 시
     세션.user_id ≠ 요청 userId면 **매칭 실패로 접음**(새 세션 발급 — 404/403 구분 없음).
     userId 없는 머신 호출은 owner 전권(기존 계약 유지).
   - 비-SQL 저장소 없음(세션=SQL, SELECT-WHERE로 스코프).
3. **히스토리·영속**: `_load_context`가 세션 기반이라 대화 재구성(chat_history)·영속(_persist)
   재사용. 세션 channel="a2a"로 표기(세션 화면에서 출처 구분).
   - **제품 가시 변화**: A2A 대화가 관리자 세션 화면에 쌓인다 — **승인됨(영속·표시, 2026-07-17)**.
4. 기억(387)과 결합: userId 있으면 user 축 + 이제 세션 축(run_id)도 자연 동작(세션이 생기므로).

## 범위 결정: P1 먼저 완성·검증·커밋 후 P2 이어서(2026-07-17)

## P2 — 승인(HIL) 브리지

서빙에 checkpointer 주입 → interrupt를 예외로 떨어뜨리지 않고(현 fail-closed) **승인 대기로 변환**:

1. interrupt 감지 → Approval 생성(user_id=metadata.userId — 387 스탬프 그대로).
2. A2A 응답 = Task `state: "input-required"` + metadata에 approvalId·contextId(표준 표현).
3. **재개 입구 — 결정: (a) A2A 순수(2026-07-17)**:
   - (a) **A2A 순수**: 외부가 같은 taskId로 approve/reject 메시지 전송 → 우리가 resolve+재개+
     결과 반환까지 A2A 안에서. 표준 순수하나 "승인 의미"의 메시지 규약은 우리 확장.
   - (b) **REST 혼합**: 외부가 `POST /approvals/{id}/resolve`(머신 토큰 — 이미 동작 확인) 후
     A2A 후속 메시지로 결과 회수. 인프라 재사용 최대, 프로토콜은 두 개 혼합.
4. 체크포인트 수명: 승인 대기는 기존 관문(346 — 승인 pending은 보존, TTL 스윕)에 그대로 편승.

## 완료 조건(측정 가능) — verify_388

- P1-C1: contextId 없이 send → 응답에 contextId, 두 번째 send(같은 contextId)에서 이전 대화
  참조 질문이 통함(히스토리 관통 — "아까 말한 코드?"에 답).
- P1-C2: 타 에이전트/타 userId의 contextId 재개 시도 → 새 세션(내용 누출 0, 오라클 0).
- P1-C3: A2A 대화가 세션·메시지로 영속(channel="a2a"), 관리자 세션 화면 조회 가능.
- P1-C4: 기존 채팅 API·내부 채팅 무회귀(SUITE_OK·suite 51/51).
- P2-C1: 승인 필요 도구 → input-required 응답(실행 0 — 부수효과 없음 확인).
- P2-C2: 승인 → 재개 → 결과 수신. 거부 → 실행 0 종결.
- P2-C3: 소유권 — 타 userId가 남의 approval 결정 불가.
- codex 적대 리뷰(외부 프로토콜 입구 + 인가 경계라 필수).

## P1 결과(2026-07-17)

- verify_388 **10/10**: contextId 발급(sess-)·재개 에코·세션 영속(channel=a2a·소유자 스탬프·
  메시지 4행/2턴)·위조 contextId 접기(오라클 0)·타 userId 바인딩 접기·기억 스코프 user+run 축.
- **codex 적대 리뷰: 보안 결함 0** — own=userId 바인딩(SELECT-WHERE)·히스토리 주입은 session_pk
  통과 시만·lazy-create 레이스(영속 전 contextId 재사용=새 세션으로 접힘·제공 id로 생성 안 함)·
  persistHistory=false 계약·스트림 조기 이탈(0턴 미영속=무해)·relay 무시(아웃 명시 일치) 전부 무결.
  Finding 1건 = verify_061 monkeypatch가 구 시그니처(소비자 누락) → 새 계약(튜플 반환)으로 갱신, 그린.
- 여파 갱신 1건: verify_387 I3b가 저장 스코프 **정확일치** 단언이라 run 축 추가로 깨짐 → user 축
  값 고정 단언으로 완화(계약 진화 반영). 22/22 복귀.
- **suite 51/51 · flaky 0 · 실패 0** · metrics-fast 전판 그린 · make test SUITE_OK.

## 아웃

- 서빙 relay(code 에이전트 1홉 중계) 경로의 세션/승인 — 원격이 자기 것 소유(정직한 경계 유지).
- A2A tasks/get 폴링·푸시 알림 표준 표면 — 필요 시 후속.

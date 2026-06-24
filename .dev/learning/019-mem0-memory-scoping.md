# 019 — mem0 메모리 스코핑: user_id 축, thread_id 직교, entity-id 제약

맥락: 메모리 유저 스코핑 작업(스펙 docs/spec/018).
대상: `packages/api/src/api/{chat,memory,schemas}.py`, mem0 2.0.7.

## 핵심 — mem0 `user_id`와 LangGraph `thread_id`는 직교축

LangGraph 문서 원문: **"thread-id scopes a single session, while user-id scopes
across sessions — confusing them is the most common production mistake."**

- mem0 **`user_id`** = *누구의* 기억인가 → **세션을 가로지른다**(cross-session).
- LangGraph **`thread_id`** = *어느 대화*인가 → 우리 `session_id`에 대응(단일 세션).

두 축을 한 변수로 합치면 안 된다. 우리 설계:
```
mem_scope = f"user:{userId}" if userId else f"session:{session_id}"
mem.add(messages, user_id=mem_scope)        # who
# (미래) graph.invoke(..., config={"thread_id": session_id})  # which conversation
```
→ `userId` 있으면 기억=유저·체크포인트=세션으로 **독립**. `userId` 없으면 둘 다
`session_id`로 합쳐져 **세션 단기**. 체크포인터가 나중에 들어와도 `thread_id=session_id`면
충돌 없음 — **유저 식별 결정이 미래 체크포인트를 막지 않는다.**

## 함정 1 — mem0 entity-id는 내부 공백·빈값을 거부한다 (조용한 무력화)

mem0 2.0.7 `mem0/memory/main.py:139-165` `_validate_and_trim_entity_id`:
앞뒤 공백 trim, **빈/공백-only → ValueError**, **내부 공백 → ValueError**.

`memory.py`가 호출을 `except Exception`으로 감싸므로, `userId="john doe"` 같은 값은
**조용히 삼켜진다** — 저장·회상 0인데 트레이스엔 `user:john doe`로 보임 = 데이터 유실인데
에러도 안 남. 가장 위험한 종류의 버그.

**대응**: API 경계(`ChatRequest.userId`의 `field_validator`)에서 정규화 —
빈/공백-only → `None`(세션 단기 폴백), 내부 공백 → **422 명시 거부**.
라이브러리 내부 제약은 **경계에서 막아** 조용한 실패를 시끄러운 실패로 바꾼다.

## 함정 2 — 단일 keyspace 충돌

mem0 `user_id`는 평면 네임스페이스다. `userId`와 `session_id`를 같은 축에 실으면
`userId="sess-abc123"`가 세션 키와 충돌 가능 → **접두사 분리**(`user:` / `session:`).

## 일반화 가능한 규칙

- **외부 SDK의 키/식별자 제약(공백·길이·문자셋)은 설계 전 Context 단계에 소스/문서로 선확인.**
  reviewer 주장도 1차 출처(설치된 소스)로 검증한다 — "추측 말고 동일 사례를 찾아라" 준수.
- **키(저장)와 라벨(표시)을 한 값으로 묶어라** — truthiness 분기를 두 곳에 두면 리팩터에서 어긋난다.
- **except로 감싼 외부 호출은 조용한 실패의 온상** — 경계 검증으로 실패를 표면화.

관련: 회고 [[009-memory-user-scoping]] · 스펙 docs/spec/018 · [[012-runtime-config-single-source]]

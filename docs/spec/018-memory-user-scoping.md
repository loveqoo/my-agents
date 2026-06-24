# 018 — 메모리 유저 스코핑 (세션 단기 ↔ 유저 장기)

상태: **초안 (AI 작성 — 인간 검토 대기)**
날짜: 2026-06-24
브랜치: `feat/agent-service` — **main 머지·push 금지**(사용자가 직접 브랜치 테스트)
지배 스펙: [007-real-agent-service](007-real-agent-service.md) (Phase 2 — 메모리)
연관 코드: `packages/api/src/api/chat.py`, `memory.py`, `schemas.py`, `models.py`,
`admin/src/admin/views/AgentsView.tsx`, `admin/src/playground/DebugChat.tsx`

---

## 배경 — 현재 메모리는 "에이전트 1버킷"

`memory.py`는 mem0를 `user_id = agent_id` 하나로만 호출한다
(`mem.search(query, filters={"user_id": agent_id})`, `mem.add(messages, user_id=agent_id)`).
즉 **에이전트별·세션 무관 장기 버킷 1개**. 스펙(007/docs)이 말한 두 종류 —
(a) 에이전트 작업기억, (b) **유저에 대한 메모리** — 중 (b)의 "유저 차원"이 없다.

한편 에이전트 설정의 `memories`는 이미 **타입 멀티셀렉트**다(블록에서 선택):

| 타입 | 의미(블록 정의) | 현재 배선 |
|---|---|---|
| `단기(세션)` | "현재 세션의 인-컨텍스트 윈도우. 세션이 끝나면 비워짐. 영속성 없음." | historyDepth 윈도우(=대화 이력 절단)뿐, mem0 미배선 |
| `장기·의미론적` | "Cross-session 벡터 스토어. 매 턴 의미 유사 top-k 검색. TTL 없음." | mem0 배선됨 (현재 유일) |
| `장기·일화적` | "이벤트 로그를 일 단위 요약" | 미배선 |
| `절차적` | (블록) | 미배선 |

`memory.memory_enabled()`는 정확히 `"장기·의미론적"` 포함 여부만 본다.

---

## 사용자가 정한 데이터 모델 (논의 확정)

- **메모리 사용** = 에이전트별 on/off (기존 타입 선택 유지 — `장기·의미론적`이 mem0 켬).
- **유저 식별 = 에이전트 토글이 아니라 요청의 `userId` 필드 유무로 결정**(토글 폐기, 결정 확정).
  - **`userId` 없음/null** → 메모리 사용 시 **현재 세션 한정 단기 기억**(세션과 함께 소멸).
  - **`userId` 있음** → mem0 기본 장기·의미론 기억을 **유저 단위**로 제공.

### 결정 A — 유저 추출은 "명시적 `userId`" (항상 받는 nullable 필드)
호출자(Playground 입력칸 / 미래 A2A 핸들러 / 외부 클라이언트)가 `userId`를 넘긴다.
`ChatRequest`에 항상 존재하는 nullable 필드로 받고, **값 유무가 곧 스코프**다(별도 에이전트 토글 없음).
인증주체 도출(B)은 현재 단일 관리자라 의미 없음(멀티유저 인증 전), mem0 자동 추출(C)은
신원 키를 만들지 못해 단독 불가 — 둘 다 기각.

---

## 핵심 설계 — `user_id` 두 축은 직교한다

LangGraph 문서: **"thread-id scopes a single session, user-id scopes across sessions —
confusing them is the most common production mistake."** 이를 그대로 따른다.

- mem0 **`user_id`** = *누구의* 기억인가 (세션 가로지름)
- (미래) LangGraph **`thread_id`** = *어느 대화*인가 → 우리 `session_id`에 대응

### mem0 `user_id` 결정 규칙 (chat.py)
```
if not memory_enabled(memories):        # 장기·의미론적 미선택
    → 메모리 미사용
elif userId:                            # 요청에 userId 들어옴
    mem_scope = f"user:{userId}"        # 세션 가로지르는 유저 장기 기억
else:                                   # userId 없음/null
    mem_scope = f"session:{session_id}" # 세션 단기 — 세션과 함께 소멸
```
> **접두사 분리(타자 검증 반영, P3)**: 두 모드가 mem0 `user_id` 단일 keyspace를 공유하므로
> `user:` / `session:` 접두사로 분리한다 — `userId="sess-xxxx"` 충돌 방지. 또한 이 `mem_scope`를
> 트레이스 `memoryScope` 라벨과 **동일 값으로 묶어** 스코프/라벨 불일치 위험(P2) 제거.

| 모드 | mem0 `user_id` | (미래)`thread_id` | 효과 |
|---|---|---|---|
| `userId` 없음 | `session_id` | `session_id` | 두 축이 한 키로 합쳐짐 = 세션 단기 |
| `userId` 있음 | `userId` | `session_id` | 기억=유저, 체크포인트=세션 (독립) |

→ **체크포인터가 나중에 들어와도 `thread_id = session_id`면 충돌 없음.** 이번 결정이 미래를 막지 않는다.

### "세션 단기"를 mem0로 구현하는 의미
`단기(세션)` 블록의 정의는 "영속성 없음"이지만, 사용자 요구는 **"메모리 사용 시" 세션 단기 기억**.
이를 `user_id = session_id`로 mem0를 돌려 구현한다 — 같은 `add/search` 경로, 키만 세션.
세션이 끝나면 그 키로 더 안 쌓이고 회상도 안 되므로 사실상 세션 수명과 동치.
(별도 TTL/삭제는 이번 범위 밖. 추후 세션 종료 시 `user_id=session_id` 메모리 purge 옵션 검토.)

> **해석(확정)**: 에이전트 "유저 식별 토글"은 폐기. **타입 선택(장기·의미론적=mem0 켬)** 위에
> **요청 `userId` 유무(스코프 축)**가 얹힌다. `단기(세션)` 타입은 종전대로 historyDepth 윈도우
> 의미를 유지하고, mem0의 세션 단기는 "장기·의미론적이 켜졌지만 userId가 없을 때"에 동작한다.

---

## A2A에서의 유저 (미래 — 슬롯만 호환)

A2A 규격상 유저는 두 경로로 들어온다: (1) **위임 토큰**(클라 에이전트가 인증→토큰을
`sendMessage`에 실어 보냄, 원격은 인증 유저를 대신해 동작), (2) **메시지 `metadata`**
(`Record<string,any>`에 session/맥락 동봉). **어느 쪽이든 결국 같은 `userId` 슬롯으로 수렴** —
미래 A2A 핸들러가 토큰/metadata에서 신원을 뽑아 chat 경로의 `userId`에 넣는다.
**이번 스펙은 A2A 핸들러를 구현하지 않는다**(플래그만 존재). 슬롯만 비워둔다.

---

## 변경 계획

### A. `schemas.py`
- `ChatRequest`에 `userId: str | None = None` 추가(항상 존재하는 nullable 필드).
- **`field_validator`(타자 검증 반영, P2)**: mem0 2.0.7이 `user_id`의 내부 공백·빈 문자열을
  `ValueError`로 거부 → 경계에서 정규화. 빈/공백-only → `None`(세션 단기 폴백),
  내부 공백 → 422 명시 거부(조용한 무력화·데이터 유실 방지).

### B. `chat.py`
- `chat()`에서 `body.userId`를 받아 위 규칙으로 `mem_scope` 산출:
  `mem_scope = f"user:{body.userId}" if body.userId else f"session:{ctx['session_id']}"`.
- `memory.search` / `memory.add` 호출의 첫 인자를 `agent_id` → **`mem_scope`**로 교체.
- 트레이스 `trace["memoryScope"] = mem_scope`(키=라벨 동일 값). 인스펙터 표시·디버그용.
- (참고: 에이전트 토글 없음 — config 변경 불필요.)

### C. `memory.py`
- `search(agent_id, ...)` / `add(agent_id, ...)`의 인자명을 `mem_user`(또는 `scope_id`)로 정리.
  내부 `filters={"user_id": mem_user}`, `user_id=mem_user`. 시그니처 의미만 명확히 — 동작 동일.

### D. Playground `DebugChat.tsx`
- 헤더/옵션에 **"유저로서 대화" 입력칸**(userId). 비우면 세션 단기.
- chat 요청 바디에 `userId` 포함. 원격 테스트 시 같은 userId로 새 세션을 열어 **장기 회상이 되는지** 눈으로 확인.
- 인스펙터에 `memoryScope` 표시(이미 `trace.memories`는 노출 중 — 스코프 라벨만 추가).

---

## 검증 (완료 조건)

- [ ] `tsc --noEmit` + 파이썬 import/기동 OK.
- [ ] **userId 없음**: 같은 에이전트로 세션 A에서 사실을 말함 → 세션 B(새 세션)에서 회상 **안 됨**(세션 격리). 세션 A 안에선 회상 됨.
- [ ] **동일 userId**: 세션 A에서 말한 사실을 세션 B에서 **회상 됨**(유저 장기).
- [ ] **다른 userId**: 서로 회상 **안 됨**(유저 격리).
- [ ] 메모리 미사용(장기·의미론적 미선택) 에이전트는 mem0 호출 0 (기존 graceful 유지).
- [ ] 트레이스 `memoryScope`가 인스펙터에 정확히 표시.
- [ ] **타자 검증**: 서브에이전트 또는 codex로 chat.py 키 분기·폴백 로직 비판 리뷰(세션 단기↔유저 장기 누수 없음 확인). 자가검증 지양.
- [ ] dry-run 고려: mem0 키 변경은 기존 `agent_id` 버킷과 단절되므로(키가 바뀜) 기존 시드 메모리는 회상에서 빠진다 — 회귀가 아니라 의도된 재스코핑임을 명시.

---

## 범위 밖 (이번 스펙 제외)

- 실제 A2A 프로토콜 핸들러/신원 추출 (슬롯만 호환).
- LangGraph 체크포인터/`thread_id`/HIL interrupt 도입.
- `장기·일화적`·`절차적` 타입 배선.
- 세션 종료 시 단기 메모리 purge, 메모리 관리/삭제 UI.
- 멀티유저 인증(인증주체 기반 userId 도출), 에이전트별 유저 식별 토글(폐기됨).

## 비고
- main 머지·push 금지. 검증 후 사용자가 직접 브랜치에서 테스트.
- 기존 `agent_id` 스코프 단절은 의도 — 필요 시 마이그레이션은 별도 논의.

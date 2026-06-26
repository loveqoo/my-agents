# 032 — Playground userId를 인증 주체에서 도출 (수동 입력 제거)

상태: **구현 완료 (AI 작성·검증 — 인간 브랜치 테스트 대기, main 머지 금지)**
날짜: 2026-06-26
브랜치: `feat/agent-service` — **main 머지·push 금지**(사용자가 직접 브랜치 테스트)
지배 스펙: [031 멀티유저 인증](./031-multi-user-auth-and-pluggable-providers.md)(§범위 밖에서 "userId↔인증주체 전면 도출"을 후속으로 명시), [021 Playground userId UX](./021-playground-userid-ux.md)(현 입력·잠금·과거선택), [020 mem0 multi-scope](./020-mem0-multi-scope-and-catalog-realign.md)(userId=mem0 user_id 축)
연관 코드: `packages/api/src/api/chat.py`, `schemas.py`(ChatRequest); `admin/src/playground/{Playground,DebugChat}.tsx`, `admin/src/api.ts`

---

## 배경 — 왜 지금

031로 세션 쿠키 인증이 생겨 **인증 주체(누가 로그인했나)**가 서버에 존재한다. 그런데 Playground는
여전히 **mem0 user_id 축(누구의 장기기억을 읽고/쓰나)**을 헤더에서 손으로 입력받는다. 평상시 둘은
같은 사람이므로 수동 입력은 군더더기다. 사용자 결정: **입력을 완전히 제거하고 항상 로그인 유저로 고정**.

### 두 개념 구분(설계 근거)
- **인증 주체**: `current_principal`(쿠키 유저 `User` 또는 머신 토큰 `"machine"`).
- **mem0 user_id 축**: `chat.py`의 recall/add 스코프 키(`body.userId` → 제거 대상).

→ 1차에서 둘을 **일치**시킨다: user_id 축 = 인증된 유저의 안정 식별자.

---

## 설계 결정

1. **축 값 = `str(user.id)`(UUID).** 이메일은 가변이라 기억 축으로 부적합. UUID는 안정적이고 mem0
   user_id 문자열 키로 그대로 쓴다. (Inspector는 UUID를 그대로 노출 — 불투명하지만 정확.)
2. **머신 토큰 호출(하위호환)** = 유저 신원 없음 → `user_id = None`(세션 단기 폴백). 기존 "빈 userId"
   동작과 동일하므로 mock_remote·E2E·playground 머신경로 **무회귀**.
3. **"새 대화" 버튼 유지하되 userId 잠금에서 분리.** 원래는 userId를 다시 풀려고 `userIdLocked`에
   묶여 있었다(021). userId가 사라지니 그 사유는 소멸하지만, *대화 초기화*는 독립적으로 유용 →
   `messages.length > 0`일 때 노출하는 일반 리셋으로 격하.
4. **받아들이는 한계**: 과거에 손으로 타이핑한 userId("alice" 등)로 쌓인 기억은 축이 UUID로 바뀌어
   더는 회상되지 않는다. dev 도구의 테스트 데이터라 수용. ("다른 유저로 테스트" 능력 상실도 수용 —
   사용자가 '완전 자동'을 선택. 필요해지면 어드민 전용 override를 후속 스펙으로.)

---

## 변경 계획 (파일별)

### A. 백엔드
- `schemas.py`: `ChatRequest`에서 `userId` 필드 + `_clean_user_id` validator **제거**. (extra 필드는
  pydantic 기본 무시라 잔존 클라이언트가 보내도 422 안 남 — 안전.)
- `chat.py`:
  - `chat()` 핸들러에 `principal=Depends(current_principal)` 주입. `from .auth import current_principal`.
  - 도출: `user_id = None if isinstance(principal, str) else str(principal.id)` (str 센티넬 = "machine").
  - `body.userId` 3개 사용처(recall scope·add scope·`_persist` 호출, ~336/376/445)를 도출한 `user_id`로 치환.
  - `_remote_stream`에도 `user_id`를 인자로 전달(현재 `body.userId` 의존 제거).

### B. 프론트엔드
- `api.ts`: `streamChat`에서 `userId` 파라미터 + body 전송 제거. dead가 된 `listUserIds` export 제거.
- `Playground.tsx`: `userId`/`userIds` state, `listUserIds` 로드, 낙관적 추가, DebugChat에 넘기던
  `userId`/`setUserId`/`userIds`/`userIdLocked` prop 제거. `onResetConversation`은 유지(아래).
  `streamChat` 호출에서 userId 인자 제거.
- `DebugChat.tsx`: 헤더의 `AutoComplete`(userId) + Tooltip + 잠금 분기 제거, 관련 import 정리.
  "새 대화" 버튼은 `messages.length > 0`에 노출하는 리셋으로 유지.

### C. 잔존(건드리지 않음)
- `GET /sessions/users`·`sessions.user_id` 컬럼·`listUserIds`: **존치**. 계획 초안은 "프론트
  소비처가 사라진다"고 봤으나 **실제 소비처가 둘이었다** — Playground 헤더(제거 대상) + 어드민
  "메모리 > 유저 메모리" 탭(`MemoryView.tsx`, 유저별 mem0 기억 조회). 후자는 그대로 동작하며 이제
  UUID 목록을 보여준다(Inspector UUID 노출 결정과 일관). 그래서 `listUserIds`는 죽은 코드가 아니라
  유지. (교훈: "마지막 소비처"를 단정하기 전 grep로 전수 확인 — retrospect 023.)

---

## 검증

1. **라이브**: 로그인 후 Playground에서 채팅 → trace의 recall/add 스코프 `user_id`가 **로그인 유저
   UUID**인지 Inspector로 확인. 머신 토큰 직접 호출 시 `user_id` None(세션 단기)인지 확인.
2. **무회귀**: 머신 Bearer 토큰으로 `/agents/{id}/chat` 정상 스트림(하위호환).
3. **브라우저**(Playwright+시스템Chrome): 헤더에 userId 입력이 없고, 채팅·"새 대화"·인스펙터 정상.
4. **타자 리뷰**: 서브에이전트/codex로 — principal 도출 분기 누수(머신→None), 스코프 축 치환 누락,
   프론트 dead 코드 잔존 점검.

## 완료 조건
- [x] schemas/chat.py에서 `body.userId` 제거 + principal 도출로 치환(recall/add/_persist/_remote_stream)
- [x] 프론트 userId 입력·상태·prop 제거, streamChat 시그니처 정리(`listUserIds`는 MemoryView 소비처 때문에 존치)
- [x] 라이브(UUID 축 확인)+머신 무회귀+브라우저 통과, 타자 리뷰 PASS
- [ ] **main 머지 금지**

## 검증 결과(2026-06-26)
- 라이브(쿠키): 로그인 유저(verify032, UUID `f771ed47…`)로 mem0 에이전트 채팅 →
  trace `memoryScope.user_id == f771ed47…` 일치 확인.
- 라이브(머신 Bearer): `memoryScope`에 user_id 축 없음(run_id+agent_id만) → 세션 단기 폴백, 무회귀.
- 무인증 채팅 401. tsc --noEmit 통과(자체+codex 독립).
- 브라우저(Playwright+시스템Chrome, `tests/browser/shot-playground-032.mjs`): 헤더 userId 입력 0개,
  채팅 1턴(remote/code 경로) 정상, "새 대화" 노출·클릭 리셋 정상.
- 타자 리뷰: **codex SHIP + 독립 서브에이전트 SHIP**(수렴, HIGH/MED 0). 양쪽이 `streamChat`
  두 번째 호출자 `Chat.tsx`(positional 4인자)도 무영향임을 확인.

## 범위 밖 (후속)
- 어드민 전용 "다른 유저로 테스트"(userId override) — 필요 시 권한 보호된 후속.
- `/sessions/users`·`sessions.user_id` 정리 또는 UUID→표시이름 매핑.
- 과거 typed-userId 기억 마이그레이션(축 변경 이관).

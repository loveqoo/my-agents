# 090 — 플레이그라운드 과거 메시지 역방향 페이징 (상단 "이전 메시지 더 보기")

> ⚠️ **파킹(미착수) — 제안 #2가 아님.** 작성자가 #2를 *터미널 히스토리식 입력 재호출*(스펙 091)로
> 정정했다. 본 스펙은 그 오독에서 나온 **별개의 좋은 후속 후보**로, 사용자가 "좋은 기능"이라 보존을
> 원해 남겨둔다. 착수 여부는 8항목 소진 후 Scaffolding에서 재논의.

> 보고(#2): "플레이그라운드의 채팅 영역 맨 앞에서 위쪽 화살표를 누르면 과거의 메시지를 순차적으로
> 가져왔으면 좋겠어." → 채팅 목록 **상단에서 이전 대화를 역방향으로 순차 로드**(load-earlier).
> 사용자 합의: 인터랙션 = "채팅 목록 상단서 이전 대화 더 불러오기", 구현 깊이 = **백엔드 커서 페이징**.
> 관련: retrospect 024(세션 페이징 엔벌로프 — 마지막 소비처 단정 함정), learning 068(list≠item 스코핑·404 열거),
> retrospect 058(세션 읽기 SELECT-WHERE 융합)·learning 073(타이밍 오라클 계층별), retrospect 045/055(세션 이어가기 비동기 레이스).

## 배경 — 측정한 현황

- **메시지 엔드포인트는 무페이징 전량 반환**: `GET /sessions/{id}/messages`(`sessions.py:221`)가
  `ORDER BY Message.created_at`로 세션의 **모든** 메시지를 한 번에 돌려준다(limit·cursor 없음).
- **소비처 2곳**(둘 다 전량 의존): ① `Playground.tsx:280` `loadSession`(과거 세션 선택 시 전체 복원),
  ② `SessionsView.tsx:51`(관리자 세션 검토 — 전체 대화 표시). → 응답 형태 변경 시 **둘 다** 갱신해야 함.
- **턴 내부 정렬이 이미 미정의(측정)**: `_persist`(`chat.py:404-405`)가 user·assistant 메시지를 **같은
  트랜잭션**에서 `db.add`. Postgres `func.now()`는 트랜잭션 시각이라 **둘의 `created_at`이 동일**하다.
  `Message.id`는 **UUID(단조 아님)**. 즉 `ORDER BY created_at`만으로는 한 턴의 user/assistant 상대순서가
  DB-임의다(오늘도 그렇다). 커서 페이징은 **안정적 전순서**가 필수라 이 타이를 정직하게 풀어야 한다.
- **채팅 렌더**: `AdminShell` → `Playground.tsx` → `DebugChat.tsx`. 스크롤 컨테이너 `DebugChat.tsx:746`,
  **변경 시 항상 맨 아래로 auto-scroll**(`686-692`, deps `[messages, streaming, showPrompt]`). prepend와 충돌.

## 결정 (사용자 합의)

- **백엔드 커서 페이징.** 엔드포인트에 `limit`+`before`(opaque cursor)를 추가한다. 과거 세션을 열면
  **최근 N개만** 싣고, 채팅 목록 **상단의 "↑ 이전 메시지 더 보기"**로 더 오래된 묶음을 **DB에서 fetch**해
  prepend한다. 대용량 세션도 와이어로 전부 받지 않는다.
- **안정적 전순서 = `(created_at, role_rank, id)`.** `role_rank`: user→0, 그 외→1. created_at 타이(한 턴
  내부)를 role로 깨 user가 assistant보다 먼저 오게 한다 — **페이징 안정성 + 턴 내부 표시 정확성**을 동시에
  얻는다(기존 잠복 결함도 덤으로 교정). 읽기 전용·마이그레이션 0(쓰기 경로 `_persist` 불변).
- **엔벌로프 응답 + 소비처 2곳 모두 갱신**(retrospect 024). `limit` 미지정 = 전량(현행 의미 보존)으로
  `SessionsView`는 `.items`만 읽게 1줄 변경, `Playground`만 페이징을 쓴다.
- **소유권 불변**: 메시지는 *이미 owner-스코핑된 세션*의 자식. `_get_session_or_404(session, id,
  _own_scope(principal))`(`sessions.py:227`)가 단일 게이트로 유지된다. 커서는 `session_pk == s.id`로
  바인딩된 쿼리에 **세션 내부 정렬 경계만** 더한다 — 새 입구·새 오라클 0.

## API 계약

```
GET /sessions/{session_id}/messages
  ?limit=int|null     # 미지정 → 전량(ascending). 지정 → 페이지 크기.
  ?before=str|null    # opaque cursor. 그 커서보다 "더 오래된" limit개를 반환.
→ MessagePage {
    items:   list[MessageOut]   # 항상 ascending(시간순) — 프런트가 그대로 prepend/append
    hasMore: bool               # items[0]보다 더 오래된 메시지가 존재하는가
    cursor:  str | null         # items[0](이 배치의 최古)의 키를 인코딩한 토큰 → 다음 before. items 없으면 null
  }
```

정렬 키 `K = (created_at, role_rank, id)`, `role_rank = CASE WHEN role='user' THEN 0 ELSE 1 END`.

- **`limit` 미지정**: `WHERE session_pk=s.id ORDER BY K ASC` 전량. `hasMore=False`, `cursor=key(items[0])`(있으면).
- **`limit` 지정, `before` 없음**(초기 로드): `ORDER BY K DESC LIMIT limit+1` → 앞 `limit`개 취함,
  `hasMore = (반환수 > limit)`, 취한 것 reverse → items ascending, `cursor=key(items[0])`.
- **`limit` 지정, `before=cursor`**(이전 묶음): cursor 디코드 → `(c_created, c_rank, c_id)`;
  `WHERE session_pk=s.id AND K < (c_created, c_rank, c_id) ORDER BY K DESC LIMIT limit+1` → 동일 처리.

커서 인코딩: `base64url(json.dumps([created_at_iso, role_rank, id_str]))`. 디코드 실패/형식오류 → `400`
(단, 어떤 값이 와도 쿼리는 `session_pk==s.id`로 바인딩돼 **다른 세션에 닿지 못함** — cross-session 누출 0).
페이지 크기 기본 = **30**(상수, 추후 조정 가능). 초기 윈도 = 동일 30.

> **정직성 한 줄**: 이 페이징은 *시간순 안정 전순서*를 보장한다. 한 턴이 페이지 경계에 걸리면 user/assistant가
> 두 배치로 갈릴 수 있다(여전히 시간순 — 기능상 무해). 매우 드문 동일-`created_at` 교차턴(서로 다른 트랜잭션이
> 같은 마이크로초)에서는 role_rank가 묶음을 만들 수 있으나 `id`가 최종 타이를 깨 전순서는 유지된다(문서화 잔존).

## 설계

### 1. 백엔드 (`sessions.py` + `schemas.py`)

- `schemas.py`: `MessagePage(items: list[MessageOut], hasMore: bool, cursor: str | None)` 추가.
- `sessions.py`:
  - `_msg_order_key()` — `(Message.created_at, case(...role_rank...), Message.id)` 튜플 헬퍼(ORDER BY·커서 비교 공유, 드리프트 0).
  - `_encode_cursor(m) / _decode_cursor(s)` — base64url(json) 왕복. 디코드 실패 → `HTTPException(400)`.
  - `list_session_messages`를 `response_model=MessagePage`로. `s = await _get_session_or_404(...)`는 **그대로**(단일 게이트).
    limit 분기로 위 세 경로 구현. `limit+1` 트릭으로 `hasMore`. items는 항상 ascending.
- **쓰기 경로(`_persist`) 불변** — 마이그레이션·스키마 변경 0.

### 2. 프런트 API (`api.ts`)

- `getSessionMessages(id, opts?: { limit?: number; before?: string })` → `Promise<MessagePage>`(쿼리스트링 조립).
- `MessagePage` 타입 export. `SessionMessage`(아이템) 타입 유지.

### 3. 소비처 2곳

- **`SessionsView.tsx:51`**: `const page = await getSessionMessages(id); setMessages(page.items)` — limit 미지정(전량). 동작 동일.
- **`Playground.tsx` `loadSession`**: `getSessionMessages(sid, { limit: PAGE })` → `page.items` 매핑해 convos 복원 +
  **per-session 페이징 상태 저장**: `{ cursor: page.cursor, hasMore: page.hasMore }`. (기존 seq 레이스 가드·낙관적
  session_id 고정/롤백 그대로.)

### 4. "이전 메시지 더 보기" (Playground + DebugChat)

- **Playground 상태**: `olderByAgent: Record<agentId, { cursor: string | null; hasMore: boolean; loading: boolean }>`.
- **`loadOlder()`**: hasMore·!loading일 때 `getSessionMessages(sid, { limit: PAGE, before: cursor })` →
  매핑한 배치를 convos **앞에 prepend** → cursor/hasMore 갱신. loadSession과 동일한 **seq 레이스 가드** 적용(로드 중
  세션/에이전트 전환 시 폐기). 활성 세션이 DB 세션과 묶여 있을 때만 가능(라이브 신규 대화는 hasMore=false).
- **DebugChat**: 메시지 목록 **최상단**에, `hasMoreOlder`일 때 `Prompts`/`Button` "↑ 이전 메시지 더 보기"
  (loading 시 스피너). 클릭 → `onLoadOlder`.
- **스크롤 앵커링(핵심)**: prepend 전 `scrollHeight` 캡처 → prepend 후 `scrollTop += (newScrollHeight - oldScrollHeight)`로
  뷰포트 고정(맨 아래로 튀지 않게). **auto-scroll-to-bottom 효과(`686-692`)는 prepend에는 실행 금지** — append/stream에만.
  (prepend 플래그/ref로 구분.)

## RBAC/소유권 경계 체크리스트 (트리거: 세션 데이터 읽기 엔드포인트 수정)

1. **입구 열거**: 변경 입구는 읽기 하나 `GET /sessions/{id}/messages`(파라미터 추가)뿐. **새 create/update/
   delete/resume/lazy-create/외부 프로토콜 입구 0**. 메시지는 이미 owner-스코핑된 세션의 자식.
2. **입구별 소유권**: 읽기 — owner 스코프는 `_get_session_or_404(session, id, _own_scope(principal))`로 **이미
   SELECT-WHERE 융합**(058/067/070). 새 쿼리는 `session_pk == s.id`(s=소유 검증된 세션)에 커서 경계만 추가.
   **fetch-then-check 신규 도입 0**, cross-session 도달 0(쿼리가 s.id에 바인딩).
3. **단일 헬퍼**: `_get_session_or_404`가 소유권 단일 게이트로 **불변**. 정렬 키도 `_msg_order_key` 단일 출처.
4. **존재 비노출**: 세션 단위 404가 존재를 접음(068, 기존). 커서는 *이미 인가된 세션 내부*의 (created_at,role,id)라
   다른 세션 열거 불가(쿼리 s.id 바인딩). 타 세션 커서를 넣어도 그 값으로 **이 세션** 행만 필터 — 누출 0.
5. **검증 사다리 3런(비겹침)**:
   - ① **단위 시맨틱**: 정렬·커서 경계·`limit`·`hasMore`(limit+1 트릭)·role_rank 타이·빈/마지막 페이지·왕복 커서·malformed→400.
   - ② **실 인프라 통합(seed+restart)**: M개 메시지 세션 시드 → 초기 N + 반복 loadOlder로 **첫 메시지까지 정확히 1회씩** 수집(중복·누락 0) → 타 유저 세션은 여전히 404.
   - ③ **적대 타자(codex)**: "보장 목록의 여집합" — 커서 위변조·cross-session·off-by-one(최古 메시지 유실)·페이지 경계 중복/누락·turn 분할.
6. **자가-잠금 핀**: 정당한 본인이 자기 세션을 **첫 메시지까지 끝까지** 페이징(off-by-one으로 최古 1건 유실 없음) — ②에 포함.

## 완료 기준 (측정 가능)

- [ ] `MessagePage` 엔벌로프 + `limit`/`before` 파라미터, 정렬 키 `(created_at, role_rank, id)` 백엔드 구현.
- [ ] `getSessionMessages` opts 시그니처 + 소비처 2곳(SessionsView·Playground) 갱신, **admin tsc 0**.
- [ ] DebugChat 상단 "↑ 이전 메시지 더 보기" + 스크롤 앵커링(prepend 시 뷰포트 고정, 맨 아래로 안 튐).
- [ ] `verify_090` GREEN: 단위(정렬/커서/limit/hasMore/role타이/왕복/malformed) + 실인프라 통합(M개 시드→끝까지 중복·누락 0·타유저 404).
- [ ] 무회귀: `verify_session`류 기존 세션 테스트 GREEN, 적대 codex 통과/수용.
- [ ] 브라우저 검증: 다턴 세션 열기→상단 버튼 클릭→이전 묶음 prepend·스크롤 고정 시각 확인(Playwright 시스템 Chrome).

## 비목표

- `SessionsView` 페이징(관리자 검토는 전량 유지 — limit 미지정). 무한 스크롤 자동 트리거(버튼 클릭이 합의).
  쓰기 경로/스키마 변경. live(신규) 대화의 과거 로드(DB에 더 오래된 게 없음).

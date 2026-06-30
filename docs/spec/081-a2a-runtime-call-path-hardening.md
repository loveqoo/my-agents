# 081 — A2A 런타임 호출 경로 견고화 (071 후속): stale endpoint 자가치유 + 호출 폴백 + 오프라인 정직화

## 배경 (다른 에이전트 리포트 + 실측 검증)

증상(사용자): 외부 A2A 에이전트를 connect로 등록 → Playground 채팅 시 **"외부 에이전트 응답 오류 404"**.
071(카드 prefix-상대 resolution + probe 404 정직화)은 *등록 시점*의 카드 해석 버그를 닫았고
verify_071_live(카카오페이 시나리오)는 통과한다. 즉 이 404는 카드 prefix 버그가 아니라 **A2A
런타임 호출 경로의 별개 공백**이다. 리포트의 3개 주장을 코드로 모두 확인:

- **A** — `connect_agent`(agents.py:502-508)는 probe가 dead여도 `status="offline"`로 **등록 허용**,
  `_a2a_stream`(chat.py:417-430)은 `endpoint` 유무만 보고 status 무시하고 호출 → 사용자에겐 raw 404 프레임.
- **B** — `resync_agent`(agents.py:636)는 `last_sync="방금"`만 쓰고 **카드/endpoint 재해석 0**. 071 보정은
  `fetch_card` 시점에만 걸리므로 071 이전 등록분·원격 변경분의 stale endpoint는 resync로도 안 고쳐짐.
- **C** — `_stream_sse`(a2a_client.py:199-202)는 `status_code>=400`에 에러 프레임 후 종료, message/send 폴백 없음.

### 정직한 원인 분별 (액면 수용 금지)

A2A 표준에서 `message/stream`과 `message/send`는 **같은 endpoint URL**로 가는 JSON-RPC 메서드다(이 코드도
`a2a_stream(endpoint, …)`가 단일 endpoint에 method만 바꿔 POST). 따라서:

- **그 URL이 404면 send 폴백도 같은 URL이라 똑같이 404** → **C는 "stream 라우트를 별도로 둔 비표준 서버"
  에만 듣는 방어책**(표준 단일-endpoint 모델에선 저수율).
- 그러므로 사용자의 404의 **1순위 원인은 B**(저장된 endpoint가 틀림 — 071의 원래 카카오페이 버그와 동류).
  로컬 DB엔 외부 에이전트가 없어(시드 3개뿐) 사용자 환경의 stale 행을 직접 못 보지만, 구조상 B가 들어맞는다.

## 목표 (완료 조건 — 측정 가능)

**P1 (B, 1순위) — stale endpoint 자가치유 resync.**
1. connect/external 등록 시 카드 출처 URL(`body.url`/`body.cardUrl`)을 `config["cardUrl"]`에 저장.
2. `resync_agent`: `config["cardUrl"]`이 있으면 re-fetch_card → `_resolve_card_endpoint` 재실행 → endpoint·
   `config["card"]` 스냅샷·status(live/offline) 갱신 후 커밋. cardUrl 없으면(레거시) 기존 `last_sync`만 +
   "재연결 1회 필요" 사유. SSRF는 fetch_card·probe_endpoint가 각각 `guard_url` 선행(044/055 불변).
3. 즉시 우회: 사용자가 그 에이전트를 **한 번 재연결**(삭제+connect)하면 071 해석으로 올바른 endpoint 저장
   + cardUrl 채워져 이후 resync가 자가치유. (B는 재발 방지 + 레거시 자가치유 경로.)

**P2 (A) — 오프라인/호출실패 정직화.** `_a2a_stream`이 A2A 호출에서 4xx/끊김 에러 프레임을 받으면 raw
`외부 에이전트 응답 오류 404` 대신 **행동가능 안내**("엔드포인트에 도달 못 함 — 재동기화(자가치유) 또는
재연결하세요")를 덧붙인다. 045 철학 유지(등록은 허용, 호출 status만 정직). 등록 자체는 안 막는다.

**P3 (C) — stream 404/405 → message/send 폴백(방어).** `a2a_stream`이 streaming POST의 **초기 응답**이
404/405(route/method 부재, 본문 전이라 텍스트 미방출)면 **같은 endpoint로 message/send 1회 폴백**. 부분
스트림 후엔 폴백 금지(404는 본문 전이라 안전). 표준 단일-endpoint에선 동일 실패일 수 있음을 정직 기록 —
별도 stream 라우트 서버 구제용. 그 외 4xx/5xx는 기존대로 에러 프레임.

## 설계

### `agents.py`
- `connect_agent`/`register_external_agent`: 빌더에 카드 출처 URL 전달 → `cfg["cardUrl"] = card_url`.
  (`_build_external_agent`/`_build_code_agent_from_card`에 `card_url` 인자 추가, cfg에 저장.)
- `resync_agent`: cardUrl 분기. 있으면 `agent_card.fetch_card(cardUrl)` → `probe_endpoint` → endpoint·
  card·status 갱신(connect와 동일 해석, 단 새 Agent 생성이 아니라 기존 행 in-place 갱신 — id/소유·버전 보존).
  fetch 실패(ValueError)면 status="offline"로 정직 표기하고 last_sync 갱신(등록은 유지).

### `chat.py`
- `_a2a_stream`: 에러 프레임 수신 시 메시지에 actionable hint 부가(텍스트가 한 줄도 안 온 채 에러로 끝났을 때만).

### `a2a_client.py`
- `_stream_sse`: 초기 `resp.status_code in (404, 405)`면 에러 프레임 대신 **재시도 신호**(`{"_fallback": status}`)
  를 yield하고 종료. 그 외 `>=400`은 기존 에러 프레임.
- `a2a_stream`: streaming 분기에서 `_fallback` 신호를 가로채면 `_send_single`로 1회 폴백(같은 endpoint·headers).
  폴백도 실패하면 그 에러 프레임을 그대로 전달. 보안 불변: endpoint/guard/cap 동일 경로 재사용.

### 경계 (learning 064/066 — 신뢰경계 유지)
- resync re-fetch는 **저장된 cardUrl**(우리가 connect 때 사용자 입력으로 받아 정규화·guard 통과한 값)에서만.
  request Host 등 외부 파생 아님 → host-poisoning 무관. fetch_card/guard_url가 사설/루프백/userinfo 거부 유지.

## 검증 사다리 3런 (069 항목 5, 비겹침)

1. **단위 시맨틱**:
   - resync re-resolve: prefix-상대 카드를 주는 mock으로 stale endpoint(`…/a2a`)를 올바른 `…/prefix/a2a`로
     교정·cardUrl 없으면 no-op+last_sync.
   - C 폴백: stream POST에 404, send POST에 200(텍스트) 주는 mock → 폴백으로 텍스트 수신. 단일-endpoint
     404(둘 다 404)면 에러 프레임(폴백해도 동일) 무회귀.
   - A: 에러 프레임에 hint 부가 술어(텍스트 온 뒤 에러엔 미부가).
2. **실 인프라 통합**(verify_071_live 패턴 — 스레드 A2A 서버): connect 등록 → DB endpoint 손상 →
   resync → 교정 확인 → chat 텍스트 수신. 045/057/060/063/071 무회귀.
3. **적대 codex**(rung 3): resync re-fetch가 SSRF/host-confusion 새 입구를 여나? 폴백이 텍스트 이중방출·cap/guard
   우회·토큰 에코를 하나? offline hint가 내부정보 누출하나? "보장 목록의 여집합".

## RBAC 체크리스트 적용 여부
**미적용** — 트리거 객관신호(user_id·테넌트 컬럼·`_own_scope`/`_visible_or_404`/`_assert_*owns`) 없음.
네트워크 endpoint resolution + liveness + 전송 폴백이라 소유권 경계 무관(069 트리거, self-judgment 아님).
resync는 기존 행 in-place 갱신이라 새 소유 경계·입구 없음.

## 검증 결과 (3런 그린)

- **단위**(`tests/verify_081_unit.py`) ALL PASS 7 — C 폴백 3(stream404→send 텍스트 / 단일-endpoint 404
  이중방출 없음 / 500 폴백 안 함) + A 안내 술어 2(무방출 에러에 부가 / 부분스트림 뒤 미부가).
- **라이브 통합**(`tests/verify_081_live.py`) ALL PASS 8 — connect가 cardUrl 저장·초기 endpoint prefix 보존
  → DB endpoint 손상 → resync 재fetch·재resolve로 교정 → status online → 교정 endpoint로 호출 텍스트 도달
  → 레거시(cardUrl 없음) no-op+last_sync. 실 DB(SessionLocal)+스레드 A2A 서버.
- **회귀**: 045·057·060·063(unit/live)·071(card/live)·042 모두 PASS(무회귀).

### 적대 codex(rung 3) 지적 처리 (정직 기록)

- **F1 — stream 404/405 분기의 무경계 `aread()`**(거대 에러 바디 버퍼링). → **수정**: 폴백은 같은
  endpoint로 `_send_single`을 새로 열어 본문 불필요 → 본문을 읽지 않고 `async with client.stream`이
  미소비 응답을 닫게 함(무경계 읽기 제거, memory: cap-the-raw-source). 공유 `>=400` 경로는 무회귀로 보존.
- **F2 — resync의 config 전체 재할당이 동시 편집을 last-writer-wins로 덮을 수 있음.** → **수용(기록)**:
  앱 전역 JSONB 쓰기가 낙관적 락 없는 동일 모델(replaceAgent·버전 저장 등)이고, resync는 관리자 수동
  액션(저빈도)이라 창이 작다. 081 단독으로 앱 전역 동시성 모델을 바꾸지 않음 — 별도 과제로 둠.
- **F3 — `probe_endpoint`가 try 밖이라 raise 시 500**(codex 조건부). → **성립**: `probe_endpoint`는
  total(`except Exception: return False`, "절대 raise 안 함")이라 raise 경로 없음. connect_agent도 동일 구조.
- 핵심 보장(SSRF/host-confusion·폴백 이중방출/누출·토큰 에코·offline hint 누출)은 codex가 성립 확인.

## 완료 체크
- [x] P1 cardUrl 저장(connect/external) + resync 자가치유(re-fetch→re-resolve→endpoint·card·status 갱신)
- [x] P2 `_a2a_stream` 오프라인/4xx 행동가능 안내(텍스트 무방출 시만)
- [x] P3 `a2a_stream` stream 404/405 → message/send 1회 폴백(부분스트림 후 금지)
- [x] 3런 검증(단위 매트릭스 + 라이브 통합 + 적대 codex) 그린, 045/057/060/063/071 무회귀

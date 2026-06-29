# 060 — A2A 에이전트를 플레이그라운드에서 테스트 가능하게 (endpoint 정규화 + 로컬테스트 UX)

> 상태: **초안(AI 작성, 인간 검토 대기)**. 작업 방식 = CLAUDE.md 6단계 루프.

## 1. 문제 (재현으로 확정)

사용자가 A2A로 등록한 에이전트를 플레이그라운드에서 채팅하면
**"URL은 http(s) 절대 URL이어야 합니다"** 에러가 뜬다. 코드 함수로 결정적 재현한 결과 두 실패 모드:

| 모드 | 카드 `url` | 등록 | 채팅(guard_url) |
|---|---|---|---|
| **1 (사용자 보고)** | 스킴 없음 `127.0.0.1:9000/a2a` | ✅ 통과 (`validate_card`가 문자열만 검사) | ❌ `URL은 http(s) 절대 URL이어야 합니다` (net_guard.py:43) |
| **2 (다음 벽)** | 루프백 `http://127.0.0.1:8000/_remote/a2a` | ✅ 통과 | ❌ 사설 대역 차단 → `A2A_ALLOWED_HOSTS` 필요 |
| 2b | 루프백 + allowlist | ✅ | ✅ 통과 |

### 근본 원인
- **모드 1**: `agent_card.validate_card`(agent_card.py:30-32)가 서비스 `url`이 *절대 http(s) URL*인지
  검사하지 않는다 — "비어있지 않은 문자열"이면 통과. 그래서 스킴 없는/상대 url이 등록은 되고,
  실제 호출 시점(`a2a_client.a2a_stream` → `guard_url(endpoint)`, a2a_client.py:145)에 비로소 거부된다.
  실패가 *등록*이 아니라 *채팅*에서, 모호한 문구로 늦게 표면화.
- **모드 2**: 로컬/사설 A2A(127.0.0.1 등)는 SSRF 가드 기본 차단. dev mock 카드들(mock_remote.py)이
  바로 `http://127.0.0.1:8000/_remote/a2a`를 광고하므로 *로컬 A2A 테스트를 하는 누구나* 이 벽에 닿는다.
  (이번 세션에서 차단 메시지는 host echo + `A2A_ALLOWED_HOSTS=<host>` 예시로 이미 개선됨.)

### 등록 경로 (현행)
`POST /agents/connect`(스펙 057)는 URL 하나(카드 URL)를 받아 `fetch_card`로 카드를 가져오고,
카드의 `url` 필드를 `endpoint = _clip(card.get("url"), 400)`으로 저장(agents.py:380/421). 사용자가
endpoint를 직접 타이핑하는 칸은 없다 — 카드의 `url`이 곧 호출 endpoint.

## 2. 합의된 방향 (2026-06-29)

- **모드 1 = 관대 정규화** (사용자 선택). 자동 추측이되 **보안은 불변** — 정규화된 url에 `guard_url`이
  그대로 돌아 사설 대역(모드 2)을 여전히 막는다. 정규화는 "틀린 메시지(모드 1)"를 "성공" 또는
  "맞는 메시지(모드 2)"로 바꿀 뿐, 가드를 우회하지 않는다.
- **범위 = 스킴 + 로컬테스트 UX 둘 다** (사용자 선택).

## 3. 설계

### Part A — 서비스 url 관대 정규화 (모드 1)
`net_guard.py`에 순수 함수 추가:
```python
def normalize_http_url(raw: str, *, base: str | None = None) -> str:
    """A2A 서비스 url을 절대 http(s) URL로 정규화. 못 하면 ValueError(조치 메시지).
    - 이미 http(s):// → 그대로
    - '/'로 시작(진짜 상대경로) + base 있음 → urljoin(base, raw)
    - 스킴 없는 host:port[/path] → 'http://' 전치(dev 관대, curl/브라우저 관례)
    결과를 urlparse해 scheme∈{http,https} & hostname 존재를 단언, 아니면 ValueError."""
```
- `agent_card.fetch_card`: `validate_card(data)` 직후 `data = {**data, "url": normalize_http_url(data["url"], base=candidate)}`
  로 카드의 서비스 url을 정규화해 반환 → 저장 endpoint가 절대 http(s). (connect의 external·code 두
  빌더 모두 `card.get("url")`을 쓰므로 한 곳 수정으로 양 분기 커버.)
- 정규화 불가(빈 값·`ftp://`·`://`·호스트 없음)면 `fetch_card`가 ValueError → connect가 400 +
  "서비스 url을 절대 http(s) URL로 해석할 수 없습니다(받은 값: '...'). 카드의 url을
  'http://host:port/path' 형태로 지정하세요." (등록 시점 조기·명확 실패.)
- `register_code_agent`(body.endpoint 직접, SDK 경로)도 같은 함수로 정규화(일관성, base 없음).

### Part B — 로컬/사설 테스트 UX (모드 2)
- **B1 (완료, 이번 세션)**: 채팅 SSRF 차단 메시지에 host echo + `A2A_ALLOWED_HOSTS=<host>` 복붙 예시.
- **B2 연결 모달 사전 안내**: `ConnectAgentModal`(AgentsView.tsx)에 한 줄 힌트 — "로컬/사설
  endpoint(127.0.0.1·10.x·192.168.x)는 서버 `A2A_ALLOWED_HOSTS`에 호스트를 등록해야 호출됩니다."
  (벽에 닿기 전에 학습.)
- **B3 플레이그라운드 에러 가시화**: A2A 채팅이 에러 프레임을 줄 때 그 문구가 채팅에 그대로
  노출되는지 확인(현행 `_a2a_stream`이 `{'error': ...}` yield). 노출 안 되면 Alert로 띄운다.

### Part C — E2E 검증 자산
- `tests/verify_060_a2a_playground.py`: mock 외부 A2A 카드(well-known)를 `/agents/connect`로 등록 →
  `A2A_ALLOWED_HOSTS=127.0.0.1` 하에 채팅 → **실제 mock A2A 응답 프레임 수신**을 단언(전 경로 green).
  라이브 인프라(DB+서버) 필요 — 사용자가 외부라 라이브 어려우면 핵심은 정규화 단위테스트로 커버하고
  E2E는 내가 이 호스트에서 실측(메모리 'Verify UI in browser proactively').

## 4. 완료 조건 (측정 가능)

- **C1**: 스킴 없는 `host:port/path` 카드 url → 등록이 `http://host:port/path`로 정규화·저장(`endpoint.startswith("http")`).
- **C2**: `/path` 상대 카드 url → 카드 base origin으로 resolve(절대 http(s)).
- **C3**: 이미 절대 `https://...` → 불변.
- **C4**: 정규화 불가(`ftp://x`·빈 값·`://`·호스트 없음) → 등록이 400 + 조치 메시지(http(s) 언급).
- **C5 (보안 불변)**: 정규화된 사설 url도 채팅 `guard_url`이 모드-2 메시지로 차단(`SsrfBlocked`).
- **C6 (E2E)**: mock 외부 A2A 등록 + allowlist → 채팅이 비어있지 않은 A2A 응답 수신.
- **C7 (UI)**: 연결 모달에 사설-endpoint allowlist 힌트 노출.
- **C8 (UI)**: A2A 채팅 에러가 플레이그라운드에 노출(모호하지 않은 문구).

## 5. 검증 (타자 우선)
- 단위: `tests/verify_060_*`(C1~C5 정규화·가드 무회귀).
- 통합/E2E: 이 호스트 라이브 부팅으로 C6(register→chat) 실측 + 브라우저 스샷으로 C7/C8.
- 적대: codex 리뷰 — 정규화가 SSRF 가드를 우회시키지 않는지(C5), urljoin/스킴 전치의 엣지
  (`//host`·`http:/x`·이중스킴·포트만·IPv6 `[::1]`), 조치 메시지가 비밀값 누출 안 하는지.

## 6. 범위 밖
- SSRF allowlist를 dev에서 loopback 기본 허용으로 바꾸기(보안 기본값 유지 — opt-in 존속).
- A2A 카드 서명/신뢰 검증(별 스펙).
- stdio MCP 등 비-A2A 경로.

# 042 — A2A 실호출 (외부 에이전트 런타임, 026 2차)

> 로드맵 P5-b(#11, 마지막 항목). 1차는 스펙 026(카드 등록·표시). 본 스펙은 등록된 외부
> 에이전트를 **실제로 호출해 응답을 받는** A2A 런타임 전송 계층을 추가한다.
> 관련: 026(범위 정의·SSRF 유예), 009(`_remote_stream` 코드-에이전트 패턴), 041(검증 사다리),
> learning 028(서버측 URL fetch 보안), [[verification-ladder-three-rungs]].

## 배경·문제

외부(`source="external"`) 에이전트는 현재 `chat.py:_external_notice_stream`이 **"런타임 호출은
2차" 안내 1프레임**만 흘리고 끝난다. A2A 협업이 이 플랫폼의 코어 가치인데(왜-멀티에이전트 메모리),
외부 에이전트는 등록·카드 표시까지만 되고 **실제로 말을 걸 수 없다.**

A2A는 JSON-RPC 2.0(`message/stream` 스트리밍 / `message/send` 단건) + SSE다. 코드-에이전트의
`_remote_stream`(`POST {messages}` → `{text}` SSE)과 **포맷이 다르다** → 재사용 불가, 새 전송 계층이 필요.

## 비범위

- 멀티턴 A2A 세션(`contextId`/`taskId` 이어가기)·push notification·input-required 재개: 본 스펙은
  **단일 턴 요청→스트리밍 응답**까지. (멀티턴 컨텍스트 보존은 후속.)
- A2A 인증 스킴 OAuth2/OIDC/mTLS 협상: 카드 `securitySchemes` 전수 대응은 비범위. 저장된 토큰을
  `Authorization: Bearer`로 싣는 것까지(가장 흔한 케이스).
- 외부 에이전트로의 도구/메모리 위임(우리 MCP를 A2A로 노출): 별도 스펙.

## 목표(완료 조건, 측정 가능)

1. `source="external"` 에이전트에 `/chat` → 등록된 카드 `url`(A2A 엔드포인트)로 **JSON-RPC
   `message/stream` 호출** → SSE 응답에서 텍스트를 뽑아 우리 SSE(`{text}`)로 재전송. trace·영속까지.
2. 카드 `capabilities.streaming=false`면 `message/send`(단건)로 폴백, result에서 텍스트 추출.
3. **SSRF 가드**: outbound URL의 호스트를 IP로 resolve해 사설/루프백/링크로컬/메타데이터 대역이면
   **차단**(기본). 단 호스트가 `A2A_ALLOWED_HOSTS`(쉼표구분 allowlist, 예 `127.0.0.1,localhost`)에
   있으면 사설대역이라도 허용 → 127.0.0.1 mock 동작. 이 가드는 신규 `a2a_client`와 기존
   `agent_card.fetch_card` **양쪽**에 적용(026에서 유예한 빚 청산).
4. 저장된 토큰을 복호화해 Bearer로 전송(레거시 마스킹 `•`면 헤더 생략 — `_remote_stream` 동일 규칙).
5. mock A2A JSON-RPC 서비스(`POST /_remote/a2a`)가 `message/send`·`message/stream`을 구현 →
   라이브 외부 에이전트 없이 **결정적** 통합 검증.
6. 검증 3 rung 모두 통과: 단위(파서·SSRF), 실 DB 통합(등록→chat→영속), 적대 리뷰.

## 설계

### A. SSRF 가드 — `net_guard.py`(신규, 공유)

서버측 outbound fetch는 보안 표면(learning 028). free fix는 이미 있음(사이즈캡·타임아웃·스킴검증).
**사설대역 차단은 트레이드오프**(127.0.0.1 dev mock을 깸)라 026에서 유예 → 실호출이 일어나는 지금 청산.

```
def guard_url(url) -> None:            # http(s)·호스트 resolve·IP 대역 검사. 위반시 ValueError.
    parse → scheme in (http,https) 강제
    host가 A2A_ALLOWED_HOSTS(쉼표구분) 에 있으면 → 즉시 통과(dev allowlist)
    host resolve: socket.getaddrinfo(host) → 모든 IP
    각 IP가 ipaddress로 loopback/private/link_local/reserved/multicast → 차단
```

- `fetch_card`(등록 시점, admin 인가)·`a2a_client`(런타임 호출) 둘 다 연결 직전 `guard_url` 호출.
- **알려진 한계(스펙 §7 빚)**: resolve→connect 사이 DNS 재바인딩(TOCTOU). 진짜 차단은 resolved
  IP 핀(httpx transport 커스텀). 본 스펙은 resolve-and-check까지(admin 등록 경계라 현실적 바),
  IP 핀은 빚으로 명문화.

### B. A2A 클라이언트 전송 — `a2a_client.py`(신규)

```
async def a2a_stream(endpoint, token, user_text, *, streaming=True) -> AsyncIterator[dict]:
    guard_url(endpoint)
    body = jsonrpc("message/stream" if streaming else "message/send", {
        "message": {"role":"user","parts":[{"kind":"text","text":user_text}],
                    "messageId": uuid, "kind":"message"}})
    headers = {"Content-Type":"application/json"} + Bearer(decrypt(token)) if not masked
    streaming: httpx.stream POST → SSE data: 줄마다 JSONRPCResponse 파싱
       result kind별 텍스트 추출:
         - Message(parts[].kind=="text")
         - Task(status.message.parts)
         - status-update(status.message.parts; final 플래그로 종료)
         - artifact-update(artifact.parts)
         - error(JSONRPCResponse.error) → {error} yield
    non-streaming: 단건 JSONRPCResponse → result에서 동일 추출
    yield {"text": ...} / {"error": ...}
```

- 사이즈캡(누적 응답 상한)·타임아웃·`status>=400`시 본문 미에코(자격증명 누출 방지, `_remote_stream` 규칙).
- 텍스트 추출은 **포맷 관대**(parts 없거나 kind 다르면 스킵, 크래시 금지).

### C. chat.py 배선

`_external_notice_stream` → `_a2a_stream(ctx, body, user_text, user_id)`로 교체:
세션 프레임 → `a2a_client.a2a_stream(ctx["endpoint"], ctx["token"], user_text, streaming=카드값)`
순회하며 `{text}`/`{error}` 재전송·누적 → trace(`a2a:True`, `promptRef=ext_agent_id`) → 비오류시
`_persist` → done. `_remote_stream`과 같은 골격(라우터 분기 `source=="external"`는 유지, 함수만 교체).

### D. mock A2A 서비스 — `mock_remote.py` `POST /_remote/a2a`

JSON-RPC 처리: `method=="message/send"` → 단건 JSONRPCResponse(result=Message, 결정적 날씨 응답).
`method=="message/stream"` → SSE, status-update 이벤트 여러 개(텍스트 청크) + `final:true` 종료.
입력 `params.message.parts[].text`를 받아 결정적 응답(같은 입력=같은 출력). 카드의 `url`은 이미
`http://127.0.0.1:8000/_remote/a2a`를 광고 중 → 엔드포인트만 채우면 됨.

## 검증(3 rung 사다리 — learning 040)

1. **단위(시맨틱) `tests/verify_042_a2a_client.py`**: a2a_client 파서에 canned SSE/단건 주입 →
   Message/Task/status-update/artifact-update/error 각각 텍스트·에러 추출 정확. `guard_url`이
   사설/루프백 IP 차단(env off) & 허용(env on) & 공인 IP 통과. 마스킹 토큰시 헤더 생략.
2. **실 DB 통합 `.dev/probe_042_a2a_integration.py`**: 실 앱+실 DB. mock `/_remote/a2a`를 url로
   외부 에이전트 등록 → `POST /{id}/chat` → SSE `{text}` 프레임 수신·Message 영속·trace `a2a:True` 확인.
   (env `A2A_ALLOW_PRIVATE=true`로 127.0.0.1 mock 허용.)
3. **적대 리뷰(서브에이전트)**: "SSRF 가드 우회·토큰 누출·무한 응답(미캡)·악성 SSE 크래시·env 미설정
   프로덕션서 사설 호출 가능?" — 불변식 여집합 탐색.

## 보안 결정(합의 완료 2026-06-27 — 호스트 allowlist)

SSRF 사설대역 차단을 **기본 ON**(프로덕션 안전)으로 하되, `A2A_ALLOWED_HOSTS`(쉼표구분 호스트
allowlist, 예 `127.0.0.1,localhost`)에 명시한 호스트는 사설대역이라도 통과시킨다. dev는 이 env로
mock(127.0.0.1)을 허용한다. 026에서 유예한 트레이드오프를 이렇게 청산한다.
(검토 대안: env 전역 opt-in / 차단 안 함 — allowlist가 prod에서 우발적 사설 노출을 가장 좁게 막음.)

## 검증 결과(3 rung — learning 040)

- **rung 1 단위 `tests/verify_042_a2a_client.py` 44/44**: 파서(Message/Task/status-update/artifact-update,
  형식 관대성)·error 우선·final 종료·SSRF(사설/CGNAT/IPv6 루프백·매핑·ULA/0.0.0.0 차단, allowlist 통과,
  공인 통과)·토큰 마스킹·decrypt 실패→error 프레임(미크래시).
- **rung 2 통합 `.dev/probe_042_a2a_integration.py` 전부 통과**: uvicorn 실서버 실 소켓 라운드트립으로
  message/stream·message/send 두 경로 + 영속 + trace(a2a:True) + SSRF 차단(allowlist 밖 사설→error·무영속).
- **rung 3 적대 리뷰(서브에이전트)**: 아래 결함 발견·수정.

### 적대 리뷰로 수정한 것
- **H1/H2(바운드 무력)**: 단건은 `resp.content`가 전체 선버퍼링, 스트림은 `aiter_lines`가 개행 없는
  입력 무한 버퍼링 → 양쪽 다 **raw 바이트 누적 캡**(`_capped_lines`/stream)으로 교체. DoS 차단.
- **H3(미프레임 크래시)**: `crypto.decrypt`가 키 회전 시 RuntimeError를 try 밖에서 던져 스트림이
  done 없이 끊김 → 토큰 빌드를 try 안으로, 광역 except로 **항상 error 프레임화**(제너레이터 무-raise 보장).
- **M1(denylist 누락)**: 개별 플래그 denylist가 CGNAT 100.64/10을 통과 → **`not is_global`** 단일 기준으로
  교체(문서·벤치마킹·CGNAT까지 포괄). `follow_redirects=False` 명시(리다이렉트 SSRF 우회 차단).
- **L1**: 공백-only 응답 영속 방지(`full.strip()`).

## §7 빚·한계

- **DNS 재바인딩 TOCTOU(C1/C2, 미해결 빚)**: `guard_url`은 resolve-and-check까지 — resolve→connect
  사이 재바인딩으로 사설/메타데이터 대역에 닿을 여지가 남는다(httpx가 connect 때 재resolve). 진짜
  차단은 **resolved-IP 핀**(커스텀 transport로 검사한 IP에만 연결)이 필요. **외부 에이전트 등록은
  admin 인가 경계**라 위협이 제한적이고, IP 핀은 독립적 크기 → 별도 후속. (적대 리뷰는 critical로
  평가했으나, 등록 경계 + redirects 비활성 + 공인대역만 통과로 현실 노출을 좁혔다.)
- **allowlist 포트 무시(M2)**: `A2A_ALLOWED_HOSTS`는 호스트 단위 → 그 호스트의 모든 포트 허용. dev
  편의(127.0.0.1 mock)엔 의도된 범위. 운영서 실호스트 추가 시 host:port 단위가 필요하면 후속.
- **외부 error.message passthrough(L2)**: 외부 에이전트의 JSON-RPC error.message를 우리 프레임에
  옮긴다(`외부 에이전트 오류:` 접두). 공격자가 자기 에러 문구를 통제 — 우리 비밀/본문 누출은 아님(저severity).
- 멀티턴 A2A 컨텍스트(contextId/taskId)·input-required 재개·push notification: 후속 스펙.
- OAuth2/OIDC/mTLS 인증 스킴: Bearer만. 카드 securitySchemes 전수 대응 후속.

# 032 — A2A 실호출 회고 (스펙 042, P5-b · 로드맵 마지막)

> 지배 스펙: `docs/spec/042-a2a-runtime-call.md`. 관련 learning: [[041-bounded-knob-must-cap-the-raw-source]],
> [[040-real-infra-integration-catches-glue-and-deployment-drift]], 028(서버측 URL fetch 보안),
> 회고 [[031-hil-approval-gating]]. 026(1차 카드 등록)의 2차.

## 무엇을 했나

- 외부(`source="external"`) 에이전트의 `_external_notice_stream`("2차 예정" 안내)을 **실 A2A 런타임
  호출**로 교체. 새 전송 계층 `a2a_client.py`(JSON-RPC `message/stream`/`message/send` + SSE 파서),
  chat.py `_a2a_stream`(세션→스트림 재전송→trace(a2a:True)→영속, `_remote_stream` 골격 재사용).
- **026에서 유예한 SSRF 빚 청산**: 공유 `net_guard.guard_url`(호스트 IP resolve → `not is_global`
  차단, `A2A_ALLOWED_HOSTS` allowlist로 dev 127.0.0.1 mock 허용). `fetch_card`·`a2a_client` 양쪽 적용.
- mock A2A JSON-RPC 서비스(`/_remote/a2a`) 추가 → 카드가 이미 광고하던 url을 실제 응답으로 채움(결정적).

## 사람과 합의한 한 분기

SSRF 사설대역 차단은 트레이드오프(127.0.0.1 mock을 깸)라 026에서 유예했다. 실호출이 일어나는
지금 청산하며 **AskUserQuestion으로 방식을 물었다** → 사용자가 **호스트 allowlist** 선택(env 전역
opt-in/차단 안 함 대신). "큰 결정은 사람과"를 지킨 지점 — 기본 차단 + 명시 호스트만 통과가 prod
우발 노출을 가장 좁게 막는다.

## 검증을 또 *사다리*로 (41의 패턴 재사용)

1. **단위(verify_042, 44/44):** 파서 형식 관대성·SSRF 대역·토큰 마스킹·decrypt실패→프레임. *논리* 박제.
2. **실서버 통합(probe_042):** ASGITransport로는 a2a_client의 outbound 호출이 in-process 앱에 안 닿아
   (실 소켓 필요) **uvicorn을 실제로 띄웠다**. stream·send 두 경로 라운드트립·영속·SSRF 차단. *글루* 박제.
3. **적대 리뷰(서브에이전트):** 불변식 여집합 — 아래 진짜 결함 4종 발견.

## 적대 리뷰가 잡은 것 — "있는 줄 알았던 캡이 실제로 안 막음"

- **H1/H2(바운드 무력):** 단건은 `resp.content`가 슬라이스 *전에* 전체를 버퍼링, 스트림은
  `aiter_lines`가 개행 없는 입력을 무한 버퍼링 → `MAX_RESPONSE_BYTES`가 둘 다 무력. **raw 바이트
  누적 캡**으로 교체. 단위·통합 둘 다 happy-path만 봐서 못 잡았고, 목도 happy-path라 거짓 초록을 줬다.
- **H3(미프레임 크래시):** `crypto.decrypt`의 RuntimeError(키 회전)가 `try` 밖에서 터져 스트림이
  done 없이 끊김 → 토큰 빌드를 try 안으로 + 광역 except로 **제너레이터 무-raise 보장**.
- **M1(denylist 누락):** 개별 플래그(is_private 등)가 CGNAT 100.64/10을 통과 → **`not is_global`** 단일
  기준으로 교체(누락 대역 포괄). IPv6 매핑·ULA·0.0.0.0도 한 번에.
- **C1/C2(DNS 재바인딩):** resolve→connect TOCTOU는 IP 핀이 필요 → admin 등록 경계 + redirects 비활성
  근거로 **명시적 빚(§7)**으로 남김(적대자는 critical 평가, 위협모델로 좁힘을 기록).

## 작게 헛디딘 것

- **크로스 이벤트루프:** probe가 메인 루프에서 app의 `SessionLocal`(uvicorn 스레드 루프 바인딩)을 써서
  "attached to a different loop". → probe 전용 엔진을 따로 만들어 격리. 하니스 한정, 코드 버그 아님.
- **세션 id 오해:** probe가 보낸 raw sessionId가 매칭 안 돼 서버가 `sess-xxxxxx`를 새로 발급 → 내
  raw id로 조회해 영속 검사 실패. 반환된 `session` 프레임 값으로 조회해야 했다(측정 오류, memory probe-deeper).

## 다음에 가져갈 것

- **"캡/리밋이 *원천*을 막는지" 확인**: post-buffer 슬라이스·프레임드 라인 카운트는 캡이 아니다(learning 041).
- 외부 호출 제너레이터는 **절대 raise 안 함**을 불변식으로(모든 실패 → error 프레임 + done). decrypt 같은
  비-HTTP 예외도 광역 except로.
- SSRF는 **denylist 대신 `not is_global` allowlist-inversion** 기본. 개별 플래그는 누락 대역을 남긴다.
- 로드맵 P0~P5 12항목 **전부 완료** — 다음 작업은 Scaffolding에서 새로 정한다.

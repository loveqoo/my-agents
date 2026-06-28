# 040 — 원격 어드민 로그인 실패: http 위의 Secure 쿠키 (라벨 오판 + curl green 함정)

스펙 아님 — 트러블슈팅 회고. 원격(Tailscale) 사용자가 "어드민 로그인 안 됨"을 보고했고,
서버는 모든 자가검증에서 건강(curl 라운드트립 200)했는데 브라우저에선 로그인이 안 잡혔다.
근본 원인은 **세션 쿠키의 `Secure` 플래그 + 평문 http 접속**이었다.

## 무슨 일이 있었나

증상: 원격 사용자가 admin SPA에서 로그인하면 POST는 204를 받지만 세션이 안 잡혀
**다시 로그인 폼으로 튕김**. 서버측 curl 라운드트립(login→204+Set-Cookie, `/users/me`→200)은
완전히 건강. "서버는 멀쩡한데 브라우저만 실패"라는 어긋남.

진단: 쿠키에 `Secure`가 붙어 있었다(`CookieTransport` 기본 + `AUTH_COOKIE_SECURE` 미설정→
기본 true). 브라우저는 **Secure 쿠키를 HTTPS에서만 저장**한다(localhost는 secure context로 예외).
사용자가 **평문 http(`http://100.72.45.58:5173`)**로 접속하니 브라우저가 쿠키를 *silently drop* →
로그인이 안 잡힘. curl은 Secure를 강제하지 않아 서버 라운드트립은 통과했다.

## 두 개의 오판

### (1) 진단 단계 — "(TLS over TCP)" 라벨을 TLS 종료로 오독
처음에 "그럼 https로 접속하면 Secure 쿠키가 저장돼 해결"이라고 **자신 있게 안내했고, 틀렸다.**
`tailscale serve status`가 MagicDNS 엔드포인트를 "(TLS over TCP)"로 라벨링한 걸 보고 Tailscale이
TLS를 종료(terminate)해 준다고 가정했다. 사용자가 "https는 접속 안 됨"이라고 하자 그제서야
`serve status --json`을 봤다 — `"TCPForward": "127.0.0.1:5173"`만 있고 **`TerminateTLS`가 없었다.**
즉 **raw TCP 패스스루**였다. vite는 평문 HTTP만 말하므로, https로 들어온 TLS ClientHello를
vite가 평문 바이트로 받아 **핸드셰이크가 깨진다** → https 접속 자체가 불가.

라벨(추상화의 이름)이 실제 동작과 달랐다. **추측 대신 1차출처(`--json`)를 먼저 봤다면** 잘못된
https 안내를 안 했을 것이다. (memory: probe-deeper-before-concluding / "추측 말고 동일 사례 확인".)

### (2) 검증 단계 — curl green이 브라우저 실패를 못 잡았다
서버측 curl 라운드트립이 통과하니 "서버는 건강"이라 결론냈는데, 그 green은 **거짓**이었다.
curl은 `Secure` 플래그를 무시하고 어떤 스킴에서도 쿠키를 보낸다. **실제 클라이언트(브라우저)의
제약을 검증 도구(curl)가 재현하지 못한** 것이다. → learning 051로 추출.

## 고침

`AUTH_COOKIE_SECURE=false`를 루트 `.env`에 추가하고 api 서버 재기동(살아있는 프로세스 env는
파일 수정으로 안 바뀜 — learning 049). `.env.example`에도 문서화(원격 http 접속 시 필요, WireGuard
터널이 암호화하니 사설 tailnet 한정 안전, 공개 노출 시엔 true 유지+진짜 TLS 종료). 검증:
Set-Cookie에서 Secure 사라짐(쿠키잔 Secure 컬럼 FALSE), 평문 http 라운드트립 login→204→
`/users/me`→200, **사용자 브라우저 로그인 성공 확인**.

대안(택하지 않음): Tailscale을 `--tls-terminated-tcp`로 재설정 → 진짜 https. 하지만 지금 되는
http 접속이 끊기고(https 강제), 타넷 HTTPS 인증서 활성에 의존. 사용자가 이미 http로 잘 접속 중이라
덜 침습적이고 의존 없는 쿠키 플래그 쪽을 택했다.

## 다음에 다르게

- **접속 토폴로지가 얽힌 진단은 라벨이 아니라 1차출처(설정 dump)부터** 본다. "(TLS over TCP)"
  같은 요약 라벨을 동작으로 단정하지 않는다. `--json`에 `TerminateTLS`가 있나로 패스스루/종료를 가른다.
- **인증·쿠키·CORS처럼 브라우저 정책이 끼는 경로는 curl green을 신뢰하지 않는다.** 검증 도구가
  실 클라이언트 제약(Secure/SameSite/mixed-content)을 재현하는지 본다(learning 051).
- 원격 사용자라 최종 확인(브라우저 로그인)은 사용자만 할 수 있었다 — 그 전까지 헤더 레벨로
  최대한 좁혀 두고(Secure 제거 실증) 사용자 확인은 마지막 1회로 끝냈다.

관련: learning 051(검증 도구 충실성), 049(살아있는 프로세스 env=재기동 필요),
[[restart-dev-servers-for-tailscale]](Tailscale 접속·프록시), 035(초록 verify≠견고).

# 018 — 어드민 same-origin API 프록시 (회고)

스펙: [027](../../docs/spec/027-admin-same-origin-api-proxy.md)
날짜: 2026-06-26
연결: [[029-same-origin-proxy-collapses-cross-origin-class]], [[probe-deeper-before-concluding]],
[[restart-dev-servers-for-tailscale]]

## 무엇을 했나

admin이 API를 same-origin `/api/*`로 호출하고 vite dev 프록시가 `127.0.0.1:8000`으로 넘기게 바꿨다.
브라우저가 API 호스트를 모르게 되어 Tailscale 도메인/IP/scheme가 바뀌어도 무설정 동작 —
CORS·mixed-content·cert·호스트 종속이 통째로 사라졌다.

## 아팠던 것 — 증상마다 env를 땜질하며 회귀를 반복했다

이번 fetch 에러를 **여러 번** 잘못 좁혔다. 시간순으로:

1. 백그라운드 서버 재기동 때 `EXTRA_CORS_ORIGINS='*'`를 빠뜨려 CORS 400 회귀.
2. vite 재기동 때 `VITE_ALLOWED_HOSTS`를 빠뜨려 host-check 403.
3. 또 `VITE_API_BASE`를 빠뜨려 `localhost:8000` fallback → 원격 브라우저서 안 닿음.

매번 "이 env 하나 더"로 땜질했는데, **근본은 브라우저가 API 호스트를 직접 아는 구조** 자체였다.
호스트를 알게 하는 한 도메인·scheme·cert·origin이 전부 변수로 따라온다. 사용자가 *"하드코딩 범위가
매우 좁았으면"*이라고 방향을 잡아준 뒤에야 same-origin 프록시로 **클래스를 제거**했다 — 증상 하나가
아니라 증상을 만들던 결합(브라우저↔API 직접 cross-origin)을 끊는 게 답이었다.

## 잘된 것 — 사용자 의도를 설계 축으로 받아 최소 표면으로 수렴

- "좁은 하드코딩"이라는 **제약을 설계 기준**으로 삼으니 답이 한 줄(루프백 프록시 타깃)로 좁혀졌다.
- 검증을 **서버측 `/api` 프록시 curl(200/401)**로 끝냈다 — 무인증 401이 "vite SPA가 아니라 진짜
  API에 도달"을 증명. [005]가 경고한 tailscale **hairpin curl**(자기 IP로 가는 self-call) 함정을 피해,
  브라우저 의존 없이 결정적으로 확인.

## 다음에

- 원격 접근 프런트에서 fetch가 깨지면 **env를 하나씩 더하기 전에** "브라우저가 API 호스트를 알아야
  하나?"를 먼저 묻는다. 아니라면 same-origin 프록시가 거의 항상 더 좁고 견고하다
  ([[029-same-origin-proxy-collapses-cross-origin-class]]).
- [[probe-deeper-before-concluding]]의 변주: 내 측정(서버측 200)이 사용자 보고(브라우저 fetch 실패)와
  어긋날 때, **계층(브라우저 origin vs 서버 루프백)**이 다르다는 신호로 읽는다.

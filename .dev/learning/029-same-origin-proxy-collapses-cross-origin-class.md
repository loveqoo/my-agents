# 029 — same-origin 프록시는 cross-origin 문제 "클래스"를 통째로 없앤다

날짜: 2026-06-26
출처: 스펙 [027](../../docs/spec/027-admin-same-origin-api-proxy.md) — Tailscale 원격 접근 fetch 회귀
연결: [[018-admin-same-origin-api-proxy]], [[probe-deeper-before-concluding]],
[[restart-dev-servers-for-tailscale]]

## 교훈

프런트가 **다른 호스트의 API를 직접** 부르는 순간, 그 호스트가 변수가 되며 딸려오는 문제가 한 묶음이다:

- **CORS**(cross-origin 프리플라이트), **mixed-content**(https 페이지→http API 차단),
  **cert**(MagicDNS는 FQDN 인증서라 짧은 이름이면 경고), **호스트 종속**(도메인/IP 바뀌면 재설정).

이걸 **하나씩 env로 땜질**하면(`EXTRA_CORS_ORIGINS`, `VITE_API_BASE`, `VITE_ALLOWED_HOSTS` …)
재시작·도메인 변경마다 회귀가 재발한다. 증상이 아니라 **결합**(브라우저↔API 직접 cross-origin)이 원인.

**same-origin 프록시**가 클래스를 제거한다: 프런트는 **자기 origin의 상대경로**(`/api/*`)만 부르고,
dev 서버(vite)·리버스 프록시가 루프백으로 넘긴다. 브라우저는 API 호스트를 **모르므로**:
- same-origin → CORS 없음 · 동일 scheme → mixed-content 없음 · 호스트 하나 → cert 추가 없음
- 도메인/IP/scheme를 바꿔도 **무설정**. 하드코딩은 **프록시 타깃 한 줄**(루프백, 불변)로 수렴.

## 적용 방법

- 원격(터널/VPN/tailscale) 뒤의 프런트에서 fetch가 깨지면, env를 더하기 전에 먼저 묻는다:
  **"브라우저가 API 호스트를 직접 알아야 하나?"** 아니라면 same-origin 프록시로 바꾼다.
  - vite: `server.proxy['/api'] = { target:'http://127.0.0.1:8000', changeOrigin:true,
    rewrite: p=>p.replace(/^\/api/,'') }`. 클라이언트 `BASE='/api'`.
- **검증은 프록시 경유 curl**로(브라우저·hairpin 없이): 인증→200, **무인증→401**(프록시가 SPA가 아니라
  진짜 API에 닿는다는 증거; SPA fallback이면 200 HTML).
- 사용자가 "하드코딩 범위를 좁혀라" 류의 **제약을 주면 그걸 설계 축으로** 삼는다 — 최소 표면 해법으로
  수렴하는 강한 신호다.

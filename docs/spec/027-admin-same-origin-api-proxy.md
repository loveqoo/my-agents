# 027 — 어드민 API 호출을 same-origin `/api` 프록시로

상태: **실행·검증 완료(Execution/Verification) — main 머지 보류**(사용자 직접 브랜치 테스트 예정)
날짜: 2026-06-26
브랜치: `feat/agent-service` — **main 머지 금지**
연동: [007 실 에이전트 서비스](./007-real-agent-service.md),
[[probe-deeper-before-concluding]], [[restart-dev-servers-for-tailscale]]
참고: `.dev/troubleshooting/005-tailscale-expose-dev-servers.md`(서버 노출은 `tailscale serve`)

## 배경 / 문제

사용자는 admin을 **Tailscale**(MagicDNS 호스트명, 예 `https://msd-m4-max:5173`, TLS over TCP)로
접근한다. 기존 admin은 브라우저가 **API 호스트를 직접** 알아야 했다 —
`VITE_API_BASE=http://localhost:8000`(api.ts fallback). 이 구조의 비용:

- **localhost 무의미**: 원격 브라우저에서 `localhost`는 *그 기기 자신*이라 API에 안 닿음.
- **도메인 종속**: tailscale 도메인/IP를 바꾸면 `VITE_API_BASE`를 매번 갈아야 함.
- **부수 문제 연쇄**: https 페이지 → http API면 **mixed-content 차단**, cross-host면 **CORS**,
  MagicDNS는 FQDN cert라 짧은 이름이면 **cert 경고**. 재시작마다 env(`EXTRA_CORS_ORIGINS`/
  `VITE_API_BASE`/`VITE_ALLOWED_HOSTS`)를 빠뜨려 **회귀가 반복**됐다.

사용자 요청: *"이 부분은 하드코딩될 텐데, 하드코딩 범위가 매우 좁았으면 좋겠다."*

## 결정 — same-origin 프록시 (하드코딩 = 루프백 타깃 한 줄)

admin은 API를 **자기 origin의 상대경로 `/api/*`**로 호출하고, **vite dev 프록시**가 이를
`127.0.0.1:8000`으로 넘긴다. 브라우저는 API 호스트를 **모른다**.

- 브라우저↔서버는 항상 페이지가 이미 연 **단일 origin**(`https://<tailscale-host>:5173`).
  → **CORS 없음**(same-origin), **mixed-content 없음**(동일 scheme), **cert 추가 없음**(호스트 하나).
- **도메인/IP/scheme를 바꿔도 무설정 동작** — 브라우저는 호스트를 안 박으니까.
- **유일한 하드코딩** = `admin/vite.config.ts` 프록시 타깃 `http://127.0.0.1:8000`(루프백, 불변).

## 변경 (`admin/`)

- **`vite.config.ts`**: `server.proxy`에 `'/api' → { target: 'http://127.0.0.1:8000',
  changeOrigin: true, rewrite: p => p.replace(/^\/api/, '') }` 추가.
- **`src/api.ts`**: `BASE` 기본값 `'http://localhost:8000'` → **`'/api'`**(same-origin 상대경로).
  모든 호출이 `${BASE}${path}` 한 군데로 흐르므로 호출부 수정 0. 절대 URL이 필요하면
  `VITE_API_BASE`로 여전히 override 가능.
- **`.env`**(로컬, gitignore): `VITE_API_BASE=/api`.

## 검증 (서버측, hairpin 없이)

1. vite `/api/agents`(Bearer) → **200**: 프록시가 8000으로 정상 포워딩 + 인증 헤더 전달.
2. vite `/api/agents`(무인증) → **401**: vite SPA fallback이 아니라 **진짜 API에 도달**한다는 증거
   (SPA였다면 200 HTML).
3. 브라우저(`https://msd-m4-max:5173`) 하드 리프레시 → fetch 정상(사용자 확인).

## 완료 조건

- [x] admin → same-origin `/api` 프록시(vite.config) + `BASE='/api'`(api.ts) + `.env=/api`
- [x] 서버측 검증: `/api/agents` Bearer→200, 무인증→401
- [x] 브라우저 실동작 확인(사용자) — CORS·cert·mixed-content·도메인 종속 모두 제거
- [ ] **main 머지 금지**(사용자 직접 브랜치 테스트 예정)
- [ ] (추후) 프로덕션 빌드의 정적 서빙/리버스 프록시 경로는 별도 — dev(vite)만 본 스펙 범위

# 005 — Tailscale로 개발 서버(API·Vite) 노출이 안 됨

날짜: 2026-06-24
브랜치: `feat/agent-service`
관련: [[017-unmapped-status-crash]], main.py, admin/vite.config.ts

## 증상
Tailscale(`100.72.45.58`)로 어드민 UI/API에 접속 불가.
- 8000(API)·5173(Vite)는 `127.0.0.1`/`[::1]` 루프백에만 바인딩 → tailnet에서 안 닿음.
- 바인딩을 tailscale IP(`100.72.45.58`)로 직접 옮기자, **TCP는 붙는데 HTTP 응답 0바이트(행)** — uvicorn 로그에 요청조차 안 찍힘. Vite(node)는 같은 IP에서 소형 응답은 200.

## 잘못된 추측 (기록용 — 하지 말 것)
- "uvicorn이 utun IP 바인딩 시 응답 못 한다" → **웹에 그런 케이스 없음.** 근거 없는 추측이었음.
- 자기 자신의 tailscale IP로 가는 **헤어핀** curl 테스트는 신뢰 불가 → 진단 근거에서 제외해야 함.

## 실제 원인 (측정으로 확정)
- **utun9(tailscale) 인터페이스 MTU = 1280** (`ping -D -s 1400` → `Message too long`, `-s 1200`은 통과).
- Tailscale 공식 문서: ">1280 패킷은 조용히 드롭" → "TCP는 붙는데 응답 행"은 문서화된 동일 증상.
- 앱이 utun IP에 직접 바인딩하면 대형 응답이 1280을 못 맞춰 드롭됨. (어드민은 JS 번들 수백 KB·`/openapi.json` 51KB 등 대형 응답 다수.)

## 해결: 서버는 루프백, `tailscale serve`로 tailnet에만 프록시
tailscaled의 netstack이 1280 MTU에 맞춰 세그멘테이션하므로 앱은 utun에 직접 패킷을 안 보냄.

```bash
# 1) API — 루프백 + 전체 오리진 허용(노출 경계는 serve가 보장)
EXTRA_CORS_ORIGINS='*' uv run --package api api          # → 127.0.0.1:8000

# 2) Vite — IPv4 루프백(중요!) + host-check 해제 + API base=tailscale IP
cd admin && VITE_ALLOWED_HOSTS=true VITE_API_BASE=http://100.72.45.58:8000 \
  npm run dev -- --host 127.0.0.1                        # → 127.0.0.1:5173

# 3) tailscale serve — tailnet에만 raw TCP 포워드 (--bg 영구)
tailscale serve --bg --tcp=8000 tcp://127.0.0.1:8000
tailscale serve --bg --tcp=5173 tcp://127.0.0.1:5173
```

접속: **`http://100.72.45.58:5173`** (tailnet 어디서나, 로컬 포함).

## 함정 (재발 방지)
- **Vite는 기본 `[::1]`(IPv6 루프백)에 뜬다.** `tailscale serve --tcp ... tcp://127.0.0.1`(IPv4)와 미스매치 → UI만 HTTP 000(exit 56). 반드시 `--host 127.0.0.1`로 IPv4 루프백에 맞춘다.
- MagicDNS 호스트명 엔드포인트는 `TLS over TCP`라 `http://<host>`는 실패. **IP + http://** 를 쓰거나 `https://<host>` 사용.
- 코드 변경(main.py `API_HOST`/`EXTRA_CORS_ORIGINS`, vite.config `VITE_ALLOWED_HOSTS`)은 **기본값 무변경**(loopback·localhost) — 노출은 전적으로 env opt-in.

## 검증 (실측, ssh 미사용 — 로컬 curl)
- 소형 401(42B)·인증 200(9KB)·**Vite 모듈 178KB** 모두 serve 경유 정상.
- utun 직접 바인딩이면 행이던 대형 응답이 통과 → MTU 처리 확인.
- 바인딩은 둘 다 `127.0.0.1` — `0.0.0.0`/utun 노출 0.

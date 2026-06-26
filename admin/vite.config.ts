import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// allowedHosts: 기본은 로컬(localhost)만 — Tailscale MagicDNS 호스트명으로 접속하면
// Vite host-check에 걸리므로 VITE_ALLOWED_HOSTS로만 연다. "true"=호스트 검사 해제
// (노출 경계는 `tailscale serve`가 보장하므로 안전), 그 외엔 쉼표구분 호스트 목록.
const _ah = (process.env.VITE_ALLOWED_HOSTS ?? '').trim()
const allowedHosts =
  _ah === 'true' ? true : _ah ? _ah.split(',').map((s) => s.trim()).filter(Boolean) : undefined

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    allowedHosts,
    // same-origin 프록시: admin은 `/api/*`로 부르고 여기서 API로 넘긴다. 유일한 하드코딩 = 루프백 타깃.
    // 덕분에 브라우저는 API 호스트를 몰라도 되고, CORS·mixed-content·cert 문제가 통째로 사라진다.
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api/, ''),
      },
    },
  },
})

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
  server: { port: 5173, allowedHosts },
})

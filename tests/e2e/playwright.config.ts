import { defineConfig, devices } from '@playwright/test'

/* E2E: 어드민 UI(5173) + 백엔드 API(8000). Postgres·API·MLX는 이미 떠 있다고 가정.
   Vite는 reuseExistingServer로 떠 있으면 재사용, 없으면 띄운다.
   전제: `uv run --package api api` (8000) + Postgres + 로컬 MLX(8045) 가동. */
const API = process.env.API_BASE ?? 'http://127.0.0.1:8000'
const UI = process.env.UI_BASE ?? 'http://localhost:5173'
// 서버/UI의 개발용 토큰과 동일해야 함(.env API_AUTH_TOKEN / admin/.env VITE_API_TOKEN).
const TOKEN = process.env.API_AUTH_TOKEN ?? 'mat_dev_local_2026'

export default defineConfig({
  testDir: './specs',
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false, // 공유 DB 상태 — 순차 실행으로 간섭 최소화
  workers: 1,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: UI,
    extraHTTPHeaders: { Authorization: `Bearer ${TOKEN}` },
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'api', testMatch: /api\.spec\.ts/, use: { baseURL: API } },
    {
      name: 'admin',
      testMatch: /admin\.spec\.ts/,
      use: { ...devices['Desktop Chrome'], baseURL: UI },
      dependencies: ['api'],
    },
  ],
  webServer: {
    command: 'cd ../../admin && npm run dev',
    url: UI,
    reuseExistingServer: true,
    timeout: 30_000,
  },
})

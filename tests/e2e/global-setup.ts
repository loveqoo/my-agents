import { request, type FullConfig } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'

/* 스펙 366 — admin/mobile 브라우저 프로젝트 인증 프로비저닝.
   SPA는 same-origin `/api` 프록시 + 쿠키 세션이라, 머신 Bearer 토큰은 /users/me를 유저로
   해석 못 해(401) 로그인 화면에 막힌다. 표준 해법: UI 오리진 경유로 로그인해 쿠키를
   storageState로 저장 → 브라우저 프로젝트가 이 상태를 이어받아 자동 인증. */

const UI = process.env.UI_BASE ?? 'http://localhost:5173'
const EMAIL = process.env.ADMIN_EMAIL ?? 'admin@example.com'
const PASSWORD = process.env.ADMIN_PASSWORD ?? 'adminpass123'

// 저장 위치(cwd=tests/e2e 기준). config의 admin/mobile 프로젝트가 같은 경로를 storageState로 읽는다.
export const STORAGE_STATE = '.auth/admin.json'

export default async function globalSetup(_config: FullConfig): Promise<void> {
  const ctx = await request.newContext({ baseURL: UI })
  const res = await ctx.post('/api/auth/login', {
    form: { username: EMAIL, password: PASSWORD },
  })
  if (!res.ok()) {
    throw new Error(`e2e 로그인 실패 (${res.status()}) — API(8000)+vite(5173) 기동 확인`)
  }
  fs.mkdirSync(path.dirname(STORAGE_STATE), { recursive: true })
  await ctx.storageState({ path: STORAGE_STATE })
  await ctx.dispose()
}

/* 스펙 179 e2e — mock 도구 트리거로 delete_record 어드민 승인 흐름을 플레이그라운드에서 실증.
   채팅 "레코드 삭제" → 승인 대기 → 승인 페이지 pending → 승인 → 도구 실행. 시스템 Chrome. */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium
const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = process.argv[2] ?? '/tmp/hil-179'
const _fx = (await import(process.cwd() + '/tests/browser/_fixture.mjs')).provisionSuper()
const fails = []
const ok = (c, m) => { console.log((c ? '  ok  ' : ' FAIL ') + m); if (!c) fails.push(m) }
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await (await browser.newContext({ viewport: { width: 1400, height: 950 } })).newPage()
try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByPlaceholder('you@example.com').fill(_fx.email)
  await page.getByPlaceholder('비밀번호').fill(_fx.password)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })

  // Playground → research-assistant(local-tools 물림)
  await page.getByText('Playground', { exact: true }).first().click()
  await page.waitForTimeout(1200)
  const combo = page.locator('button').filter({ hasText: 'research-assistant' }).first()
  if (await combo.count()) { await combo.click(); await page.waitForTimeout(400)
    const opt = page.getByText('research-assistant', { exact: false }).first()
    await opt.click().catch(() => {}); await page.waitForTimeout(600) }

  // 위험 도구 트리거
  const ta = page.locator('textarea').first()
  await ta.click(); await ta.fill('레코드 r1 삭제해줘')
  await ta.press('Enter')
  const waited = await page.getByText(/승인 대기|승인이 필요|delete_record/i).first()
    .waitFor({ timeout: 25000 }).then(() => true).catch(() => false)
  await page.waitForTimeout(1500)
  await page.screenshot({ path: `${OUT}-1-chat.png`, fullPage: true })
  ok(waited, '채팅에 "승인 대기" 프레임 노출(도구 트리거→interrupt)')

  // 승인 페이지 → pending 확인 + 승인
  await page.getByText('승인', { exact: true }).first().click()
  await page.waitForTimeout(1200)
  const pending = await page.getByText(/delete_record|data\.delete|삭제/i).first()
    .waitFor({ timeout: 8000 }).then(() => true).catch(() => false)
  await page.screenshot({ path: `${OUT}-2-queue.png`, fullPage: true })
  ok(pending, '승인 페이지에 pending 항목(delete_record) 노출')

  const approveBtn = page.getByRole('button', { name: /승인|approve/i }).first()
  const hasBtn = await approveBtn.count()
  ok(hasBtn > 0, '승인 버튼 존재')
  if (hasBtn) {
    await approveBtn.click()
    await page.waitForTimeout(2500)
    await page.screenshot({ path: `${OUT}-3-approved.png`, fullPage: true })
    const cleared = await page.getByText(/대기 중인 승인이 없|모두 처리/i).first()
      .waitFor({ timeout: 8000 }).then(() => true).catch(() => false)
    ok(cleared, '승인 후 큐 비워짐(해소됨)')
  }
  console.log(fails.length ? `\n실패 ${fails.length}` : '\n스펙 179 HIL 승인 e2e — 통과.')
} catch (e) { console.error('오류:', e.message); fails.push(e.message); await page.screenshot({ path: `${OUT}-err.png` }).catch(() => {}) }
finally { await _fx.cleanup?.(); await browser.close() }
process.exit(fails.length ? 1 : 0)

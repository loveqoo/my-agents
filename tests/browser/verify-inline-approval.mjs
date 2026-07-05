/* 스펙 180 — 대화 내 인라인 승인. member가 "레코드 삭제"→대화에 인라인 승인 바가 뜨고→
   승인 메뉴로 안 가고 그 자리서 승인→폴링 유지로 완료 턴이 그 자리서 표시. 거부도 확인. */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium
const URL = 'http://127.0.0.1:5173'
const EMAIL = process.env.MEMBER_EMAIL ?? 'shotfix_selfdemo@example.com'
const PASSWORD = process.env.MEMBER_PASSWORD ?? 'Selfdemo1!pw'
const fails = []
const ok = (c, m) => { console.log((c ? '  ok  ' : ' FAIL ') + m); if (!c) fails.push(m) }
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await (await browser.newContext({ viewport: { width: 1400, height: 950 } })).newPage()
const pickDemo = async () => {
  await page.getByText('Playground', { exact: true }).first().click()
  await page.waitForTimeout(1000)
  const combo = page.locator('button').filter({ hasText: /self-approval-demo|본인 승인 데모|research-assistant/ }).first()
  await combo.click(); await page.waitForTimeout(400)
  await page.getByText(/self-approval-demo|본인 승인 데모/, { exact: false }).first().click().catch(()=>{})
  await page.waitForTimeout(500)
}
try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  await pickDemo()

  // ── 승인 경로 ──────────────────────────────────────────────
  const ta = page.locator('textarea').first()
  await ta.click(); await ta.fill('레코드 r1 삭제해줘'); await ta.press('Enter')
  await page.getByText(/승인 대기/i).first().waitFor({ timeout: 25000 })
  await page.waitForTimeout(800)
  // 인라인 바가 대화(입력 영역)에 떠야 — 승인 메뉴로 안 감
  const inlinePrompt = await page.getByText(/이 도구 실행을 승인할까요/).count()
  ok(inlinePrompt > 0, '대화에 인라인 승인 바 노출("이 도구 실행을 승인할까요?")')
  ok(/본인 승인 대기/.test(await page.locator('#root').innerText()), '인라인 바 "본인 승인 대기" 라벨')
  const phBlocked = await ta.getAttribute('placeholder')
  ok(/위 승인\/거부를 선택하세요/.test(phBlocked || ''), `입력 잠금+안내 (got: ${phBlocked})`)
  await page.screenshot({ path: '/tmp/inline-approval-bar.png', fullPage: true })

  // 그 자리서 승인 (승인 메뉴 이동 없음)
  await page.getByRole('button', { name: /승인 및 재개/ }).first().click()
  let updated = false
  for (let i = 0; i < 10; i++) {
    await page.waitForTimeout(2600)
    const b = await page.locator('#root').innerText()
    if (/결정적 mock 응답/.test(b) && !/승인 대기/.test(b)) { updated = true; break }
  }
  ok(updated, '인라인 승인 → 그 자리서 완료 턴 표시(폴링 유지, 화면 이동 없음)')
  await page.screenshot({ path: '/tmp/inline-approval-done.png', fullPage: true })

  // ── 거부 경로 ──────────────────────────────────────────────
  await ta.click(); await ta.fill('레코드 r2 삭제해줘'); await ta.press('Enter')
  await page.getByText(/승인 대기/i).first().waitFor({ timeout: 25000 })
  await page.waitForTimeout(800)
  await page.getByRole('button', { name: '거부' }).first().click()
  await page.waitForTimeout(1500)
  ok(/거부됨 — 실행이 중단/.test(await page.locator('#root').innerText()), '인라인 거부 → "거부됨" 표시')
  // 거부 후 입력이 다시 열려 이어갈 수 있어야
  const phAfter = await ta.getAttribute('placeholder')
  ok(!/승인 대기|선택하세요/.test(phAfter || ''), `거부 후 입력 재개 (placeholder: ${phAfter})`)

  console.log(fails.length ? `\n실패 ${fails.length}` : '\n스펙 180 인라인 승인 — 통과.')
} catch (e) { console.error('오류:', e.message); fails.push(e.message); await page.screenshot({path:'/tmp/inline-approval-err.png'}).catch(()=>{}) }
finally { await browser.close() }
process.exit(fails.length ? 1 : 0)

/* 본인(self) 승인 검증 — member 계정으로 approver=self 도구를 트리거하고 본인이 승인.
   member 로그인→self-approval-demo→"레코드 삭제"→승인 대기→승인 페이지(본인 것)→승인→자동 갱신. */
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
try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  ok(true, 'member 로그인 성공')

  await page.getByText('Playground', { exact: true }).first().click()
  await page.waitForTimeout(1200)
  // self-approval-demo 선택
  const combo = page.locator('button').filter({ hasText: /self-approval-demo|본인 승인 데모|research-assistant/ }).first()
  await combo.click(); await page.waitForTimeout(400)
  await page.getByText(/self-approval-demo|본인 승인 데모/, { exact: false }).first().click().catch(()=>{})
  await page.waitForTimeout(600)

  const ta = page.locator('textarea').first()
  await ta.click(); await ta.fill('레코드 r1 삭제해줘'); await ta.press('Enter')
  await page.getByText(/승인 대기/i).first().waitFor({ timeout: 25000 })
  ok(true, 'member: 승인 대기(delete_record interrupt)')

  // 승인 페이지 — member 본인 것만 보임 + 승인
  await page.getByText('승인', { exact: true }).first().click()
  await page.waitForTimeout(1200)
  const bodyQ = await page.locator('#root').innerText()
  ok(/delete_record/i.test(bodyQ), '승인 페이지에 본인 요청(delete_record) 노출')
  ok(/본인 승인 필요/.test(bodyQ), '본문 "본인 승인 필요" 표기')
  const selfTag = await page.getByText('본인 승인', { exact: true }).count()
  const adminTag = await page.getByText('관리자 승인', { exact: true }).count()
  ok(selfTag > 0 && adminTag === 0, `태그가 "본인 승인"(self=${selfTag}, admin=${adminTag})`)
  await page.screenshot({ path: '/tmp/self-approval-queue.png', fullPage: true })
  const approveBtn = page.getByRole('button', { name: /승인 및 재개|승인|approve/i }).first()
  ok(await approveBtn.count() > 0, 'member가 본인 승인 버튼 보임(403 아님)')
  await approveBtn.click()
  await page.waitForTimeout(2500)
  const cleared = await page.getByText(/대기 중인 승인이 없|모두 처리/i).first()
    .waitFor({ timeout: 8000 }).then(()=>true).catch(()=>false)
  ok(cleared, 'member 본인 승인 → 큐 비워짐(자기 것 승인 성공, 서버 재개)')
  await page.screenshot({ path: '/tmp/self-approval-done.png', fullPage: true })
  // (단일 브라우저에서 승인하러 이동하면 Playground 언마운트로 폴링이 끊긴다 — 채팅 자동 갱신은
  //  2브라우저/탭 유지 시. 단일 브라우저는 세션 재열람으로 결과 확인. 여기선 self 승인 성공까지 검증.)
  console.log(fails.length ? `\n실패 ${fails.length}` : '\n본인(self) 승인 — 통과.')
} catch (e) { console.error('오류:', e.message); fails.push(e.message); await page.screenshot({path:'/tmp/self-approval-err.png'}).catch(()=>{}) }
finally { await browser.close() }
process.exit(fails.length ? 1 : 0)

/* 스펙 205 검증 — 인스펙터 정직성 3건(실모델 qwen 의존 · plan-execute-demo에 web-fetch 배선 전제).
   실행: PLAYWRIGHT_DIR=<dir> node tests/browser/verify-inspector-honesty-205.mjs */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(`${pwDir}/index.js`)
const chromium = _pw.chromium ?? _pw.default?.chromium
const _fx = (await import('./_fixture.mjs')).provisionSuper()
const OUT = '/private/tmp/claude-501/-Users-anthony-Repository-github-loveqoo-my-agents/0f419f54-5016-4410-97ef-deab94d7cbcb/scratchpad'
const ok = (c, m) => console.log((c ? '  ok  ' : ' FAIL ') + m)
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await (await browser.newContext({ viewport: { width: 1600, height: 1100 } })).newPage()
const bodyText = () => page.locator('body').innerText()
await page.goto('http://127.0.0.1:5173', { waitUntil: 'networkidle' })
await page.getByPlaceholder('you@example.com').fill(_fx.email)
await page.getByPlaceholder('비밀번호').fill(_fx.password)
await page.getByRole('button', { name: '로그인' }).click()
await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
await page.getByRole('menuitem', { name: 'Playground' }).click()
await page.waitForTimeout(1500)
await page.locator('button:has(.ant-avatar)').first().click()
await page.waitForTimeout(600)
await page.locator('.ant-dropdown').getByText('plan-execute-demo', { exact: true }).first().click()
await page.waitForTimeout(1200)
const ta = page.locator('textarea').first()
await ta.click(); await ta.fill("백과사전에서 '한글'을 찾아서 한 줄로 요약해줘"); await ta.press('Enter')
const t0 = Date.now()
while (Date.now() - t0 < 150000) { if (/\d+ mcp/.test(await bodyText())) break; await page.waitForTimeout(2000) }
await page.waitForTimeout(2000)
await page.getByText('인스펙터', { exact: true }).last().click()
await page.waitForTimeout(1200)
const head = await bodyText()
// 1) 턴 배지
ok(/턴 1(\s|$)/.test(head.match(/턴 \d+/)?.[0] ?? '') || (head.match(/턴 (\d+)/)?.[1] === '1'), `1 턴 배지=질문 순번 (${head.match(/턴 \d+/)?.[0]})`)
// 2) 토큰 — 실측(수백대) 또는 ≈
const tokIn = /입력 토큰[^\d≈]*([≈\d,]+)/.exec(head)?.[1]
const tokOut = /출력 토큰[^\d≈]*([≈\d,]+)/.exec(head)?.[1]
console.log('  토큰:', tokIn, '/', tokOut)
ok(!!tokIn && (tokIn.includes('≈') || parseInt(tokIn.replace(/[^\d]/g, '')) > 50), '2 토큰 실측(>50) 또는 ≈ 표기')
// 3) 전송 프롬프트 실측 — 프롬프트·설정 탭에 계획·도구 안내
await page.getByText('프롬프트·설정', { exact: true }).first().click()
await page.waitForTimeout(1000)
// system 메시지 행 펼치기(본문은 행별 접힘 설계)
await page.getByText('system', { exact: true }).first().click()
await page.waitForTimeout(600)
const t2 = await bodyText()
ok(/실제 전송된 메시지/.test(t2), '3a 캡션=실측 표기')
ok(/작업 계획/.test(t2), '3b 시스템 프롬프트에 # 작업 계획 노출(커스텀 impl 실측)')
ok(/사용 가능한 도구|wiki_search/.test(t2), '3c 도구 안내 노출')
ok(/모델 호출 \d+회/.test(t2) || !/모델 호출/.test(t2), '3d 호출 수 병기(다회 시)')
await page.screenshot({ path: `${OUT}/verify-205.png`, fullPage: true })
await browser.close()
console.log('DONE')

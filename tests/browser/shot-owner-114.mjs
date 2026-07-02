/* 스펙 114 검증 — 소유 표시(OwnerTag) + 비소유 관리 버튼 숨김. 시스템 Chrome.
   admin(vite :5173) 로그인 후 /agents 응답을 인터셉트해 소유 변형을 주입:
   - item[0]: owner_id=타인 + can_manage=false → "다른 사용자" 태그 + 상세 삭제/편집 버튼 숨김
   - item[1]: owner_id=null → "공유" 태그 + (super라 can_manage=true) 버튼 유지
   백엔드 can_manage 로직은 verify_114가 이미 검증 — 여기선 프론트 렌더/게이팅만 결정적으로 확인.

   실행: PLAYWRIGHT_DIR=<dir> node tests/browser/shot-owner-114.mjs [out.png] */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = process.argv[2] ?? '/tmp/owner-114.png'
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password

const fails = []
const check = (c, m) => { console.log((c ? '  ok  ' : ' FAIL ') + m); if (!c) fails.push(m) }

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1100, height: 1200 } })
const page = await ctx.newPage()

// /agents(목록만) 인터셉트 → 실제 응답을 받아 소유 변형 주입.
await page.route((u) => u.pathname.endsWith('/agents'), async (route) => {
  if (route.request().method() !== 'GET') return route.continue()
  const resp = await route.fetch()
  let arr
  try { arr = await resp.json() } catch { return route.fulfill({ response: resp }) }
  if (Array.isArray(arr) && arr.length) {
    arr[0] = { ...arr[0], owner_id: '11111111-1111-1111-1111-111111111111', can_manage: false }
    if (arr.length > 1) arr[1] = { ...arr[1], owner_id: null, can_manage: true }
  }
  route.fulfill({ response: resp, json: arr })
})

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  await page.getByText('에이전트', { exact: true }).first().click()
  await page.waitForTimeout(1200)

  const bodyText = await page.locator('body').innerText()
  check(bodyText.includes('다른 사용자'), 'A "다른 사용자" 태그 렌더(비소유 항목)')
  check(bodyText.includes('공유'), 'B "공유" 태그 렌더(owner_id=null 항목)')
  await page.screenshot({ path: OUT, fullPage: true })
  console.log('SHOT', OUT)

  // 비소유(다른 사용자) 행 상세 → 삭제/편집 숨김 + 안내문.
  const otherRow = page.locator('tr', { hasText: '다른 사용자' }).first()
  if (await otherRow.count()) {
    await otherRow.click()
    await page.waitForTimeout(700)
    const noManage = await page.getByText('관리 권한 없음').count()
    check(noManage > 0, 'C 비소유 상세: "관리 권한 없음" 안내(삭제/편집 대체)')
    // 상세 드로어 안에 활성 삭제 버튼이 없어야(비소유). 안내문만.
    const delBtns = await page.getByRole('button', { name: /삭제|등록 해제/ }).count()
    check(delBtns === 0, `C 비소유 상세: 삭제/등록해제 버튼 없음 (found ${delBtns})`)
    await page.screenshot({ path: OUT.replace('.png', '-detail.png') })
    console.log('SHOT', OUT.replace('.png', '-detail.png'))
  } else {
    check(false, 'C 비소유 행을 찾지 못함(시드 에이전트 0?)')
  }
} catch (e) {
  check(false, 'EXC ' + (e?.message ?? e))
} finally {
  await browser.close()
}

console.log(fails.length ? `\n❌ ${fails.length} FAILED` : '\n✅ ALL PASS (SHOT114_OK)')
process.exit(fails.length ? 1 : 0)

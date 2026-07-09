/* 기억 어휘 정리 실검증 (스펙 269) — 필수 단언(learning 151·UI 검증은 기능적으로).
   ① 직접 응답 폼: "하는 일" 기억 그룹에 단기(세션) 선택지 없음·장기 기억(mem0) 있음·그룹 카운트 /1.
   ② 세부: "단기 기억" 필드 라벨 있음·"채팅 히스토리" 필드 라벨 없음.
   ③ 노드형 폼: 노드 기억 Select 옵션에 단기(세션) 없음·장기 있음.
   판정=pass/fail(스크린샷 아님). 죽은 선택지 제거를 실제 DOM에서 단언.

   실행: PLAYWRIGHT_DIR=<abs>/tests/e2e/node_modules/playwright \
         ADMIN_EMAIL=admin@example.com ADMIN_PASSWORD=adminpass123 \
         node tests/browser/verify-269-memory-framing.mjs */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium
const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const EMAIL = process.env.ADMIN_EMAIL ?? 'admin@example.com'
const PASSWORD = process.env.ADMIN_PASSWORD ?? 'adminpass123'

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ viewport: { width: 1280, height: 1000 } })
const page = await ctx.newPage()
const log = (...a) => console.log(...a)
const fails = []
const check = (c, m) => { log((c ? '  ok  ' : ' FAIL ') + m); if (!c) fails.push(m) }

async function login() {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  await page.waitForTimeout(500)
}

async function openNewForm(typeLabel) {
  await page.getByRole('button', { name: /새 에이전트/ }).first().click()
  await page.waitForTimeout(700)
  await page.getByPlaceholder('예: research-assistant').fill('probe-269-' + Date.now().toString(36))
  if (typeLabel) {
    const field = page.locator('label', { hasText: '에이전트 종류' }).first()
    await field.locator('.ant-select').first().click()
    await page.waitForTimeout(300)
    await page.locator('.ant-select-dropdown:visible .ant-select-item-option', { hasText: typeLabel }).first().click()
    await page.waitForTimeout(400)
  }
}

try {
  await login()

  // ── ① 직접 응답: "하는 일" 기억 그룹 ──
  await openNewForm(null) // 기본=직접 응답
  await page.getByRole('button', { name: '다음' }).click() // 정체성 → 하는 일
  await page.waitForTimeout(500)

  // 기억 Collapse 패널 펼치기(헤더 텍스트 "기억")
  const memHeader = page.locator('.ant-collapse-header', { hasText: '기억' }).first()
  await memHeader.click()
  await page.waitForTimeout(400)

  const shortInDirect = await page.getByText('단기(세션)', { exact: false }).count()
  check(shortInDirect === 0, `직접 폼 기억 그룹에 단기(세션) 선택지 없음 (found ${shortInDirect})`)
  const longVisible = await page.getByText('장기 기억 (mem0)', { exact: false }).first().isVisible().catch(() => false)
  check(longVisible, '직접 폼 기억 그룹에 장기 기억(mem0) 선택지 있음')
  // 그룹 카운트 태그 = "/1"(단기 제외 후 장기 1개만)
  const memHeaderText = await memHeader.innerText().catch(() => '')
  check(/\/\s*1\b/.test(memHeaderText), `기억 그룹 카운트 총 1 (단기 제외) (header="${memHeaderText.replace(/\n/g, ' ')}")`)

  // ── ② 세부: 단기 기억 라벨 / 채팅 히스토리 라벨 부재 ──
  await page.getByRole('button', { name: '다음' }).click() // 하는 일 → 세부
  await page.waitForTimeout(500)
  // 라벨 span은 정확 매칭으로 본다 — Field가 <label>로 설명문까지 감싸므로 hasText는 설명 괄호
  // "(채팅 히스토리)"까지 잡는다(그건 의도된 메커니즘 명시). 필드 *라벨*만 검사.
  const shortTermLabel = await page.getByText('단기 기억', { exact: true }).count()
  check(shortTermLabel > 0, `세부에 "단기 기억" 필드 라벨 있음 (found ${shortTermLabel})`)
  const chatHistLabel = await page.getByText('채팅 히스토리', { exact: true }).count()
  check(chatHistLabel === 0, `세부에 "채팅 히스토리" 필드 라벨 없음(설명문 괄호는 허용) (found ${chatHistLabel})`)
  // 닫기
  await page.keyboard.press('Escape').catch(() => {})
  await page.waitForTimeout(400)

  // ── ③ 노드형: 노드 기억 Select 옵션 ──
  await openNewForm('노드형')
  await page.getByRole('button', { name: '다음' }).click() // 정체성 → 하는 일(노드 편집기)
  await page.waitForTimeout(500)
  await page.getByRole('button', { name: /노드 추가/ }).click()
  await page.waitForTimeout(400)
  // 노드 카드의 "기억 (선택)" Select 열기
  const memSelect = page.locator('.ant-select').filter({ hasText: /이 노드가 회상할 기억|등록된 기억 없음/ }).first()
  const hasMemSelect = await memSelect.count()
  check(hasMemSelect > 0, `노드 카드에 기억 Select 존재 (found ${hasMemSelect})`)
  if (hasMemSelect > 0) {
    await memSelect.click()
    await page.waitForTimeout(400)
    const dd = page.locator('.ant-select-dropdown:visible')
    const shortInNode = await dd.getByText('단기(세션)', { exact: false }).count()
    check(shortInNode === 0, `노드 기억 옵션에 단기(세션) 없음 (found ${shortInNode})`)
    const longInNode = await dd.getByText('장기 기억 (mem0)', { exact: false }).count()
    check(longInNode > 0, `노드 기억 옵션에 장기 기억(mem0) 있음 (found ${longInNode})`)
  }

  log('')
  log(`${fails.length === 0 ? 'ALL GREEN' : 'FAILED ' + fails.length}`)
  process.exitCode = fails.length ? 1 : 0
} catch (e) {
  log('ERROR ' + (e?.stack ?? e))
  process.exitCode = 1
} finally {
  await browser.close()
}

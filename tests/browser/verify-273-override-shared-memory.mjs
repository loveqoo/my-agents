/* 오버라이드 드로어 공용 기억 컨트롤 검증 (스펙 273) — 필수 단언(UI 기능적).
   ① 구조: step 1 좌측 피커에 '기억' 그룹 없음(도구만), 우측에 공용 단기/장기 컨트롤(라벨+공용 도움말).
   ② 기능 왕복(핵심): 공용 컨트롤로 단기=0·장기 선택 → 적용 → 실제 메시지 전송 시
      POST /chat 요청 body.overrides에 historyDepth=0·memories 반영(드래프트→payload 배선).

   실행: PLAYWRIGHT_DIR=<abs>/tests/e2e/node_modules/playwright \
         ADMIN_EMAIL=admin@example.com ADMIN_PASSWORD=adminpass123 \
         node tests/browser/verify-273-override-shared-memory.mjs */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium
const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const EMAIL = process.env.ADMIN_EMAIL ?? 'admin@example.com'
const PASSWORD = process.env.ADMIN_PASSWORD ?? 'adminpass123'

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ viewport: { width: 1280, height: 1100 } })
const page = await ctx.newPage()
const log = (...a) => console.log(...a)
const fails = []
const check = (c, m) => { log((c ? '  ok  ' : ' FAIL ') + m); if (!c) fails.push(m) }
const AGENT = 'ov-273-' + Date.now().toString(36)
const cleanup = { agents: [] }

try {
  await page.goto(URL, { waitUntil: 'domcontentloaded', timeout: 30000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })

  // 직접형(impl 미지정) mock-llm 에이전트 — 결정적, 기본 memories=[]·historyDepth=20.
  const ar = await page.request.post(`${URL}/api/agents`, {
    data: { name: AGENT, config: { model: 'mock-llm', prompt: '테스트용', mcps: [], memories: [] } },
  })
  const a = await ar.json()
  check(ar.ok(), `테스트 에이전트 생성 (${ar.status()})`)
  if (a?.id) cleanup.agents.push(a.id)

  // Playground → 에이전트 선택 → 오버라이드 드로어 → step 1
  await page.getByRole('menuitem', { name: 'Playground' }).click()
  await page.waitForTimeout(1200)
  await page.locator('button:has(.ant-avatar)').first().click()
  await page.waitForTimeout(400)
  await page.getByText(AGENT, { exact: false }).first().click()
  await page.waitForTimeout(600)
  await page.locator('button[title*="오버라이드"]').first().click()
  await page.waitForTimeout(600)
  const drawer = page.getByRole('dialog')
  await drawer.getByRole('button', { name: '다음' }).click()
  await page.waitForTimeout(500)

  // ── ① 구조: 좌측=도구 트리(스펙 277·278 아코디언 — 열어야 렌더), '기억' 그룹 없음(273 이동) ──
  const ovAcc = drawer.locator('.ant-collapse-header').filter({ hasText: '도구' }).first()
  await ovAcc.click(); await page.waitForTimeout(400)
  const hasToolTree = await drawer.locator('.ant-tree').count()
  check(hasToolTree > 0, `좌측에 도구 트리(스펙 277) (found ${hasToolTree})`)
  const headers = await drawer.locator('.ant-collapse-header').allTextContents()
  check(!headers.some((h) => h.trim().startsWith('기억')), `좌측에 '기억' 그룹 없음(273 이동) (headers=${JSON.stringify(headers)})`)

  // 공용 단기 컨트롤: 라벨 + AgentForm과 동일한 공용 hint
  const shortLabel = await drawer.getByText('단기 기억', { exact: true }).count()
  check(shortLabel > 0, `'단기 기억' 공용 컨트롤 라벨 (found ${shortLabel})`)
  const sharedHint = await drawer.getByText('최근 N개 대화(채팅 히스토리)를 모델에 넣습니다.', { exact: true }).count()
  check(sharedHint > 0, `공용 도움말 문구(단일 출처) (found ${sharedHint})`)
  // 공용 장기 컨트롤: 라벨 + 공용 placeholder/도움말
  const longLabel = await drawer.getByText('장기 기억', { exact: true }).count()
  check(longLabel > 0, `'장기 기억' 공용 컨트롤 라벨 (found ${longLabel})`)

  // ── ② 기능 왕복: 단기=0 선택 ──
  const shortWrap = drawer.locator('div', { has: page.getByText('단기 기억', { exact: true }) })
    .filter({ has: page.locator('.ant-select') }).last()
  await shortWrap.locator('.ant-select').first().click()
  await page.waitForTimeout(300)
  await page.locator('.ant-select-dropdown:visible .ant-select-item-option', { hasText: '기억 안 함 (0개)' }).first().click()
  await page.waitForTimeout(300)

  // 장기: 첫 옵션 선택(카탈로그 = 장기 기억 (mem0))
  const longWrap = drawer.locator('div', { has: page.getByText('장기 기억', { exact: true }) })
    .filter({ has: page.locator('.ant-select') }).last()
  await longWrap.locator('.ant-select').first().click()
  await page.waitForTimeout(300)
  const memOpts = await page.locator('.ant-select-dropdown:visible .ant-select-item-option').allTextContents()
  log('  ..  장기 옵션: ' + JSON.stringify(memOpts))
  let pickedMem = null
  if (memOpts.length > 0) {
    pickedMem = memOpts[0]
    await page.locator('.ant-select-dropdown:visible .ant-select-item-option').first().click()
    await page.waitForTimeout(200)
  }
  await page.keyboard.press('Escape'); await page.waitForTimeout(200)

  // 적용 — 새 대화
  await drawer.getByRole('button', { name: /적용 — 새 대화/ }).click()
  await page.waitForTimeout(800)

  // 메시지 전송하며 chat 요청 body 캡처 → overrides 배선 단언
  let chatBody = null
  page.on('request', (req) => {
    if (req.method() === 'POST' && /\/api\/agents\/[^/]+\/chat/.test(req.url())) {
      try { chatBody = JSON.parse(req.postData() ?? 'null') } catch {}
    }
  })
  const box = page.locator('textarea').first()
  await box.fill('안녕')
  await box.press('Enter')
  await page.waitForTimeout(2500)

  log('CHAT_BODY.overrides=' + JSON.stringify(chatBody?.overrides ?? null))
  check(!!chatBody, 'chat 요청 캡처됨')
  check(chatBody?.overrides?.historyDepth === 0, `overrides.historyDepth=0 배선 (got ${chatBody?.overrides?.historyDepth})`)
  if (pickedMem) {
    const mems = chatBody?.overrides?.memories ?? []
    check(Array.isArray(mems) && mems.includes(pickedMem), `overrides.memories에 '${pickedMem}' 배선 (got ${JSON.stringify(mems)})`)
  } else {
    log('  ..  등록 메모리 블록 없음 — 장기 배선 단언 스킵')
  }

  log('\n' + (fails.length ? `FAILED ${fails.length}: ${fails.join(' | ')}` : 'ALL GREEN'))
  if (fails.length) process.exitCode = 1
} catch (e) {
  log('ERROR ' + (e?.stack ?? e))
  process.exitCode = 1
} finally {
  for (const id of cleanup.agents) { try { await page.request.delete(`${URL}/api/agents/${id}`) } catch {} }
  await browser.close()
}

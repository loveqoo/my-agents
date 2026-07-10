/* 공용 기억 컨트롤 검증 (스펙 271) — 필수 단언(UI 검증은 기능적으로, 회고 UI-verification-must-be-functional).
   ① 직접형 폼: "하는 일"에 "기억" 구획(단기+장기) 있음·"세부"엔 단기 기억 없음(이동 확인).
   ② 단기 컨트롤 쓰기 배선: 하는 일서 단기=40 설정 → 요약에 "단기 기억 40" 반영(form 상태 기록).
   ③ 노드 카드: 단기+장기 공용 컨트롤 렌더.
   ④ 저장 왕복(API): historyDepth·memories 보존(데이터 모델 무변경).

   실행: PLAYWRIGHT_DIR=<abs>/tests/e2e/node_modules/playwright \
         ADMIN_EMAIL=admin@example.com ADMIN_PASSWORD=adminpass123 \
         node tests/browser/verify-271-shared-memory.mjs */
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

async function closeModal() {
  // 폼 모달 닫기(취소 버튼 우선, 없으면 X, 그래도 남으면 Escape) + 사라질 때까지 대기.
  const cancel = page.getByRole('button', { name: /취소|닫기/ }).first()
  if (await cancel.count()) await cancel.click({ force: true }).catch(() => {})
  const x = page.locator('.ant-modal-close').first()
  if (await x.count()) await x.click({ force: true }).catch(() => {})
  await page.keyboard.press('Escape').catch(() => {})
  await page.locator('.ant-modal-wrap').first().waitFor({ state: 'hidden', timeout: 4000 }).catch(() => {})
  await page.waitForTimeout(300)
}

async function openNew(typeLabel) {
  await page.getByRole('button', { name: /새 에이전트/ }).first().click()
  await page.waitForTimeout(700)
  await page.getByPlaceholder('예: research-assistant').fill('probe-271-' + Date.now().toString(36))
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

  // ── ① 직접형: 기억 구획 위치 ──
  await openNew(null) // 기본=직접 응답
  await page.getByRole('button', { name: '다음' }).click() // 정체성 → 하는 일
  await page.waitForTimeout(500)
  const memHeaderInStep2 = await page.getByText('기억', { exact: true }).count()
  check(memHeaderInStep2 > 0, `하는 일에 "기억" 구획 헤더 있음 (found ${memHeaderInStep2})`)
  const shortInStep2 = await page.getByText('단기 기억', { exact: true }).count()
  const longInStep2 = await page.getByText('장기 기억', { exact: true }).count()
  check(shortInStep2 > 0, `하는 일에 "단기 기억" 컨트롤 있음 (found ${shortInStep2})`)
  check(longInStep2 > 0, `하는 일에 "장기 기억" 컨트롤 있음 (found ${longInStep2})`)

  // ② 단기 쓰기 배선: 단기 기억 Select를 최근 40개로 → 요약 반영
  const shortWrap = page.locator('div', { has: page.getByText('단기 기억', { exact: true }) }).filter({ has: page.locator('.ant-select') }).last()
  await shortWrap.locator('.ant-select').first().click()
  await page.waitForTimeout(300)
  await page.locator('.ant-select-dropdown:visible .ant-select-item-option', { hasText: '최근 40개 메시지' }).first().click()
  await page.waitForTimeout(300)

  await page.getByRole('button', { name: '다음' }).click() // 하는 일 → 세부
  await page.waitForTimeout(400)
  const shortInStep3 = await page.getByText('단기 기억', { exact: true }).count()
  check(shortInStep3 === 0, `세부엔 "단기 기억" 없음(하는 일로 이동) (found ${shortInStep3})`)

  await page.getByRole('button', { name: '다음' }).click() // 세부 → 요약
  await page.waitForTimeout(400)
  const summaryText = await page.locator('.ant-modal-container, body').first().innerText()
  check(/단기 기억[\s\S]{0,20}40/.test(summaryText) || summaryText.includes('최근 40개'),
    `요약에 단기 기억 40 반영(단기 컨트롤이 form 상태에 씀)`)
  await closeModal()

  // ── ③ 노드 카드: 공용 단기+장기 ──
  await openNew('노드형')
  await page.getByRole('button', { name: '다음' }).click()
  await page.waitForTimeout(500)
  await page.getByRole('button', { name: /노드 추가/ }).click()
  await page.waitForTimeout(400)
  const nodeShort = await page.getByText('단기 기억', { exact: true }).count()
  const nodeLong = await page.getByText('장기 기억', { exact: true }).count()
  check(nodeShort > 0, `노드 카드에 "단기 기억" 공용 컨트롤 (found ${nodeShort})`)
  check(nodeLong > 0, `노드 카드에 "장기 기억" 공용 컨트롤 (found ${nodeLong})`)
  await closeModal()

  // ── ④ 저장 왕복(API): 데이터 모델 무변경 ──
  const rt = await page.evaluate(async () => {
    const H = { 'Content-Type': 'application/json' }
    const jf = async (url, opt) => {
      const r = await fetch(url, { credentials: 'include', headers: H, ...opt })
      const t = await r.text(); let j = null; try { j = JSON.parse(t) } catch {}
      return { ok: r.ok, status: r.status, j, t }
    }
    const config = {
      model: 'qwen3.6-35b', persona: '', impl: '',
      historyDepth: 40, persistHistory: true, ephemeral: false,
      memories: ['장기 기억 (mem0)'], mcps: [], vectorTables: [],
    }
    const nm = 'rt-271-' + Date.now().toString(36)
    const cr = await jf('/api/agents', { method: 'POST', body: JSON.stringify({ name: nm, description: null, config }) })
    if (!cr.ok) return { step: 'create', status: cr.status, body: cr.t.slice(0, 200) }
    const got = await jf(`/api/agents/${cr.j.id}`)
    return { step: 'ok', hd: got.j?.historyDepth, mem: got.j?.memories }
  })
  log('ROUNDTRIP=' + JSON.stringify(rt))
  check(rt.step === 'ok', `저장 왕복 (step=${rt.step}${rt.body ? ' ' + rt.body : ''})`)
  check(rt.hd === 40, `historyDepth 보존 40 (got ${rt.hd})`)
  check(Array.isArray(rt.mem) && rt.mem.includes('장기 기억 (mem0)'), `memories 보존 (got ${JSON.stringify(rt.mem)})`)

  log('\n' + (fails.length ? `FAILED ${fails.length}: ${fails.join(' | ')}` : 'ALL GREEN'))
  if (fails.length) process.exitCode = 1
} catch (e) {
  log('ERROR ' + (e?.stack ?? e))
  process.exitCode = 1
} finally {
  await browser.close()
}

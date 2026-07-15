/* 스펙 359 e2e 스샷 — 노드형 회상 내용이 인스펙터 실행흐름에 MemoryRow로 렌더되는지(예전엔 카운트만).
   노드형 3노드(검색·기억확인·마무리) 에이전트를 API로 만들고, admin 스코프에 회상 쿼리(=유저 메시지)와
   동일 텍스트 기억을 시드한 상태에서 UI로 채팅→트레이스 칩 클릭→실행흐름의 회상 노드에 내용 표시.
   다해상도(1500·1100·768) 스샷 + 깨짐 확인.

   전제: 서버 8000(새 chat.py)·admin 5173(새 Inspector), admin 기억 시드(회상 쿼리와 동일 텍스트).
   실행: PLAYWRIGHT_DIR=<dir> ADMIN_EMAIL=admin@example.com ADMIN_PASSWORD=adminpass123 \
         node tests/browser/shot-recall-content-359.mjs */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium
const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const EMAIL = process.env.ADMIN_EMAIL ?? 'admin@example.com'
const PASSWORD = process.env.ADMIN_PASSWORD ?? 'adminpass123'
const OUTDIR = process.env.OUTDIR ?? '/tmp'
const NAME = 'recall359-' + Date.now().toString(36)
const MSG = '지식베이스에서 계정 생성 방법을 검색해 알려줘.'  // admin 시드 기억과 동일 → 확실한 히트

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1500, height: 1100 } })
const page = await ctx.newPage()
const log = (...a) => console.log(...a)
const fails = []
const check = (c, m) => { log((c ? '  ok  ' : ' FAIL ') + m); if (!c) fails.push(m) }

async function selectAgent(name) {
  await page.locator('button:has(.ant-avatar)').first().click()
  await page.waitForTimeout(300)
  await page.getByText(name, { exact: false }).first().click()
  await page.waitForTimeout(500)
}

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  await page.waitForTimeout(500)

  // 노드형 에이전트 생성(기억확인·마무리 노드가 user 키워드로 회상)
  const setup = await page.evaluate(async (nm) => {
    const H = { 'Content-Type': 'application/json' }
    const jf = async (url, opt) => {
      const r = await fetch(url, { credentials: 'include', headers: H, ...opt })
      const t = await r.text(); let j = null; try { j = JSON.parse(t) } catch {}
      return { ok: r.ok, status: r.status, j, t }
    }
    const config = {
      model: 'qwen3.6-35b', persona: '', impl: 'pipeline', historyDepth: 20,
      persistHistory: true, ephemeral: false, memories: ['장기 기억 (mem0)'], mcps: [], vectorTables: [],
      nodes: [
        { name: '검색', context: 'carry', model: 'qwen3.6-35b', tools: [], prompt: '질문을 간결히 파악하세요.' },
        { name: '기억확인', context: 'carry', model: 'qwen3.6-35b', tools: [], memories: ['장기 기억 (mem0)'], memoryQuery: 'user', prompt: '위 내용을 한 문장으로 요약하세요.' },
        { name: '마무리', context: 'carry', model: 'qwen3.6-35b', tools: [], memories: ['장기 기억 (mem0)'], memoryQuery: 'user', prompt: '최종 답변을 정중한 한 문단으로 정리하세요.' },
      ],
    }
    const cr = await jf('/api/agents', { method: 'POST', body: JSON.stringify({ name: nm, description: null, config }) })
    if (!cr.ok) return { step: 'create', status: cr.status, body: cr.t.slice(0, 200) }
    const draft = (cr.j.versions || []).find((v) => v.status === 'draft') || (cr.j.versions || [])[0]
    const ac = await jf(`/api/agents/${cr.j.id}/activate`, { method: 'POST', body: JSON.stringify({ version: draft?.version }) })
    if (!ac.ok) return { step: 'activate', status: ac.status }
    return { step: 'ok', id: cr.j.id }
  }, NAME)
  log('SETUP=' + JSON.stringify(setup))
  check(setup.step === 'ok', `에이전트 생성·활성 (step=${setup.step}${setup.body ? ' ' + setup.body : ''})`)
  if (setup.step !== 'ok') throw new Error('셋업 실패')

  await page.getByRole('menuitem', { name: 'Playground' }).click()
  await page.waitForTimeout(1200)
  await selectAgent(NAME)

  const box = page.locator('textarea').first()
  await box.click(); await box.fill(MSG); await page.waitForTimeout(200); await box.press('Enter')
  log('  --  전송: ' + MSG)

  const traceChip = page.getByText(/\d+\s*mem/).last()
  const arrived = await traceChip.waitFor({ state: 'visible', timeout: 120000 }).then(() => true).catch(() => false)
  check(arrived, '응답 도착(트레이스 칩 표시)')
  if (arrived) await traceChip.click({ timeout: 8000 })
  await page.waitForTimeout(600)

  // 실행 흐름 탭 활성화(있으면)
  const flowTab = page.getByRole('tab', { name: /실행 흐름/ }).first()
  if (await flowTab.isVisible().catch(() => false)) { await flowTab.click(); await page.waitForTimeout(400) }

  const bodyText = await page.locator('#root').innerText().catch(() => '')
  // C1: 회상 노드 라벨 + 내용(시드 기억 텍스트) 표시
  check(/기억 회상/.test(bodyText), 'C1: 실행흐름에 "기억 회상" 표시')
  check(bodyText.includes('계정 생성 방법'), 'C2: 회상 내용(시드 기억 텍스트) 실행흐름에 렌더(예전엔 카운트만)')
  check(!/sk-[A-Za-z0-9_-]{6,}/.test(bodyText), 'C3: 비밀 토큰 노출 없음')

  // 다해상도 스샷 — wide/mid/narrow. narrow는 드로워/모달 레이아웃.
  for (const [w, h, tag] of [[1500, 1100, 'wide'], [1100, 950, 'mid'], [768, 1000, 'narrow']]) {
    await page.setViewportSize({ width: w, height: h })
    await page.waitForTimeout(500)
    const out = `${OUTDIR}/recall359-${tag}.png`
    await page.screenshot({ path: out, fullPage: false })
    log('shot:', out)
  }

  // 정리 — 테스트 에이전트 삭제
  await page.evaluate(async (id) => {
    await fetch(`/api/agents/${id}`, { method: 'DELETE', credentials: 'include' }).catch(() => {})
  }, setup.id)
} catch (e) {
  log('ERR ' + (e?.stack ?? e))
  await page.screenshot({ path: `${OUTDIR}/recall359-error.png`, fullPage: false }).catch(() => {})
  fails.push('예외: ' + e.message)
} finally {
  await browser.close()
}
log('\n' + (fails.length ? `FAIL ${fails.length}: ${fails.join(' | ')}` : 'PASS'))
process.exit(fails.length ? 1 : 0)

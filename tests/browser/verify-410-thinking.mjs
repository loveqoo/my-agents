/* 사고 과정 표시 e2e(스펙 410) — 플레이그라운드가 thinking 응답의 사고 과정을 접이식 패널로
   보여주는지 실증. 셋업(인증 fetch): MLX 기본 chat 모델의 thinking 능력 켜기 + 단건(stream=off)
   thinking 에이전트 생성 → 채팅 → '사고 과정'(@ant-design/x Think) 패널 등장 단언 → 정리(복원).

   실행: PLAYWRIGHT_DIR=<abs>/tests/e2e/node_modules/playwright node tests/browser/verify-410-thinking.mjs [out.png] */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium
const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password
const OUT = process.argv[2] ?? '/tmp/verify-410-thinking.png'

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } })
const page = await ctx.newPage()
const fails = []
const ok = (cond, msg) => { console.log((cond ? '  ok  ' : ' FAIL ') + msg); if (!cond) fails.push(msg) }
let created = null // { agentId, modelId, origCaps }
try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.waitForTimeout(1500)

  // 셋업(인증 fetch, 같은 출처 /api 프록시): MLX chat 모델 thinking 능력 ON + 단건 thinking 에이전트.
  created = await page.evaluate(async () => {
    const j = (r) => r.json()
    const models = await fetch('/api/models?kind=chat', { credentials: 'include' }).then(j)
    // 기본 chat(MLX) 우선, 없으면 첫 원격 chat.
    const mlx = models.find((m) => m.is_default) ?? models.find((m) => m.provider_kind === 'remote') ?? models[0]
    const origCaps = { ...(mlx.capabilities ?? {}) }
    await fetch(`/api/models/${mlx.id}`, {
      method: 'PUT', credentials: 'include', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: mlx.name, provider_id: mlx.provider_id, model_id: mlx.model_id,
        kind: mlx.kind, is_default: mlx.is_default, params: mlx.params ?? {},
        capabilities: { ...origCaps, thinking: true }, meta: mlx.meta ?? {} }),
    })
    const ag = await fetch('/api/agents', {
      method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
      // 스트리밍 모드(stream 미설정=기본 켜짐) — 서버가 reasoning을 델타로 실시간 스트리밍(스펙 410).
      body: JSON.stringify({ name: 'v410-thinking', config: { model: mlx.name,
        modelParams: { enable_thinking: true } } }),
    }).then(j)
    return { agentId: ag.id, modelId: mlx.id, origCaps }
  })
  ok(!!created?.agentId, '셋업: 단건 thinking 에이전트 생성')

  // 플레이그라운드 이동 + 에이전트 선택.
  const pg = page.getByText('Playground', { exact: true }).first()
  if (!(await pg.isVisible().catch(() => false))) { await page.locator('button').first().click(); await page.waitForTimeout(500) }
  await pg.waitFor({ timeout: 10000 }); await pg.click(); await page.waitForTimeout(2000)
  const already = await page.getByText('v410-thinking', { exact: false }).first().isVisible().catch(() => false)
  if (!already) {
    await page.locator('button').filter({ hasText: /원격|코드 정의|기본|노드/ }).first().click()
    await page.getByText('v410-thinking', { exact: false }).last().click()
    await page.waitForTimeout(1200)
  }
  // 사고를 유발하는 프롬프트 전송(단건이라 완성까지 시간 소요 — 넉넉히 대기).
  const input = page.getByPlaceholder(/에게 메시지/)
  // 다단계 추론을 확실히 유발하는 문제(rapid-mlx는 유휴 후 첫 요청에서 사고 — 방정식 문제로 유도).
  await input.fill('농장에 닭과 소가 합쳐 43마리, 다리는 총 116개다. 각각 몇 마리인지 방정식을 세워 단계적으로 풀어라.')
  await input.press('Enter')
  console.log('step: 사고 과정 패널 대기(단건 생성 — 최대 180s)')
  await page.getByText('사고 과정', { exact: false }).first().waitFor({ timeout: 180000 })
  ok(true, "① '사고 과정' 패널 등장(@ant-design/x Think — thinking 응답)")
  // 펼쳐 내용 확인.
  await page.getByText('사고 과정', { exact: false }).first().click().catch(() => {})
  await page.waitForTimeout(800)
  await page.screenshot({ path: OUT, fullPage: false })
  console.log('SHOT', OUT)
} catch (e) {
  ok(false, `예외: ${e.message}`)
  await page.screenshot({ path: OUT, fullPage: false }).catch(() => {})
} finally {
  // 정리: 에이전트 삭제 + 모델 능력 원복.
  if (created?.agentId) {
    await page.evaluate(async (c) => {
      await fetch(`/api/agents/${c.agentId}`, { method: 'DELETE', credentials: 'include' }).catch(() => {})
      const models = await fetch('/api/models?kind=chat', { credentials: 'include' }).then((r) => r.json()).catch(() => [])
      const m = models.find((x) => x.id === c.modelId)
      if (m) await fetch(`/api/models/${c.modelId}`, { method: 'PUT', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: m.name, provider_id: m.provider_id, model_id: m.model_id, kind: m.kind,
          is_default: m.is_default, params: m.params ?? {}, capabilities: c.origCaps, meta: m.meta ?? {} }) }).catch(() => {})
    }, created).catch(() => {})
  }
  await browser.close()
}
console.log(fails.length ? `VERIFY410_BROWSER_FAIL(${fails.length})` : 'VERIFY410_BROWSER_OK')
process.exit(fails.length ? 1 : 0)

/* 노드별 단기 기억 창 실검증 (스펙 270) — 필수 단언(learning 151).
   3노드 depth [0, 2, 상속(null→에이전트 20)], 대화 3개(이전 2 + 현재 1) 전송.
   기대 historyWindows count = [0, 1, 2](_window(conv,d)[:-1] — 현재 턴 분리):
     depth0→conv[-1:][:-1]=[]=0 / depth2→conv[-2:][:-1]=1 / 상속20→conv[:-1]=2.
   + 시드 축소 무회귀: 파이프라인이 정상 실행(그래프 노드·응답 수신).

   실행: PLAYWRIGHT_DIR=<abs>/tests/e2e/node_modules/playwright \
         ADMIN_EMAIL=admin@example.com ADMIN_PASSWORD=adminpass123 \
         node tests/browser/verify-270-history.mjs */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium
const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const EMAIL = process.env.ADMIN_EMAIL ?? 'admin@example.com'
const PASSWORD = process.env.ADMIN_PASSWORD ?? 'adminpass123'
const NAME = 'hist-270-' + Date.now().toString(36)

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } })
const page = await ctx.newPage()
const log = (...a) => console.log(...a)
const fails = []
const check = (c, m) => { log((c ? '  ok  ' : ' FAIL ') + m); if (!c) fails.push(m) }

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  await page.waitForTimeout(500)

  const setup = await page.evaluate(async (nm) => {
    const H = { 'Content-Type': 'application/json' }
    const jf = async (url, opt) => {
      const r = await fetch(url, { credentials: 'include', headers: H, ...opt })
      const t = await r.text(); let j = null; try { j = JSON.parse(t) } catch {}
      return { ok: r.ok, status: r.status, j, t }
    }
    const config = {
      model: 'qwen3.6-35b', persona: '', impl: 'pipeline',
      historyDepth: 20, persistHistory: false, ephemeral: false,
      memories: [], mcps: [], vectorTables: [],
      nodes: [
        { name: '무이력', context: 'carry', model: 'qwen3.6-35b', tools: [], historyDepth: 0, prompt: '한 문장으로 답하세요.' },
        { name: '조금', context: 'carry', model: 'qwen3.6-35b', tools: [], historyDepth: 2, prompt: '한 문장으로 답하세요.' },
        { name: '상속', context: 'carry', model: 'qwen3.6-35b', tools: [], prompt: '한 문장으로 답하세요.' },
      ],
    }
    const cr = await jf('/api/agents', { method: 'POST', body: JSON.stringify({ name: nm, description: null, config }) })
    if (!cr.ok) return { step: 'create', status: cr.status, body: cr.t.slice(0, 200) }
    const draft = (cr.j.versions || []).find((v) => v.status === 'draft') || (cr.j.versions || [])[0]
    const ac = await jf(`/api/agents/${cr.j.id}/activate`, { method: 'POST', body: JSON.stringify({ version: draft?.version }) })
    if (!ac.ok) return { step: 'activate', status: ac.status }
    const got = await jf(`/api/agents/${cr.j.id}`)
    return { step: 'ok', id: cr.j.id, hds: (got.j?.nodes || []).map((n) => n.historyDepth ?? null) }
  }, NAME)
  log('SETUP=' + JSON.stringify(setup))
  check(setup.step === 'ok', `생성·활성 (step=${setup.step}${setup.body ? ' ' + setup.body : ''})`)
  // 왕복: 노드 historyDepth 보존(0·2·미지정=null)
  check(JSON.stringify(setup.hds) === JSON.stringify([0, 2, null]), `왕복: 노드 historyDepth 보존 (got ${JSON.stringify(setup.hds)})`)
  if (setup.step !== 'ok') throw new Error('셋업 실패')

  const chat = await page.evaluate(async (id) => {
    const res = await fetch(`/api/agents/${id}/chat`, {
      method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages: [
        { role: 'user', content: '내 이름은 홍길동이야.' },
        { role: 'assistant', content: '네, 홍길동님 반갑습니다.' },
        { role: 'user', content: '방금 대화를 요약해줘.' },
      ] }),
    })
    if (!res.ok) return { error: 'status ' + res.status + ' ' + (await res.text()).slice(0, 200) }
    const reader = res.body.getReader(); const dec = new TextDecoder()
    let buf = '', out = '', trace = null, err = null
    for (;;) {
      const { value, done } = await reader.read(); if (done) break
      buf += dec.decode(value, { stream: true })
      const frames = buf.split('\n\n'); buf = frames.pop() ?? ''
      for (const f of frames) {
        const lines = f.split('\n')
        const ev = lines.find((l) => l.startsWith('event: '))?.slice(7)
        const dl = lines.find((l) => l.startsWith('data: ')); if (!dl) continue
        const d = dl.slice(6); if (d === '[DONE]') continue
        try {
          const p = JSON.parse(d)
          if (ev === 'trace') trace = p
          else if (typeof p.text === 'string') out += p.text
          else if (typeof p.error === 'string') err = p.error
        } catch {}
      }
    }
    return {
      outLen: out.length,
      graph: (trace?.graph || []).map((g) => g.node),
      hw: trace?.historyWindows ?? null,
      err, latencyMs: trace?.latencyMs,
    }
  }, setup.id)
  log('CHAT=' + JSON.stringify(chat).slice(0, 1200))
  check(!chat.error && !chat.err, `chat 오류 없음 (${chat.error ?? chat.err ?? 'none'})`)
  // 무회귀: 시드 축소에도 파이프라인 3노드 정상 실행 + 응답 수신
  check((chat.outLen ?? 0) > 0, `응답 수신(${chat.outLen}자, ${chat.latencyMs}ms) — 시드 축소 무회귀`)
  check(['무이력', '조금', '상속'].every((n) => (chat.graph || []).includes(n)), `3노드 전부 실행 (got ${JSON.stringify(chat.graph)})`)
  // 핵심: historyWindows 노드별 count = [0, 1, 2]
  const hw = chat.hw || []
  check(hw.length === 3, `historyWindows 3건(노드마다) (got ${hw.length})`)
  const byNode = Object.fromEntries(hw.map((h) => [h.node, h]))
  check(byNode['무이력']?.count === 0, `depth0 노드 대화 0개 (got ${byNode['무이력']?.count})`)
  check(byNode['조금']?.count === 1, `depth2 노드 대화 1개 (got ${byNode['조금']?.count})`)
  check(byNode['상속']?.count === 2, `상속(20) 노드 대화 2개=이전 전부 (got ${byNode['상속']?.count})`)
  check(byNode['무이력']?.depth === 0 && byNode['조금']?.depth === 2 && byNode['상속']?.depth === 20,
    `depth 기록(상속=에이전트 20 해석) (got ${JSON.stringify(hw.map((h) => [h.node, h.depth]))})`)

  log('\n' + (fails.length ? `FAILED ${fails.length}: ${fails.join(' | ')}` : 'ALL GREEN'))
  if (fails.length) process.exitCode = 1
} catch (e) {
  log('ERROR ' + (e?.stack ?? e))
  process.exitCode = 1
} finally {
  await browser.close()
}

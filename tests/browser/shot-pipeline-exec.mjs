/* 노드형 execute e2e (스펙 259-261 #1) — 시스템 Chrome.
   admin 로그인 → 브라우저 세션 fetch로: 파이프라인 에이전트(2노드 carry→clean, JSON) 생성 →
   활성화 → chat SSE → 트레이스에서 노드가 순서대로 실행됐는지 확인(플랫폼 모델 해석+실 그래프 왕복).
   mock-llm은 canned라 내용은 결정적이지 않지만, "2노드가 순서대로 돌고 크래시 0"이 통합 rung의 핵심.

   실행: PLAYWRIGHT_DIR=<abs>/tests/e2e/node_modules/playwright \
         ADMIN_EMAIL=admin@example.com ADMIN_PASSWORD=adminpass123 \
         node tests/browser/shot-pipeline-exec.mjs */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium
const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const EMAIL = process.env.ADMIN_EMAIL ?? 'admin@example.com'
const PASSWORD = process.env.ADMIN_PASSWORD ?? 'adminpass123'
const NAME = 'pipe-exec-' + Date.now().toString(36)

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ viewport: { width: 1280, height: 1000 } })
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

  const result = await page.evaluate(async (nm) => {
    const H = { 'Content-Type': 'application/json' }
    const jf = async (url, opt) => {
      const r = await fetch(url, { credentials: 'include', headers: H, ...opt })
      const t = await r.text()
      let j = null; try { j = JSON.parse(t) } catch {}
      return { ok: r.ok, status: r.status, j, t }
    }
    // 1) 생성 — 2노드(분석 carry / 요약 clean, JSON+키)
    const config = {
      model: 'mock-llm', prompt: '', impl: 'pipeline',
      historyDepth: 20, persistHistory: true, ephemeral: false,
      nodes: [
        { name: '분석', prompt: '입력을 분석하라', model: 'mock-llm', tools: [], context: 'carry' },
        { name: '요약', prompt: '요약하라', model: 'mock-llm', tools: [], context: 'clean', format: 'json', fields: ['summary'] },
      ],
    }
    const cr = await jf('/api/agents', { method: 'POST', body: JSON.stringify({ name: nm, description: null, config }) })
    if (!cr.ok) return { step: 'create', status: cr.status, body: cr.t.slice(0, 300) }
    const id = cr.j.id
    const draft = (cr.j.versions || []).find((v) => v.status === 'draft') || (cr.j.versions || [])[0]
    const ver = draft?.version
    // 2) 활성화
    const ac = await jf(`/api/agents/${id}/activate`, { method: 'POST', body: JSON.stringify({ version: ver }) })
    if (!ac.ok) return { step: 'activate', status: ac.status, body: ac.t.slice(0, 300), id, ver }
    // 3) chat SSE
    const res = await fetch(`/api/agents/${id}/chat`, {
      method: 'POST', credentials: 'include', headers: H,
      body: JSON.stringify({ messages: [{ role: 'user', content: '테스트 입력입니다. 분석하고 요약해줘.' }] }),
    })
    if (!res.ok) return { step: 'chat', status: res.status, body: (await res.text()).slice(0, 300), id }
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
    return { step: 'ok', id, ver, out, trace, err }
  }, NAME)

  log('RESULT=' + JSON.stringify(result).slice(0, 1200))
  check(result.step === 'ok', `실행 완료 단계 도달 (step=${result.step}${result.status ? ' status=' + result.status : ''})`)
  check(!result.err, `chat 오류 없음 (err=${result.err ?? 'none'})`)
  // 트레이스 그래프 — 선언 노드(분석·요약)가 순서대로 실행됐나(trace.graph[].node)
  const graph = Array.isArray(result.trace?.graph) ? result.trace.graph : []
  const nodeSeq = graph.map((g) => g.node)
  log('GRAPH_NODES=' + JSON.stringify(nodeSeq))
  const iA = nodeSeq.indexOf('분석'), iS = nodeSeq.indexOf('요약')
  check(iA >= 0 && iS >= 0, `트레이스에 두 노드(분석·요약) 실행 (got ${JSON.stringify(nodeSeq)})`)
  check(iA >= 0 && iS > iA, `노드 순서 보존(분석→요약, iA=${iA} iS=${iS})`)
  // clean 격리 흔적: 요약 노드 summary에 remove(이전 대화 제거) 흔적
  const sumNode = graph.find((g) => g.node === '요약')
  check(!!sumNode && /remove/i.test(sumNode.summary || ''), `clean 격리 실행(요약 노드 RemoveMessage 흔적)`)
  check(typeof result.out === 'string' && result.out.length > 0, `응답 텍스트 수신(길이 ${result.out?.length ?? 0})`)

  log('\n' + (fails.length ? `FAILED ${fails.length}: ${fails.join(' | ')}` : 'ALL GREEN'))
  if (fails.length) process.exitCode = 1
} catch (e) {
  log('ERROR ' + (e?.stack ?? e))
  process.exitCode = 1
} finally {
  await browser.close()
}

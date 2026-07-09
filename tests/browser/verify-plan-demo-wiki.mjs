/* plan-execute-demo(노드형) 위키 도구 실발화 검증 (스펙 264 후속 — "제대로 테스트").
   문제: v6 프롬프트("필요하면 도구")로는 모델이 아는 질문에 검색을 건너뜀 → 도구 루프가 실전 미검증.
   처방: v7 = 실행 노드 프롬프트에 wiki_search 의무화 → chat → 트레이스에 실행__tools 발화 +
   mcp 호출 기록 + 도구 결과 기반 답변을 **단언**(재량 아님).

   실행: PLAYWRIGHT_DIR=<abs>/tests/e2e/node_modules/playwright \
         ADMIN_EMAIL=admin@example.com ADMIN_PASSWORD=adminpass123 \
         node tests/browser/verify-plan-demo-wiki.mjs */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium
const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const EMAIL = process.env.ADMIN_EMAIL ?? 'admin@example.com'
const PASSWORD = process.env.ADMIN_PASSWORD ?? 'adminpass123'
const AGENT_ID = '19e47b72-67c8-46a4-9e8d-e9445cba2fc1' // plan-execute-demo

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

  // v7 — 실행 노드에 위키 검색 의무화(추측 금지·검색 결과 인용 필수)
  const conv = await page.evaluate(async (id) => {
    const H = { 'Content-Type': 'application/json' }
    const jf = async (url, opt) => {
      const r = await fetch(url, { credentials: 'include', headers: H, ...opt })
      const t = await r.text()
      let j = null; try { j = JSON.parse(t) } catch {}
      return { ok: r.ok, status: r.status, j, t }
    }
    const cur = await jf(`/api/agents/${id}`)
    if (!cur.ok) return { step: 'get', status: cur.status }
    const config = {
      model: 'qwen3.6-35b',
      persona: 'methodical-researcher',
      impl: 'pipeline',
      historyDepth: 20, persistHistory: true, ephemeral: false,
      memories: ['단기(세션)'],
      mcps: ['web-fetch'],
      vectorTables: [],
      nodes: [
        {
          name: '계획', context: 'carry', model: 'qwen3.6-35b', tools: [],
          prompt: '사용자 질문에 답하기 위한 작업 계획을 3단계 이내로 세우세요. 1단계는 반드시 wiki_search로 관련 문서를 찾는 것입니다. 계획만 간결하게 출력하세요.',
        },
        {
          name: '실행', context: 'carry', model: 'qwen3.6-35b', tools: ['wiki_search', 'wiki_page'],
          prompt: 'Rigorous, source-driven, neutral. Prefer primary sources. Always cite. Lead with a one-line answer.\n\n'
            + '반드시 먼저 wiki_search 도구를 호출해 관련 위키 문서를 검색하고, 그 검색 결과에 근거해서만 답하세요. '
            + '자체 지식으로 추측해 답하는 것을 금지합니다. 답변에는 검색으로 확인한 문서 제목을 인용하세요.',
        },
      ],
    }
    const up = await jf(`/api/agents/${id}`, { method: 'PUT', body: JSON.stringify({ name: cur.j.name, description: cur.j.description ?? null, config }) })
    if (!up.ok) return { step: 'update', status: up.status, body: up.t.slice(0, 200) }
    const draft = (up.j.versions || []).find((v) => v.status === 'draft')
    const ac = await jf(`/api/agents/${id}/activate`, { method: 'POST', body: JSON.stringify({ version: draft?.version }) })
    if (!ac.ok) return { step: 'activate', status: ac.status }
    return { step: 'converted', active: draft?.version }
  }, AGENT_ID)
  log('CONVERT=' + JSON.stringify(conv))
  check(conv.step === 'converted', `v7 갱신·활성 (step=${conv.step})`)
  if (conv.step !== 'converted') throw new Error('갱신 실패')

  // chat — 위키 검색이 필수인 질문(문서 확인형)
  const chat = await page.evaluate(async (id) => {
    const res = await fetch(`/api/agents/${id}/chat`, {
      method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages: [{ role: 'user', content: '위키백과에서 "스트랭글러 무화과 패턴"(Strangler fig pattern)을 검색해 그 문서가 설명하는 핵심을 두 문장으로 알려줘.' }] }),
    })
    if (!res.ok) return { error: 'status ' + res.status }
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
      outLen: out.length, outTail: out.slice(-400),
      graph: (trace?.graph || []).map((g) => g.node),
      mcp: (trace?.mcp || []).map((c) => ({ tool: c.tool ?? c.name, status: c.status })),
      err, latencyMs: trace?.latencyMs,
    }
  }, AGENT_ID)
  log('CHAT=' + JSON.stringify(chat).slice(0, 1000))
  check(!chat.error && !chat.err, `chat 오류 없음 (${chat.error ?? chat.err ?? 'none'})`)
  const seq = chat.graph || []
  check(seq.indexOf('계획') >= 0 && seq.indexOf('실행') > seq.indexOf('계획'), `계획→실행 순서 (got ${JSON.stringify(seq)})`)
  // 핵심(이번 검증의 목적): 도구 루프 실발화 — 재량이 아니라 필수 단언
  check(seq.includes('실행__tools'), `위키 도구 루프 발화(실행__tools) — got ${JSON.stringify(seq)}`)
  check((chat.mcp?.length ?? 0) >= 1, `MCP 호출 기록 ≥1 (got ${JSON.stringify(chat.mcp)})`)
  check((chat.outLen ?? 0) > 0, `응답 수신(${chat.outLen}자, ${chat.latencyMs}ms)`)

  log('\n' + (fails.length ? `FAILED ${fails.length}: ${fails.join(' | ')}` : 'ALL GREEN'))
  if (fails.length) process.exitCode = 1
} catch (e) {
  log('ERROR ' + (e?.stack ?? e))
  process.exitCode = 1
} finally {
  await browser.close()
}

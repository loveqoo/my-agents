/* plan-execute-demo를 노드형(impl=pipeline)으로 전환하고 실모델로 동작 테스트 (스펙 264).
   admin 로그인 → PUT /agents/{id}(v6 초안: 계획→실행 2노드, wiki 도구, 프롬프트 본문 내장) →
   activate → chat SSE(실모델 qwen3.6-35b) → 트레이스 그래프에 계획→실행 순서·토큰 수신 단언.
   가역: v5 보존(revert 가능).

   실행: PLAYWRIGHT_DIR=<abs>/tests/e2e/node_modules/playwright \
         ADMIN_EMAIL=admin@example.com ADMIN_PASSWORD=adminpass123 \
         node tests/browser/convert-plan-demo-pipeline.mjs */
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

  const result = await page.evaluate(async (id) => {
    const H = { 'Content-Type': 'application/json' }
    const jf = async (url, opt) => {
      const r = await fetch(url, { credentials: 'include', headers: H, ...opt })
      const t = await r.text()
      let j = null; try { j = JSON.parse(t) } catch {}
      return { ok: r.ok, status: r.status, j, t }
    }
    // 현재 상태 확인
    const cur = await jf(`/api/agents/${id}`)
    if (!cur.ok) return { step: 'get', status: cur.status }
    const prevActive = cur.j.activeVersion
    // 노드형 전환 config — 계획(모델이 진짜 계획 수립)→실행(프롬프트 내장+wiki 도구). carry 둘 다
    // (실행은 원 질문+계획 둘 다 봐야 함). mcps는 노드 도구 합집합(web-fetch).
    const config = {
      model: 'qwen3.6-35b',
      prompt: 'methodical-researcher', // 206 보존(노드형에선 미사용)
      impl: 'pipeline',
      historyDepth: 20, persistHistory: true, ephemeral: false,
      memories: ['단기(세션)'],
      mcps: ['web-fetch'],
      vectorTables: [],
      nodes: [
        {
          name: '계획', context: 'carry', model: 'qwen3.6-35b', tools: [],
          prompt: '사용자 질문에 답하기 위한 작업 계획을 3단계 이내로 세우세요. 필요하면 위키 검색(wiki_search·wiki_page) 활용 단계를 포함하세요. 계획만 간결하게 출력하세요.',
        },
        {
          name: '실행', context: 'carry', model: 'qwen3.6-35b', tools: ['wiki_search', 'wiki_page'],
          prompt: 'Rigorous, source-driven, neutral. Prefer primary sources. Always cite. Lead with a one-line answer.\n\n위 대화의 작업 계획에 따라 사용자 질문에 답하세요.',
        },
      ],
    }
    const up = await jf(`/api/agents/${id}`, { method: 'PUT', body: JSON.stringify({ name: cur.j.name, description: cur.j.description ?? null, config }) })
    if (!up.ok) return { step: 'update', status: up.status, body: up.t.slice(0, 300) }
    const draft = (up.j.versions || []).find((v) => v.status === 'draft')
    if (!draft) return { step: 'no-draft', versions: (up.j.versions || []).map((v) => v.version + ':' + v.status) }
    const ac = await jf(`/api/agents/${id}/activate`, { method: 'POST', body: JSON.stringify({ version: draft.version }) })
    if (!ac.ok) return { step: 'activate', status: ac.status, body: ac.t.slice(0, 300) }
    return { step: 'converted', prevActive, newActive: draft.version, impl: ac.j.impl, nodes: ac.j.nodes?.length }
  }, AGENT_ID)
  log('CONVERT=' + JSON.stringify(result))
  check(result.step === 'converted', `전환 완료 (step=${result.step}${result.status ? ' ' + result.status : ''}${result.body ? ' ' + result.body : ''})`)
  if (result.step !== 'converted') throw new Error('전환 실패 — 중단')
  log(`  --  ${result.prevActive} → ${result.newActive} 활성(되돌리기 가능)`)

  // 실모델 chat 테스트 — 계획→실행이 실제 순서로 도는지(실모델이라 오래 걸릴 수 있음).
  const chat = await page.evaluate(async (id) => {
    const res = await fetch(`/api/agents/${id}/chat`, {
      method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages: [{ role: 'user', content: '파이썬(프로그래밍 언어)이 무엇인지 위키에서 확인해 한 문단으로 답해줘.' }] }),
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
    return { outLen: out.length, outHead: out.slice(0, 300), graph: (trace?.graph || []).map((g) => g.node), err, latencyMs: trace?.latencyMs }
  }, AGENT_ID)
  log('CHAT=' + JSON.stringify(chat).slice(0, 900))
  check(!chat.error && !chat.err, `chat 오류 없음 (err=${chat.error ?? chat.err ?? 'none'})`)
  const seq = chat.graph || []
  const iP = seq.indexOf('계획'), iE = seq.indexOf('실행')
  check(iP >= 0 && iE > iP, `트레이스: 계획→실행 순서 실행 (got ${JSON.stringify(seq)})`)
  check((chat.outLen ?? 0) > 0, `실모델 응답 수신(${chat.outLen}자, ${chat.latencyMs}ms)`)
  const toolFired = seq.includes('실행__tools')
  log(`  --  wiki 도구 발화: ${toolFired ? 'YES(실행__tools)' : 'no(모델 재량 — 강제 아님)'}`)

  log('\n' + (fails.length ? `FAILED ${fails.length}: ${fails.join(' | ')}` : 'ALL GREEN'))
  if (fails.length) process.exitCode = 1
} catch (e) {
  log('ERROR ' + (e?.stack ?? e))
  process.exitCode = 1
} finally {
  await browser.close()
}

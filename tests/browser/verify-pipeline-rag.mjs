/* 노드형 RAG(search_documents) 실발화 검증 (스펙 265 후속 — RAG 축).
   learning 151: 도구 축은 "실제 발화하는 픽스처 + 호출 기록 단언"으로. 위키(MCP)에 이어 RAG.
   노드형 에이전트(문서답변 1노드, tools=['search_documents'], 실모델 qwen) 생성→활성→chat →
   트레이스에 도구 노드 발화 + search_documents 호출 기록 + 문서 근거 답변을 필수 단언.
   search_documents는 무접두 이름(265 T2b — 정확 일치 경로).

   실행: PLAYWRIGHT_DIR=<abs>/tests/e2e/node_modules/playwright \
         ADMIN_EMAIL=admin@example.com ADMIN_PASSWORD=adminpass123 \
         node tests/browser/verify-pipeline-rag.mjs */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium
const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const EMAIL = process.env.ADMIN_EMAIL ?? 'admin@example.com'
const PASSWORD = process.env.ADMIN_PASSWORD ?? 'adminpass123'
const NAME = 'rag-node-' + Date.now().toString(36)

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
      const t = await r.text()
      let j = null; try { j = JSON.parse(t) } catch {}
      return { ok: r.ok, status: r.status, j, t }
    }
    const config = {
      model: 'qwen3.6-35b', prompt: '', impl: 'pipeline',
      historyDepth: 20, persistHistory: true, ephemeral: false,
      memories: [], mcps: [], vectorTables: ['docs-kb'],
      nodes: [
        {
          name: '문서답변', context: 'carry', model: 'qwen3.6-35b', tools: ['search_documents'],
          prompt: '반드시 먼저 search_documents 도구로 지식베이스를 검색하고, 검색된 문서 내용에 근거해서만 답하세요. '
            + '자체 지식으로 추측해 답하는 것을 금지합니다. 근거 문서의 표현을 인용하세요.',
        },
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
  check(setup.step === 'ok', `노드형 RAG 에이전트 생성·활성 (step=${setup.step})`)
  if (setup.step !== 'ok') throw new Error('셋업 실패')

  const chat = await page.evaluate(async (id) => {
    const res = await fetch(`/api/agents/${id}/chat`, {
      method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages: [{ role: 'user', content: '지식베이스에서 계정 생성과 첫 로그인 방법을 검색해 문서 내용대로 알려줘.' }] }),
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
      outLen: out.length, outTail: out.slice(-350),
      graph: (trace?.graph || []).map((g) => g.node),
      mcp: trace?.mcp ?? [], rag: trace?.rag ?? null,
      traceKeys: trace ? Object.keys(trace) : [],
      err, latencyMs: trace?.latencyMs,
    }
  }, setup.id)
  log('CHAT=' + JSON.stringify(chat).slice(0, 1100))
  check(!chat.error && !chat.err, `chat 오류 없음 (${chat.error ?? chat.err ?? 'none'})`)
  const seq = chat.graph || []
  // 필수 단언(재량 아님): RAG 도구 노드 발화 + 호출 기록 + 문서 근거 답변
  check(seq.includes('문서답변__tools'), `RAG 도구 노드 발화(문서답변__tools) — got ${JSON.stringify(seq)}`)
  const calls = [...(chat.mcp || []), ...((chat.rag && Array.isArray(chat.rag)) ? chat.rag : [])]
  const ragCalled = JSON.stringify(chat).includes('search_documents')
  check(ragCalled, `search_documents 호출 기록 존재 (mcp=${JSON.stringify(chat.mcp).slice(0, 120)} rag=${JSON.stringify(chat.rag).slice(0, 120)})`)
  // 문서 근거: docs-kb 청크 고유 표현("가입 페이지"·"이메일과 비밀번호")이 답에 반영됐나
  const grounded = /가입 페이지|이메일과 비밀번호/.test(chat.outTail) || /가입 페이지|이메일과 비밀번호/.test(JSON.stringify(chat))
  check(grounded, `문서 근거 답변(docs-kb 청크 표현 반영) — tail: ${chat.outTail.slice(0, 120)}`)
  check((chat.outLen ?? 0) > 0, `응답 수신(${chat.outLen}자, ${chat.latencyMs}ms)`)

  log('\n' + (fails.length ? `FAILED ${fails.length}: ${fails.join(' | ')}` : 'ALL GREEN'))
  if (fails.length) process.exitCode = 1
} catch (e) {
  log('ERROR ' + (e?.stack ?? e))
  process.exitCode = 1
} finally {
  await browser.close()
}

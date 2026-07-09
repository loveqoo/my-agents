/* 노드별 RAG 컬렉션 스코프 + 캐싱 회상 프록시 실검증 (스펙 268) — 필수 단언(learning 151).
   3노드: n1=docs-kb만 검색(컬렉션별 도구), n2=기억 회상(user 키워드), n3=기억 회상(user 키워드 — 캐시
   공유 기대). 실모델 chat → 트레이스에서 (a) rag 호출의 tool명=search_documents__docs-kb·hitsDetail
   전부 docs-kb, (b) memoryRecalls 2건 중 2번째 cached=true, (c) 회상 노드 귀속을 단언.

   실행: PLAYWRIGHT_DIR=<abs>/tests/e2e/node_modules/playwright \
         ADMIN_EMAIL=admin@example.com ADMIN_PASSWORD=adminpass123 \
         node tests/browser/verify-pipeline-268.mjs */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium
const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const EMAIL = process.env.ADMIN_EMAIL ?? 'admin@example.com'
const PASSWORD = process.env.ADMIN_PASSWORD ?? 'adminpass123'
const NAME = 'pnode-268-' + Date.now().toString(36)

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
      model: 'qwen3.6-35b', persona: '', impl: 'pipeline',
      historyDepth: 20, persistHistory: true, ephemeral: false,
      memories: ['장기 기억 (mem0)'], mcps: [], vectorTables: ['docs-kb'],
      nodes: [
        {
          name: '검색', context: 'carry', model: 'qwen3.6-35b',
          tools: ['search_documents__docs-kb'],
          prompt: '반드시 먼저 search_documents__docs-kb 도구로 지식베이스를 검색하고, 검색 결과에 근거해 간결히 답하세요.',
        },
        {
          name: '기억확인', context: 'carry', model: 'qwen3.6-35b', tools: [],
          memories: ['장기 기억 (mem0)'], memoryQuery: 'user',
          prompt: '위 내용을 한 문장으로 요약하세요.',
        },
        {
          name: '마무리', context: 'carry', model: 'qwen3.6-35b', tools: [],
          memories: ['장기 기억 (mem0)'], memoryQuery: 'user',
          prompt: '최종 답변을 정중한 한 문단으로 정리하세요.',
        },
      ],
    }
    const cr = await jf('/api/agents', { method: 'POST', body: JSON.stringify({ name: nm, description: null, config }) })
    if (!cr.ok) return { step: 'create', status: cr.status, body: cr.t.slice(0, 200) }
    const draft = (cr.j.versions || []).find((v) => v.status === 'draft') || (cr.j.versions || [])[0]
    const ac = await jf(`/api/agents/${cr.j.id}/activate`, { method: 'POST', body: JSON.stringify({ version: draft?.version }) })
    if (!ac.ok) return { step: 'activate', status: ac.status }
    // 왕복: 노드 memories/memoryQuery 보존 확인
    const got = await jf(`/api/agents/${cr.j.id}`)
    return { step: 'ok', id: cr.j.id, n2mem: got.j?.nodes?.[1]?.memories, n2q: got.j?.nodes?.[1]?.memoryQuery, vt: got.j?.vectorTables }
  }, NAME)
  log('SETUP=' + JSON.stringify(setup))
  check(setup.step === 'ok', `생성·활성 (step=${setup.step}${setup.body ? ' ' + setup.body : ''})`)
  check(Array.isArray(setup.n2mem) && setup.n2mem.length === 1 && setup.n2q === 'user', `왕복: 노드 memories/memoryQuery 보존 (got ${JSON.stringify(setup.n2mem)}/${setup.n2q})`)
  if (setup.step !== 'ok') throw new Error('셋업 실패')

  const chat = await page.evaluate(async (id) => {
    const res = await fetch(`/api/agents/${id}/chat`, {
      method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages: [{ role: 'user', content: '지식베이스에서 계정 생성 방법을 검색해 알려줘.' }] }),
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
      outLen: out.length,
      graph: (trace?.graph || []).map((g) => g.node),
      rag: (trace?.mcp || []).filter((c) => c.server === 'rag').map((c) => ({ tool: c.tool, hits: c.hits, cols: [...new Set((c.hitsDetail || []).map((h) => h.collection ?? h.col ?? ''))] })),
      recalls: trace?.memoryRecalls ?? null,
      err, latencyMs: trace?.latencyMs,
    }
  }, setup.id)
  log('CHAT=' + JSON.stringify(chat).slice(0, 1000))
  check(!chat.error && !chat.err, `chat 오류 없음 (${chat.error ?? chat.err ?? 'none'})`)
  // (a) 컬렉션 스코프 — 검색 도구명이 컬렉션별이고 히트가 docs-kb만
  const rag0 = chat.rag?.[0]
  check(!!rag0 && rag0.tool === 'search_documents__docs-kb', `P1: rag 호출 도구=search_documents__docs-kb (got ${rag0?.tool})`)
  check(!!rag0 && rag0.cols.every((c) => !c || c === 'docs-kb'), `P1: 히트 전부 docs-kb 스코프 (got ${JSON.stringify(rag0?.cols)})`)
  check((chat.graph || []).includes('검색__tools'), `P1: 검색 노드 도구 루프 발화 (got ${JSON.stringify(chat.graph)})`)
  // (b) 회상 프록시 — 2노드 회상, 같은 키워드라 2번째 cached
  const rc = chat.recalls || []
  check(rc.length === 2, `P2: memoryRecalls 2건 (got ${rc.length})`)
  check(rc[0]?.cached === false && rc[1]?.cached === true, `P2: 2번째 회상=캐시 공유 (got ${JSON.stringify(rc.map((r) => r.cached))})`)
  check(rc[0]?.node === '기억확인' && rc[1]?.node === '마무리', `P2: 노드 귀속 (got ${JSON.stringify(rc.map((r) => r.node))})`)
  check((chat.outLen ?? 0) > 0, `응답 수신(${chat.outLen}자, ${chat.latencyMs}ms)`)

  log('\n' + (fails.length ? `FAILED ${fails.length}: ${fails.join(' | ')}` : 'ALL GREEN'))
  if (fails.length) process.exitCode = 1
} catch (e) {
  log('ERROR ' + (e?.stack ?? e))
  process.exitCode = 1
} finally {
  await browser.close()
}

/* 직접형 도구 단위 배선 검증 (스펙 276) — 필수 단언(기능적, positive+negative+control).
   ① UI 저장 왕복: 도구 피커(도구 단위)서 local-tools · echo만 체크 → 승인 오버라이드에 echo만
      나열 → 생성 → config.tools=['local-tools__echo'] + mcps=['local-tools'] 파생.
   ② 런타임 positive: echo만 배선한 에이전트에 "echo …" → trace.mcp에 echo 호출.
   ③ 런타임 negative(핵심): 같은 에이전트에 "web_search …" → web_search 호출 없음(노출 자체 차단).
   ④ control(구저장 무회귀): tools 없는 에이전트(mcps만)에 같은 메시지 → web_search 호출 됨
      — ③의 차단이 필터 때문임을 대조 증명.
   ⑤ 하이드레이션: 구저장(mcps만) 편집 열람 → 도구 피커에 그 서버 도구들이 체크된 상태.

   실행: PLAYWRIGHT_DIR=<abs>/tests/e2e/node_modules/playwright \
         ADMIN_EMAIL=admin@example.com ADMIN_PASSWORD=adminpass123 \
         node tests/browser/verify-276-tool-wiring.mjs */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium
const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const EMAIL = process.env.ADMIN_EMAIL ?? 'admin@example.com'
const PASSWORD = process.env.ADMIN_PASSWORD ?? 'adminpass123'

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await (await browser.newContext({ viewport: { width: 1280, height: 1100 } })).newPage()
const log = (...a) => console.log(...a)
const fails = []
const check = (c, m) => { log((c ? '  ok  ' : ' FAIL ') + m); if (!c) fails.push(m) }
const rand = Date.now().toString(36)
const cleanup = { agents: [] }

// SSE chat → {out, mcpCalls, err} (verify-pipeline-268 패턴)
const chatEval = async (id, text) =>
  page.evaluate(async ({ id, text }) => {
    const res = await fetch(`/api/agents/${id}/chat`, {
      method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages: [{ role: 'user', content: text }] }),
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
    return { outLen: out.length, mcp: (trace?.mcp || []).map((c) => ({ server: c.server, tool: c.tool })), err }
  }, { id, text })

async function closeModal() {
  const cancel = page.getByRole('button', { name: /^취소$/ }).first()
  if (await cancel.count()) await cancel.click({ force: true }).catch(() => {})
  await page.keyboard.press('Escape').catch(() => {})
  await page.locator('.ant-modal-wrap').first().waitFor({ state: 'hidden', timeout: 4000 }).catch(() => {})
  await page.waitForTimeout(300)
}

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  await page.waitForTimeout(500)

  // ── ① UI 저장 왕복: 직접형 폼 — 도구 단위 피커에서 echo만 ──
  const uiName = 'tw276-ui-' + rand
  await page.getByRole('button', { name: /새 에이전트/ }).first().click()
  await page.waitForTimeout(700)
  await page.getByPlaceholder('예: research-assistant').fill(uiName)
  // 모델 mock-llm 선택(공용 ModelField)
  const modelWrap = page.locator('.ant-modal div', { has: page.getByText('모델', { exact: true }) })
    .filter({ has: page.locator('.ant-select') }).first()
  await modelWrap.locator('.ant-select').first().click()
  await page.waitForTimeout(300)
  await page.locator('.ant-select-dropdown:visible .ant-select-item-option', { hasText: 'mock-llm' }).first().click()
  await page.waitForTimeout(300)
  await page.getByRole('button', { name: '다음' }).click()
  await page.waitForTimeout(500)
  // 도구 트리(스펙 277)에서 'delete_record'(local-tools 고유 도구) 자식 체크. echo는 calc-tools와
  // 중복이라 트리 스코프가 모호 → 저장 왕복 단언은 고유 도구로(런타임 ②③은 API로 echo 배선).
  const treeNode = page.locator('.ant-modal:visible .ant-tree-treenode', { has: page.getByText('delete_record', { exact: true }) }).first()
  const hasNode = await treeNode.count()
  check(hasNode > 0, `① 도구 트리에 자식 노드 'delete_record' (found ${hasNode})`)
  await treeNode.locator('.ant-tree-checkbox').first().click()
  await page.waitForTimeout(400)
  // 승인 오버라이드 = 선택 도구만(echo 1행)
  const apprHeader = page.locator('.ant-modal .ant-collapse-header', { hasText: '도구 승인 오버라이드' }).first()
  const apprText = await apprHeader.innerText().catch(() => '')
  check(apprText.includes('(1개'), `① 승인 오버라이드 = 선택 도구만 1개 (got ${JSON.stringify(apprText.slice(0, 40))})`)
  // 세부 → 요약 → 생성
  await page.getByRole('button', { name: '다음' }).click(); await page.waitForTimeout(400)
  await page.getByRole('button', { name: '다음' }).click(); await page.waitForTimeout(400)
  await page.getByRole('button', { name: '에이전트 생성' }).click()
  await page.waitForTimeout(1200)
  const saved = await page.evaluate(async (nm) => {
    const r = await fetch('/api/agents', { credentials: 'include' })
    const list = await r.json()
    const a = (Array.isArray(list) ? list : list.items ?? []).find((x) => x.name === nm)
    return a ? { id: a.id, tools: a.tools, mcps: a.mcps } : null
  }, uiName)
  if (saved?.id) cleanup.agents.push(saved.id)
  log('SAVED=' + JSON.stringify(saved))
  check(!!saved && JSON.stringify(saved.tools) === JSON.stringify(['local-tools__delete_record']), `① 저장 config.tools=['local-tools__delete_record'] (got ${JSON.stringify(saved?.tools)})`)
  check(!!saved && JSON.stringify(saved.mcps) === JSON.stringify(['local-tools']), `① mcps=['local-tools'] 파생 (got ${JSON.stringify(saved?.mcps)})`)
  await closeModal()

  // ── ②③ 런타임: echo만 배선(API 생성·활성) ──
  const rt = await page.evaluate(async (nm) => {
    const H = { 'Content-Type': 'application/json' }
    const jf = async (url, opt) => { const r = await fetch(url, { credentials: 'include', headers: H, ...opt }); return { ok: r.ok, status: r.status, j: await r.json().catch(() => null) } }
    const config = { model: 'mock-llm', persona: '간결히 답하라', mcps: ['local-tools'], tools: ['local-tools__echo'], memories: [] }
    const cr = await jf('/api/agents', { method: 'POST', body: JSON.stringify({ name: nm, config }) })
    if (!cr.ok) return { step: 'create', status: cr.status }
    const draft = (cr.j.versions || []).find((v) => v.status === 'draft') || (cr.j.versions || [])[0]
    const ac = await jf(`/api/agents/${cr.j.id}/activate`, { method: 'POST', body: JSON.stringify({ version: draft?.version }) })
    return { step: ac.ok ? 'ok' : 'activate', id: cr.j.id }
  }, 'tw276-rt-' + rand)
  check(rt.step === 'ok', `②③ 런타임 에이전트 생성·활성 (step=${rt.step})`)
  if (rt.id) cleanup.agents.push(rt.id)

  const pos = await chatEval(rt.id, 'echo hello-276')
  log('POS=' + JSON.stringify(pos))
  check(!pos.error && !pos.err, `② chat 오류 없음 (${pos.error ?? pos.err ?? 'none'})`)
  check((pos.mcp || []).some((c) => c.tool === 'echo'), `② positive: echo 호출됨 (got ${JSON.stringify(pos.mcp)})`)

  const neg = await chatEval(rt.id, 'web_search python 276 문서 찾아줘')
  log('NEG=' + JSON.stringify(neg))
  check(!neg.error && !neg.err, `③ chat 오류 없음`)
  check(!(neg.mcp || []).some((c) => c.tool === 'web_search'), `③ negative: 비선택 web_search 호출 없음 (got ${JSON.stringify(neg.mcp)})`)

  // ── ④ control: tools 없는 구저장 동형 — 같은 메시지에 web_search 호출 됨 ──
  const ctl = await page.evaluate(async (nm) => {
    const H = { 'Content-Type': 'application/json' }
    const jf = async (url, opt) => { const r = await fetch(url, { credentials: 'include', headers: H, ...opt }); return { ok: r.ok, j: await r.json().catch(() => null) } }
    const config = { model: 'mock-llm', persona: '간결히 답하라', mcps: ['local-tools'], memories: [] }
    const cr = await jf('/api/agents', { method: 'POST', body: JSON.stringify({ name: nm, config }) })
    if (!cr.ok) return { step: 'create' }
    const draft = (cr.j.versions || []).find((v) => v.status === 'draft') || (cr.j.versions || [])[0]
    const ac = await jf(`/api/agents/${cr.j.id}/activate`, { method: 'POST', body: JSON.stringify({ version: draft?.version }) })
    return { step: ac.ok ? 'ok' : 'activate', id: cr.j.id }
  }, 'tw276-ctl-' + rand)
  check(ctl.step === 'ok', `④ control 생성·활성 (step=${ctl.step})`)
  if (ctl.id) cleanup.agents.push(ctl.id)
  const ctlChat = await chatEval(ctl.id, 'web_search python 276 문서 찾아줘')
  log('CTL=' + JSON.stringify(ctlChat))
  check((ctlChat.mcp || []).some((c) => c.tool === 'web_search'), `④ control(구저장 동형): web_search 호출 됨 — ③이 필터 때문임을 대조 증명 (got ${JSON.stringify(ctlChat.mcp)})`)

  // ── ④b pipeline 게이트(codex 276 Low): agent-level config.tools가 있어도 노드 도구 풀을 안 좁힘 ──
  // curl 직접 저작으로 pipeline + config.tools=[echo]인데 노드는 web_search를 쓴다 → 노드가 여전히 호출.
  const pipe = await page.evaluate(async (nm) => {
    const H = { 'Content-Type': 'application/json' }
    const jf = async (url, opt) => { const r = await fetch(url, { credentials: 'include', headers: H, ...opt }); return { ok: r.ok, j: await r.json().catch(() => null) } }
    const config = {
      model: 'mock-llm', persona: '', impl: 'pipeline',
      mcps: ['local-tools'], tools: ['local-tools__echo'], // 직접형 잔재를 흉내 — 게이트가 무시해야
      nodes: [{ name: '검색', context: 'carry', model: 'mock-llm', tools: ['local-tools__web_search'],
                prompt: 'web_search 도구로 검색하라' }],
    }
    const cr = await jf('/api/agents', { method: 'POST', body: JSON.stringify({ name: nm, config }) })
    if (!cr.ok) return { step: 'create' }
    const draft = (cr.j.versions || []).find((v) => v.status === 'draft') || (cr.j.versions || [])[0]
    const ac = await jf(`/api/agents/${cr.j.id}/activate`, { method: 'POST', body: JSON.stringify({ version: draft?.version }) })
    return { step: ac.ok ? 'ok' : 'activate', id: cr.j.id }
  }, 'tw276-pipe-' + rand)
  check(pipe.step === 'ok', `④b pipeline 생성·활성 (step=${pipe.step})`)
  if (pipe.id) cleanup.agents.push(pipe.id)
  const pipeChat = await chatEval(pipe.id, 'web_search 파이썬 문서 찾아줘')
  log('PIPE=' + JSON.stringify(pipeChat))
  check((pipeChat.mcp || []).some((c) => c.tool === 'web_search'),
    `④b pipeline 게이트: agent-level tools 있어도 노드 web_search 호출됨(풀 미축소) (got ${JSON.stringify(pipeChat.mcp)})`)

  // ── ⑤ 하이드레이션: 구저장(mcps만) 편집 열람 → 도구 피커 체크 확장 ──
  await page.reload({ waitUntil: 'networkidle' })
  await page.waitForTimeout(800)
  await page.getByText('tw276-ctl-' + rand, { exact: false }).first().click()
  await page.waitForTimeout(700)
  await page.getByRole('button', { name: /편집/ }).first().click()
  await page.waitForTimeout(700)
  await page.getByRole('button', { name: '다음' }).click()
  await page.waitForTimeout(500)
  // 도구 트리(스펙 277) 배지 "선택/전체" — 구저장 하이드레이션이면 local-tools 도구 전체(3)가 체크.
  // 트리 리프 체크 수로 단언(부모 체크 제외 위해 checkbox-checked 중 트리 내부만·leaf는 3).
  const editTree = page.locator('.ant-modal:visible .ant-tree').first()
  const checkedLeaves = await editTree.locator('.ant-tree-treenode:not(.ant-tree-treenode-switcher-open):not(.ant-tree-treenode-switcher-close) .ant-tree-checkbox-checked').count()
  // 위 셀렉터가 취약하면 배지 텍스트로 폴백: ToolTree 헤더 Tag "3/10"
  const badge = await page.locator('.ant-modal:visible .ant-tag', { hasText: /^3\s*\/\s*\d+$/ }).count()
  check(checkedLeaves >= 3 || badge > 0, `⑤ 하이드레이션: local-tools 도구 3개 체크(트리 배지 3/N) (leaves=${checkedLeaves} badge=${badge})`)
  await closeModal()

  log('\n' + (fails.length ? `FAILED ${fails.length}: ${fails.join(' | ')}` : 'ALL GREEN'))
  if (fails.length) process.exitCode = 1
} catch (e) {
  log('ERROR ' + (e?.stack ?? e))
  process.exitCode = 1
} finally {
  for (const id of cleanup.agents) { try { await page.request.delete(`${URL}/api/agents/${id}`) } catch {} }
  await browser.close()
}

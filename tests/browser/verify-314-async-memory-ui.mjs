/* 스펙 314 프론트 기능 검증 — 자동 기억 저장 비차단 + 완료 트레일링 이벤트의 UI 반영(외형 아닌 동작).
   시나리오:
     ① 장기 메모리 켠 에이전트(memories=["장기 기억 (mem0)"]) API로 생성 → used_memory=True 유도.
     ② 플레이그라운드에서 메시지 전송 → 응답 완료.
     ③ 인스펙터 "프롬프트·설정" 탭 → "자동 저장된 기억" 섹션이 나타난다(memoryPending||memorySaved).
     ④ 리로드 없이 그 섹션이 pending("저장하는 중")을 벗어나 결과 상태로 바뀐다 → **트레일링 event:
        memory가 수신돼 조용히 패치됨을 증명**(옛 동작=리더가 [DONE]에서 멈췄다면 pending이 안 풀림).
   실행: PLAYWRIGHT_DIR=<repo>/tests/e2e/node_modules/playwright node tests/browser/verify-314-async-memory-ui.mjs */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium
const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const API = process.env.API_URL ?? 'http://127.0.0.1:8000'
const _fx = (await import('./_fixture.mjs')).provisionSuper()
const NAME = `v314-${Date.now().toString(36)}`
const LONG_TERM = '장기 기억 (mem0)'

const fails = []
const ok = (c, m) => { console.log((c ? '  ok  ' : ' FAIL ') + m); if (!c) fails.push(m) }

const login = await fetch(`${API}/auth/login`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  body: `username=${encodeURIComponent(_fx.email)}&password=${encodeURIComponent(_fx.password)}`,
})
const cookie = (login.headers.get('set-cookie') || '').split(';')[0]

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await (await browser.newContext({ viewport: { width: 1400, height: 1000 } })).newPage()
const pageErrors = []
page.on('pageerror', (e) => pageErrors.push(String(e)))
const consoleErrors = []
page.on('console', (m) => m.type() === 'error' && consoleErrors.push(m.text()))

const bodyText = () => page.locator('body').innerText()
const waitFor = async (pattern, timeout = 25000) => {
  const t0 = Date.now()
  while (Date.now() - t0 < timeout) {
    if (pattern.test(await bodyText())) return true
    await page.waitForTimeout(500)
  }
  return false
}

let id = null
try {
  // ── ① 장기 메모리 에이전트 생성 ──
  const created = await fetch(`${API}/agents`, {
    method: 'POST', headers: { 'Content-Type': 'application/json', Cookie: cookie },
    body: JSON.stringify({
      name: NAME,
      config: { model: 'mock-llm', persona: '너는 친절한 비서다.', memories: [LONG_TERM], historyDepth: 10 },
    }),
  })
  id = (await created.json().catch(() => ({})))?.id
  ok(!!id, `준비: 장기메모리 에이전트 생성(${NAME})`)

  // ── ② 로그인 → 플레이그라운드 → 전송 ──
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByPlaceholder('you@example.com').fill(_fx.email)
  await page.getByPlaceholder('비밀번호').fill(_fx.password)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  await page.getByText('Playground', { exact: true }).first().click()
  await page.waitForTimeout(1000)
  await page.locator('button:has(.ant-avatar)').first().click()
  await page.waitForTimeout(300)
  await page.getByText(NAME, { exact: false }).first().click()
  await page.waitForTimeout(500)
  const ta = page.locator('textarea').first()
  await ta.click(); await ta.fill('안녕하세요, 저는 커피를 좋아합니다.'); await ta.press('Enter')
  ok(await waitFor(/인스펙터/, 25000), '② 응답 도착(인스펙터 링크)')

  // ── ③ 인스펙터 열기 → "프롬프트·설정" 탭 → 자동 저장된 기억 섹션 ──
  await page.getByText('인스펙터', { exact: false }).last().click()
  await page.waitForTimeout(600)
  const tabSettings = page.getByRole('tab', { name: /프롬프트/ })
  if (await tabSettings.count()) { await tabSettings.first().click(); await page.waitForTimeout(400) }
  ok(await waitFor(/자동 저장된 기억/, 8000), '③ "자동 저장된 기억" 섹션 노출(memoryPending||memorySaved)')

  // ── ④ 리로드 없이 pending("저장하는 중")이 결과 상태로 전환 → 트레일링 event: memory 수신 증명 ──
  const resolved = async (timeout = 20000) => {
    const t0 = Date.now()
    while (Date.now() - t0 < timeout) {
      const txt = await bodyText()
      if (/자동 저장된 기억/.test(txt) && !/저장하는 중/.test(txt)) return true
      await page.waitForTimeout(500)
    }
    return false
  }
  ok(await resolved(), '④ 리로드 없이 pending 해제(트레일링 event: memory 수신·조용히 패치)')

  // ── 영속 병합 확인(새로고침 재현): 세션 메시지의 trace.memorySaved ──
  // (UI는 이벤트로 이미 반영. 여기선 백엔드 영속까지 왕복 확인.)
  const ssRes = await fetch(`${API}/sessions?agent_id=${id}`, { headers: { Cookie: cookie } }).catch(() => null)
  if (ssRes && ssRes.ok) {
    const sessions = await ssRes.json().catch(() => [])
    const sid = sessions[0]?.session_id ?? sessions[0]?.id
    if (sid) {
      const msgs = await (await fetch(`${API}/sessions/${sid}/messages`, { headers: { Cookie: cookie } })).json().catch(() => [])
      const ai = [...(msgs || [])].reverse().find((m) => m.role === 'assistant' && m.trace)
      ok(ai && ai.trace && ai.trace.memorySaved && !('memoryPending' in ai.trace),
        `⑤ 영속 trace에 memorySaved 병합·memoryPending 제거(status=${ai?.trace?.memorySaved?.status})`)
    }
  }

  await page.screenshot({ path: '/tmp/verify-314.png', fullPage: false }).catch(() => {})
  const fatal = [...pageErrors, ...consoleErrors].filter((e) => /Cannot read|is not a function|undefined is not|Maximum update depth|Rendered (more|fewer) hooks/i.test(e))
  ok(fatal.length === 0, `콘솔/페이지 치명 에러 0(치명 ${fatal.length})`)
  fatal.slice(0, 4).forEach((e) => console.log('    ! ' + e.slice(0, 160)))
} catch (e) {
  console.log('SCRIPT_ERROR: ' + (e?.stack ?? e))
  fails.push('스크립트 예외: ' + (e?.message ?? e))
} finally {
  if (id) await fetch(`${API}/agents/${id}`, { method: 'DELETE', headers: { Cookie: cookie } }).catch(() => {})
  await browser.close()
}

if (fails.length) {
  console.log(`\nFAIL: ${fails.length}건`)
  fails.forEach((f) => console.log('  - ' + f))
  process.exit(1)
}
console.log('\nVERIFY314_UI_OK — 비차단 완료 + 트레일링 memory 이벤트 UI 반영(pending→saved, 리로드 무)')

/* 스펙 200 e2e — '능력 부여' UI 개편(자유입력→카탈로그·코드→문장·역할/유저 분리·기억 종류 추가).
   ① 도입 문장·대상 축 Segmented ② 종류 6종 사람 말 ③ 카탈로그 옵션 수=실 등록 자원 수(측정)
   ④ 문장 미리보기+코드 라인 ⑤ 부여→사람 말 표시→회수 왕복 ⑥ 기억 종류=이름 Select 없음
   ⑦ agent 선택 값=agt_…(브로커 판정 키 일치).

   실행: PLAYWRIGHT_DIR=<dir> node tests/browser/verify-grant-ux-200.mjs */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium
const URL = 'http://127.0.0.1:5173'
const API = 'http://127.0.0.1:8000'
const _fx = (await import('./_fixture.mjs')).provisionSuper()
const OUT = process.env.OUT ?? '/private/tmp/claude-501/-Users-anthony-Repository-github-loveqoo-my-agents/0f419f54-5016-4410-97ef-deab94d7cbcb/scratchpad'

const fails = []
const ok = (c, m) => { console.log((c ? '  ok  ' : ' FAIL ') + m); if (!c) fails.push(m) }

const login = await fetch(`${API}/auth/login`, {
  method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  body: `username=${encodeURIComponent(_fx.email)}&password=${encodeURIComponent(_fx.password)}`,
})
const cookie = (login.headers.get('set-cookie') || '').split(';')[0]
const api = (path, opts = {}) => fetch(`${API}${path}`, { ...opts, headers: { 'Content-Type': 'application/json', Cookie: cookie, ...(opts.headers || {}) } })

// 실 등록 자원 수(측정 기준) — UI 옵션 수와 대조
const mcpsList = await (await api('/mcp-servers')).json().catch(() => [])
const colsList = await (await api('/collections')).json().catch(() => [])
const agentsList = await (await api('/agents')).json().catch(() => [])
console.log(`  자원: mcp=${mcpsList.length} rag=${colsList.length} agent=${agentsList.length}`)
const granted = [] // cleanup용 [subject, object]

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await (await browser.newContext({ viewport: { width: 1500, height: 1100 } })).newPage()
const pageErrors = []
page.on('pageerror', (e) => pageErrors.push(String(e)))
const bodyText = () => page.locator('body').innerText()
const waitFor = async (re, ms = 12000) => { const t0 = Date.now(); while (Date.now() - t0 < ms) { if (re.test(await bodyText())) return true; await page.waitForTimeout(300) } return false }
// 열린 드롭다운의 옵션들(닫힌 잔존 드롭다운 제외)
const openOptions = () => page.locator('.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option')
const pickOption = async (label) => {
  await openOptions().filter({ hasText: label }).first().click()
  await page.waitForTimeout(300)
}

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByPlaceholder('you@example.com').fill(_fx.email)
  await page.getByPlaceholder('비밀번호').fill(_fx.password)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  await page.getByText('유저', { exact: true }).first().click()
  await page.waitForTimeout(1500)

  const card = page.locator('.ant-card').filter({ hasText: '능력 부여' }).first()
  await card.scrollIntoViewIfNeeded()

  // ① 도입 문장 + 대상 축
  const bt = await bodyText()
  ok(/member는 여기서 열어준 능력만/.test(bt), '1a 도입 문장 노출')
  ok(/역할에게/.test(bt) && /특정 유저에게/.test(bt), '1b 대상 축 Segmented(역할/유저)')
  ok(/이 역할을 가진 모든 유저에게 적용/.test(bt), '1c 역할 축 효과 설명(기본)')

  // ② 종류 6종 사람 말 — 종류 Select 열기(카드 내 2번째 Select)
  await card.locator('.ant-select').nth(1).click()
  await page.waitForTimeout(500)
  const kindLabels = await openOptions().allInnerTexts()
  const expectKinds = ['도구 (MCP 서버)', '지식 (RAG 컬렉션)', '하위 에이전트', '기억 검색', '기억 저장', '기억 수정/삭제']
  ok(expectKinds.every((k) => kindLabels.some((l) => l.includes(k))), `2 종류 6종 사람 말 (실제 ${kindLabels.length}종)`)
  await pickOption('도구 (MCP 서버)')

  // ③ 카탈로그 옵션 수 측정 — 도구: 전체 1 + 서버 수
  ok(await waitFor(/어느 도구\?/, 4000), '3a 도구 카탈로그 Select 렌더')
  await card.locator('.ant-select').nth(2).click()
  await page.waitForTimeout(500)
  const mcpOptCount = await openOptions().count()
  ok(mcpOptCount === mcpsList.length + 1, `3b 도구 옵션 수 = 등록 ${mcpsList.length}+전체1 (실제 ${mcpOptCount})`)
  ok((await openOptions().allInnerTexts()).some((t) => t.includes('전체 — 모든 도구')), '3c 전체 옵션 명시')
  // 첫 서버 선택(없으면 전체 유지)
  if (mcpsList.length > 0) await pickOption(mcpsList[0].alias ?? mcpsList[0].name)
  else await pickOption('전체 — 모든 도구')

  // 대상: member 역할 선택
  await card.locator('.ant-select').nth(0).click()
  await page.waitForTimeout(400)
  await pickOption('member')

  // ④ 문장 미리보기 + 코드 라인
  const previewObj = mcpsList.length > 0 ? `capability:mcp:${mcpsList[0].name}` : 'capability:mcp'
  const bt2 = await bodyText()
  ok(new RegExp(`'member' 역할에게 .*사용을 허용합니다`).test(bt2), '4a 문장 미리보기')
  ok(bt2.includes(previewObj), `4b 코드 라인(${previewObj})`)
  await card.screenshot({ path: `${OUT}/grant-ux-200-filled.png` })

  // ⑤ 부여 → 사람 말 목록 → 회수
  await card.getByRole('button', { name: '부여' }).click()
  await page.waitForTimeout(1200)
  granted.push(['member', previewObj])
  ok(await waitFor(/능력을 부여했습니다|도구 · /, 6000), '5a 부여 성공')
  const bt3 = await bodyText()
  const humanCell = mcpsList.length > 0 ? `도구 · ${mcpsList[0].alias ?? mcpsList[0].name}` : '모든 도구'
  ok(bt3.includes(humanCell), `5b 목록에 사람 말 표시(${humanCell})`)
  ok(!new RegExp(`capability:mcp[^\\s]*\\s`).test(bt3.split('부여된 능력')[1] ?? bt3) || !bt3.includes(`${previewObj}\n회수`), '5c 목록 셀에 코드 비노출(툴팁만)')
  // 회수
  const row = page.locator('tr').filter({ hasText: humanCell }).filter({ hasText: '회수' }).first()
  await row.getByRole('button', { name: '회수' }).click()
  await page.waitForTimeout(1200)
  ok(await waitFor(/능력을 회수했습니다/, 5000), '5d 회수 성공')
  granted.pop()

  // ⑥ 기억 종류 → 이름 Select 없음 + 문장
  await card.locator('.ant-select').nth(1).click()
  await page.waitForTimeout(400)
  await pickOption('기억 검색')
  const bt4 = await bodyText()
  ok(!/어느 기억/.test(bt4) && !/어느 도구\?/.test(bt4), '6a 기억 종류엔 이름 Select 없음')
  // 대상 재선택(부여 후 초기화됐으므로)
  await card.locator('.ant-select').nth(0).click()
  await page.waitForTimeout(400)
  await pickOption('member')
  ok(await waitFor(/'member' 역할에게 기억 검색 사용을 허용합니다/, 4000), '6b 기억 문장 미리보기(모든 X 없음)')

  // ⑦ agent 종류 → 선택 값이 agt_(브로커 판정 키)
  if (agentsList.length > 0) {
    await card.locator('.ant-select').nth(1).click()
    await page.waitForTimeout(400)
    await pickOption('하위 에이전트')
    await card.locator('.ant-select').nth(2).click()
    await page.waitForTimeout(400)
    // 비어있지 않은 카탈로그에서도 개수 측정(mcp=0 환경 보완) — 전체1+에이전트 수
    const agentOptCount = await openOptions().count()
    ok(agentOptCount === agentsList.length + 1, `7a 에이전트 옵션 수 = 등록 ${agentsList.length}+전체1 (실제 ${agentOptCount})`)
    const aLabel = agentsList[0].alias ?? agentsList[0].name
    await pickOption(aLabel)
    const expected = `capability:agent:${agentsList[0].agentId ?? agentsList[0].agent_id}`
    ok(await waitFor(new RegExp(expected.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')), 4000), `7 agent 코드=판정 키(${expected})`)
  } else {
    ok(true, '7 에이전트 없음 — 스킵')
  }

  await card.screenshot({ path: `${OUT}/grant-ux-200-final.png` })
  ok(pageErrors.length === 0, `Z pageerror 0 (실제 ${pageErrors.length})`)
  if (pageErrors.length) console.log('  errs:', pageErrors.slice(0, 3))
} catch (e) {
  console.log('EXCEPTION:', String(e)); fails.push('exception')
} finally {
  await browser.close()
  for (const [s, o] of granted) {
    await api(`/admin/policies?subject=${encodeURIComponent(s)}&object=${encodeURIComponent(o)}&action=invoke`, { method: 'DELETE' }).catch(() => {})
  }
  console.log('CLEANUP', granted.length)
}
console.log(fails.length === 0 ? '\n✅ ALL PASS (GRANTUX200_OK)' : `\n❌ ${fails.length} FAILED`)
process.exit(fails.length === 0 ? 0 : 1)

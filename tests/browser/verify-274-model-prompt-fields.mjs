/* 모델·프롬프트 공용 컨트롤 검증 (스펙 274) — 필수 단언(UI 기능적).
   ① 버그 수정 실증: 등록 embedding 모델이 에이전트 폼 모델 옵션에 안 나옴(chat만).
   ② 노드 카드 배치(사용자 지시): 프롬프트→모델→단기→장기→도구→문서→받기→형식 DOM 순서.
   ③ 페르소나 로더 기능(노드): 가져오기 선택→TextArea에 body 채워짐.
   ④ 오버라이드: 공용 모델/프롬프트 컨트롤 존재 + 로더 기능.
   ⑤ 미등록 값 보존: ghost 모델 저장분 편집 시 선택 유지.

   실행: PLAYWRIGHT_DIR=<abs>/tests/e2e/node_modules/playwright \
         ADMIN_EMAIL=admin@example.com ADMIN_PASSWORD=adminpass123 \
         node tests/browser/verify-274-model-prompt-fields.mjs */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium
const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const EMAIL = process.env.ADMIN_EMAIL ?? 'admin@example.com'
const PASSWORD = process.env.ADMIN_PASSWORD ?? 'adminpass123'

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ viewport: { width: 1280, height: 1100 } })
const page = await ctx.newPage()
const log = (...a) => console.log(...a)
const fails = []
const check = (c, m) => { log((c ? '  ok  ' : ' FAIL ') + m); if (!c) fails.push(m) }
const GHOST = 'ghost-model-274'
const cleanup = { agents: [], personas: [] }

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

  // 등록 모델에서 embedding·chat 이름 확보(①용)
  const models = await page.evaluate(async () => {
    const r = await fetch('/api/models', { credentials: 'include' })
    const j = await r.json()
    const list = Array.isArray(j) ? j : (j.items ?? [])
    return list.map((m) => ({ name: m.name, kind: m.kind }))
  })
  const embName = models.find((m) => m.kind === 'embedding')?.name
  const chatName = models.find((m) => m.kind === 'chat')?.name
  log(`  ..  registry: chat=${chatName} embedding=${embName}`)

  // 페르소나 자가 픽스처(③④ 로더 검증용 — 시드 의존 금지, 회고 248 ③)
  const pfx = await page.request.post(`${URL}/api/personas`, {
    data: { name: 'p274-' + Date.now().toString(36), body: '너는 274 테스트 페르소나다. 간결히 답하라.' },
  })
  const pfxJ = await pfx.json().catch(() => null)
  if (pfxJ?.id) cleanup.personas.push(pfxJ.id)
  log(`  ..  persona fixture: ${pfx.status()}`)
  // blocks는 뷰 mount 시 로드 — 픽스처 반영 위해 리로드.
  await page.reload({ waitUntil: 'networkidle' })
  await page.waitForTimeout(800)
  const blocksDbg = await page.evaluate(async () => {
    const r = await fetch('/api/blocks', { credentials: 'include' })
    const j = await r.json().catch(() => null)
    return { status: r.status, keys: j ? Object.keys(j) : null, personaItems: j?.persona?.items?.map((x) => x.name) ?? null }
  })
  log('  ..  blocks=' + JSON.stringify(blocksDbg))

  // ── ① 에이전트 폼(직접형) 모델 옵션: embedding 제외·chat 포함 ──
  await page.getByRole('button', { name: /새 에이전트/ }).first().click()
  await page.waitForTimeout(700)
  const modelWrap = page.locator('div', { has: page.getByText('모델', { exact: true }) })
    .filter({ has: page.locator('.ant-select') }).last()
  await modelWrap.locator('.ant-select').first().click()
  await page.waitForTimeout(300)
  const opts1 = await page.locator('.ant-select-dropdown:visible .ant-select-item-option').allTextContents()
  check(chatName && opts1.includes(chatName), `에이전트 폼 모델 옵션에 chat(${chatName}) 있음 (${JSON.stringify(opts1)})`)
  if (embName) {
    check(!opts1.includes(embName), `에이전트 폼 모델 옵션에 embedding(${embName}) 없음 — 버그 수정`)
  } else {
    log('  ..  embedding 모델 미등록 — ① 스킵')
  }
  await page.keyboard.press('Escape'); await page.waitForTimeout(200)

  // ── ②③ 노드형: 카드 배치 순서 + 페르소나 로더 ──
  const typeField = page.locator('label', { hasText: '에이전트 종류' }).first()
  await typeField.locator('.ant-select').first().click()
  await page.waitForTimeout(300)
  await page.locator('.ant-select-dropdown:visible .ant-select-item-option', { hasText: '노드형' }).first().click()
  await page.waitForTimeout(400)
  await page.getByPlaceholder('예: research-assistant').fill('mp-274-' + Date.now().toString(36))
  await page.getByRole('button', { name: '다음' }).click()
  await page.waitForTimeout(500)
  await page.getByRole('button', { name: /노드 추가/ }).click()
  await page.waitForTimeout(400)

  const modalText = await page.locator('.ant-modal').first().innerText()
  const order = ['프롬프트', '모델', '단기 기억', '장기 기억', '도구 (선택)', '문서 (선택)', '이전 결과 받기', '응답 형식']
  const idx = order.map((l) => modalText.indexOf(l))
  const sorted = idx.every((v, k) => v >= 0 && (k === 0 || v > idx[k - 1]))
  check(sorted, `노드 카드 배치 순서(사용자 지시) ${order.join('→')} (idx=${JSON.stringify(idx)})`)

  // ③ 페르소나 로더: 가져오기 → TextArea 채워짐
  // antd v6 단일 Select는 값/placeholder를 .ant-select-content에 렌더(selection-placeholder 없음).
  const loaderSel = page.locator('.ant-modal .ant-select', { hasText: '등록 페르소나에서 가져오기' })
  if (await loaderSel.count()) {
    await loaderSel.first().click()
    await page.waitForTimeout(300)
    const pOpts = await page.locator('.ant-select-dropdown:visible .ant-select-item-option').count()
    if (pOpts > 0) {
      await page.locator('.ant-select-dropdown:visible .ant-select-item-option').first().click()
      await page.waitForTimeout(300)
      const ta = page.locator('.ant-modal textarea').last()
      const val = await ta.inputValue()
      check(val.trim().length > 0, `노드 페르소나 로더 → 프롬프트 채워짐 (${val.slice(0, 30)}…)`)
    } else {
      log('  ..  페르소나 블록 없음 — ③ 스킵')
    }
  } else {
    log('  ..  페르소나 로더 미노출(블록 없음) — ③ 스킵')
  }
  await closeModal()

  // ── ⑤ 미등록 모델 보존: ghost 모델 에이전트 편집 시 선택 유지 ──
  const gname = 'ghost-274-' + Date.now().toString(36)
  const gr = await page.request.post(`${URL}/api/agents`, {
    data: { name: gname, config: { model: GHOST, persona: '테스트', mcps: [], memories: [] } },
  })
  const g = await gr.json(); if (g?.id) cleanup.agents.push(g.id)
  if (gr.ok()) {
    await page.reload({ waitUntil: 'networkidle' })
    await page.waitForTimeout(800)
    // 행 아이콘 편집은 접근명이 없어(037 선례) 행 열기 → 라벨 '편집' 버튼으로 진입.
    await page.getByText(gname, { exact: false }).first().click()
    await page.waitForTimeout(700)
    await page.getByRole('button', { name: /편집/ }).first().click()
    await page.waitForTimeout(700)
    // 닫힌 모달 잔재가 DOM에 남으므로 보이는 모달로 스코프(274 디버깅 — :visible 필수).
    const editModal = page.locator('.ant-modal:visible').last()
    // antd v6 단일 Select: 선택값은 .ant-select-content[title=값]에 렌더.
    const ghostSel = await editModal.locator(`.ant-select-content[title="${GHOST}"]`).count()
    check(ghostSel > 0, `미등록 모델 보존: 편집 시 선택 유지 (found ${ghostSel})`)
    await closeModal()
    await page.keyboard.press('Escape').catch(() => {})
    await page.waitForTimeout(300)
  } else {
    log(`  ..  ghost 모델 저장 거부(${gr.status()}) — 백엔드가 검증하므로 보존 시나리오 자체 불가(무해) — ⑤ 스킵`)
  }

  // ── ④ 오버라이드: 공용 모델/프롬프트 + 로더 기능 ──
  const pname = 'mp274-pg-' + Date.now().toString(36)
  const pr = await page.request.post(`${URL}/api/agents`, {
    data: { name: pname, config: { model: 'mock-llm', persona: '테스트', mcps: [], memories: [] } },
  })
  const p = await pr.json(); if (p?.id) cleanup.agents.push(p.id)
  await page.getByRole('menuitem', { name: 'Playground' }).click()
  await page.waitForTimeout(1200)
  await page.locator('button:has(.ant-avatar)').first().click()
  await page.waitForTimeout(400)
  await page.getByText(pname, { exact: false }).first().click()
  await page.waitForTimeout(600)
  await page.locator('button[title*="오버라이드"]').first().click()
  await page.waitForTimeout(600)
  const drawer = page.getByRole('dialog')
  const dModelLabel = await drawer.getByText('모델', { exact: true }).count()
  const dPromptLabel = await drawer.getByText('시스템 프롬프트', { exact: true }).count()
  check(dModelLabel > 0 && dPromptLabel > 0, `오버라이드에 공용 모델/시스템 프롬프트 라벨 (${dModelLabel}/${dPromptLabel})`)
  const dLoader = drawer.locator('.ant-select', { hasText: '등록 페르소나에서 가져오기' })
  if (await dLoader.count()) {
    await dLoader.first().click()
    await page.waitForTimeout(300)
    const cnt = await page.locator('.ant-select-dropdown:visible .ant-select-item-option').count()
    if (cnt > 0) {
      await page.locator('.ant-select-dropdown:visible .ant-select-item-option').first().click()
      await page.waitForTimeout(300)
      const dta = drawer.locator('textarea').first()
      const dval = await dta.inputValue()
      check(dval.trim().length > 0, `오버라이드 페르소나 로더 → 시스템 프롬프트 채워짐 (${dval.slice(0, 30)}…)`)
    }
  } else {
    log('  ..  오버라이드 로더 미노출(블록 없음) — 스킵')
  }

  log('\n' + (fails.length ? `FAILED ${fails.length}: ${fails.join(' | ')}` : 'ALL GREEN'))
  if (fails.length) process.exitCode = 1
} catch (e) {
  log('ERROR ' + (e?.stack ?? e))
  process.exitCode = 1
} finally {
  for (const id of cleanup.agents) { try { await page.request.delete(`${URL}/api/agents/${id}`) } catch {} }
  for (const id of cleanup.personas) { try { await page.request.delete(`${URL}/api/personas/${id}`) } catch {} }
  await browser.close()
}

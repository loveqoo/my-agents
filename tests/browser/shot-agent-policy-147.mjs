/* 스펙 147 e2e — 에이전트 최소 어휘(public/private/external) + private A2A 정책.
   W1: 리스트 보조줄에 "public" 태그 행 존재 + 구 어휘("공용"·"shared"·"내 소유") 화면 잔존 0.
   W2: admin이 새 에이전트("e2e-147-priv") 생성 → 그 행의 소유 태그 실측(owner_id 스탬프 방식에 따라
       public/private 어느 쪽이든 3어휘 중 하나면 ok — 어느 쪽인지 명시 보고).
   W3: private 태그 행(하나라도 있으면 — 기존 4개 존재)의 A2A 스위치가 disabled + 마우스오버 시
       "private 에이전트는 A2A를 켤 수 없습니다" 툴팁([role="tooltip"], antd 6은 이 role로 Tooltip·
       Popover 공용 렌더 — 셀렉터 버전 무관 고정).
   W3b: 소유 필터 기본값("전체")에서 "private · 타인"(주황) 태그 행이 0개인지 확인(코디네이터 지시 —
       타인 private는 기본 숨김이나, admin은 can_manage가 항상 true라 ownerKind가 'others'로 못 떨어져
       현재 구현상 이 태그 자체가 admin 시야에 절대 안 뜬다 — 실측대로 0건이 "정상"임을 기록).
   W4: public 행의 A2A 스위치는 활성(비활성 아님) — 클릭 금지(상태 변경 없음, 관찰만).
   W5: "태그 안내" 팝오버에 public/private/external 어휘 확인 + 인접 태그 간 시각 간격(px, >0) 실측.
   W6: 정리 — 생성한 e2e-147-priv 삭제.

   템플릿=shot-agents-ux-144.mjs(로그인·에이전트 생성/삭제·아이콘 버튼 정규식·API pre-clean/cleanup).
   DataTable 행은 tbody 1개 = tr 2개(메인+보조줄, 스펙 146) 한 몸 — tbody를 `hasText`로 필터하면 두
   tr 텍스트를 합쳐 스코프 고정할 수 있다(에이전트 이름은 메인 tr에만 있어도 같은 tbody).
   Tag 텍스트 매칭은 Playwright hasText(substring)로 하면 "private"가 "private · 타인"까지 집어
   먹으므로, 태그 텍스트는 page.evaluate로 직접 읽어 exact 비교한다(사전 조사로 확인한 함정).

   앱 코드 수정 없음 — 검증 전용. 기존 에이전트의 A2A 스위치 클릭 금지(상태 변경 없음).

   실행: PLAYWRIGHT_DIR=<dir> node tests/browser/shot-agent-policy-147.mjs */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = '/tmp/agent-147-policy.png'
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password

const AGENT_NAME = 'e2e-147-priv'

const fails = []
const check = (c, m) => { console.log((c ? '  ok  ' : ' FAIL ') + m); if (!c) fails.push(m) }

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1400, height: 1000 } })
const page = await ctx.newPage()
const consoleErrors = []
page.on('console', (m) => m.type() === 'error' && consoleErrors.push(m.text()))

const tbodyFor = (name) => page.locator('table > tbody').filter({ hasText: name })

// tbody(전체 테이블 fixture) 안 .ant-tag의 exact-trim 텍스트 배열 — hasText substring 함정 회피.
async function tagTexts(locator) {
  return (await locator.locator('.ant-tag').allInnerTexts()).map((t) => t.trim())
}

async function gotoAgents() {
  await page.getByRole('menuitem', { name: '에이전트' }).first().click()
  await page.getByRole('banner').getByRole('heading', { name: '에이전트' }).waitFor({ timeout: 10000 })
  await page.waitForTimeout(400)
}

try {
  // ---------- 로그인 ----------
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByRole('banner').getByRole('heading', { name: '에이전트' }).waitFor({ timeout: 10000 })
  await page.waitForTimeout(500)

  // ---------- 사전 정리(멱등화): API로 잔여 "e2e-147-priv" 삭제 ----------
  const listResp0 = await page.request.get(`${URL}/api/agents`)
  const arr0 = await listResp0.json()
  const stale = arr0.filter((a) => typeof a.name === 'string' && a.name.startsWith(AGENT_NAME))
  for (const a of stale) await page.request.delete(`${URL}/api/agents/${a.id}`).catch(() => {})
  console.log(`(사전정리) 잔여 "${AGENT_NAME}*" ${stale.length}건 제거`)
  if (stale.length) {
    await page.reload({ waitUntil: 'networkidle' })
    await page.getByRole('banner').getByRole('heading', { name: '에이전트' }).waitFor({ timeout: 10000 })
    await page.waitForTimeout(500)
  }

  // ================= W1: 리스트 보조줄 public 태그 + 구 어휘 잔존 0 =================
  const allTagsW1 = await tagTexts(page.locator('table'))
  const publicRowsW1 = allTagsW1.filter((t) => t === 'public').length
  check(publicRowsW1 > 0, `W1a: 보조줄 "public" 태그 행 존재(실측 ${publicRowsW1}건)`)

  const bodyText = await page.locator('body').innerText()
  const oldVocabHits = ['공용', '내 소유'].filter((w) => bodyText.includes(w))
  const bareShared = /\bshared\b/i.test(bodyText)
  check(
    oldVocabHits.length === 0 && !bareShared,
    `W1b: 구 어휘("공용"/"내 소유"/독립단어 "shared") 화면 잔존 0(발견=${JSON.stringify(oldVocabHits)}, bareShared=${bareShared})`
  )

  // ================= 준비: "e2e-147-priv" 생성(admin 계정) =================
  await page.getByRole('button', { name: /새 에이전트/ }).first().click()
  const createDialog = page.getByRole('dialog')
  await createDialog.locator('.ant-modal-title', { hasText: '에이전트 생성' }).waitFor({ timeout: 5000 })
  await page.getByPlaceholder('예: 리서치 어시스턴트').fill(AGENT_NAME)
  await createDialog.getByRole('button', { name: '에이전트 생성', exact: true }).click()
  await createDialog.waitFor({ state: 'hidden', timeout: 8000 }).catch(() => {})
  await page.waitForTimeout(600)
  const createdCount = await page.locator('table tbody tr').filter({ hasText: AGENT_NAME }).count()
  check(createdCount === 1, `준비: "${AGENT_NAME}" 생성 → 목록에 1행(실제=${createdCount})`)

  // ================= W2: 새 에이전트 소유 태그 실측(owner 스탬프 방식에 따라 public/private 어느 쪽이든 ok) =================
  const listResp1 = await page.request.get(`${URL}/api/agents`)
  const arr1 = await listResp1.json()
  const created = arr1.find((a) => a.name === AGENT_NAME)
  const expectedTag = !created
    ? null
    : created.owner_id == null
    ? 'public'
    : created.can_manage === false
    ? 'private · 타인'
    : 'private'
  const createdRowTags = await tagTexts(tbodyFor(AGENT_NAME))
  const w2Vocab = new Set(['public', 'private', 'private · 타인'])
  const createdOwnerTags = createdRowTags.filter((t) => w2Vocab.has(t))
  check(
    !!created && createdOwnerTags.length === 1 && createdOwnerTags[0] === expectedTag,
    `W2: "${AGENT_NAME}" 실측 — API owner_id=${created?.owner_id ?? 'null'}, can_manage=${created?.can_manage} → 기대 태그="${expectedTag}", 행 태그=${JSON.stringify(createdOwnerTags)}(3어휘 중 하나=${w2Vocab.has(createdOwnerTags[0])})`
  )

  // ================= W3: private 태그 행의 A2A 스위치 disabled + 툴팁 =================
  // 기존 4개(dbg-agent* 등, 타 사용자 소유 — admin은 can_manage 항상 true라 "private"로 보임) +
  // 방금 만든 e2e-147-priv(자기 소유 → private) 중 하나를 사용. e2e-147-priv가 private면 그 행을
  // 우선 사용(코디네이터 지시 경로 a), 아니면 기본 목록에서 "private"(정확히, "private · 타인" 제외)
  // 태그가 붙은 첫 행으로 폴백(경로 b는 "타인" 태그가 admin 시야에 안 뜨는 현재 구현상 대상 없음 —
  // 아래 W3b에서 그 실측을 별도로 남긴다).
  let w3TargetName = expectedTag === 'private' ? AGENT_NAME : null
  if (!w3TargetName) {
    const fallback = await page.evaluate(() => {
      const tbodies = Array.from(document.querySelectorAll('table > tbody'))
      for (const tb of tbodies) {
        const tags = Array.from(tb.querySelectorAll('.ant-tag')).map((t) => t.textContent.trim())
        if (tags.includes('private')) {
          const nameEl = tb.querySelector('td div div') // 이름 컬럼 첫 div>div(이름 텍스트)
          return nameEl ? nameEl.textContent.trim() : null
        }
      }
      return null
    })
    w3TargetName = fallback
  }
  check(!!w3TargetName, `W3 준비: "private"(정확) 태그 붙은 대상 행 확보(대상="${w3TargetName}")`)

  let w3Disabled = false
  let w3TooltipText = ''
  if (w3TargetName) {
    const targetTbody = tbodyFor(w3TargetName)
    const sw = targetTbody.locator('.ant-switch').first()
    w3Disabled = await sw.isDisabled().catch(() => false)
    await sw.hover({ timeout: 5000 }).catch(() => {})
    await page.waitForTimeout(500)
    w3TooltipText = (await page.locator('[role="tooltip"]').first().innerText().catch(() => '')) ?? ''
    // 툴팁 자취 제거(다음 체크 오염 방지) — 다른 곳으로 마우스 이동.
    await page.mouse.move(10, 10)
    await page.waitForTimeout(200)
  }
  const w3TooltipOk = w3TooltipText.includes('private 에이전트는 A2A를 켤 수 없습니다')
  check(
    w3Disabled && w3TooltipOk,
    `W3: "${w3TargetName}" 행 A2A 스위치 disabled(${w3Disabled}) + 툴팁 "private 에이전트는 A2A를 켤 수 없습니다" 포함(${w3TooltipOk}) [실측 툴팁="${w3TooltipText}"]`
  )

  // ================= W3b: 소유 필터 기본값("전체")에서 "private · 타인"(주황) 행 0개 =================
  // 실측 근거: admin(super)은 ownership.may_manage가 항상 True(특권)를 반환해 프론트 ownerKind()가
  // 'others'로 절대 안 떨어진다(can_manage===false 조건 자체가 admin껜 성립 불가) — 그 결과 "타인
  // private" 필터를 선택해도 admin 시야에는 이 태그가 원천적으로 안 뜬다. 기본값에서 0건은 "숨김 성공"이
  // 아니라 "이 태그가 admin껜 절대 안 뜨는 현재 구현"의 실측치로 기록한다(이상 징후로 보고).
  const allTagsDefault = await tagTexts(page.locator('table'))
  const othersCountDefault = allTagsDefault.filter((t) => t === 'private · 타인').length
  check(othersCountDefault === 0, `W3b: 소유 필터 "전체"(기본)에서 "private · 타인" 태그 행 0개(실측=${othersCountDefault})`)

  // "숨김 해제" 선택 시에도(경로 b 확인차) 몇 건 뜨는지 실측만 남긴다(실패 판정에는 안 씀 — 관찰용).
  // 위치 고정 셀렉터(정렬 다음, 소스 앞) 사용 — 재선택 시 라벨 텍스트가 바뀌어 hasText 재매칭이
  // 불안정해지는 것을 피한다(툴바 순서: 검색Input, 정렬Select, 소유Select, 소스Select, 상태Select).
  const ownerSelect = page.locator('.ant-select').nth(1)
  await ownerSelect.click()
  await page.waitForTimeout(200)
  await page.locator('.ant-select-item-option', { hasText: '숨김 해제' }).first().click()
  await page.waitForTimeout(400)
  const allTagsOthersFilter = await tagTexts(page.locator('table'))
  const othersCountFiltered = allTagsOthersFilter.filter((t) => t === 'private · 타인').length
  console.log(`  관찰  W3b-부가: "private · 타인 (숨김 해제)" 필터 선택 시 행 수=${await page.locator('table > tbody').count()}, "private · 타인" 태그=${othersCountFiltered}건(admin 계정 특성상 0 예상)`)
  // 필터 원복
  await ownerSelect.click()
  await page.waitForTimeout(200)
  await page.locator('.ant-select-item-option', { hasText: '소유: 전체' }).first().click()
  await page.waitForTimeout(400)

  // ================= W4: public 행 A2A 스위치 활성(클릭 금지) =================
  const w4TargetName = await page.evaluate(() => {
    const tbodies = Array.from(document.querySelectorAll('table > tbody'))
    for (const tb of tbodies) {
      const tags = Array.from(tb.querySelectorAll('.ant-tag')).map((t) => t.textContent.trim())
      const sw = tb.querySelector('.ant-switch')
      if (tags.includes('public') && sw) {
        const nameEl = tb.querySelector('td div div')
        return nameEl ? nameEl.textContent.trim() : null
      }
    }
    return null
  })
  check(!!w4TargetName, `W4 준비: "public" 태그 + A2A 스위치 있는 대상 행 확보(대상="${w4TargetName}")`)
  let w4NotDisabled = false
  if (w4TargetName) {
    const sw = tbodyFor(w4TargetName).locator('.ant-switch').first()
    w4NotDisabled = !(await sw.isDisabled().catch(() => true))
  }
  check(w4NotDisabled, `W4: "${w4TargetName}" 행(public) A2A 스위치 활성(disabled 아님=${w4NotDisabled}) — 클릭 안 함(상태 변경 없음)`)

  // ================= W5: "태그 안내" 팝오버 + 태그 간 시각 간격 =================
  await page.getByText('태그 안내', { exact: false }).click()
  await page.waitForTimeout(400)
  const popoverText = (await page.locator('.ant-popover-content').first().innerText().catch(() => '')) ?? ''
  const vocabOk = ['public', 'private', 'external'].every((w) => popoverText.includes(w))
  check(vocabOk, `W5a: "태그 안내" 팝오버에 public/private/external 어휘 포함(${vocabOk}) [본문="${popoverText.slice(0, 160)}..."]`)
  // 팝오버 닫기(다음 측정 오염 방지)
  await page.keyboard.press('Escape').catch(() => {})
  await page.waitForTimeout(300)

  const gap = await page.evaluate(() => {
    const tds = Array.from(document.querySelectorAll('table td[colspan]'))
    for (const td of tds) {
      const tags = td.querySelectorAll('.ant-tag')
      if (tags.length >= 2) {
        const r1 = tags[0].getBoundingClientRect()
        const r2 = tags[1].getBoundingClientRect()
        return { gapPx: Math.round((r2.left - r1.right) * 10) / 10, t1: tags[0].textContent.trim(), t2: tags[1].textContent.trim() }
      }
    }
    return null
  })
  check(!!gap && gap.gapPx > 0, `W5b: 인접 태그("${gap?.t1}"↔"${gap?.t2}") 간격=${gap?.gapPx}px(붙어있지 않음=${!!gap && gap.gapPx > 0})`)

  // ---------- 스크린샷(사용자 확인용) — private 행 스위치 disabled+툴팁 보이게 재현 ----------
  if (w3TargetName) {
    const sw = tbodyFor(w3TargetName).locator('.ant-switch').first()
    await sw.hover({ timeout: 5000 }).catch(() => {})
    await page.waitForTimeout(400)
  }
  await page.screenshot({ path: OUT, fullPage: true }).catch(() => {})
  console.log('shot:', OUT)
  await page.mouse.move(10, 10)
  await page.waitForTimeout(200)

  // ================= W6: 정리 — e2e-147-priv 삭제 =================
  await gotoAgents()
  await tbodyFor(AGENT_NAME).first().click()
  const delBtn = page.getByRole('button', { name: /삭제/ })
  await delBtn.waitFor({ timeout: 8000 })
  await delBtn.click()
  const confirmDialog = page.getByRole('dialog')
  await confirmDialog.getByText('에이전트를 삭제할까요?', { exact: true }).waitFor({ timeout: 5000 })
  await confirmDialog.getByRole('button', { name: '삭제', exact: true }).click()
  await page.waitForTimeout(800)
  const remaining = await page.locator('table tbody tr').filter({ hasText: AGENT_NAME }).count()
  check(remaining === 0, `W6: 정리 — 목록에서 "${AGENT_NAME}" 사라짐(잔여 행=${remaining})`)

  console.log(consoleErrors.length ? 'CONSOLE_ERRORS ' + JSON.stringify(consoleErrors.slice(0, 8)) : 'NO_CONSOLE_ERRORS')
} catch (e) {
  console.error('예외', e.message)
  await page.screenshot({ path: OUT, fullPage: true }).catch(() => {})
  fails.push('예외: ' + e.message)
} finally {
  // best-effort 잔여 정리(테스트 실패로 중도 종료해도 다음 실행이 안 새게).
  try {
    const listResp2 = await page.request.get(`${URL}/api/agents`)
    const arr2 = await listResp2.json()
    for (const a of arr2.filter((x) => typeof x.name === 'string' && x.name.startsWith(AGENT_NAME))) {
      await page.request.delete(`${URL}/api/agents/${a.id}`).catch(() => {})
    }
  } catch { /* best effort */ }
  await browser.close()
  if (_fx) _fx.teardown()
}

console.log(`\n${fails.length ? 'FAIL ' + fails.length : 'PASS'}`)
process.exit(fails.length ? 1 : 0)

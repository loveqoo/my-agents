/* 스펙 078 검증 — 미반영 초안 배지(Playground). 시스템 Chrome.
   시나리오(사용자 보고 재현): 신규 에이전트는 v1 draft 상태(미활성)다 →
   (양성) Playground에서 그 에이전트 선택 시 헤더에 "미반영 초안" 배지 + AgentCombo 행에 '초안' Tag.
   (음성) 시드 활성 에이전트(Doc Translator=code, active) 선택 시 배지 없음(거짓초록 방지).
   정리: 끝에서 생성한 테스트 에이전트를 삭제.

   antd6 클래스: Tag=.ant-tag(불변), Modal=.ant-modal-container(스펙075) — learning 080.

   실행: PLAYWRIGHT_DIR=<repo>/tests/e2e/node_modules/playwright \
         node tests/browser/shot-draft-badge-078.mjs /tmp/draft078 */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = process.argv[2] ?? '/tmp/draft078'
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password
const NAME = 'DraftBadge078-' + Math.random().toString(36).slice(2, 7)

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ viewport: { width: 1400, height: 960 } })
const page = await ctx.newPage()
const log = (...a) => console.log(...a)

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  await page.waitForTimeout(600)

  // ===== 신규 에이전트 생성(=v1 draft, 미활성) =====
  await page.getByRole('button', { name: /새 에이전트/ }).first().click()
  await page.waitForTimeout(700)
  await page.locator('.ant-modal-container input').first().fill(NAME)
  await page.waitForTimeout(150)
  await page.getByRole('button', { name: '에이전트 생성' }).click()
  await page.waitForTimeout(1000)
  log('CREATED_AGENT=' + NAME)

  // ===== Playground =====
  await page.getByText('Playground', { exact: true }).first().click()
  await page.waitForTimeout(1400)

  // AgentCombo 트리거 열기(기본 선택은 Doc Translator='원격 (SDK)').
  const trigger = page.locator('button', { hasText: '(SDK)' }).first()
  if (await trigger.count()) await trigger.click()
  else await page.locator('button', { hasText: '에이전트' }).first().click()
  await page.waitForTimeout(500)

  // 드롭다운에서 '초안' Tag 개수(신규 에이전트가 draft라 >=1) + 캡처.
  const draftTagsInMenu = await page.locator('.ant-tag', { hasText: '초안' }).count()
  log('MENU_DRAFT_TAGS=' + draftTagsInMenu + ' (expect >=1; 신규 에이전트가 draft)')
  await page.screenshot({ path: `${OUT}-A-picker-draft-tag.png`, fullPage: true })

  // 신규 에이전트 선택.
  const mine = page.locator('button', { hasText: NAME }).first()
  if (await mine.count()) {
    await mine.click()
    log('SELECTED=' + NAME)
  } else {
    log('NEW_AGENT_NOT_IN_PICKER')
  }
  await page.waitForTimeout(900)

  // (양성) 헤더에 "미반영 초안" 배지.
  const badgePos = await page.locator('.ant-tag', { hasText: '미반영 초안' }).count()
  log('HEADER_DRAFT_BADGE_DRAFT_AGENT=' + badgePos + ' (expect >=1)')
  await page.screenshot({ path: `${OUT}-B-header-badge.png`, fullPage: true })

  // ===== (음성) 시드 활성 에이전트로 전환 → 배지 없음 =====
  const trigger2 = page.locator('button', { hasText: NAME }).first()
  if (await trigger2.count()) await trigger2.click()
  else await page.locator('button', { hasText: '(SDK)' }).first().click()
  await page.waitForTimeout(500)
  const dt = page.locator('button', { hasText: 'Doc Translator' }).first()
  if (await dt.count()) {
    await dt.click()
    log('SWITCHED_TO=Doc Translator (active, no draft)')
  } else {
    log('DOC_TRANSLATOR_NOT_FOUND')
  }
  await page.waitForTimeout(900)
  const badgeNeg = await page.locator('.ant-tag', { hasText: '미반영 초안' }).count()
  log('HEADER_DRAFT_BADGE_ACTIVE_AGENT=' + badgeNeg + ' (expect 0)')
  await page.screenshot({ path: `${OUT}-C-active-no-badge.png`, fullPage: true })

  // ===== 정리: 테스트 에이전트 삭제 =====
  await page.getByText('에이전트', { exact: true }).first().click()
  await page.waitForTimeout(1000)
  // 목록에서 테스트 에이전트 카드/행을 열어 삭제. 이름 클릭 → 상세 → 삭제.
  const card = page.locator(`text=${NAME}`).first()
  if (await card.count()) {
    await card.click()
    await page.waitForTimeout(700)
    const delBtn = page.getByRole('button', { name: /삭제|등록 해제/ }).first()
    if (await delBtn.count()) {
      await delBtn.click()
      await page.waitForTimeout(500)
      // 확인 모달.
      const confirm = page.locator('.ant-modal-container').getByRole('button', { name: /삭제|확인|등록 해제/ }).first()
      if (await confirm.count()) { await confirm.click(); log('CLEANUP_DELETED=' + NAME) }
      else log('CLEANUP_CONFIRM_NOT_FOUND')
    } else log('CLEANUP_DELETE_BTN_NOT_FOUND')
  } else log('CLEANUP_CARD_NOT_FOUND')
  await page.waitForTimeout(600)

  log('DONE')
} catch (e) {
  log('ERROR ' + (e?.message ?? e))
  await page.screenshot({ path: `${OUT}-error.png` }).catch(() => {})
  process.exitCode = 1
} finally {
  await browser.close()
}

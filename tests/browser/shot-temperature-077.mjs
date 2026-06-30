/* 스펙 077 검증 — 온도 에이전트 필드 + 오버라이드 페르소나 대칭. 시스템 Chrome.
   (A) 생성 모달: Temperature 라벨·Switch·Slider 존재 → 토글 ON 시 값 0.7 표시(자동→수동).
   (B) Playground 오버라이드 드로어: '페르소나 블록에서 채우기' Select 존재 →
       첫 페르소나 선택 시 아래 시스템 프롬프트 TextArea가 채워짐(빈→비지 않음).

   실행: PLAYWRIGHT_DIR=<repo>/tests/e2e/node_modules/playwright \
         node tests/browser/shot-temperature-077.mjs /tmp/temp077 */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = process.argv[2] ?? '/tmp/temp077'
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password

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

  // ===== (A) 생성 모달 온도 슬라이더 =====
  await page.getByRole('button', { name: /새 에이전트/ }).first().click()
  await page.waitForTimeout(800)
  const tempLabel = await page.getByText('Temperature', { exact: true }).count()
  log('A_TEMP_LABEL=' + tempLabel + ' (expect >=1)')

  // 온도 Field 안의 Switch(끔=자동). 모달 안에서 Slider는 disabled 상태로 시작.
  const sliderBefore = await page.locator('.ant-modal-container .ant-slider').first().getAttribute('class')
  const disabledBefore = (sliderBefore ?? '').includes('ant-slider-disabled')
  log('A_SLIDER_DISABLED_BEFORE=' + disabledBefore + ' (expect true=자동)')

  // Temperature 행의 Switch 토글 → 수동. 온도 Field의 첫 switch를 잡는다.
  // (페이지 내 다른 Switch와 구분: Temperature 라벨의 Field 컨테이너 내부 switch)
  const tempSwitch = page.locator('.ant-modal-container .ant-switch').first()
  await tempSwitch.click()
  await page.waitForTimeout(250)
  const sliderAfter = await page.locator('.ant-modal-container .ant-slider').first().getAttribute('class')
  const disabledAfter = (sliderAfter ?? '').includes('ant-slider-disabled')
  log('A_SLIDER_DISABLED_AFTER=' + disabledAfter + ' (expect false=수동)')
  // 값 표시 span에 0.7
  const shows07 = await page.locator('.ant-modal-container').getByText('0.7', { exact: true }).count()
  log('A_VALUE_0.7_SHOWN=' + shows07 + ' (expect >=1)')
  await page.screenshot({ path: `${OUT}-A-create-temp.png`, fullPage: true })

  // 모달 닫기(취소)
  await page.getByRole('button', { name: '취소' }).first().click()
  await page.waitForTimeout(400)

  // ===== (B) Playground 오버라이드 페르소나 Select =====
  await page.getByText('Playground', { exact: true }).first().click()
  await page.waitForTimeout(1200)
  // 기본 에이전트가 code면 오버라이드가 bypass되므로 web(ui) 에이전트로 전환.
  // 상단 에이전트 셀렉터(커스텀 button, 모델배지 '(SDK)' 포함)를 열고 'Research Assistant'(seed ui) 선택.
  const trigger = page.locator('button', { hasText: '(SDK)' }).first()
  if (await trigger.count()) await trigger.click()
  else await page.locator('header button, button:has-text("원격")').first().click()
  await page.waitForTimeout(500)
  const ra = page.locator('button', { hasText: 'Research Assistant' }).first()
  if (await ra.count()) {
    await ra.click()
    log('B_SELECTED_WEB_AGENT=Research Assistant')
  } else {
    log('B_WEB_AGENT_NOT_FOUND')
  }
  await page.waitForTimeout(800)
  // 오버라이드 드로어 열기
  await page.getByRole('button', { name: /오버라이드/ }).first().click()
  await page.waitForTimeout(700)
  const personaFill = await page.getByText('페르소나 블록에서 채우기', { exact: true }).count()
  log('B_PERSONA_SELECT_LABEL=' + personaFill + ' (expect >=1; 코드/외부 에이전트면 0=정상 bypass)')

  if (personaFill > 0) {
    // 시스템 프롬프트 TextArea(드로어 내 유일) 초기값.
    const ta = page.locator('.ant-drawer textarea').first()
    const taBefore = await ta.inputValue().catch(() => '')
    // 페르소나 Select 열기(antd6: clickable=.ant-select-content) → 라벨로 스코프해 첫 옵션 선택.
    await page.locator('label', { hasText: '페르소나 블록에서 채우기' }).locator('.ant-select').first().click()
    await page.waitForTimeout(400)
    // antd6 옵션 클래스 폴백.
    let opts = page.locator('.ant-select-item-option')
    if (!(await opts.count())) opts = page.locator('.ant-select-item')
    const optCount = await opts.count()
    log('B_PERSONA_OPTIONS=' + optCount)
    if (optCount > 0) {
      // 마지막 옵션 선택(현재 로드된 페르소나=첫 옵션과 다른 것이라야 변화가 드러남).
      const pick = opts.nth(optCount - 1)
      const pickLabel = (await pick.textContent().catch(() => '')) ?? ''
      await pick.click()
      await page.waitForTimeout(400)
      const taAfter = await ta.inputValue().catch(() => '')
      log('B_PICKED=' + pickLabel.trim() + ' BEFORE_LEN=' + (taBefore?.length ?? 0) + ' AFTER_LEN=' + (taAfter?.length ?? 0))
      log('B_FILLED=' + (taAfter.length > 0 && taAfter !== taBefore))
    }
    await page.screenshot({ path: `${OUT}-B-override-persona.png`, fullPage: true })
  } else {
    await page.screenshot({ path: `${OUT}-B-override-bypass.png`, fullPage: true })
  }
  log('DONE')
} catch (e) {
  log('ERROR ' + (e?.message ?? e))
  await page.screenshot({ path: `${OUT}-error.png` }).catch(() => {})
  process.exitCode = 1
} finally {
  await browser.close()
}

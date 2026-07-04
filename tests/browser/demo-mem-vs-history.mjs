/* 실증(스펙 후보) — 메모리 vs 채팅 히스토리 차이를 트레이스로 보인다.
   같은 로그인 사용자로: 세션 A에서 사실 진술 → "새 대화"(히스토리 리셋) → 세션 B에서 같은 사실을
   물어봄. 히스토리는 세션 B에서 비어 있지만, 메모리는 user 스코프라 세션을 넘어 회상되는지 관측한다.
   관측 지점 = 트레이스 칩 "N mem"(그 턴 회상 건수) + 인스펙터.

   Mock LLM 호스트에선 추출/임베딩이 degenerate할 수 있음 — 결과를 정직히 로그(회상 0이면 그것도 발견).
   템플릿=shot-broker-rag-inspector-130.mjs(플레이그라운드 채팅·트레이스 칩) + shot-playground-032("새 대화").
   실행: PLAYWRIGHT_DIR=<dir> ADMIN_EMAIL=.. ADMIN_PASSWORD=.. node tests/browser/demo-mem-vs-history.mjs */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = process.env.OUT ?? '/tmp/mem-demo'
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password

const AGENT = 'Research Assistant' // 장기 기억 (mem0) 켜진 시드 에이전트
const FACT = '내가 가장 좋아하는 색은 파랑색이야. 꼭 기억해줘.'
const ASK = '내가 가장 좋아하는 색이 뭐야?'
const log = (...a) => console.log(...a)

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
const page = await ctx.newPage()

async function sendTurn(text, tag) {
  const box = page.locator('textarea').first()
  await box.click()
  await box.fill(text)
  await page.keyboard.press('Enter')
  log(`  → 전송[${tag}]: ${text}`)
  // 응답 도착: 트레이스 칩("N mem") 또는 새 assistant 메시지 대기(최대 120s)
  const chip = page.getByText(/\d+\s*mem/).last()
  const ok = await chip.waitFor({ state: 'visible', timeout: 120000 }).then(() => true).catch(() => false)
  await page.waitForTimeout(1500)
  const chipText = ok ? await chip.innerText().catch(() => '(칩없음)') : '(응답/칩 미도착)'
  const memN = (chipText.match(/(\d+)\s*mem/) || [])[1] ?? '?'
  log(`  ← 트레이스[${tag}]: "${chipText.replace(/\n/g, ' ')}" → 회상 ${memN}건`)
  await page.screenshot({ path: `${OUT}-${tag}.png`, fullPage: true }).catch(() => {})
  return { ok, memN, chipText }
}

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })

  await page.getByRole('menuitem', { name: 'Playground' }).click()
  await page.waitForTimeout(1000)

  // 에이전트 선택(아바타 버튼 → 이름)
  await page.locator('button:has(.ant-avatar)').first().click().catch(() => {})
  await page.waitForTimeout(500)
  await page.getByText(AGENT, { exact: false }).first().click().catch(() => {})
  await page.waitForTimeout(800)
  const headerOk = await page.getByText(AGENT, { exact: false }).first().isVisible().catch(() => false)
  log(`에이전트 선택: ${AGENT} (헤더 표시=${headerOk})`)

  // ---- 세션 A: 사실 진술 (이후 메모리 자동 add) ----
  log('\n[세션 A] 사실을 말한다 — 이 턴의 회상은 보통 0(아직 저장 전).')
  const a = await sendTurn(FACT, 'A-fact')

  // ---- 새 대화 → 세션 B (히스토리 리셋) ----
  const resetBtn = page.getByRole('button', { name: '새 대화' })
  const canReset = await resetBtn.count()
  log(`\n"새 대화" 버튼 ${canReset}개 — 세션 B로 히스토리 리셋`)
  if (canReset) { await resetBtn.first().click(); await page.waitForTimeout(1200) }

  // ---- 세션 B: 같은 사실을 물어봄 (히스토리 비었음 — 메모리만이 답을 알 수 있음) ----
  log('\n[세션 B] 새 세션(히스토리 0). 같은 사실을 물어본다 — 회상 >0이면 메모리가 세션을 넘은 것.')
  const b = await sendTurn(ASK, 'B-ask')

  log('\n================ 결과 ================')
  log(`세션 A 회상: ${a.memN}건 (진술 턴)`)
  log(`세션 B 회상: ${b.memN}건 (새 세션 질문 턴) — 히스토리는 0인데 이게 >0이면 = 메모리가 세션을 가로지름`)
  log(b.memN !== '?' && Number(b.memN) > 0
    ? '판정: ✅ 메모리가 세션 B(빈 히스토리)에서 세션 A의 사실을 회상 — 히스토리로는 불가능한 일'
    : '판정: ⚠ 세션 B 회상 0/미검출 — Mock 백엔드 추출·임베딩 degenerate 가능성(실 모델 필요). 구조는 user 스코프이나 mock이 증류를 못 함')
} catch (e) {
  log('ERROR ' + (e?.message ?? e))
  await page.screenshot({ path: `${OUT}-error.png`, fullPage: true }).catch(() => {})
  process.exitCode = 1
} finally {
  await browser.close()
  if (_fx) _fx.teardown()
}

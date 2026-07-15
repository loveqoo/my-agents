/* 노드형(일렬 파이프라인) 저작→저장→왕복 기능 검증 (스펙 259) — 시스템 Chrome.
   admin 로그인 → 새 에이전트 → 종류=노드형 → (모델/프롬프트 숨김 확인) → 하는 일: 노드 추가·
   프롬프트/모델/도구 입력·프롬프트 불러오기 → 요약(처리 단계 확인) → 생성 → 브라우저 세션으로
   GET /api/agents 재조회해 config.nodes 보존을 단언(외형 아닌 기능 검증 — 메모리 규칙).

   실행: PLAYWRIGHT_DIR=<abs>/tests/e2e/node_modules/playwright \
         ADMIN_EMAIL=admin@example.com ADMIN_PASSWORD=adminpass123 \
         node tests/browser/shot-pipeline-259.mjs tests/browser/out-259 */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = process.argv[2] ?? '/tmp/pipeline-259'
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password
const NAME = 'pipeline-' + Date.now().toString(36)

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ viewport: { width: 1280, height: 1000 } })
const page = await ctx.newPage()
const log = (...a) => console.log(...a)
const fails = []
const check = (cond, msg) => { log((cond ? '  ok  ' : ' FAIL ') + msg); if (!cond) fails.push(msg) }

async function pickFieldSelect(labelText, optionText) {
  const field = page.locator('label', { hasText: labelText }).first()
  await field.locator('.ant-select').first().click()
  await page.waitForTimeout(300)
  await page.locator('.ant-select-dropdown:visible .ant-select-item-option', { hasText: optionText }).first().click()
  await page.waitForTimeout(300)
}
async function openSelectByPlaceholder(placeholder, nth = 0) {
  // learning 080: antd6 DOM 클래스 개명 — .ant-* 가정 말고 getByText로 렌더 먼저 잡는다.
  await page.getByText(placeholder, { exact: true }).nth(nth).click({ force: true })
  await page.waitForTimeout(300)
  return page.locator('.ant-select-dropdown:visible .ant-select-item-option')
}

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  await page.waitForTimeout(600)

  await page.getByRole('button', { name: /새 에이전트/ }).first().click()
  await page.waitForTimeout(700)

  // ── 단계 0 정체성 ──
  await page.getByPlaceholder('예: research-assistant').fill(NAME)
  await pickFieldSelect('에이전트 종류', '노드형')
  await page.waitForTimeout(400)
  // 노드형이면 모델/프롬프트 숨김 + 안내(종류 필드 아래 합류, 스펙 263) 노출
  const noteVisible = await page.getByText('노드는 다음 "하는 일" 단계에서 추가합니다', { exact: false }).isVisible().catch(() => false)
  const modelFieldHidden = !(await page.locator('label', { hasText: '프롬프트' }).first().isVisible().catch(() => false))
  check(noteVisible && modelFieldHidden, '단계0: 노드형 선택 시 모델/프롬프트 숨김 + 안내 노출(종류 아래)')
  await page.screenshot({ path: `${OUT}-step0.png` })

  // 다음 → 단계 1 하는 일
  await page.getByRole('button', { name: '다음' }).click()
  await page.waitForTimeout(500)
  check(await page.getByText('처리 단계 (노드)', { exact: true }).isVisible().catch(() => false), '단계1: 노드 편집기 헤더(처리 단계) 렌더')
  const nextBtn = page.getByRole('button', { name: '다음' })
  // 노드 없으면 "다음" 비활성(pipelineInvalid) — 게이트 확인
  check(await nextBtn.isDisabled().catch(() => false), '단계1: 노드 0개면 다음 비활성(빈 파이프라인 게이트)')

  // 노드 추가 (2개) — add()가 모델을 첫 옵션으로 자동 채움(프롬프트만 채우면 유효).
  await page.getByRole('button', { name: /노드 추가/ }).click()
  await page.waitForTimeout(300)
  const promptBoxes = page.getByPlaceholder('이 노드가 할 일을 지시하세요 (예: 입력을 분석해 핵심 3가지를 뽑아라)')
  await promptBoxes.first().fill('입력을 분석해 핵심 3가지를 뽑아라')
  await page.waitForTimeout(200)

  // 도구 선택 — 노드1에 첫 도구 배정(→ 저장 시 mcps/vectorTables 풀 파생 검증). 등록 도구 없으면 skip.
  let toolPicked = false
  try {
    const opts = await openSelectByPlaceholder('이 노드가 참고할 도구', 0)
    const n = await opts.count()
    if (n > 0) { await opts.first().click(); toolPicked = true; await page.keyboard.press('Escape') }
    log('  info  노드 도구 옵션 ' + n + '개' + (n ? ' — 첫 도구 선택' : ''))
  } catch (e) { log('  info  도구 선택 skip: ' + (e?.message ?? e).slice(0, 60)) }
  await page.waitForTimeout(200)

  // 출력 형식(스펙 261): 노드1을 JSON으로 전환 — 왕복 보존 검증용. (필수 키 태그 입력은 unit이 덮음.)
  await page.getByText('JSON', { exact: true }).first().click({ force: true })
  await page.waitForTimeout(200)

  // 둘째 노드 + 프롬프트 불러오기(있으면) → 프롬프트 자동 채움 확인
  await page.getByRole('button', { name: /노드 추가/ }).click()
  await page.waitForTimeout(300)
  const promptLoad = page.getByText('등록 프롬프트에서 가져오기', { exact: true }).last()
  if (await promptLoad.isVisible().catch(() => false)) {
    await promptLoad.click({ force: true })
    await page.waitForTimeout(300)
    const popt = page.locator('.ant-select-dropdown:visible .ant-select-item-option')
    if (await popt.count() > 0) { await popt.first().click(); await page.waitForTimeout(300) }
    const after2 = await promptBoxes.nth(1).inputValue()
    check(after2.trim().length > 0, '단계1: 프롬프트 불러오기가 노드 프롬프트를 채움(결정 #1)')
  } else {
    log('  info  등록 프롬프트 없음 — 둘째 노드 수동 입력')
  }
  if (!(await promptBoxes.nth(1).inputValue()).trim()) await promptBoxes.nth(1).fill('요약해서 한 문단으로 정리하라')
  await page.waitForTimeout(200)
  // 맥락 모드(스펙 260): 노드2를 "이전 결과만"(clean)으로 전환 — 왕복 보존 검증용.
  await page.getByText('이전 결과만', { exact: true }).last().click({ force: true })
  await page.waitForTimeout(200)
  // 두 노드 다 채워지면 "다음" 활성(모델 자동채움 + 프롬프트 입력 → pipelineValid)
  check(!(await nextBtn.isDisabled().catch(() => true)), '단계1: 노드 채우면 다음 활성(pipelineValid)')
  await page.screenshot({ path: `${OUT}-step1.png`, fullPage: true })

  // 다음 → 단계2 세부 → 다음 → 단계3 요약
  await page.getByRole('button', { name: '다음' }).click()
  await page.waitForTimeout(400)
  await page.getByRole('button', { name: '다음' }).click()
  await page.waitForTimeout(400)
  const summaryVisible = await page.getByText('처리 단계', { exact: false }).first().isVisible().catch(() => false)
  check(summaryVisible, '단계3: 요약에 "처리 단계" 행 노출')
  await page.screenshot({ path: `${OUT}-summary.png`, fullPage: true })

  // 생성
  await page.getByRole('button', { name: '에이전트 생성' }).click()
  await page.waitForTimeout(1500)

  // ── 왕복 검증: 브라우저 세션으로 API 재조회 ──
  const roundtrip = await page.evaluate(async (nm) => {
    const r = await fetch('/api/agents?limit=200', { credentials: 'include' })
    if (!r.ok) return { error: 'status ' + r.status }
    const j = await r.json()
    const items = Array.isArray(j) ? j : (j.items ?? j.data ?? [])
    const a = items.find((x) => x.name === nm)
    if (!a) return { error: 'not found', count: items.length }
    return { impl: a.impl, conformance: a.conformance, nodes: a.nodes, mcps: a.mcps, vectorTables: a.vectorTables, source: a.source, format0: a.nodes?.[0]?.format }
  }, NAME)
  log('ROUNDTRIP=' + JSON.stringify(roundtrip))
  check(roundtrip && !roundtrip.error, '왕복: 생성된 에이전트 조회됨')
  check(roundtrip?.impl === 'pipeline', `왕복: impl=pipeline (got ${roundtrip?.impl})`)
  check(Array.isArray(roundtrip?.nodes) && roundtrip.nodes.length === 2, `왕복: nodes 2개 보존 (got ${roundtrip?.nodes?.length})`)
  check(roundtrip?.nodes?.[0]?.prompt?.includes('핵심 3가지'), '왕복: 노드1 프롬프트 보존')
  check(!!roundtrip?.nodes?.[0]?.model, '왕복: 노드1 모델 보존')
  // 맥락 모드 왕복(스펙 260): 노드1 기본 carry·노드2 clean 보존
  check((roundtrip?.nodes?.[0]?.context ?? 'carry') === 'carry', `왕복: 노드1 맥락=carry (got ${roundtrip?.nodes?.[0]?.context})`)
  check(roundtrip?.nodes?.[1]?.context === 'clean', `왕복: 노드2 맥락=clean 보존 (got ${roundtrip?.nodes?.[1]?.context})`)
  // 출력 형식 왕복(스펙 261): 노드1 format=json 보존
  check(roundtrip?.nodes?.[0]?.format === 'json', `왕복: 노드1 출력형식=json 보존 (got ${roundtrip?.nodes?.[0]?.format})`)
  check(roundtrip?.conformance === 'conforming', `왕복: conformance=conforming (got ${roundtrip?.conformance})`)
  if (toolPicked) {
    const derivedPool = (roundtrip?.mcps?.length ?? 0) + (roundtrip?.vectorTables?.length ?? 0)
    check((roundtrip?.nodes?.[0]?.tools?.length ?? 0) === 1, `왕복: 노드1 도구 1개 보존 (got ${roundtrip?.nodes?.[0]?.tools?.length})`)
    check(derivedPool > 0, `왕복: 도구 풀 파생됨 mcps=${JSON.stringify(roundtrip?.mcps)} vt=${JSON.stringify(roundtrip?.vectorTables)}`)
  } else {
    log('  info  도구 미선택 환경 — 풀 파생 검증 skip')
  }

  log('\n' + (fails.length ? `FAILED ${fails.length}: ${fails.join(' | ')}` : 'ALL GREEN'))
  if (fails.length) process.exitCode = 1
} catch (e) {
  log('ERROR ' + (e?.stack ?? e))
  await page.screenshot({ path: `${OUT}-error.png`, fullPage: true }).catch(() => {})
  process.exitCode = 1
} finally {
  await browser.close()
}

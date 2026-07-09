/* 스펙 256 후속(사용자 보고) — 멀티라인 엔티티 값이 검색 결과에서 예전처럼(원시 텍스트) 나오던 버그.
   parseEntityText가 값에 개행이 있으면 연속 줄을 key:value로 못 봐 통째 null → 원문 폴백.
   수정 후: 연속 줄을 직전 필드 값에 이어붙여 **구조화(EntityFields)** 로 렌더 — "빈 필드:" 신호로 확인.

   검색 시험(RetrievalTestPanel)이 플레이그라운드 인스펙터 HitCard와 동일한 parseEntityText+EntityFields
   경로(스펙 255 공용화)라, 오케스트레이터 없이 이 화면에서 재현·검증 가능.

   실행: PLAYWRIGHT_DIR=<dir> node tests/browser/shot-entity-multiline-256.mjs */
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT_DIR = path.join(__dirname, 'out-256-multiline')
fs.mkdirSync(OUT_DIR, { recursive: true })
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password

const NEW_NAME = 'e2e-multiline-256'
const SCHEMA_TEXT = JSON.stringify({
  type: 'object',
  required: ['metadata', 'data'],
  properties: { metadata: { type: 'object', required: ['pid'] } },
})

const fails = []
const check = (c, m) => { console.log((c ? '  ok  ' : ' FAIL ') + m); if (!c) fails.push(m) }

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1400, height: 1100 } })
const page = await ctx.newPage()
const rowFor = (name) => page.locator('table tbody tr').filter({ hasText: name })
async function shot(name) { await page.screenshot({ path: path.join(OUT_DIR, `${name}.png`), fullPage: true }).catch(() => {}) }

const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'ml-256-'))
const goodFile = path.join(tmpDir, 'good.jsonl')
// 핵심: data.description이 **여러 줄**(개행 포함) + 빈 필드(full_path/default_value/candidate).
// 직렬화 시 "description: <1줄>\n<2줄>\n<3줄>" 형태라 옛 파서는 통째 null → 원문 폴백했다.
const DESC = '* 35세 이상으로 자녀나 반려동물을 양육하\n자가의 자동차를 보유한 안정된 기반의 가족\n라이프스타일 보유자 그룹을 추정합니다.'
fs.writeFileSync(
  goodFile,
  [1, 2].map((n) => JSON.stringify({
    metadata: { pid: n },
    data: { full_path: '', column_name: 'category_value', filter_name: `페르소나 ${n}`, description: DESC, default_value: '', candidate: '' },
  })).join('\n') + '\n'
)

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByRole('banner').getByRole('heading', { name: '에이전트' }).waitFor({ timeout: 10000 })
  await page.waitForTimeout(500)

  // 사전 정리
  const arr0 = await (await page.request.get(`${URL}/api/collections`)).json()
  for (const c of arr0.filter((c) => typeof c.name === 'string' && c.name.startsWith(NEW_NAME))) {
    await page.request.delete(`${URL}/api/collections/${c.id}`).catch(() => {})
  }

  await page.getByRole('menuitem', { name: 'RAG 컬렉션' }).first().click()
  await page.getByRole('banner').getByRole('heading', { name: 'RAG 컬렉션' }).waitFor({ timeout: 10000 })
  await page.waitForTimeout(400)

  // 생성 — 엔티티형
  await page.getByRole('button', { name: /컬렉션 생성/ }).click()
  const dlg = page.getByRole('dialog')
  await dlg.locator('.ant-modal-title', { hasText: '컬렉션 생성' }).waitFor({ timeout: 5000 })
  await dlg.locator('label', { hasText: '종류' }).locator('.ant-select').click()
  await page.locator('.ant-select-item-option[title*="엔티티형"]').click()
  await page.waitForTimeout(300)
  await dlg.getByPlaceholder('예: docs-kb').fill(NEW_NAME)
  await dlg.getByPlaceholder(/"type": "object"/).fill(SCHEMA_TEXT)
  await dlg.locator('label', { hasText: '임베딩 모델' }).locator('.ant-select').click()
  await page.waitForTimeout(300)
  // mock-embed는 실제 임베딩 모델이 있으면 숨겨짐(스펙 218) — 선택 가능한 첫 옵션을 고른다.
  await page.locator('.ant-select-dropdown:visible .ant-select-item-option:not(.ant-select-item-option-disabled)').first().click()
  await page.waitForTimeout(200)
  await shot('create-filled')
  await dlg.getByRole('button', { name: '생성', exact: true }).click()
  await page.waitForTimeout(1000)
  const createErr = await page.locator('.ant-message-error').allInnerTexts().catch(() => [])
  if (createErr.length) console.log('  (생성 에러 토스트)', JSON.stringify(createErr))
  await dlg.waitFor({ state: 'hidden', timeout: 8000 }).catch(() => {})
  await page.waitForTimeout(700)
  // 엔티티 컬렉션은 "엔티티 임베딩" 탭에 있다(스펙 212 목록 분리) — 전환 후 행을 찾는다.
  await page.getByRole('tab', { name: /엔티티 임베딩/ }).click().catch(() => {})
  await page.waitForTimeout(500)
  await shot('after-create')
  check((await rowFor(NEW_NAME).count()) === 1, `생성: "${NEW_NAME}" 행 1개`)

  // 업로드 — 문서 관리는 행 클릭으로 열린다(스펙 197: 전용 '문서' 버튼 제거).
  await rowFor(NEW_NAME).getByText(NEW_NAME).click()
  const docsDrawer = page.locator('.ant-drawer')
  await docsDrawer.getByText(`문서 관리 · ${NEW_NAME}`, { exact: true }).waitFor({ timeout: 5000 })
  await docsDrawer.locator('input[type="file"]').setInputFiles(goodFile)
  const okShown = await page.locator('.ant-message-success', { hasText: '인제스트 완료' }).first().waitFor({ timeout: 8000 }).then(() => true).catch(() => false)
  check(okShown, `업로드: "인제스트 완료" 토스트=${okShown}`)
  await page.waitForTimeout(600)
  await page.keyboard.press('Escape')
  await page.waitForTimeout(400)

  // 검색 시험 — 멀티라인 엔티티 히트가 구조화 렌더되는지
  await rowFor(NEW_NAME).getByRole('button', { name: /검색/ }).first().click()
  const searchDrawer = page.locator('.ant-drawer')
  await searchDrawer.getByText(`검색 시험 · ${NEW_NAME}`, { exact: true }).waitFor({ timeout: 5000 })
  await page.waitForTimeout(300)
  await searchDrawer.locator('textarea').first().fill('페르소나 자동차')
  await searchDrawer.getByRole('button', { name: /검색/ }).click()
  await page.waitForTimeout(1800)

  const drawerText = await searchDrawer.innerText().catch(() => '')
  await shot('search-result-multiline')
  // 구조화 신호: "빈 필드:" 는 EntityFields(구조화)만 냄. 원시 폴백은 "full_path:"·"default_value:"를
  //   리터럴 라인으로 흘릴 뿐 "빈 필드:" 를 못 만든다.
  const structured = /빈 필드\s*:/.test(drawerText)
  // 멀티라인 값(description 3줄)이 히트 본문에 실렸는지(검색 자체가 뭔가 반환했는지 방증).
  const hasDescBody = drawerText.includes('룰을 추정합니다') || drawerText.includes('안정된 기반')
  check(structured, `구조화 렌더(EntityFields "빈 필드:" 신호) 표시=${structured}`)
  check(hasDescBody, `멀티라인 description 본문 표시=${hasDescBody}`)
  console.log(`(발췌) 드로어 전문="${drawerText.slice(0, 400).replace(/\n/g, ' | ')}"`)

  await page.keyboard.press('Escape')
  await page.waitForTimeout(300)

  // 정리
  const delBtn = rowFor(NEW_NAME).getByRole('button', { name: /delete/i })
  await delBtn.click()
  const confirmDialog = page.getByRole('dialog')
  await confirmDialog.getByText('컬렉션을 삭제할까요?', { exact: true }).waitFor({ timeout: 5000 })
  await confirmDialog.getByRole('button', { name: '삭제', exact: true }).click()
  await page.waitForTimeout(800)
  check((await rowFor(NEW_NAME).count()) === 0, `정리: "${NEW_NAME}" 삭제됨`)
} catch (e) {
  console.error('예외', e.message)
  await shot('exception')
  fails.push('예외: ' + e.message)
} finally {
  try {
    const arr1 = await (await page.request.get(`${URL}/api/collections`)).json()
    for (const c of arr1.filter((x) => typeof x.name === 'string' && x.name.startsWith(NEW_NAME))) {
      await page.request.delete(`${URL}/api/collections/${c.id}`).catch(() => {})
    }
  } catch { /* best effort */ }
  fs.rmSync(tmpDir, { recursive: true, force: true })
  await browser.close()
  if (_fx) _fx.cleanup?.()
}

console.log(`\n${fails.length ? 'FAIL ' + fails.length : 'ALL PASS'} — out: ${OUT_DIR}`)
process.exit(fails.length ? 1 : 0)

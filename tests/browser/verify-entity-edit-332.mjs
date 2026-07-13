/* 스펙 332 기능 e2e — 엔티티 문서 편집(JSONL 행 단위).
   E1) 엔티티 문서 행의 편집 버튼이 **활성**(331에선 아예 없었음) → 에디터에 JSONL 로드+행 단위 힌트
   E2) 행 하나만 교체 → 저장 → "재임베딩 1 · 재사용 1" 토스트(행 단위 부분 재임베딩 실효과)
   E3) API 왕복: GET content == 수정 JSONL(blob 교체)
   실행: PLAYWRIGHT_DIR=<abs playwright dir> node tests/browser/verify-entity-edit-332.mjs */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const API = process.env.API_URL ?? 'http://127.0.0.1:8000'
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password
const S = Math.random().toString(36).slice(2, 8)
const COL = `e2e-332-${S}`

const fails = []
const ok = (cond, msg) => {
  console.log((cond ? '  ok  ' : ' FAIL ') + msg)
  if (!cond) fails.push(msg)
}
const row = (id, data) => JSON.stringify({ metadata: { id }, data })
const R1 = '인셉션 — 꿈속에서 생각을 심는 요원, 2010년 SF.'
const R2 = '올드보이 — 15년 감금의 복수극, 2003년.'
const R2N = '올드보이 — 오대수의 처절한 복수와 반전, 2003년 느와르.'
const ORIG = `${row(1, R1)}\n${row(2, R2)}`
const EDITED = `${row(1, R1)}\n${row(2, R2N)}`

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await (await browser.newContext({ viewport: { width: 1360, height: 950 } })).newPage()
let cid = null

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })

  const models = await (await page.request.get(`${API}/models`)).json()
  const emb = models.find((m) => m.kind === 'embedding')
  const colRes = await page.request.post(`${API}/collections`, {
    data: { name: COL, kind: 'entity', embedding_model_id: emb.id },
  })
  ok(colRes.status() === 201, `준비: 엔티티 컬렉션 (${colRes.status()})`)
  cid = (await colRes.json()).id
  const upRes = await page.request.post(`${API}/collections/${cid}/documents`, {
    multipart: { file: { name: 'movies.jsonl', mimeType: 'application/jsonl', buffer: Buffer.from(ORIG) } },
  })
  ok(upRes.status() === 201, `준비: JSONL 업로드 (${upRes.status()})`)

  // E1 — 편집 버튼 활성 + 에디터 로드 + 행 단위 힌트
  await page.getByText('RAG 컬렉션', { exact: true }).first().click()
  await page.waitForTimeout(800)
  await page.getByRole('tab', { name: '엔티티 임베딩' }).click() // 스펙 212 kind 탭 — 엔티티는 둘째 탭
  await page.waitForTimeout(400)
  await page.getByText(COL, { exact: true }).first().click()
  await page.getByText(`문서 관리 · ${COL}`).waitFor({ timeout: 8000 })
  await page.waitForTimeout(600)
  const editBtn = page.locator('.ant-drawer-section').locator('.anticon-edit').first()
  ok(!(await editBtn.locator('xpath=ancestor::button').isDisabled()), 'E1a 엔티티 편집 버튼 활성')
  await editBtn.click()
  await page.getByText('문서 편집 · movies.jsonl').waitFor({ timeout: 8000 })
  const cm = page.locator('.cm-content')
  await cm.waitFor({ timeout: 8000 })
  ok((await cm.innerText()).includes('인셉션'), 'E1b 에디터에 JSONL 로드')
  ok(await page.getByText(/한 줄 = 한 엔티티/).count() > 0, 'E1c 행 단위 힌트 문구')

  // E2 — 행 하나 교체 → 저장 → 부분 재임베딩 토스트
  await cm.click()
  await page.keyboard.press('ControlOrMeta+a')
  await page.keyboard.insertText(EDITED)
  await page.getByRole('button', { name: '저장', exact: true }).click()
  const toast = page.locator('.ant-message').getByText(/저장 완료 — 청크 2개 \(재임베딩 1 · 재사용 1\)/)
  await toast.waitFor({ timeout: 15000 })
  ok(true, `E2 토스트: ${(await toast.innerText()).trim()}`)

  // E3 — blob 실제 교체
  const docs = await (await page.request.get(`${API}/collections/${cid}/documents`)).json()
  const doc = docs.items.find((d) => d.filename === 'movies.jsonl')
  const content = await (await page.request.get(`${API}/collections/${cid}/documents/${doc.id}/content`)).json()
  ok(content.text === EDITED, 'E3 GET content == 수정 JSONL(blob 교체)')
} finally {
  if (cid) {
    const delRes = await page.request.delete(`${API}/collections/${cid}`).catch(() => null)
    console.log(`CLEANUP 컬렉션 삭제 (${delRes?.status?.() ?? 'skip'})`)
  }
  await browser.close()
}

console.log()
if (fails.length) {
  console.log(`FAILED ${fails.length}건: ${fails.join(' | ')}`)
  process.exit(1)
}
console.log('VERIFY332_UI_OK — 엔티티 편집 버튼 활성→JSONL 편집→행 단위 재임베딩 토스트→blob 교체')

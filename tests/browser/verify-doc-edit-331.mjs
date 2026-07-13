/* 스펙 331 기능 e2e — RAG 문서 런타임 수정(에디터 → 저장 → 실효과).
   외형이 아니라 **기능**을 단언한다(회고: 스샷 한 장 완료 선언 금지):
   E1) 문서 행 편집 버튼 → 에디터 Modal(CodeMirror)에 원문 로드
   E2) 본문 교체 → 저장 → "저장 완료 — 청크 … 재임베딩 … 재사용" 토스트
   E3) API 왕복: GET content == 수정 본문 (blob 실제 교체)
   E4) 검색 실효과: 수정 문단 동일질의 → score≈1.0 최상위(재임베딩이 실제 일어남)
   준비물(컬렉션+문서)은 page.request(세션 쿠키 공유)로 시드하고 끝나면 삭제.

   실행: PLAYWRIGHT_DIR=<abs playwright dir> node tests/browser/verify-doc-edit-331.mjs */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const API = process.env.API_URL ?? 'http://127.0.0.1:8000'
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password
const S = Math.random().toString(36).slice(2, 8)
const COL = `e2e-331-${S}`

const fails = []
const ok = (cond, msg) => {
  console.log((cond ? '  ok  ' : ' FAIL ') + msg)
  if (!cond) fails.push(msg)
}

const P1 = '첫 문단입니다. 이 문서는 편집 기능 검증을 위해 준비된 원본 본문을 담고 있습니다.'
const P2 = '둘째 문단입니다. 저장 전의 내용이며 편집 후에는 다른 문장으로 교체될 예정입니다.'
const NEW2 = '둘째 문단은 오로라 관측 일정과 카나리 배포 지침으로 완전히 교체되었습니다.'

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ viewport: { width: 1360, height: 950 } })
const page = await ctx.newPage()
let cid = null

try {
  // 로그인
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })

  // 시드: 컬렉션(mock-embed) + 텍스트 문서 — page.request는 로그인 쿠키를 공유한다.
  const models = await (await page.request.get(`${API}/models`)).json()
  const emb = models.find((m) => m.kind === 'embedding')
  ok(!!emb, `준비: embedding 모델 (${emb?.name})`)
  const colRes = await page.request.post(`${API}/collections`, {
    data: { name: COL, kind: 'document', embedding_model_id: emb.id, chunk_size: 60, chunk_overlap: 0 },
  })
  ok(colRes.status() === 201, `준비: 컬렉션 생성 (${colRes.status()})`)
  cid = (await colRes.json()).id
  const upRes = await page.request.post(`${API}/collections/${cid}/documents`, {
    multipart: { file: { name: 'notes.md', mimeType: 'text/markdown', buffer: Buffer.from(`${P1}\n\n${P2}`) } },
  })
  ok(upRes.status() === 201, `준비: 문서 업로드 (${upRes.status()})`)

  // E1 — 컬렉션 메뉴 → 행 클릭(문서 드로어) → 편집 버튼 → 에디터에 원문
  await page.getByText('RAG 컬렉션', { exact: true }).first().click()
  await page.waitForTimeout(800)
  await page.getByText(COL, { exact: true }).first().click()
  await page.getByText(`문서 관리 · ${COL}`).waitFor({ timeout: 8000 })
  await page.waitForTimeout(600)
  const drawer = page.locator('.ant-drawer-section')  // antd v6: content→section
  await drawer.locator('.anticon-edit').first().click()
  await page.getByText('문서 편집 · notes.md').waitFor({ timeout: 8000 })
  const cm = page.locator('.cm-content')
  await cm.waitFor({ timeout: 8000 })
  const loaded = await cm.innerText()
  ok(loaded.includes('첫 문단입니다'), 'E1 에디터에 원문 로드')

  // E2 — 전체 교체 입력 → 저장 → 통계 토스트
  await cm.click()
  await page.keyboard.press('ControlOrMeta+a')
  await page.keyboard.insertText(`${P1}\n\n${NEW2}`)
  await page.getByRole('button', { name: '저장', exact: true }).click()
  const toast = page.locator('.ant-message').getByText(/저장 완료 — 청크 \d+개 \(재임베딩 \d+ · 재사용 \d+\)/)
  await toast.waitFor({ timeout: 15000 })
  ok(true, `E2 저장 토스트: ${(await toast.innerText()).trim()}`)

  // E3 — blob 실제 교체(API 왕복)
  const docs = await (await page.request.get(`${API}/collections/${cid}/documents`)).json()
  const doc = docs.items.find((d) => d.filename === 'notes.md')
  const content = await (await page.request.get(`${API}/collections/${cid}/documents/${doc.id}/content`)).json()
  ok(content.text === `${P1}\n\n${NEW2}`, 'E3 GET content == 수정 본문(blob 교체)')

  // E4 — 검색 실효과: 새 문단 동일질의 최상위. 점수 임계는 느슨하게 — dev DB 기본 임베딩이
  // 실모델(e5)이면 동일 텍스트도 1.0이 아니다(query 접두·정규화). 핵심 단언은 "최상위=수정 문단".
  const sr = await (
    await page.request.post(`${API}/collections/${cid}/search`, { data: { query: NEW2, top_k: 3 } })
  ).json()
  const top = sr.results?.[0]
  ok(!!top && top.text === NEW2 && top.score > 0.8, `E4 수정 문단이 검색 최상위 (score=${top?.score})`)
  ok(!sr.results?.some((h) => h.text.includes('저장 전의 내용')), 'E4b 구 본문은 검색에 없음')
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
console.log('VERIFY331_UI_OK — 편집→저장→재임베딩→검색 실효과 전부 통과')

/* 스펙 149 e2e — 엔티티 RAG(JSONL 한 줄=한 엔티티, metadata 동반 검색) 브라우저 검증.
   (K1) RAG 컬렉션 생성 모달: 종류 Select에서 "엔티티형…" 선택 → 청크 크기/겹침 입력이 사라지고
        "JSON Schema (선택)" TextArea가 나타난다.
   (K2) 식별 이름 "e2e-entities-149" + 별명 "E2E 엔티티" + JSON Schema + 임베딩 모델 "mock-embed" →
        생성 → 목록에 "E2E 엔티티" 행 + "엔티티" 태그.
   (K3) 문서 관리 드로어: 업로드 버튼 라벨 "JSONL 업로드" + 청크 정책 입력 없음.
   (K4) 스키마 위반 JSONL 업로드 → "1번째 줄" 포함 오류 메시지, 문서 목록은 비어 있다(fail-closed).
   (K5) 정상 JSONL(3행) 업로드 → "인제스트 완료" 메시지 + 문서 목록 1건.
   (K6) 검색 시험 드로어: 질의 "무선 키보드" → 결과 카드에 metadata JSON("pid" 포함)이 보인다.
   (K7) 정리: "E2E 엔티티" 컬렉션 삭제 → 목록에서 사라짐.

   템플릿=shot-naming-148.mjs(로그인·banner heading 대기·antd 6 Select 옵션(.ant-select-item-option[title=…])·
   아이콘 버튼 정규식 매치 관례). 앱 코드 수정 없음 — 검증 전용.

   실행: PLAYWRIGHT_DIR=<dir> node tests/browser/shot-entity-rag-149.mjs */
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT_DIR = path.join(__dirname, 'out-149')
fs.mkdirSync(OUT_DIR, { recursive: true })
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password

const NEW_NAME = 'e2e-entities-149'
const NEW_ALIAS = 'E2E 엔티티'
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
const consoleErrors = []
page.on('console', (m) => m.type() === 'error' && consoleErrors.push(m.text()))

const rowFor = (name) => page.locator('table tbody tr').filter({ hasText: name })

async function shot(name) {
  await page.screenshot({ path: path.join(OUT_DIR, `${name}.png`), fullPage: true }).catch(() => {})
}

async function gotoCollections() {
  await page.getByRole('menuitem', { name: 'RAG 컬렉션' }).first().click()
  await page.getByRole('banner').getByRole('heading', { name: 'RAG 컬렉션' }).waitFor({ timeout: 10000 })
  await page.waitForTimeout(400)
}

// 임시 JSONL 파일 작성용 스크래치 디렉토리.
const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'entity-rag-149-'))
const badFile = path.join(tmpDir, 'bad.jsonl')
const goodFile = path.join(tmpDir, 'good.jsonl')
fs.writeFileSync(badFile, JSON.stringify({ metadata: { sid: 1 }, data: '텍스트입니다' }) + '\n')
fs.writeFileSync(
  goodFile,
  [1, 2, 3]
    .map((n) => JSON.stringify({ metadata: { pid: n }, data: { name: `무선 키보드 ${n}`, desc: '저소음 무선 키보드' } }))
    .join('\n') + '\n'
)

try {
  // ---------- 로그인 ----------
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByRole('banner').getByRole('heading', { name: '에이전트' }).waitFor({ timeout: 10000 })
  await page.waitForTimeout(500)

  // ---------- 사전 정리(멱등화): API로 잔여 NEW_NAME 컬렉션 삭제 ----------
  const listResp0 = await page.request.get(`${URL}/api/collections`)
  const arr0 = await listResp0.json()
  const stale = arr0.filter((c) => typeof c.name === 'string' && c.name.startsWith(NEW_NAME))
  for (const c of stale) await page.request.delete(`${URL}/api/collections/${c.id}`).catch(() => {})
  console.log(`(사전정리) 잔여 "${NEW_NAME}*" ${stale.length}건 제거`)

  await gotoCollections()

  // ================= K1: 생성 모달 — 종류=엔티티형 선택 시 청크 필드 사라지고 JSON Schema 등장 =================
  const collCreateBtn = page.getByRole('button', { name: /컬렉션 생성/ })
  const collCreateBtnDisabled = await collCreateBtn.isDisabled().catch(() => true)
  if (collCreateBtnDisabled) {
    check(false, 'K1: "컬렉션 생성" 버튼이 disabled(임베딩 모델 미등록 추정) — 모달을 열 수 없어 검증 불가')
    throw new Error('컬렉션 생성 버튼 disabled — 이후 스텝 진행 불가')
  }
  await collCreateBtn.click()
  const collDialog = page.getByRole('dialog')
  await collDialog.locator('.ant-modal-title', { hasText: '컬렉션 생성' }).waitFor({ timeout: 5000 })

  // 종류 Select — 라벨 텍스트로 필드 그룹을 찾은 뒤 그 안의 .ant-select를 조작.
  const kindLabel = collDialog.locator('label', { hasText: '종류' })
  const kindSelect = kindLabel.locator('.ant-select')
  await kindSelect.click()
  await page.locator('.ant-select-item-option[title*="엔티티형"]').click()
  await page.waitForTimeout(300)

  const chunkSizeLabelCount = await collDialog.locator('label', { hasText: '청크 크기' }).count()
  const schemaLabelCount = await collDialog.locator('label', { hasText: 'JSON Schema' }).count()
  check(chunkSizeLabelCount === 0, `K1a: 엔티티형 선택 후 "청크 크기" 입력 사라짐(개수=${chunkSizeLabelCount})`)
  check(schemaLabelCount === 1, `K1b: 엔티티형 선택 후 "JSON Schema" TextArea 등장(개수=${schemaLabelCount})`)
  await shot('k1-create-entity-kind')

  // ================= K2: 이름/별명/스키마/임베딩 모델 입력 → 생성 → 목록에 태그 =================
  await collDialog.getByPlaceholder('예: docs-kb').fill(NEW_NAME)
  await collDialog.getByPlaceholder('예: 사내 위키').fill(NEW_ALIAS)
  await collDialog.getByPlaceholder(/"type": "object"/).fill(SCHEMA_TEXT)

  const embedSelect = collDialog.locator('label', { hasText: '임베딩 모델' }).locator('.ant-select')
  await embedSelect.click()
  await page.locator('.ant-select-item-option', { hasText: 'mock-embed' }).first().click()
  await page.waitForTimeout(200)
  await shot('k2-create-filled')

  await collDialog.getByRole('button', { name: '생성', exact: true }).click()
  await collDialog.waitFor({ state: 'hidden', timeout: 8000 }).catch(() => {})
  await page.waitForTimeout(700)

  const newRow = rowFor(NEW_ALIAS)
  const newRowCount = await newRow.count()
  let newRowText = ''
  if (newRowCount > 0) newRowText = await newRow.first().innerText()
  check(
    newRowCount === 1 && newRowText.includes('엔티티'),
    `K2: 생성 후 목록에 "${NEW_ALIAS}" 행 1개 + "엔티티" 태그 포함(실제=${newRowCount}, 텍스트="${newRowText.replace(/\n/g, ' | ')}")`
  )
  await shot('k2-list-after-create')

  // ================= K3: 문서 관리 드로어 — 업로드 버튼 라벨 + 청크 정책 부재 =================
  await newRow.first().getByRole('button').first().click() // 파일(문서) 아이콘 버튼 — actions 첫 번째
  const docsDrawer = page.locator('.ant-drawer')
  await docsDrawer.getByText(`문서 관리 · ${NEW_NAME}`, { exact: true }).waitFor({ timeout: 5000 })
  await page.waitForTimeout(300)

  const uploadBtnText = await docsDrawer.getByRole('button', { name: /업로드/ }).first().innerText()
  const chunkPolicyCount = await docsDrawer.locator('label', { hasText: '청크 크기' }).count()
  check(uploadBtnText.includes('JSONL 업로드'), `K3a: 업로드 버튼 라벨="JSONL 업로드"(실제="${uploadBtnText}")`)
  check(chunkPolicyCount === 0, `K3b: 드로어에 "청크 크기" 입력 없음(개수=${chunkPolicyCount})`)
  await shot('k3-docs-drawer')

  // ================= K4: 위반 JSONL 업로드 → "1번째 줄" 포함 오류, 문서 목록 비어있음 =================
  const fileInput = docsDrawer.locator('input[type="file"]')
  await fileInput.setInputFiles(badFile)
  const badErrToast = page.locator('.ant-message-error', { hasText: '1번째 줄' })
  const badErrShown = await badErrToast.first().waitFor({ timeout: 8000 }).then(() => true).catch(() => false)
  let badErrText = ''
  if (badErrShown) badErrText = await badErrToast.first().innerText().catch(() => '')
  check(badErrShown && badErrText.includes('1번째 줄'), `K4a: 위반 업로드 → "1번째 줄" 포함 오류 토스트(실측="${badErrText}")`)
  await shot('k4-bad-upload-error')
  await page.waitForTimeout(500)

  const docRowsAfterBad = await docsDrawer.locator('table tbody tr').count()
  const emptyTextShown = await docsDrawer.getByText('문서 없음').count()
  check(
    docRowsAfterBad === 0 || emptyTextShown > 0,
    `K4b: 위반 업로드 후 문서 목록 비어있음(행=${docRowsAfterBad}, "문서 없음" 표시=${emptyTextShown})`
  )
  await shot('k4-docs-empty-after-bad')

  // ================= K5: 정상 JSONL 업로드 → "인제스트 완료" + 문서 목록 1건 =================
  await fileInput.setInputFiles(goodFile)
  const goodOkToast = page.locator('.ant-message-success', { hasText: '인제스트 완료' })
  const goodOkShown = await goodOkToast.first().waitFor({ timeout: 8000 }).then(() => true).catch(() => false)
  check(goodOkShown, `K5a: 정상 업로드 → "인제스트 완료" 성공 토스트 표시=${goodOkShown}`)
  await page.waitForTimeout(600)
  const docRowsAfterGood = await docsDrawer.locator('table tbody tr').count()
  check(docRowsAfterGood === 1, `K5b: 정상 업로드 후 문서 목록 1건(실제=${docRowsAfterGood})`)
  await shot('k5-docs-one-after-good')

  // ================= K6: 검색 시험 — 질의 "무선 키보드" → 결과 카드에 metadata JSON =================
  await docsDrawer.getByRole('button', { name: /close|닫기/i }).click({ trial: false }).catch(async () => {
    // antd Drawer 닫기 버튼 접근성 이름이 잡히지 않으면 ESC로 대체.
    await page.keyboard.press('Escape')
  })
  await page.waitForTimeout(400)

  const searchBtn = rowFor(NEW_ALIAS).getByRole('button', { name: /검색/ }).first()
  await searchBtn.waitFor({ timeout: 8000 })
  await searchBtn.click()
  const searchDrawer = page.locator('.ant-drawer')
  await searchDrawer.getByText(`검색 시험 · ${NEW_NAME}`, { exact: true }).waitFor({ timeout: 5000 })
  await page.waitForTimeout(300)

  const queryBox = searchDrawer.locator('textarea').first()
  await queryBox.fill('무선 키보드')
  await searchDrawer.getByRole('button', { name: /검색/ }).click()
  await page.waitForTimeout(1500)

  const drawerText = await searchDrawer.innerText().catch(() => '')
  const metaCode = searchDrawer.locator('code', { hasText: 'pid' })
  const metaCodeCount = await metaCode.count()
  let metaCodeText = ''
  if (metaCodeCount > 0) metaCodeText = await metaCode.first().innerText()
  check(
    metaCodeCount > 0 && /"pid"/.test(metaCodeText),
    `K6: 결과 카드에 metadata JSON("pid" 포함) 표시(개수=${metaCodeCount}, 텍스트="${metaCodeText}")`
  )
  console.log(`(참고) 검색 드로어 전문(발췌)="${drawerText.slice(0, 300).replace(/\n/g, ' | ')}"`)
  await shot('k6-search-result-metadata')

  await page.keyboard.press('Escape')
  await page.waitForTimeout(300)

  // ================= K7: 정리 — 컬렉션 삭제 =================
  // 목록 행의 삭제 버튼은 아이콘 전용(Tooltip title="삭제"는 시각적 안내일 뿐 접근성 이름에 안 실림) —
  // antd DeleteOutlined의 접근성 이름은 영어 "delete"(148/144 학습: 아이콘 라벨은 원어 그대로).
  const delBtn = rowFor(NEW_ALIAS).getByRole('button', { name: /delete/i })
  await delBtn.waitFor({ timeout: 8000 })
  await delBtn.click()
  const confirmDialog = page.getByRole('dialog')
  await confirmDialog.getByText('컬렉션을 삭제할까요?', { exact: true }).waitFor({ timeout: 5000 })
  await confirmDialog.getByRole('button', { name: '삭제', exact: true }).click()
  await page.waitForTimeout(800)
  const remaining = await rowFor(NEW_ALIAS).count()
  check(remaining === 0, `K7: 정리 — 목록에서 "${NEW_ALIAS}" 사라짐(잔여 행=${remaining})`)
  await shot('k7-list-after-delete')

  console.log(consoleErrors.length ? 'CONSOLE_ERRORS ' + JSON.stringify(consoleErrors.slice(0, 8)) : 'NO_CONSOLE_ERRORS')
} catch (e) {
  console.error('예외', e.message)
  await shot('exception')
  fails.push('예외: ' + e.message)
} finally {
  // best-effort 잔여 정리(테스트 실패로 중도 종료해도 다음 실행이 안 새게).
  try {
    const listResp1 = await page.request.get(`${URL}/api/collections`)
    const arr1 = await listResp1.json()
    for (const c of arr1.filter((x) => typeof x.name === 'string' && x.name.startsWith(NEW_NAME))) {
      await page.request.delete(`${URL}/api/collections/${c.id}`).catch(() => {})
    }
  } catch { /* best effort */ }
  fs.rmSync(tmpDir, { recursive: true, force: true })
  await browser.close()
  if (_fx) _fx.teardown()
}

console.log(`\n${fails.length ? 'FAIL ' + fails.length : 'PASS'}`)
process.exit(fails.length ? 1 : 0)

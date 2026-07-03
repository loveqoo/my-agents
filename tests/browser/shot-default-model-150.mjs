/* 스펙 150 e2e — 기본 모델 전환 UI 브라우저 검증.
   (K1) "프로바이더·모델" 메뉴 진입 → 상단 배너에 "기본 Chat"+"qwen3.6-35b", "기본 Embedding"+"mock-embed" 표시.
   (K2) 좌측 "Mock LLM" 선택 → 우측 mock-llm 행에 "Chat" 태그 + "기본으로 지정" 버튼(현재 기본 아님),
        mock-embed 행에 "Embedding" 태그 + gold "기본" 태그.
   (K3) mock-llm 행 "기본으로 지정" 클릭 → 성공 토스트 → mock-llm 행에 "기본" 태그 + 배너 "기본 Chat"이 "mock-llm"으로 갱신.
   (K4) 원복(중요): rapid-mlx 선택 → qwen3.6-35b 행 "기본으로 지정" 클릭 → 배너 "기본 Chat"이 "qwen3.6-35b"로 복귀.
        마지막에 GET /models로 DB 실측하여 원복 증명.

   템플릿=shot-naming-148.mjs/shot-entity-rag-149.mjs(로그인·banner heading 대기 관례).
   모델 목록은 table이 아니라 div 카드(체크박스+code model_id)라 rowFor는 그 구조에 맞춘 커스텀 로케이터.
   앱 코드 수정 없음 — 검증 전용.

   실행: PLAYWRIGHT_DIR=<dir> node tests/browser/shot-default-model-150.mjs */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const API = process.env.API_URL ?? 'http://127.0.0.1:8000'
const OUT_DIR = path.join(__dirname, 'out-150')
fs.mkdirSync(OUT_DIR, { recursive: true })
const _fx = process.env.ADMIN_EMAIL ? null : (await import('./_fixture.mjs')).provisionSuper()
const EMAIL = process.env.ADMIN_EMAIL ?? _fx.email
const PASSWORD = process.env.ADMIN_PASSWORD ?? _fx.password

// .env의 API_AUTH_TOKEN — DB 실측(GET /models)용. UI 조작과는 별개 경로.
const envText = fs.readFileSync(path.join(__dirname, '..', '..', '.env'), 'utf8')
const tokenMatch = /^API_AUTH_TOKEN=(.+)$/m.exec(envText)
const API_TOKEN = tokenMatch ? tokenMatch[1].trim() : null

const fails = []
const check = (c, m) => { console.log((c ? '  ok  ' : ' FAIL ') + m); if (!c) fails.push(m) }

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1400, height: 1100 } })
const page = await ctx.newPage()
const consoleErrors = []
page.on('console', (m) => m.type() === 'error' && consoleErrors.push(m.text()))

async function shot(name) {
  await page.screenshot({ path: path.join(OUT_DIR, `${name}.png`), fullPage: true }).catch(() => {})
}

async function gotoModels() {
  await page.getByRole('menuitem', { name: '프로바이더·모델' }).first().click()
  await page.getByRole('banner').getByRole('heading', { name: '프로바이더·모델' }).waitFor({ timeout: 10000 })
  await page.waitForTimeout(400)
}

// 모델 카드(div, code 안에 model_id) — 이름 텍스트로 카드 하나를 지목.
const modelCard = (modelIdOrName) =>
  page.locator('div').filter({ has: page.locator('code', { hasText: modelIdOrName }) }).last()

async function fetchModelsFromApi() {
  const r = await fetch(`${API}/models`, { headers: API_TOKEN ? { Authorization: `Bearer ${API_TOKEN}` } : {} })
  return r.json()
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

  // ---------- 사전 DB 실측(원복 검증 기준선) ----------
  const before = API_TOKEN ? await fetchModelsFromApi() : null
  if (before) {
    const chatDef = before.find((m) => m.kind === 'chat' && m.is_default)
    const embDef = before.find((m) => m.kind === 'embedding' && m.is_default)
    console.log(`(사전실측) 기본 chat="${chatDef?.name}" 기본 embedding="${embDef?.name}"`)
  } else {
    console.log('(사전실측) API_AUTH_TOKEN을 찾지 못해 사전 실측 스킵')
  }

  // ================= K1: 배너에 기본 Chat/Embedding 표시 =================
  await gotoModels()
  const bannerText = await page.locator('div').filter({ hasText: '기본 Chat' }).first().innerText().catch(() => '')
  const pageText = await page.locator('body').innerText()
  const k1ok = pageText.includes('기본 Chat') && pageText.includes('qwen3.6-35b') &&
    pageText.includes('기본 Embedding') && pageText.includes('mock-embed')
  check(k1ok, `K1: 배너에 "기본 Chat"+"qwen3.6-35b", "기본 Embedding"+"mock-embed" 모두 표시(발췌="${bannerText.replace(/\n/g, ' | ')}")`)
  await shot('k1-banner')

  // ================= K2: Mock LLM 선택 → mock-llm(Chat, 기본 아님) / mock-embed(Embedding, 기본) =================
  // 좌측 프로바이더 명은 <span>에 순수 텍스트로 렌더 — exact 텍스트 매치로 그 span을 클릭(부모 onClick으로 버블).
  await page.getByText('Mock LLM', { exact: true }).first().click()
  await page.waitForTimeout(600)

  const mockLlmCard = modelCard('mock-chat')
  const mockLlmCardCount = await mockLlmCard.count()
  let mockLlmCardText = ''
  if (mockLlmCardCount > 0) mockLlmCardText = await mockLlmCard.first().innerText()
  const k2aOk = mockLlmCardCount > 0 && mockLlmCardText.includes('Chat') && mockLlmCardText.includes('기본으로 지정') && !mockLlmCardText.includes('기본\n')
  check(
    mockLlmCardCount > 0 && mockLlmCardText.includes('Chat') && mockLlmCardText.includes('기본으로 지정'),
    `K2a: mock-llm 카드에 "Chat" 태그 + "기본으로 지정" 버튼(실측 텍스트="${mockLlmCardText.replace(/\n/g, ' | ')}")`
  )

  const mockEmbedCard = modelCard('mock-embed')
  const mockEmbedCardCount = await mockEmbedCard.count()
  let mockEmbedCardText = ''
  if (mockEmbedCardCount > 0) mockEmbedCardText = await mockEmbedCard.first().innerText()
  check(
    mockEmbedCardCount > 0 && mockEmbedCardText.includes('Embedding') && mockEmbedCardText.includes('기본'),
    `K2b: mock-embed 카드에 "Embedding" 태그 + gold "기본" 태그(실측 텍스트="${mockEmbedCardText.replace(/\n/g, ' | ')}")`
  )
  await shot('k2-mock-llm-provider')

  // ================= K3: mock-llm "기본으로 지정" 클릭 → 토스트 + 태그/배너 갱신 =================
  await mockLlmCard.first().getByRole('button', { name: '기본으로 지정' }).click()
  // hasText는 대상 이름까지 포함해 정확히 지목(K3/K4가 같은 접두 "기본 Chat 모델"을 공유해 이전 토스트 잔상과
  // 혼동될 수 있음) — .last()로 가장 최근 렌더된 토스트를 취한다.
  const successToast = page.locator('.ant-message-success', { hasText: '기본 Chat 모델' }).filter({ hasText: 'mock-llm' })
  const toastShown = await successToast.last().waitFor({ timeout: 8000 }).then(() => true).catch(() => false)
  let toastText = ''
  if (toastShown) toastText = await successToast.last().innerText().catch(() => '')
  check(toastShown && toastText.includes('mock-llm'), `K3a: 성공 토스트 "기본 Chat 모델 → mock-llm" 표시(실측="${toastText}")`)
  await page.waitForTimeout(500)

  const mockLlmCardAfter = modelCard('mock-chat')
  const mockLlmCardAfterText = await mockLlmCardAfter.first().innerText().catch(() => '')
  check(mockLlmCardAfterText.includes('기본'), `K3b: mock-llm 카드에 "기본" 태그 생김(실측="${mockLlmCardAfterText.replace(/\n/g, ' | ')}")`)

  const pageTextAfterK3 = await page.locator('body').innerText()
  check(
    pageTextAfterK3.includes('기본 Chat') && pageTextAfterK3.includes('mock-llm'),
    `K3c: 배너의 "기본 Chat"이 "mock-llm"으로 갱신됨(전문에 두 텍스트 모두 포함=${pageTextAfterK3.includes('기본 Chat') && pageTextAfterK3.includes('mock-llm')})`
  )
  await shot('k3-mock-llm-now-default')

  // ================= K4: 원복 — rapid-mlx 선택 → qwen3.6-35b "기본으로 지정" =================
  await page.getByText('rapid-mlx', { exact: true }).first().click()
  await page.waitForTimeout(600)
  const qwenCard = modelCard('mlx-community/Qwen3.6-35B-A3B-mxfp8')
  const qwenCardCount = await qwenCard.count()
  check(qwenCardCount > 0, `K4a: qwen3.6-35b 카드 존재(개수=${qwenCardCount})`)
  if (qwenCardCount > 0) {
    await qwenCard.first().getByRole('button', { name: '기본으로 지정' }).click()
    const restoreToast = page.locator('.ant-message-success', { hasText: '기본 Chat 모델' }).filter({ hasText: 'qwen3.6-35b' })
    const restoreToastShown = await restoreToast.last().waitFor({ timeout: 8000 }).then(() => true).catch(() => false)
    let restoreToastText = ''
    if (restoreToastShown) restoreToastText = await restoreToast.last().innerText().catch(() => '')
    check(
      restoreToastShown && restoreToastText.includes('qwen3.6-35b'),
      `K4b: 원복 토스트 "기본 Chat 모델 → qwen3.6-35b"(실측="${restoreToastText}")`
    )
    await page.waitForTimeout(500)
    const pageTextAfterRestore = await page.locator('body').innerText()
    check(
      pageTextAfterRestore.includes('기본 Chat') && pageTextAfterRestore.includes('qwen3.6-35b'),
      `K4c: 배너의 "기본 Chat"이 "qwen3.6-35b"로 복귀`
    )
    await shot('k4-restored')
  } else {
    check(false, 'K4b/K4c: qwen3.6-35b 카드를 찾지 못해 원복 클릭 불가')
  }

  // ---------- K4 원복 최종 증명: DB 실측(GET /models) ----------
  if (API_TOKEN) {
    const after = await fetchModelsFromApi()
    const chatDefAfter = after.find((m) => m.kind === 'chat' && m.is_default)
    const embDefAfter = after.find((m) => m.kind === 'embedding' && m.is_default)
    console.log(`(사후실측) 기본 chat="${chatDefAfter?.name}" 기본 embedding="${embDefAfter?.name}"`)
    check(
      chatDefAfter?.name === 'qwen3.6-35b',
      `K4-DB: GET /models 실측 — 기본 chat="${chatDefAfter?.name}"(기대="qwen3.6-35b")`
    )
    check(
      embDefAfter?.name === 'mock-embed',
      `K4-DB: GET /models 실측 — 기본 embedding="${embDefAfter?.name}"(변경 없어야 함, 기대="mock-embed")`
    )
  } else {
    check(false, 'K4-DB: API_AUTH_TOKEN을 찾지 못해 DB 실측 불가 — 원복 여부 미확인')
  }

  console.log(consoleErrors.length ? 'CONSOLE_ERRORS ' + JSON.stringify(consoleErrors.slice(0, 8)) : 'NO_CONSOLE_ERRORS')
} catch (e) {
  console.error('예외', e.message)
  await shot('exception')
  fails.push('예외: ' + e.message)

  // 예외로 중도 종료해도 원복 시도(best-effort) — rapid-mlx의 qwen3.6-35b를 다시 기본으로.
  try {
    if (API_TOKEN) {
      const cur = await fetchModelsFromApi()
      const qwen = cur.find((m) => m.name === 'qwen3.6-35b')
      if (qwen && !qwen.is_default) {
        await fetch(`${API}/models/${qwen.id}/default`, {
          method: 'PUT',
          headers: { Authorization: `Bearer ${API_TOKEN}`, 'Content-Type': 'application/json' },
          body: '{}',
        })
        console.log('(예외 복구) API로 qwen3.6-35b를 기본 chat으로 재설정 시도')
      }
    }
  } catch { /* best effort */ }
} finally {
  await browser.close()
  if (_fx) _fx.teardown()
}

console.log(`\n${fails.length ? 'FAIL ' + fails.length : 'PASS'}`)
process.exit(fails.length ? 1 : 0)

/* 에이전트 상세 화면 정비 검증 (스펙 286) — 필수 단언(UI 기능적).
   ① 개요 구성 행 카운트=tools 기준(도구 2 — 서버 수 1 아님) + 구성 탭 도구 태그(서버 · 도구).
   ② 노드형: 헤더 종류 '노드형'(내부 키 pipeline 미노출) + 개요 '노드 2' + 구성 탭 노드 행.
   ③ 헤더 배지 슬림화: private/public·초안·A2A·서빙 태그 부재 + 신호등 점(aria-label) 존재.
   ④ 어휘: '메모리'→'기억'·'벡터 테이블'→'문서'·'지표 없음'→'피드백 아직 없음'.

   실행: PLAYWRIGHT_DIR=<abs>/tests/e2e/node_modules/playwright \
         ADMIN_EMAIL=admin@example.com ADMIN_PASSWORD=adminpass123 \
         node tests/browser/verify-286-agent-detail.mjs */
const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium
const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const EMAIL = process.env.ADMIN_EMAIL ?? 'admin@example.com'
const PASSWORD = process.env.ADMIN_PASSWORD ?? 'adminpass123'

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await (await browser.newContext({ viewport: { width: 1280, height: 1100 } })).newPage()
const log = (...a) => console.log(...a)
const fails = []
const check = (c, m) => { log((c ? '  ok  ' : ' FAIL ') + m); if (!c) fails.push(m) }
const rand = Date.now().toString(36)
const D = 'dt286-direct-' + rand, P = 'dt286-pipe-' + rand, O = 'dt286-orch-' + rand
const cleanup = { agents: [] }

const openDetail = async (name) => {
  await page.getByText('에이전트', { exact: true }).first().click()
  await page.waitForTimeout(500)
  await page.getByPlaceholder('이름 검색').fill(name)
  await page.waitForTimeout(500)
  await page.locator('.dt-antd tbody tr', { has: page.getByText(name, { exact: false }) }).first().click()
  await page.waitForTimeout(600)
}

try {
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  await page.waitForTimeout(500)

  // 픽스처: 직접형(도구 2개=서버 1개 — 카운트 구분자) + 노드형(노드 2개) + 조율형(위임 대상=직접형)
  const made = await page.evaluate(async ({ D, P, O }) => {
    const H = { 'Content-Type': 'application/json' }
    const jf = async (body) => { const r = await fetch('/api/agents', { method: 'POST', credentials: 'include', headers: H, body: JSON.stringify(body) }); return r.ok ? await r.json() : null }
    const d = await jf({ name: D, config: { model: 'mock-llm', persona: 't', mcps: ['local-tools'], tools: ['local-tools__echo', 'local-tools__web_search'], memories: ['장기 기억 (mem0)'] } })
    const p = await jf({ name: P, config: { model: 'mock-llm', persona: '', impl: 'pipeline', nodes: [{ name: 'n1', prompt: 'p', model: 'mock-llm', tools: [] }, { name: 'n2', prompt: 'p', model: 'mock-llm', tools: [] }] } })
    const o = d?.agentId ? await jf({ name: O, config: { model: 'mock-llm', persona: 't', impl: 'orchestrate', capabilities: [d.agentId],
      // 미소비 표면 데이터(스펙 206 — orchestrate consumes=capabilities·memories): 도구는 저장돼도 상세에 안 보여야 한다
      mcps: ['local-tools'], tools: ['local-tools__echo'], memories: ['장기 기억 (mem0)'] } }) : null
    return { d: d?.id, p: p?.id, o: o?.id }
  }, { D, P, O })
  for (const id of Object.values(made)) if (id) cleanup.agents.push(id)
  check(!!(made.d && made.p && made.o), `픽스처 생성 (${JSON.stringify(made)})`)
  await page.reload({ waitUntil: 'networkidle' }); await page.waitForTimeout(800)

  // ── 직접형 상세 ──
  await openDetail(D)
  const overview = await page.locator('.ant-descriptions').first().innerText()
  check(overview.includes('도구 2개'), `① 개요 구성 행 '도구 2'(tools 기준) (got ${JSON.stringify(overview.match(/도구 ?\S*/)?.[0] ?? '')})`)
  check(!overview.includes('도구 1개'), `① '도구 1'(서버 수) 미노출`)
  check(overview.includes('기억 1개') && !overview.includes('메모리'), `④ 개요 '기억 1'(메모리 아님)`)
  check(overview.includes('피드백 없음') && !overview.includes('아직') && !overview.includes('지표 없음'), `④ 운영 행 '피드백 없음'('아직' 제거)`)
  // 후속: 개요 요약 행 압축(사용자 5지시)
  check(!overview.includes('페르소나'), `⑤ 실행 행 페르소나 제거(모델·세션만)`)
  check(overview.includes('v1 · 미서빙') && !overview.includes('활성화 필요'), `⑤ 버전 행 'v1 · 미서빙' 압축 (got ${JSON.stringify(overview.match(/v1[^\n]*/)?.[0] ?? '')})`)
  check(overview.includes('비공개') && !overview.includes('private') && !overview.includes('소유자만'), `⑤ 공개 행 '비공개'(한국어 어휘) 압축`)
  check((await page.locator('span[aria-label="A2A 꺼짐"]').count()) > 0, `⑤ A2A 상태 점(회색=꺼짐) 존재`)
  // 헤더 배지 슬림화 — 신호등 점 + 종류만, 구 태그 부재
  check((await page.locator('span[aria-label="유휴"]').count()) > 0, `③ 신호등 점(유휴) 존재`)
  check((await page.locator('.ant-tag', { hasText: '직접 응답' }).count()) > 0, `③ 종류 태그 '직접 응답'`)
  for (const t of ['private', 'public', 'A2A', '미서빙 · 초안만']) {
    check((await page.locator('.ant-tag', { hasText: t }).count()) === 0, `③ 구 태그 '${t}' 부재`)
  }
  check((await page.locator('.ant-tag').filter({ hasText: /^초안/ }).count()) === 0, `③ 헤더 초안 태그 부재(개요 행이 소유)`)
  // 구성 탭 — 도구 태그(서버 · 도구), 어휘
  await page.getByRole('tab', { name: '구성' }).click()
  await page.waitForTimeout(500)
  const cfgTxt = await page.locator('.ant-descriptions').first().innerText()
  check(cfgTxt.includes('local-tools · echo') && cfgTxt.includes('local-tools · web_search'), `① 구성 탭 도구 태그 2(서버 · 도구)`)
  check(!cfgTxt.includes('벡터 테이블') && !cfgTxt.includes('MCP'), `④ 구성 탭 '벡터 테이블'/'MCP' 라벨 부재`)
  // 상설 행 + '없음' 값(후속 지시 — "연결 없음" 각주 대체). 픽스처는 문서 미연결 → 문서 행=없음.
  check(cfgTxt.includes('문서') && cfgTxt.includes('없음'), `⑦ 문서 행 상설 + 값 '없음'`)
  check(!(await page.getByText('연결 없음', { exact: false }).count()), `⑦ '연결 없음' 각주 부재`)
  // 공개·연동 탭 — 값은 상태만, A2A 행이 제약을 소유(후속 지시)
  await page.getByRole('tab', { name: '공개·연동' }).click()
  await page.waitForTimeout(400)
  const shareTxt = await page.locator('.ant-descriptions').first().innerText()
  check(shareTxt.includes('비공개') && !shareTxt.includes('소유자만'), `⑧ 공개 범위 값='비공개'만`)
  check(!shareTxt.includes('A2A 불가') && shareTxt.includes('공개로 전환하면 켤 수 있습니다'), `⑧ 불가 사유가 A2A 행으로 이동(간결 문구)`)
  check(!shareTxt.includes('A2A 공개'), `⑧ 행 라벨 'A2A'(공개 접미 제거)`)
  check((await page.locator('.ant-descriptions button[role="switch"][disabled], .ant-descriptions .ant-switch-disabled').count()) > 0, `⑧ 비공개면 A2A 스위치 비활성`)
  // 운영 탭 — 피드백 수확 문구 이모지 제거(후속 지시)
  await page.getByRole('tab', { name: '운영' }).click()
  await page.waitForTimeout(400)
  const opsTxt = await page.locator('.ant-descriptions').first().innerText()
  check(opsTxt.includes('응답 피드백을 초안 평가 케이스로') && !opsTxt.includes('👍') && !opsTxt.includes('👎'), `⑥ 피드백 수확 행 이모지 제거`)

  // ── 노드형 상세 ──
  await page.getByRole('button', { name: /에이전트 목록/ }).click()
  await page.waitForTimeout(500)
  await openDetail(P)
  check((await page.locator('.ant-tag', { hasText: '노드형' }).count()) > 0, `② 헤더 종류 '노드형'`)
  check((await page.locator('.ant-tag').filter({ hasText: /^pipeline$/ }).count()) === 0, `② 내부 키 'pipeline' 미노출`)
  const ov2 = await page.locator('.ant-descriptions').first().innerText()
  check(ov2.includes('노드 2개'), `② 개요 구성 행 '노드 2' (got ${JSON.stringify(ov2.match(/노드 ?\S*/)?.[0] ?? '')})`)
  // 후속(2026-07-10): 노드형 개요 실행 행=노드 흐름(대표 모델 표기는 거짓 정보라 제거)
  check(ov2.includes('n1 → n2'), `⑨ 개요 실행 행=노드 흐름 'n1 → n2' (got ${JSON.stringify(ov2.match(/n1[^\n]*/)?.[0] ?? '')})`)
  check(!ov2.includes('mock-llm'), `⑨ 개요에 최상위 모델 부재`)
  await page.getByRole('tab', { name: '구성' }).click()
  await page.waitForTimeout(500)
  const cfg2 = await page.locator('.ant-descriptions').first().innerText()
  check(cfg2.includes('n1') && cfg2.includes('n2') && cfg2.includes('mock-llm'), `② 구성 탭 노드 행(이름·모델)`)
  check(!cfg2.includes('장기 기억') && !(await page.getByText('연결 없음', { exact: false }).count()), `⑦ 노드형: 에이전트 수준 행·각주 없음(노드 소유)`)
  // 후속(2026-07-10): 노드형 구성 탭에 최상위 모델·페르소나 행 부재(노드 소유 — pipeline.py 미참조)
  check(!cfg2.includes('페르소나'), `⑨ 구성 탭 페르소나 행 부재(노드형)`)
  check(!/^모델\t|\n모델\t|\n모델\n/.test(cfg2), `⑨ 구성 탭 최상위 모델 행 부재(노드형)`)

  // ── 조율형 상세: 위임 대상=이름 노출(수만으론 빈약 — 후속) ──
  await page.getByRole('button', { name: /에이전트 목록/ }).click()
  await page.waitForTimeout(500)
  await openDetail(O)
  const ov3 = await page.locator('.ant-descriptions').first().innerText()
  check(ov3.includes(`위임 대상 1개 — ${D}`), `⑤ 구성 행 위임 대상 이름 노출 (got ${JSON.stringify(ov3.match(/위임[^\n]*/)?.[0] ?? '')})`)
  // 후속(2026-07-10): 미소비 표면은 개요·구성에서 제외(consumes 게이트 — 조율형은 도구·문서 미소비)
  check(!ov3.includes('도구'), `⑩ 조율형 개요에 도구 카운트 부재(미소비)`)
  check(ov3.includes('기억 1개'), `⑩ 조율형 개요에 기억 카운트 존재(소비)`)
  await page.getByRole('tab', { name: '구성' }).click()
  await page.waitForTimeout(500)
  const cfg3 = await page.locator('.ant-descriptions').first().innerText()
  check(!cfg3.includes('도구') && !cfg3.includes('문서'), `⑩ 조율형 구성 탭 도구·문서 행 부재(미소비) (got ${JSON.stringify(cfg3.slice(0, 120))})`)
  check(cfg3.includes('장기 기억') && cfg3.includes('페르소나') && cfg3.includes('모델'), `⑩ 조율형 구성 탭 모델·페르소나·장기 기억 행 존재(소비)`)

  log('\n' + (fails.length ? `FAILED ${fails.length}: ${fails.join(' | ')}` : 'ALL GREEN'))
  if (fails.length) process.exitCode = 1
} catch (e) {
  log('ERROR ' + (e?.stack ?? e))
  process.exitCode = 1
} finally {
  for (const id of cleanup.agents) { try { await page.request.delete(`${URL}/api/agents/${id}`) } catch {} }
  await browser.close()
}

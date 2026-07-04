/* 스펙 166 — 사용 시나리오 감사 러너(검증 축1). 여정 정의 = tests/browser/scenarios.md(단일 출처).
   J1(저마찰 생성→사용)·J2(지식 붙이기)를 실제로 실행하며 각 단계의 기대결과 대비 실제 결과를
   ok(완료)/friction(마찰)/blocked(막힘)으로 판정한다. **초록 강요 금지** — 도달 못 하면 blocked로
   정직히 기록(그 자체가 이 감사의 산출물). 로그인/네비 패턴은 shot-collection-publish-163.mjs·
   ui-audit.mjs, 플레이그라운드 에이전트 스위치는 shot-playground-a2a-155.mjs 그대로 재사용.

   실행: PLAYWRIGHT_DIR=<abs>/tests/e2e/node_modules/playwright \
         ADMIN_EMAIL=admin@example.com ADMIN_PASSWORD=adminpass123 \
         node tests/browser/scenario-audit.mjs tests/browser/out-scenario [ts] */
import { mkdirSync, writeFileSync } from 'node:fs'

const pwDir = process.env.PLAYWRIGHT_DIR
const _pw = await import(pwDir ? `${pwDir}/index.js` : 'playwright')
const chromium = _pw.chromium ?? _pw.default?.chromium

const URL = process.env.ADMIN_URL ?? 'http://127.0.0.1:5173'
const OUT = process.argv[2] ?? 'tests/browser/out-scenario'
const EMAIL = process.env.ADMIN_EMAIL ?? 'admin@example.com'
const PASSWORD = process.env.ADMIN_PASSWORD ?? 'adminpass123'
// 고정 숫자(Date.now 미사용 — 브리프 지시) — argv[3]로 override 가능.
const TS = process.argv[3] ?? '166704'
const AGENT_NAME = `scn-${TS}`
const COLLECTION_NAME = `scn-col-${TS}`

mkdirSync(OUT, { recursive: true })

const scorecard = []
const stepNo = { J1: 0, J2: 0 }
function record(journey, label, expected, status, actual, shotPath) {
  stepNo[journey] += 1
  const row = { journey, step: stepNo[journey], label, status, expected, actual, shot: shotPath ?? null }
  scorecard.push(row)
  const tag = status === 'ok' ? ' OK ' : status === 'friction' ? 'FRIC' : 'BLK '
  console.log(`  [${tag}] ${journey}#${row.step} ${label}\n         기대: ${expected}\n         실제: ${actual}`)
  return row
}

const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ viewport: { width: 1400, height: 1000 } })
const page = await ctx.newPage()

async function shot(name) {
  const p = `${OUT}/${name}.png`
  await page.screenshot({ path: p, fullPage: true }).catch(() => {})
  return p
}

async function fetchJson(path) {
  return page.evaluate((p) => fetch(p, { credentials: 'include' }).then((r) => r.json()), path)
}

// antd Field 컴포넌트는 <label><span>라벨</span>{children}</label> — 라벨 텍스트로 Select를 찾아
// 클릭·첫 옵션 선택. 옵션 포털은 body에 렌더(.ant-select-dropdown), 열린 것 중 마지막 = 방금 연 것.
async function selectFirstOptionByLabel(scopeSelector, labelText) {
  const label = page.locator(`${scopeSelector} label`, { hasText: labelText }).first()
  const select = label.locator('.ant-select').first()
  await select.click()
  await page.waitForTimeout(350)
  // rc-virtual-list가 측정용 숨김 클론을 같이 렌더한다(:visible 아님) — 실제 보이는 옵션만 골라야
  // 첫 옵션 클릭이 통과한다(스펙 166 실측: hidden 클론이 .first()에 잡혀 waitFor 타임아웃).
  const option = page.locator('.ant-select-item-option:visible').first()
  await option.waitFor({ timeout: 5000 })
  const text = (await option.textContent())?.trim() ?? ''
  await option.click()
  await page.waitForTimeout(150)
  return text
}

let cleanup = { agentId: null, collectionId: null, agentDeleteStatus: null, collectionDeleteStatus: null }

try {
  // ---------- 로그인 ----------
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 })
  await page.getByText('my-agents 로그인', { exact: true }).waitFor({ timeout: 10000 })
  await page.getByPlaceholder('you@example.com').fill(EMAIL)
  await page.getByPlaceholder('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await page.getByText('에이전트', { exact: true }).first().waitFor({ timeout: 10000 })
  await page.waitForTimeout(600)

  await page.locator('[data-menu-id$="agents"]').first().click()
  await page.waitForTimeout(900)

  /* ============================= J1 — 저마찰 생성 → 사용 ============================= */

  // J1 #1 — "새 에이전트" 클릭 → 생성 모달이 열리는가.
  {
    let status = 'blocked'
    let actual = ''
    try {
      await page.getByRole('button', { name: /새 에이전트/ }).first().click()
      await page.locator('.ant-modal-title', { hasText: '에이전트 생성' }).waitFor({ timeout: 5000 })
      status = 'ok'
      actual = '생성 모달(제목 "에이전트 생성")이 열림'
    } catch (e) {
      actual = `모달이 열리지 않음 — ${e.message}`
    }
    const s = await shot('j1-1-modal-open')
    record('J1', '"새 에이전트" 클릭', '생성 폼(모달)이 열린다', status, actual, s)
  }

  // J1 #2 — 이름·모델·페르소나 채우고 생성.
  let creationOk = false
  if (scorecard.find((r) => r.journey === 'J1' && r.step === 1).status === 'ok') {
    let status = 'blocked'
    let actual = ''
    try {
      await page.locator('.ant-modal-container').getByPlaceholder('예: research-assistant').fill(AGENT_NAME)
      const modelPicked = await selectFirstOptionByLabel('.ant-modal-container', '모델')
      const personaPicked = await selectFirstOptionByLabel('.ant-modal-container', '페르소나')
      // 종류(impl)는 기본값(직접 응답) 그대로 둔다(브리프 지시).
      const okBtn = page.locator('.ant-modal-footer').getByRole('button', { name: '에이전트 생성', exact: true })
      const disabled = await okBtn.isDisabled().catch(() => false)
      if (disabled) {
        actual = `생성 버튼이 비활성 상태(이름/모델/페르소나 값 문제 의심). model=${modelPicked}, persona=${personaPicked}`
      } else {
        await okBtn.click()
        // 토스트("...생성됨 — v1 초안...") 또는 모달이 닫히는지로 성공 판정.
        const toastShown = await page
          .getByText(/생성됨/, { exact: false })
          .first()
          .waitFor({ timeout: 8000 })
          .then(() => true)
          .catch(() => false)
        const modalClosed = (await page.locator('.ant-modal-container').filter({ hasText: '에이전트 생성' }).count()) === 0
        if (toastShown || modalClosed) {
          status = 'ok'
          actual = `생성 완료(토스트 표시=${toastShown}, 모달 닫힘=${modalClosed}). model=${modelPicked}, persona=${personaPicked}`
          creationOk = true
        } else {
          const errMsg = await page.locator('.ant-message-notice').first().textContent().catch(() => null)
          actual = `생성 실패 — 토스트 없음/모달 유지. 에러 메시지=${errMsg ?? '(없음)'}`
        }
      }
    } catch (e) {
      actual = `예외 — ${e.message}`
    }
    const s = await shot('j1-2-after-create')
    record(
      'J1',
      '이름 입력·모델/페르소나 선택 후 생성',
      '에이전트가 만들어지고 목록/상세에 보인다',
      status,
      actual,
      s,
    )
  } else {
    record('J1', '이름 입력·모델/페르소나 선택 후 생성', '에이전트가 만들어지고 목록/상세에 보인다', 'blocked', '이전 단계(모달 열기)가 blocked라 진행 불가', null)
  }

  // 생성된 에이전트 id 확보(정리용 + 이후 단계 검증용).
  if (creationOk) {
    try {
      const agents = await fetchJson('/api/agents')
      const found = Array.isArray(agents) ? agents.find((a) => a.name === AGENT_NAME) : null
      if (found) cleanup.agentId = found.id
    } catch { /* id 확보 실패는 정리 단계에서 보고 */ }
  }

  // J1 #3+#4 — 그 에이전트로 대화 시도 + 메시지 전송·응답 확인.
  if (creationOk) {
    let navStatus = 'blocked'
    let navActual = ''
    let chatOk = false
    try {
      await page.locator('[data-menu-id$="debug"]').first().click()
      await page.waitForTimeout(1200)

      // 트리거는 "현재 선택된" 에이전트 이름을 보여준다 — 존재하는 모든 에이전트 이름의 정규식으로
      // 열고, 드롭다운 안에서 우리 신규 에이전트 이름 행을 골라 클릭(shot-playground-a2a-155 패턴).
      const allAgents = await fetchJson('/api/agents')
      const namePattern = (Array.isArray(allAgents) ? allAgents : [])
        .map((a) => esc(a.name))
        .filter(Boolean)
        .join('|')
      if (!namePattern) throw new Error('에이전트 목록을 가져오지 못함(트리거 매칭 불가)')
      const trigger = page.getByRole('button', { name: new RegExp(namePattern) }).first()
      await trigger.waitFor({ timeout: 10000 })
      await trigger.click()
      await page.waitForTimeout(400)
      const row = page.locator('button', { hasText: new RegExp(`^${esc(AGENT_NAME)}`) }).last()
      await row.waitFor({ timeout: 8000 })
      await row.click()
      await page.waitForTimeout(500)

      const input = page.getByPlaceholder(`${AGENT_NAME}에게 메시지…`)
      const inputShown = await input.waitFor({ timeout: 8000 }).then(() => true).catch(() => false)
      if (inputShown) {
        navStatus = 'ok'
        navActual = `대화 입력창(placeholder="${AGENT_NAME}에게 메시지…") 렌더됨`
      } else {
        // 초안이라 대화 불가/활성화 필요 안내가 있는지 화면 텍스트로 확인.
        const bodyText = await page.locator('body').innerText().catch(() => '')
        const hint = /초안|활성화|draft|activate/i.test(bodyText) ? bodyText.slice(0, 300) : '(관련 문구 없음)'
        navActual = `대화 입력창이 안 뜸 — 화면 텍스트 힌트: ${hint}`
      }
    } catch (e) {
      navActual = `예외 — ${e.message}`
    }
    const s3 = await shot('j1-3-chat-entry')
    record('J1', '생성한 에이전트로 대화 진입 시도', '막힘 없이 대화 진입 가능', navStatus, navActual, s3)

    if (navStatus === 'ok') {
      let sendStatus = 'blocked'
      let sendActual = ''
      try {
        const input = page.getByPlaceholder(`${AGENT_NAME}에게 메시지…`)
        await input.click()
        await input.fill('안녕')
        await input.press('Enter')

        const gotText = await page
          .waitForFunction(
            () => {
              const nodes = document.querySelectorAll('.ant-bubble-start .ant-bubble-content')
              if (nodes.length === 0) return false
              const last = nodes[nodes.length - 1]
              return (last.textContent || '').trim().length > 0
            },
            { timeout: 20000, polling: 500 },
          )
          .then(() => true)
          .catch(() => false)

        if (gotText) {
          const bubbleText = await page
            .locator('.ant-bubble-start .ant-bubble-content')
            .last()
            .textContent()
            .catch(() => '')
          sendStatus = 'ok'
          sendActual = `20초 내 비어있지 않은 응답 렌더됨(앞 120자): ${(bubbleText ?? '').trim().slice(0, 120)}`
          chatOk = true
        } else {
          const bubbleText = await page
            .locator('.ant-bubble-start .ant-bubble-content')
            .last()
            .textContent()
            .catch(() => null)
          sendActual = `20초 내 응답 없음(빈 상태 유지). 마지막 버블 텍스트=${JSON.stringify(bubbleText)}`
        }
      } catch (e) {
        sendActual = `예외 — ${e.message}`
      }
      const s4 = await shot('j1-4-send-message')
      record('J1', '메시지 "안녕" 전송', '어시스턴트 응답이 온다(빈 화면·에러 아님)', sendStatus, sendActual, s4)
    } else {
      record('J1', '메시지 "안녕" 전송', '어시스턴트 응답이 온다(빈 화면·에러 아님)', 'blocked', '이전 단계(대화 진입)가 blocked라 진행 불가', null)
    }
  } else {
    record('J1', '생성한 에이전트로 대화 진입 시도', '막힘 없이 대화 진입 가능', 'blocked', '이전 단계(에이전트 생성)가 blocked/실패라 진행 불가', null)
    record('J1', '메시지 "안녕" 전송', '어시스턴트 응답이 온다(빈 화면·에러 아님)', 'blocked', '이전 단계(에이전트 생성)가 blocked/실패라 진행 불가', null)
  }

  /* ============================= J2 — 지식 붙이기 ============================= */

  // J1이 실패로 끝나 생성 모달이 열린 채 남아있으면(오버레이가 메뉴 클릭을 가로막음) 먼저 닫는다.
  if (await page.locator('.ant-modal-container').count()) {
    await page.keyboard.press('Escape').catch(() => {})
    await page.waitForTimeout(300)
  }

  await page.locator('[data-menu-id$="collections"]').first().click()
  await page.waitForTimeout(900)

  let collectionCreated = false
  {
    let status = 'blocked'
    let actual = ''
    try {
      const createBtn = page.getByRole('button', { name: /컬렉션 생성/ }).first()
      const disabled = await createBtn.isDisabled().catch(() => false)
      if (disabled) {
        const bannerText = await page.locator('body').innerText().catch(() => '')
        actual = `"컬렉션 생성" 버튼이 비활성(임베딩 모델 미등록 추정). 화면 텍스트 일부: ${bannerText.slice(0, 200)}`
      } else {
        await createBtn.click()
        await page.locator('.ant-modal-title', { hasText: '컬렉션 생성' }).waitFor({ timeout: 5000 })
        await page.locator('.ant-modal-container').getByPlaceholder('예: docs-kb').fill(COLLECTION_NAME)
        const embedPicked = await selectFirstOptionByLabel('.ant-modal-container', '임베딩 모델')
        await page.locator('.ant-modal-footer').getByRole('button', { name: '생성', exact: true }).click()
        await page.waitForTimeout(1200)
        const collections = await fetchJson('/api/collections')
        const found = Array.isArray(collections) ? collections.find((c) => c.name === COLLECTION_NAME) : null
        if (found) {
          cleanup.collectionId = found.id
          status = 'ok'
          actual = `컬렉션이 목록에 등장(id=${found.id}, embedding=${embedPicked})`
          collectionCreated = true
        } else {
          const errMsg = await page.locator('.ant-message-notice').first().textContent().catch(() => null)
          actual = `생성 후 목록에서 찾지 못함. 에러 메시지=${errMsg ?? '(없음)'}`
        }
      }
    } catch (e) {
      actual = `예외 — ${e.message}`
    }
    const s = await shot('j2-1-collection-create')
    record('J2', '컬렉션 생성(이름·임베딩 모델)', '컬렉션이 목록에 보인다', status, actual, s)
  }

  // J2 #2+#3 — 에이전트 생성 폼을 열어 "문서" 선택 영역에 방금 만든 컬렉션이 나타나는지.
  {
    let openStatus = 'blocked'
    let openActual = ''
    let formOpen = false
    try {
      await page.locator('[data-menu-id$="agents"]').first().click()
      await page.waitForTimeout(900)
      await page.getByRole('button', { name: /새 에이전트/ }).first().click()
      await page.locator('.ant-modal-title', { hasText: '에이전트 생성' }).waitFor({ timeout: 5000 })
      const docsPanel = page.locator('.ant-modal-container .ant-collapse-header', { hasText: '문서' }).first()
      const panelFound = await docsPanel.waitFor({ timeout: 5000 }).then(() => true).catch(() => false)
      if (panelFound) {
        openStatus = 'ok'
        openActual = '생성 모달에 "문서" 선택 영역(Collapse 패널)이 있음'
        formOpen = true
      } else {
        openActual = '생성 모달에 "문서" 선택 영역을 찾지 못함'
      }
    } catch (e) {
      openActual = `예외 — ${e.message}`
    }
    const s2 = await shot('j2-2-form-docs-section')
    record('J2', '에이전트 생성 폼을 연다', '폼에 "벡터 테이블/지식" 선택 영역이 있다', openStatus, openActual, s2)

    let visStatus = 'blocked'
    let visActual = ''
    if (formOpen && collectionCreated) {
      try {
        const docsPanel = page.locator('.ant-modal-container .ant-collapse-header', { hasText: '문서' }).first()
        await docsPanel.click()
        await page.waitForTimeout(400)
        const item = page.locator('.ant-modal-container .ant-checkbox-wrapper', { hasText: COLLECTION_NAME })
        const shown = await item.first().waitFor({ timeout: 5000 }).then(() => true).catch(() => false)
        visStatus = shown ? 'ok' : 'blocked'
        visActual = shown
          ? `"${COLLECTION_NAME}" 체크박스가 문서 선택지에 나타남`
          : `"${COLLECTION_NAME}"이 문서 선택지에 보이지 않음(연결 경로 공백 의심)`
      } catch (e) {
        visActual = `예외 — ${e.message}`
      }
    } else {
      visActual = !formOpen
        ? '이전 단계(폼 열기)가 blocked라 진행 불가'
        : '이전 단계(컬렉션 생성)가 blocked/실패라 진행 불가'
    }
    const s3 = await shot('j2-3-collection-in-picker')
    record('J2', '방금 만든 컬렉션을 선택지에서 찾는다', '생성한 컬렉션이 선택지에 나타난다', visStatus, visActual, s3)

    // 모달을 열어둔 채 정리 단계로 넘어가지 않도록 닫는다(취소 — 이 폼은 제출 안 함).
    try {
      const cancelBtn = page.locator('.ant-modal-footer').getByRole('button', { name: '취소', exact: true })
      if (await cancelBtn.count()) await cancelBtn.click()
      await page.waitForTimeout(300)
    } catch { /* 닫기 실패는 무시 — 정리 단계는 API 직접 호출이라 영향 없음 */ }
  }
} catch (e) {
  console.error('RUNNER ERROR:', e.message)
  await shot('runner-exception')
} finally {
  /* ============================= 정리(cleanup) ============================= */
  console.log('\n--- 정리 ---')
  if (cleanup.agentId) {
    try {
      const st = await page.evaluate(
        (id) => fetch(`/api/agents/${id}`, { method: 'DELETE', credentials: 'include' }).then((r) => r.status),
        cleanup.agentId,
      )
      cleanup.agentDeleteStatus = st
      console.log(`  에이전트(${cleanup.agentId}) 삭제 → ${st}`)
    } catch (e) {
      console.log(`  에이전트 삭제 실패: ${e.message}`)
    }
  } else {
    console.log(`  에이전트 id 미확보 — "${AGENT_NAME}" 수동 정리 필요`)
  }
  if (cleanup.collectionId) {
    try {
      const st = await page.evaluate(
        (id) => fetch(`/api/collections/${id}`, { method: 'DELETE', credentials: 'include' }).then((r) => r.status),
        cleanup.collectionId,
      )
      cleanup.collectionDeleteStatus = st
      console.log(`  컬렉션(${cleanup.collectionId}) 삭제 → ${st}`)
    } catch (e) {
      console.log(`  컬렉션 삭제 실패: ${e.message}`)
    }
  } else {
    console.log(`  컬렉션 id 미확보 — "${COLLECTION_NAME}" 수동 정리 필요`)
  }

  writeFileSync(`${OUT}/scorecard.json`, JSON.stringify({ ts: TS, agentName: AGENT_NAME, collectionName: COLLECTION_NAME, cleanup, scorecard }, null, 2))
  await browser.close()
}

console.log('\n=== 여정×단계 요약 ===')
for (const r of scorecard) {
  console.log(`  ${r.journey}#${r.step} [${r.status}] ${r.label}`)
}
const blockedOrFail = scorecard.filter((r) => r.status === 'blocked')
console.log(`\nscorecard → ${OUT}/scorecard.json`)
console.log(`총 ${scorecard.length}단계 중 blocked ${blockedOrFail.length}건`)
process.exit(blockedOrFail.length ? 1 : 0)

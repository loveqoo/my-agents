import { test, expect, type APIRequestContext } from '@playwright/test'
import { SEED, A2A_SIGNATURE, BLOCK_CATEGORIES } from '../seed'

/* 백엔드 API 통합 — request 픽스처(브라우저 없음). baseURL = API(8000).
   고유 이름으로 데이터를 만들고 끝에 삭제해 시드 오염을 막는다. */

const uniq = (p: string) => `${p}-${Date.now()}-${Math.floor(Math.random() * 1e4)}`

/* SSE 프레임 파서 (모듈 공용). */
function sseText(sse: string): string {
  let out = ''
  for (const line of sse.split('\n')) {
    if (!line.startsWith('data: ')) continue
    const d = line.slice(6)
    if (!d.trim().startsWith('{')) continue
    try {
      const o = JSON.parse(d)
      if (typeof o.text === 'string') out += o.text
    } catch {
      /* skip */
    }
  }
  return out
}
function sseTrace(sse: string): Record<string, unknown> | null {
  const frames = sse.split('\n\n')
  for (const f of frames) {
    if (!f.includes('event: trace')) continue
    const line = f.split('\n').find((l) => l.startsWith('data: '))
    if (line) return JSON.parse(line.slice(6))
  }
  return null
}
function sseSession(sse: string): string | null {
  for (const f of sse.split('\n\n')) {
    const line = f.split('\n').find((l) => l.startsWith('data: '))
    if (!line) continue
    try {
      const d = JSON.parse(line.slice(6))
      if (typeof d.session === 'string') return d.session
    } catch {
      /* skip */
    }
  }
  return null
}

async function createAgent(request: APIRequestContext, name: string, config: object = {}) {
  const res = await request.post('/agents', {
    data: {
      name,
      config: {
        model: SEED.chatModel,
        prompt: '',
        memories: [],
        vectorTables: [],
        mcps: [],
        historyDepth: 10,
        ...config,
      },
    },
  })
  expect(res.ok(), `create ${name}: ${res.status()}`).toBeTruthy()
  return res.json()
}

test.describe('인증', () => {
  test('토큰 없거나 틀리면 401, mock_remote는 개방', async ({ request }) => {
    expect((await request.get('/agents', { headers: { Authorization: '' } })).status()).toBe(401)
    expect((await request.get('/agents', { headers: { Authorization: 'Bearer wrong' } })).status()).toBe(401)
    // mock_remote(외부 에이전트 스탠드인)는 API 토큰 비요구
    const r = await request.post('/_remote/agent', {
      headers: { Authorization: '' },
      data: { messages: [{ role: 'user', content: 'hi' }] },
    })
    expect(r.ok()).toBeTruthy()
  })
})

test.describe('블록', () => {
  test('GET /blocks → 4 카테고리, 각 항목 존재', async ({ request }) => {
    const res = await request.get('/blocks')
    expect(res.ok()).toBeTruthy()
    const blocks = await res.json()
    for (const key of BLOCK_CATEGORIES) {
      expect(blocks[key], key).toBeTruthy()
      expect(Array.isArray(blocks[key].items)).toBeTruthy()
      expect(blocks[key].items.length).toBeGreaterThan(0)
    }
  })

  test('prompt 생성 → 수정 → 목록/본문 반영 → 삭제', async ({ request }) => {
    const name = uniq('prompt')
    const created = await (await request.post('/prompts', { data: { name, tone: 't', body: 'b' } })).json()
    expect(created.id).toBeTruthy()
    const list = await (await request.get('/prompts')).json()
    expect(list.some((p: { name: string }) => p.name === name)).toBeTruthy()
    // 수정(PUT): 본문·톤 변경이 반영되어야 한다 (014 작성 UI가 쓰는 경로)
    const edited = await (
      await request.put(`/prompts/${created.id}`, { data: { name, tone: 't2', body: 'b2' } })
    ).json()
    expect(edited.tone).toBe('t2')
    expect(edited.body).toBe('b2')
    const got = await (await request.get(`/prompts/${created.id}`)).json()
    expect(got.body).toBe('b2')
    const del = await request.delete(`/prompts/${created.id}`)
    expect(del.status()).toBe(204)
  })

  test('memory-types 작성(key 포함) → /blocks에 key 노출 → 수정 → 삭제 (015)', async ({ request }) => {
    const key = uniq('mem').replace(/-/g, '_')
    const created = await (
      await request.post('/memory-types', { data: { key, name: '작업기억', scope: 'agent', body: 'b' } })
    ).json()
    expect(created.id).toBeTruthy()
    // /blocks 집계 memory 항목에 key가 노출되어야(편집 폼 prefill 경로)
    const blocks = await (await request.get('/blocks')).json()
    const item = blocks.memory.items.find((m: { key?: string }) => m.key === key)
    expect(item, 'memory 항목에 key 노출').toBeTruthy()
    // 수정(PUT)
    const edited = await (
      await request.put(`/memory-types/${created.id}`, { data: { key, name: '수정됨', scope: 'user', body: 'b2' } })
    ).json()
    expect(edited.name).toBe('수정됨')
    expect(edited.scope).toBe('user')
    expect((await request.delete(`/memory-types/${created.id}`)).status()).toBe(204)
  })

  test('작성한 프롬프트 → 단순 에이전트 systemPrompt로 해석', async ({ request }) => {
    const name = uniq('prompt')
    const body = '너는 고양이다. 문장 끝에 냐옹을 붙여라.'
    const p = await (await request.post('/prompts', { data: { name, tone: '장난', body } })).json()
    // 그 프롬프트를 이름으로 선택한 단순 에이전트(이름은 식별 규칙 준수 — 영소문자·대시)
    const agent = await (
      await request.post('/agents', {
        data: {
          name: uniq('cat-agent'),
          config: { model: SEED.chatModel, prompt: name, memories: [], vectorTables: [], mcps: [], historyDepth: 6, persistHistory: true },
        },
      })
    ).json()
    // 서빙용 해석 본문이 프롬프트 body여야 한다 (resolve_prompt)
    expect(agent.systemPrompt).toBe(body)
    await request.delete(`/agents/${agent.id}`)
    await request.delete(`/prompts/${p.id}`)
  })

  test('MCP 생성 → 로컬은 외부 서빙 불가(커스텀 서빙 MCP만) → 삭제', async ({ request }) => {
    const name = uniq('mcp')
    const m = await (
      await request.post('/mcp-servers', {
        data: { name, source: 'local', transport: 'stdio', tools: ['x'], enabled_tools: ['x'] },
      })
    ).json()
    expect(m.id).toBeTruthy()
    // 외부 서빙(publish)은 커스텀 서빙 MCP만 허용 — 로컬 stdio는 400(스펙 156/360)
    const pub = await request.put(`/mcp-servers/${m.id}/publish`, { data: { published: true } })
    expect(pub.status(), '로컬 MCP 외부서빙 거부').toBe(400)
    expect((await request.delete(`/mcp-servers/${m.id}`)).status()).toBe(204)
  })
})

test.describe('에이전트 CRUD + 버저닝', () => {
  test('생성 → 조회 → 삭제(404)', async ({ request }) => {
    const a = await createAgent(request, uniq('agent'))
    expect(a.source).toBe('ui')
    expect(a.activeVersion).toBeNull()
    expect(a.versions).toHaveLength(1)
    expect(a.versions[0].status).toBe('draft')

    const got = await request.get(`/agents/${a.id}`)
    expect(got.ok()).toBeTruthy()

    expect((await request.delete(`/agents/${a.id}`)).status()).toBe(204)
    expect((await request.get(`/agents/${a.id}`)).status()).toBe(404)
  })

  test('편집은 단일 초안 유지, fork는 초안 존재 시 400', async ({ request }) => {
    const a = await createAgent(request, uniq('agent'))
    // 편집 → 기존 v1 draft 갱신(새 버전 안 생김)
    const edited = await (
      await request.put(`/agents/${a.id}`, {
        data: { name: a.name, config: { ...a.versions[0].config, historyDepth: 40 } },
      })
    ).json()
    expect(edited.versions.filter((v: { status: string }) => v.status === 'draft')).toHaveLength(1)
    // fork → 이미 draft 있으니 400
    const fork = await request.post(`/agents/${a.id}/versions`)
    expect(fork.status()).toBe(400)
    await request.delete(`/agents/${a.id}`)
  })

  test('activate → online, 재activate 400, 유일 active revert 400', async ({ request }) => {
    const a = await createAgent(request, uniq('agent'))
    const act = await request.post(`/agents/${a.id}/activate`, { data: { version: 'v1' } })
    expect(act.ok()).toBeTruthy()
    const body = await act.json()
    expect(body.activeVersion).toBe('v1')
    expect(body.status).toBe('online')
    // 이미 active인 v1 재활성화 → 400
    expect((await request.post(`/agents/${a.id}/activate`, { data: { version: 'v1' } })).status()).toBe(400)
    // 유일 active revert → 400 (승격할 archived 없음)
    expect((await request.post(`/agents/${a.id}/revert`, { data: { version: 'v1' } })).status()).toBe(400)
    await request.delete(`/agents/${a.id}`)
  })

  test('롤백: archived 버전 활성화', async ({ request }) => {
    const a = await createAgent(request, uniq('agent'))
    await request.post(`/agents/${a.id}/activate`, { data: { version: 'v1' } }) // v1 active
    await request.post(`/agents/${a.id}/versions`) // fork → v2 draft
    await request.post(`/agents/${a.id}/activate`, { data: { version: 'v2' } }) // v2 active, v1 archived
    const rolled = await (await request.post(`/agents/${a.id}/activate`, { data: { version: 'v1' } })).json()
    expect(rolled.activeVersion).toBe('v1')
    const v2 = rolled.versions.find((v: { version: string }) => v.version === 'v2')
    expect(v2.status).toBe('archived')
    await request.delete(`/agents/${a.id}`)
  })

  test('단순 에이전트(프롬프트만) 생성 → 실제 대화 가능', async ({ request }) => {
    test.setTimeout(150_000)
    // 부가기능(mcp·memory·vectorTable·permission) 없이 프롬프트만
    const a = await createAgent(request, uniq('simple'), {
      mcps: [],
      memories: [],
      vectorTables: [],
      permissions: [],
    })
    // 턴1
    const res = await request.post(`/agents/${a.id}/chat`, {
      data: { messages: [{ role: 'user', content: '한 문장으로 자기소개해줘.' }] },
      timeout: 120_000,
    })
    expect(res.ok(), `chat ${res.status()}`).toBeTruthy()
    const sse = await res.text()

    // 비어있지 않은 응답
    expect(sseText(sse).trim().length, '응답 텍스트 비어있지 않음').toBeGreaterThan(0)

    // 단순 에이전트 = 툴/메모리 미개입
    const t = sseTrace(sse)
    expect(t, '트레이스').toBeTruthy()
    expect((t!.mcp as unknown[]).length, 'MCP 호출 없음').toBe(0)
    expect((t!.memories as unknown[]).length, '메모리 회상 없음').toBe(0)
    const nodes = (t!.graph as { node: string }[]).map((n) => n.node)
    expect(nodes, 'tools 노드 없음').not.toContain('tools')
    expect(nodes, 'retrieve_memory 노드 없음').not.toContain('retrieve_memory')

    // 멀티턴 + 세션/메시지 영속
    const sid = sseSession(sse)
    expect(sid, 'session id').toBeTruthy()
    const res2 = await request.post(`/agents/${a.id}/chat`, {
      data: { messages: [{ role: 'user', content: '2 더하기 3은?' }], sessionId: sid },
      timeout: 120_000,
    })
    expect(res2.ok()).toBeTruthy()
    expect(sseText(await res2.text()).trim().length).toBeGreaterThan(0)

    const msgs = await (await request.get(`/sessions/${sid}/messages`)).json()
    expect(msgs.length, '두 턴(user+assistant ×2) 영속').toBeGreaterThanOrEqual(4)
    expect(msgs.filter((m: { role: string }) => m.role === 'assistant').length).toBeGreaterThanOrEqual(2)

    await request.delete(`/agents/${a.id}`)
  })

  test('expose 토글', async ({ request }) => {
    const a = await createAgent(request, uniq('agent'))
    const on = await (await request.put(`/agents/${a.id}/expose`, { data: { a2a: true } })).json()
    expect(on.exposed.a2a).toBe(true)
    const off = await (await request.put(`/agents/${a.id}/expose`, { data: { a2a: false } })).json()
    expect(off.exposed.a2a).toBe(false)
    await request.delete(`/agents/${a.id}`)
  })

  test('코드 에이전트 등록 — source=code, 토큰 마스킹', async ({ request }) => {
    const res = await request.post('/agents/register', {
      data: {
        endpoint: 'https://agents.example.dev/x',
        token: 'sk_live_abcdefg1234567',
        name: uniq('code'),
        commit: 'abc1234',
        repo: 'acme/x',
      },
    })
    expect(res.ok()).toBeTruthy()
    const a = await res.json()
    expect(a.source).toBe('code')
    expect(a.token).toContain('••••')
    expect(a.activeVersion).toBe('abc1234')
    await request.delete(`/agents/${a.id}`)
  })
})

test.describe('모델 레지스트리', () => {
  test('시드된 모델 + kind 필터 + 마스킹', async ({ request }) => {
    const all = await (await request.get('/models')).json()
    const names = all.map((m: { name: string }) => m.name)
    expect(names).toContain(SEED.chatModel)
    expect(names).toContain(SEED.embedModel)
    const chat = await (await request.get('/models?kind=chat')).json()
    expect(chat.every((m: { kind: string }) => m.kind === 'chat')).toBeTruthy()
    // api_key 마스킹 확인
    const withKey = all.find((m: { api_key: string | null }) => m.api_key)
    if (withKey) expect(withKey.api_key).toContain('•')
  })

  test('CRUD', async ({ request }) => {
    // 모델은 provider(FK)에서 연결처를 취득 — 생성 시 provider_id 필수, api_key는 provider 소유.
    const providers = await (await request.get('/providers')).json()
    const prov = providers[0]
    expect(prov?.id, 'provider 시드 필요').toBeTruthy()
    const name = uniq('model')
    const m = await (
      await request.post('/models', {
        data: { name, provider_id: prov.id, model_id: 'foo-bar', kind: 'chat', is_default: false, params: {} },
      })
    ).json()
    expect(m.id).toBeTruthy()
    const got = await (await request.get(`/models/${m.id}`)).json()
    expect(got.model_id).toBe('foo-bar')
    expect((await request.delete(`/models/${m.id}`)).status()).toBe(204)
  })

  test('연결 테스트 — 저장 모델 ok / 도달 불가 fail / 비밀 미노출', async ({ request }) => {
    const models = await (await request.get('/models')).json()
    const seed = models.find((m: { name: string }) => m.name === SEED.chatModel)
    expect(seed).toBeTruthy()
    const ok = await (await request.post(`/models/${seed.id}/test`)).json()
    expect(ok.ok, '저장 모델 연결').toBe(true)
    expect(ok.modelAvailable, '모델 가용').toBe(true)

    // 도달 불가 — 애드혹 provider 연결 테스트(base_url 도달 불가·비밀 미노출)
    const fail = await (
      await request.post('/providers/test', {
        data: { base_url: 'http://127.0.0.1:1/v1', api_key: 'SECRETKEY123' },
      })
    ).json()
    expect(fail.ok, '도달 불가').toBe(false)
    expect(fail.detail, '비밀 미노출').not.toContain('SECRETKEY123')
  })

  test('연결 테스트 — kind별 기능 검증: embedding은 임베딩 호출, chat은 목록 (016)', async ({ request }) => {
    // mock provider(base_url /_remote/v1)가 OpenAI 호환 /models·/embeddings 제공 — 결정적 검증.
    const providers = await (await request.get('/providers')).json()
    const mockProv = providers.find((p: { base_url: string }) => p.base_url.includes('/_remote'))
    expect(mockProv, 'mock provider 시드').toBeTruthy()
    // embedding: POST /embeddings로 벡터 수신 → ok + dims(8)
    const emb = await (
      await request.post('/models/test', { data: { provider_id: mockProv.id, model_id: 'any', kind: 'embedding' } })
    ).json()
    expect(emb.ok, '임베딩 연결').toBe(true)
    expect(emb.modelAvailable, '임베딩 기능 통과').toBe(true)
    expect(emb.dims, '임베딩 벡터 차원(양수)').toBeGreaterThan(0)
    expect(emb.detail, '차원 표기').toContain('차원')
    // chat: /models 목록에서 model_id 확인 (기능 경로가 kind로 분기되는지)
    const chat = await (
      await request.post('/models/test', { data: { provider_id: mockProv.id, model_id: 'mock-chat', kind: 'chat' } })
    ).json()
    expect(chat.ok && chat.modelAvailable, 'chat 가용').toBe(true)
    expect(chat.dims ?? null, 'chat은 dims 없음').toBeNull()
  })

  test('등록된 모델로 에이전트 실행', async ({ request }) => {
    test.setTimeout(150_000)
    const a = await createAgent(request, uniq('agent'), { model: SEED.chatModel })
    const res = await request.post(`/agents/${a.id}/chat`, {
      data: { messages: [{ role: 'user', content: '한 단어로 인사' }] },
      timeout: 120_000,
    })
    expect(res.ok()).toBeTruthy()
    expect(await res.text()).toContain('"text"')
    await request.delete(`/agents/${a.id}`)
  })
})

test.describe('히스토리 정책', () => {
  test.setTimeout(90_000)

  test('historyDepth로 실행 컨텍스트 절단(trace.contextMessages)', async ({ request }) => {
    const a = await createAgent(request, uniq('hist'), { historyDepth: 2 })
    const msgs = [
      { role: 'user', content: 'a' },
      { role: 'assistant', content: 'b' },
      { role: 'user', content: 'c' },
      { role: 'assistant', content: 'd' },
      { role: 'user', content: '마지막 질문' },
    ]
    const res = await request.post(`/agents/${a.id}/chat`, { data: { messages: msgs }, timeout: 60_000 })
    expect(res.ok()).toBeTruthy()
    const t = sseTrace(await res.text())
    expect(t?.contextMessages, 'historyDepth=2 → 마지막 2개만 모델에').toBe(2)
    await request.delete(`/agents/${a.id}`)
  })

  test('persistHistory=false면 메시지 미저장(세션 카운터만 갱신)', async ({ request }) => {
    const a = await createAgent(request, uniq('nopersist'), { persistHistory: false })
    const res = await request.post(`/agents/${a.id}/chat`, {
      data: { messages: [{ role: 'user', content: '안녕' }] },
      timeout: 60_000,
    })
    expect(res.ok()).toBeTruthy()
    const sid = sseSession(await res.text())
    expect(sid).toBeTruthy()
    const msgs = await (await request.get(`/sessions/${sid}/messages`)).json()
    expect(msgs.length, '윈도우 모드 — 메시지 미저장').toBe(0)
    const sess = await (await request.get(`/sessions/${sid}`)).json()
    expect(sess.turns, '세션 카운터는 갱신').toBeGreaterThanOrEqual(1)
    await request.delete(`/agents/${a.id}`)
  })
})

test.describe('세션 / 승인', () => {
  test('GET /sessions 시드 존재', async ({ request }) => {
    // /sessions는 페이지네이션 응답 {items, total, counts}
    const s = await (await request.get('/sessions')).json()
    expect(Array.isArray(s.items)).toBeTruthy()
    expect(s.total).toBeGreaterThan(0)
  })

  test('승인 resolve → 상태 변경', async ({ request }) => {
    const list = await (await request.get('/approvals')).json()
    const pending = list.find((x: { status: string }) => x.status === 'pending')
    test.skip(!pending, '대기 중 승인 없음 (이미 처리됨)')
    const r = await (await request.post(`/approvals/${pending.id}/resolve`, { data: { decision: 'approve' } })).json()
    expect(r.status).toBe('approved')
  })
})

test.describe('채팅 런타임 + mem0', () => {
  test.setTimeout(180_000)

  function parseTrace(sse: string): Record<string, unknown> | null {
    const frames = sse.split('\n\n')
    for (const f of frames) {
      if (f.includes('event: trace')) {
        const line = f.split('\n').find((l) => l.startsWith('data: '))
        if (line) return JSON.parse(line.slice(6))
      }
    }
    return null
  }

  function parseSessionId(sse: string): string | null {
    for (const f of sse.split('\n\n')) {
      const line = f.split('\n').find((l) => l.startsWith('data: '))
      if (!line) continue
      try {
        const d = JSON.parse(line.slice(6))
        if (typeof d.session === 'string') return d.session
      } catch {
        /* skip */
      }
    }
    return null
  }

  async function chat(request: APIRequestContext, agentId: string, content: string) {
    const res = await request.post(`/agents/${agentId}/chat`, {
      data: { messages: [{ role: 'user', content }] },
      timeout: 150_000,
    })
    expect(res.ok()).toBeTruthy()
    return res.text()
  }

  test('스트리밍 + 트레이스 + 멀티턴 세션 영속', async ({ request }) => {
    // 메모리 회상 hits는 여기서 단언하지 않는다 — mock 모델은 결정적 exact-match만 하고
    // 채팅 경로 mem0 추출/저장은 회상가능 메모리를 안 남긴다(semantic 회상은 실 임베딩 필요).
    // 회상 기능 검증은 직접 시드로 하는 스펙 363·능력 매트릭스 verify_233 소관.
    const agents = await (await request.get('/agents')).json()
    const ra = agents.find((a: { name: string }) => a.name === SEED.uiAgent)
    expect(ra, `${SEED.uiAgent} 시드 필요`).toBeTruthy()

    // 1) 턴1 — 스트리밍 + 트레이스 프레임
    const sse1 = await chat(request, ra.id, '내가 좋아하는 색은 청록색이야. 기억해줘.')
    expect(sse1).toContain('data:')
    const t1 = parseTrace(sse1)
    expect(t1, 'trace 프레임').toBeTruthy()
    expect(Array.isArray(t1!.graph)).toBeTruthy()
    expect((t1!.tokens as Record<string, number>).out).toBeGreaterThan(0)

    // 2) 턴2 — 같은 세션 멀티턴
    const sse2 = await chat(request, ra.id, '내가 좋아한다고 한 색이 뭐였지?')
    const t2 = parseTrace(sse2)
    expect(t2).toBeTruthy()
    expect(Array.isArray(t2!.memories), 'memories 배열').toBeTruthy()

    // 3) 세션/메시지 영속 — 응답이 알려준 실제 세션 id로 결정적 조회
    const sessionId = parseSessionId(sse2)
    expect(sessionId, 'session 프레임').toBeTruthy()
    const msgs = await (await request.get(`/sessions/${sessionId}/messages`)).json()
    expect(msgs.length).toBeGreaterThan(0)
    const assistant = msgs.find((m: { role: string; trace: unknown }) => m.role === 'assistant')
    expect(assistant?.trace, 'assistant 메시지에 트레이스 저장').toBeTruthy()
  })

  test('코드 에이전트 — 원격 엔드포인트로 프록시 실행', async ({ request }) => {
    test.setTimeout(60_000)
    const agents = await (await request.get('/agents')).json()
    const code = agents.find((a: { source: string }) => a.source === 'code')
    expect(code, `코드 에이전트(${SEED.codeAgent}) 시드 필요`).toBeTruthy()
    const res = await request.post(`/agents/${code.id}/chat`, {
      data: { messages: [{ role: 'user', content: '상태 알려줘' }] },
      timeout: 50_000,
    })
    expect(res.ok()).toBeTruthy()
    const sse = await res.text()
    expect(sse, '원격(mock) 응답 시그니처').toContain(A2A_SIGNATURE)
    const t = parseTrace(sse)
    expect(t?.remote, '트레이스 remote 플래그').toBe(true)
    expect((t!.graph as { node: string }[]).some((n) => n.node === 'a2a_call'), 'a2a_call 노드').toBeTruthy()
  })
})

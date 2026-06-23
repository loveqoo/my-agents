import { test, expect, type APIRequestContext } from '@playwright/test'

/* 백엔드 API 통합 — request 픽스처(브라우저 없음). baseURL = API(8000).
   고유 이름으로 데이터를 만들고 끝에 삭제해 시드 오염을 막는다. */

const uniq = (p: string) => `${p}-${Date.now()}-${Math.floor(Math.random() * 1e4)}`

async function createAgent(request: APIRequestContext, name: string, config: object = {}) {
  const res = await request.post('/agents', {
    data: {
      name,
      config: {
        model: 'local-mlx',
        persona: 'Calm SRE',
        memories: [],
        vectorTables: [],
        permissions: [],
        mcps: [],
        historyDepth: 10,
        ...config,
      },
    },
  })
  expect(res.ok(), `create ${name}: ${res.status()}`).toBeTruthy()
  return res.json()
}

test.describe('블록', () => {
  test('GET /blocks → 5 카테고리, 각 항목 존재', async ({ request }) => {
    const res = await request.get('/blocks')
    expect(res.ok()).toBeTruthy()
    const blocks = await res.json()
    for (const key of ['persona', 'memory', 'embedding', 'permission', 'mcp']) {
      expect(blocks[key], key).toBeTruthy()
      expect(Array.isArray(blocks[key].items)).toBeTruthy()
      expect(blocks[key].items.length).toBeGreaterThan(0)
    }
  })

  test('persona 생성 → 목록 포함 → 삭제', async ({ request }) => {
    const name = uniq('persona')
    const created = await (await request.post('/personas', { data: { name, tone: 't', body: 'b' } })).json()
    expect(created.id).toBeTruthy()
    const list = await (await request.get('/personas')).json()
    expect(list.some((p: { name: string }) => p.name === name)).toBeTruthy()
    const del = await request.delete(`/personas/${created.id}`)
    expect(del.status()).toBe(204)
  })

  test('MCP 생성 → publish 토글 → 삭제', async ({ request }) => {
    const name = uniq('mcp')
    const m = await (
      await request.post('/mcp-servers', {
        data: { name, source: 'local', transport: 'stdio', tools: ['x'], enabled_tools: ['x'] },
      })
    ).json()
    expect(m.id).toBeTruthy()
    const pub = await (await request.put(`/mcp-servers/${m.id}/publish`, { data: { published: true } })).json()
    expect(pub.published).toBe(true)
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

  test('단순 에이전트(페르소나만) 생성 → 실제 대화 가능', async ({ request }) => {
    test.setTimeout(150_000)
    // 부가기능(mcp·memory·vectorTable·permission) 없이 페르소나만
    const a = await createAgent(request, uniq('simple'), {
      mcps: [],
      memories: [],
      vectorTables: [],
      permissions: [],
    })
    const res = await request.post(`/agents/${a.id}/chat`, {
      data: { messages: [{ role: 'user', content: '한 단어로 인사해줘' }] },
      timeout: 120_000,
    })
    expect(res.ok(), `chat ${res.status()}`).toBeTruthy()
    const sse = await res.text()
    expect(sse, '스트리밍 텍스트 프레임').toContain('"text"')
    expect(sse, '트레이스 프레임').toContain('event: trace')
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
    expect(names).toContain('qwen3.6-35b')
    expect(names).toContain('multilingual-e5-large')
    const chat = await (await request.get('/models?kind=chat')).json()
    expect(chat.every((m: { kind: string }) => m.kind === 'chat')).toBeTruthy()
    // api_key 마스킹 확인
    const withKey = all.find((m: { api_key: string | null }) => m.api_key)
    if (withKey) expect(withKey.api_key).toContain('•')
  })

  test('CRUD', async ({ request }) => {
    const name = uniq('model')
    const m = await (
      await request.post('/models', {
        data: { name, provider: 'openai-compatible', base_url: 'http://x/v1', api_key: 'sk_secret_value', model_id: 'foo/bar', kind: 'chat', is_default: false, params: {} },
      })
    ).json()
    expect(m.id).toBeTruthy()
    expect(m.api_key).toContain('•') // 마스킹되어 반환
    const got = await (await request.get(`/models/${m.id}`)).json()
    expect(got.model_id).toBe('foo/bar')
    expect((await request.delete(`/models/${m.id}`)).status()).toBe(204)
  })

  test('등록된 모델로 에이전트 실행', async ({ request }) => {
    test.setTimeout(150_000)
    const a = await createAgent(request, uniq('agent'), { model: 'qwen3.6-35b' })
    const res = await request.post(`/agents/${a.id}/chat`, {
      data: { messages: [{ role: 'user', content: '한 단어로 인사' }] },
      timeout: 120_000,
    })
    expect(res.ok()).toBeTruthy()
    expect(await res.text()).toContain('"text"')
    await request.delete(`/agents/${a.id}`)
  })
})

test.describe('세션 / 승인', () => {
  test('GET /sessions 시드 존재', async ({ request }) => {
    const s = await (await request.get('/sessions')).json()
    expect(Array.isArray(s)).toBeTruthy()
    expect(s.length).toBeGreaterThan(0)
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

  test('스트리밍 + 트레이스 + mem0 저장/회상 + 세션 영속', async ({ request }) => {
    const agents = await (await request.get('/agents')).json()
    const ra = agents.find((a: { name: string }) => a.name === 'Research Assistant')
    expect(ra, 'Research Assistant 시드 필요').toBeTruthy()

    // 1) 사실 저장
    const sse1 = await chat(request, ra.id, '내가 좋아하는 색은 청록색이야. 기억해줘.')
    expect(sse1).toContain('data:')
    const t1 = parseTrace(sse1)
    expect(t1, 'trace 프레임').toBeTruthy()
    expect(Array.isArray(t1!.graph)).toBeTruthy()
    expect((t1!.tokens as Record<string, number>).out).toBeGreaterThan(0)

    // 2) 회상
    const sse2 = await chat(request, ra.id, '내가 좋아한다고 한 색이 뭐였지?')
    const t2 = parseTrace(sse2)
    expect(t2).toBeTruthy()
    expect((t2!.memories as unknown[]).length, 'mem0 회상 hits').toBeGreaterThan(0)

    // 3) 세션/메시지 영속 — 응답이 알려준 실제 세션 id로 결정적 조회
    const sessionId = parseSessionId(sse2)
    expect(sessionId, 'session 프레임').toBeTruthy()
    const msgs = await (await request.get(`/sessions/${sessionId}/messages`)).json()
    expect(msgs.length).toBeGreaterThan(0)
    const assistant = msgs.find((m: { role: string; trace: unknown }) => m.role === 'assistant')
    expect(assistant?.trace, 'assistant 메시지에 트레이스 저장').toBeTruthy()
  })
})

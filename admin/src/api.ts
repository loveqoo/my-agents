/* 어드민 백엔드 API 클라이언트 (007 Phase 3).
   타입은 admin/mockData.ts와 일원화 — 백엔드 출력이 동일 shape다. */
import type { Agent, Approval, BlockCategory, Session } from './admin/mockData'

const BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000'

export type { Agent, Approval, BlockCategory, Session }

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

async function j<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: init?.body ? { 'Content-Type': 'application/json' } : undefined,
    ...init,
  })
  if (!res.ok) throw new Error(`${init?.method ?? 'GET'} ${path} → ${res.status}`)
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

const post = (p: string, body?: unknown) =>
  j(p, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })
const put = (p: string, body: unknown) => j(p, { method: 'PUT', body: JSON.stringify(body) })
const del = (p: string) => j<void>(p, { method: 'DELETE' })

/* ---------- 빌딩 블록 ---------- */
export const getBlocks = () => j<Record<string, BlockCategory>>('/blocks')

export const createMcp = (body: unknown) => post('/mcp-servers', body)
export const updateMcp = (id: string, body: unknown) => put(`/mcp-servers/${id}`, body)
export const deleteMcp = (id: string) => del(`/mcp-servers/${id}`)
export const publishMcp = (id: string, published: boolean) =>
  put(`/mcp-servers/${id}/publish`, { published })

/* 카테고리별 생성/삭제 (BlocksView "새 항목"·삭제). category: personas|memory-types|vector-tables|permissions */
export const createBlockItem = (resource: string, body: unknown) => post(`/${resource}`, body)
export const deleteBlockItem = (resource: string, id: string) => del(`/${resource}/${id}`)

/* ---------- 에이전트 ---------- */
export const listAgents = () => j<Agent[]>('/agents')
export const getAgent = (id: string) => j<Agent>(`/agents/${id}`)
export const createAgent = (name: string, config: unknown) =>
  post('/agents', { name, config }) as Promise<Agent>
export const updateAgent = (id: string, name: string, config: unknown) =>
  put(`/agents/${id}`, { name, config }) as Promise<Agent>
export const deleteAgent = (id: string) => del(`/agents/${id}`)
export const activateVersion = (id: string, version: string) =>
  post(`/agents/${id}/activate`, { version }) as Promise<Agent>
export const revertVersion = (id: string, version: string) =>
  post(`/agents/${id}/revert`, { version }) as Promise<Agent>
export const forkVersion = (id: string) => post(`/agents/${id}/versions`) as Promise<Agent>
export const exposeAgent = (id: string, a2a: boolean) =>
  put(`/agents/${id}/expose`, { a2a }) as Promise<Agent>
export const registerCodeAgent = (body: unknown) => post('/agents/register', body) as Promise<Agent>
export const resyncAgent = (id: string) => post(`/agents/${id}/resync`) as Promise<Agent>

/* ---------- 모델 (LLM·임베딩 레지스트리) ---------- */
export interface Model {
  id: string
  name: string
  provider: string
  base_url: string
  api_key: string | null
  model_id: string
  kind: 'chat' | 'embedding'
  is_default: boolean
  params: Record<string, unknown>
}
export const listModels = (kind?: 'chat' | 'embedding') =>
  j<Model[]>(`/models${kind ? `?kind=${kind}` : ''}`)
export const createModel = (body: unknown) => post('/models', body) as Promise<Model>
export const updateModel = (id: string, body: unknown) => put(`/models/${id}`, body) as Promise<Model>
export const deleteModel = (id: string) => del(`/models/${id}`)

/* ---------- 세션 / 승인 ---------- */
export const listSessions = () => j<Session[]>('/sessions')
export interface SessionMessage {
  role: string
  content: string
  trace: Record<string, unknown> | null
}
export const getSessionMessages = (sessionId: string) =>
  j<SessionMessage[]>(`/sessions/${sessionId}/messages`)
export const listApprovals = () => j<Approval[]>('/approvals')
export const resolveApproval = (id: string, decision: 'approve' | 'reject') =>
  post(`/approvals/${id}/resolve`, { decision }) as Promise<Approval>

/* ---------- 채팅 SSE ---------- */
export interface ChatCallbacks {
  onToken: (t: string) => void
  onSession?: (sessionId: string) => void
  onTrace?: (trace: Record<string, unknown>) => void
}

function handleFrame(frame: string, cb: ChatCallbacks): boolean {
  const lines = frame.split('\n')
  const event = lines.find((l) => l.startsWith('event: '))?.slice(7)
  const dataLine = lines.find((l) => l.startsWith('data: '))
  if (!dataLine) return false
  const data = dataLine.slice(6)
  if (data === '[DONE]') return true
  try {
    const parsed = JSON.parse(data)
    if (event === 'trace') cb.onTrace?.(parsed)
    else if (typeof parsed.text === 'string') cb.onToken(parsed.text)
    else if (typeof parsed.session === 'string') cb.onSession?.(parsed.session)
    else if (typeof parsed.error === 'string') cb.onToken(`\n[오류] ${parsed.error}`)
  } catch {
    /* 비-JSON 프레임 무시 */
  }
  return false
}

/** chat SSE 스트리밍 (POST → fetch+ReadableStream). session/trace 이벤트도 콜백. */
export async function streamChat(
  agentId: string,
  messages: ChatMessage[],
  cb: ChatCallbacks | ((t: string) => void),
  signal?: AbortSignal,
  sessionId?: string,
): Promise<void> {
  const callbacks: ChatCallbacks = typeof cb === 'function' ? { onToken: cb } : cb
  const res = await fetch(`${BASE}/agents/${agentId}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ messages, sessionId }),
    signal,
  })
  if (!res.ok || !res.body) throw new Error(`채팅 실패: ${res.status}`)

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    const frames = buf.split('\n\n')
    buf = frames.pop() ?? ''
    for (const frame of frames) {
      if (handleFrame(frame, callbacks)) return
    }
  }
  if (buf.trim()) handleFrame(buf, callbacks)
}

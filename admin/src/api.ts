/* 어드민 백엔드 API 클라이언트 (007 Phase 3).
   타입은 admin/mockData.ts와 일원화 — 백엔드 출력이 동일 shape다. */
import type { Agent, Approval, BlockCategory, Session } from './admin/mockData'

// 기본은 same-origin 상대경로 `/api` — vite dev 프록시(vite.config.ts)가 127.0.0.1:8000으로 넘긴다.
// 브라우저는 API 호스트를 모르므로 tailscale 도메인/IP/scheme가 바뀌어도 무설정 동작(CORS·mixed-content·cert 회피).
// 별도 호스트로 직접 붙고 싶을 때만 VITE_API_BASE로 절대 URL을 준다.
const BASE = import.meta.env.VITE_API_BASE ?? '/api'
// 인증은 세션 쿠키(fastapi-users, 스펙 031)가 기본 — same-origin이라 쿠키가 자동 동행한다.
// VITE_API_TOKEN은 머신 Bearer 토큰 하위호환용(헤드리스/E2E). 있으면 함께 보낸다.
const TOKEN = import.meta.env.VITE_API_TOKEN ?? ''

export type { Agent, Approval, BlockCategory, Session }

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

// 401(세션 만료·미인증) 전역 핸들러 — AuthGate가 등록해 로그인 화면으로 되돌린다.
let unauthorizedHandler: (() => void) | null = null
export function setUnauthorizedHandler(fn: (() => void) | null): void {
  unauthorizedHandler = fn
}

/** 모든 요청 공통 헤더 (머신 Bearer 토큰 하위호환 + 본문 시 JSON). */
function authHeaders(hasBody: boolean): Record<string, string> {
  const h: Record<string, string> = {}
  if (TOKEN) h.Authorization = `Bearer ${TOKEN}`
  if (hasBody) h['Content-Type'] = 'application/json'
  return h
}

async function j<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    credentials: 'include', // 세션 쿠키 동행(절대 URL/크로스오리진에서도)
    headers: { ...authHeaders(!!init?.body), ...(init?.headers as Record<string, string>) },
  })
  if (res.status === 401) {
    unauthorizedHandler?.()
    throw new Error(`${init?.method ?? 'GET'} ${path} → 401`)
  }
  if (!res.ok) throw new Error(`${init?.method ?? 'GET'} ${path} → ${res.status}`)
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

const post = (p: string, body?: unknown) =>
  j(p, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })
const put = (p: string, body: unknown) => j(p, { method: 'PUT', body: JSON.stringify(body) })
const patch = (p: string, body: unknown) => j(p, { method: 'PATCH', body: JSON.stringify(body) })
const del = (p: string) => j<void>(p, { method: 'DELETE' })

/* ---------- 인증 (세션 쿠키, 스펙 031) ---------- */
export interface Me {
  id: string
  email: string
  is_active: boolean
  is_superuser: boolean
  is_verified: boolean
  source: string
  display_name: string | null
}

/** 로그인 — fastapi-users 인증 라우터는 OAuth2 폼(username=email). 성공 시 204 + Set-Cookie. */
export async function login(email: string, password: string): Promise<void> {
  const body = new URLSearchParams({ username: email, password })
  const res = await fetch(`${BASE}/auth/login`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body,
  })
  // 400 = 자격증명 불일치/비활성(LOGIN_BAD_CREDENTIALS). 그 외 비정상도 메시지로 던진다.
  if (!res.ok) throw new Error(res.status === 400 ? '이메일 또는 비밀번호가 올바르지 않습니다' : `로그인 실패: ${res.status}`)
}

/** 로그아웃 — DatabaseStrategy 토큰 행 삭제 = 진짜 무효화. */
export const logout = () => post('/auth/logout')

/** 현재 로그인 사용자. 미인증이면 null(전역 401 핸들러는 건너뛴다 — 초기 탐색용). */
export async function getMe(): Promise<Me | null> {
  const res = await fetch(`${BASE}/users/me`, {
    credentials: 'include',
    headers: authHeaders(false),
  })
  if (res.status === 401) return null
  if (!res.ok) throw new Error(`GET /users/me → ${res.status}`)
  return res.json() as Promise<Me>
}

/* ---------- 관리자: 유저·역할 (admin 보호, 스펙 031) ---------- */
export interface AdminUser {
  id: string
  email: string
  is_active: boolean
  is_superuser: boolean
  is_verified: boolean
  source: string
  display_name: string | null
  roles: string[]
}
export interface RoleInfo {
  id: string
  name: string
  description: string
}
export const listUsers = () => j<AdminUser[]>('/admin/users')
export const createUser = (body: {
  email: string
  password: string
  display_name?: string
  is_superuser?: boolean
}) => post('/admin/users', body) as Promise<AdminUser>
export const setUserActive = (id: string, active: boolean) =>
  j<AdminUser>(`/admin/users/${id}/active?active=${active}`, { method: 'PATCH' })
export const listRoles = () => j<RoleInfo[]>('/admin/roles')
export const grantRole = (id: string, role: string) =>
  j<AdminUser>(`/admin/users/${id}/roles`, { method: 'POST', body: JSON.stringify({ role }) })
export const revokeRole = (id: string, role: string) =>
  j<AdminUser>(`/admin/users/${id}/roles/${encodeURIComponent(role)}`, { method: 'DELETE' })

/* ---------- 배치(격리 배치 서비스, 스펙 038) — admin 보호 ---------- */
export interface BatchConfig {
  session_retention_days: number | null
  session_cleanup_cron: string | null
  min_session_turns: number | null
  memory_consolidation_threshold: number | null
  memory_consolidation_cron: string | null
  test_user_email_pattern: string | null
}
export interface BatchRun {
  id: string
  job_name: string
  status: string // running|ok|error
  dry_run: boolean
  summary: Record<string, unknown> | null
  error: string | null
  started_at: string | null
  finished_at: string | null
}
export const listBatchJobs = () => j<{ jobs: string[] }>('/admin/batch/jobs')
export const getBatchConfig = () => j<BatchConfig>('/admin/batch/config')
export const updateBatchConfig = (body: Partial<BatchConfig>) =>
  patch('/admin/batch/config', body) as Promise<BatchConfig>
export const listBatchRuns = (limit = 20) => j<BatchRun[]>(`/admin/batch/runs?limit=${limit}`)
export const triggerBatchJob = (job: string, dryRun: boolean) =>
  post(`/admin/batch/${encodeURIComponent(job)}/run?dry_run=${dryRun}`) as Promise<BatchRun & {
    run_id: string
    job: string
    status: string
    summary?: Record<string, unknown>
    error?: string
  }>

/* ---------- 빌딩 블록 ---------- */
export const getBlocks = () => j<Record<string, BlockCategory>>('/blocks')

export const createMcp = (body: unknown) => post('/mcp-servers', body)
export const updateMcp = (id: string, body: unknown) => put(`/mcp-servers/${id}`, body)
/* 저장 전 라이브 도구 탐색(스펙 054 E) — url에 실제로 붙어 도구목록만 읽음(부작용 0). */
export type McpDiscoverResult = {
  ok: boolean
  reachable: boolean
  tools: string[]
  latencyMs: number
  detail: string
}
export const discoverMcpTools = (body: { url: string; transport: string; auth?: string | null }) =>
  post('/mcp-servers/discover', body) as Promise<McpDiscoverResult>
export const deleteMcp = (id: string) => del(`/mcp-servers/${id}`)
export const publishMcp = (id: string, published: boolean) =>
  put(`/mcp-servers/${id}/publish`, { published })

/* 카테고리별 생성/수정/삭제 (BlocksView). resource: personas|memory-types|vector-tables|permissions */
export const createBlockItem = (resource: string, body: unknown) => post(`/${resource}`, body)
export const updateBlockItem = (resource: string, id: string, body: unknown) =>
  put(`/${resource}/${id}`, body)
export const deleteBlockItem = (resource: string, id: string) => del(`/${resource}/${id}`)

/* ---------- RAG 컬렉션 + 문서 인제스트 (스펙 036) ---------- */
export interface Collection {
  id: string
  name: string
  description: string
  embedding_model_id: string
  embedding_model_name: string
  dims: number
  chunk_size: number
  chunk_overlap: number
  doc_count: number
  chunk_count: number
  status: string // empty|ingesting|ready|error
}
export interface RagDocument {
  id: string
  collection_id: string
  filename: string
  content_type: string | null
  byte_size: number
  chunk_count: number
  status: string // parsing|embedding|ready|error
  error: string | null
}
export interface CollectionHealth {
  collection_id: string
  db_dims: number
  collection_dims: number
  model_dims: number | null
  consistent: boolean
  detail: string
}
export const listCollections = () => j<Collection[]>('/collections')
export const createCollection = (body: {
  name: string
  description?: string
  embedding_model_id: string
  chunk_size?: number
  chunk_overlap?: number
}) => post('/collections', body) as Promise<Collection>
export const updateCollection = (
  id: string,
  body: { description?: string; chunk_size?: number; chunk_overlap?: number },
) => put(`/collections/${id}`, body) as Promise<Collection>
export const deleteCollection = (id: string) => del(`/collections/${id}`)
export const collectionHealth = (id: string) =>
  j<CollectionHealth>(`/collections/${id}/health`)
export const listDocuments = (id: string) => j<RagDocument[]>(`/collections/${id}/documents`)
export const deleteDocument = (id: string, docId: string) =>
  del(`/collections/${id}/documents/${docId}`)
/** 문서 업로드(멀티파트). FormData는 Content-Type을 브라우저가 boundary와 함께 자동 설정 — 직접 넣지 않는다. */
export async function uploadDocument(id: string, file: File): Promise<RagDocument> {
  const fd = new FormData()
  fd.append('file', file)
  const res = await fetch(`${BASE}/collections/${id}/documents`, {
    method: 'POST',
    credentials: 'include',
    headers: TOKEN ? { Authorization: `Bearer ${TOKEN}` } : {},
    body: fd,
  })
  if (res.status === 401) {
    unauthorizedHandler?.()
    throw new Error(`POST /collections/${id}/documents → 401`)
  }
  if (!res.ok) throw new Error(`업로드 실패: ${res.status}`)
  return res.json() as Promise<RagDocument>
}

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
/* 외부(A2A) 에이전트 등록 — 카드 URL을 보내면 백엔드가 fetch·검증 후 등록(스펙 026). */
export const registerExternalAgent = (cardUrl: string, token?: string) =>
  post('/agents/external', { cardUrl, token: token || undefined }) as Promise<Agent>
export const resyncAgent = (id: string) => post(`/agents/${id}/resync`) as Promise<Agent>

/* ---------- 에이전트 전용 메모리 큐레이션 (스펙 029) ---------- */
export interface AgentMemory {
  id: string
  text: string
}
export const listAgentMemory = (id: string) => j<AgentMemory[]>(`/agents/${id}/memory`)
export const addAgentMemory = (id: string, text: string) =>
  post(`/agents/${id}/memory`, { text })
export const updateAgentMemory = (id: string, memId: string, text: string) =>
  patch(`/agents/${id}/memory/${memId}`, { text })
export const deleteAgentMemory = (id: string, memId: string) =>
  del(`/agents/${id}/memory/${memId}`)

/* ---------- 유저 메모리 큐레이션 (스펙 030) — user_id 축, 교정 전용(add 없음) ---------- */
export const listUserMemory = (userId: string) =>
  j<AgentMemory[]>(`/memory/user/${encodeURIComponent(userId)}`)
export const updateUserMemory = (userId: string, memId: string, text: string) =>
  patch(`/memory/user/${encodeURIComponent(userId)}/${encodeURIComponent(memId)}`, { text })
export const deleteUserMemory = (userId: string, memId: string) =>
  del(`/memory/user/${encodeURIComponent(userId)}/${encodeURIComponent(memId)}`)

/* ---------- 프로바이더 (연결처 — base_url + 자격증명, 스펙 035) ---------- */
export type ProviderKind = 'local' | 'mock' | 'remote'
export interface Provider {
  id: string
  name: string
  protocol: string
  base_url: string
  api_key: string | null // 마스킹(•) 또는 null — 평문 비노출
  kind: ProviderKind // 표시·배지 (스펙 047 #6): local=내 머신 / mock=결정적 목 / remote=외부 API
  description: string // 한 줄 설명(스펙 047 #6)
  modelCount: number
}
export const listProviders = () => j<Provider[]>('/providers')
export const createProvider = (body: unknown) => post('/providers', body) as Promise<Provider>
export const updateProvider = (id: string, body: unknown) =>
  put(`/providers/${id}`, body) as Promise<Provider>
export const deleteProvider = (id: string) => del(`/providers/${id}`)
export const testProviderConfig = (body: { base_url: string; api_key?: string | null }) =>
  post('/providers/test', body) as Promise<ModelProbeResult>
export const testSavedProvider = (id: string) =>
  post(`/providers/${id}/test`) as Promise<ModelProbeResult>

/* ---------- 모델 (LLM·임베딩 레지스트리) ---------- */
export interface Model {
  id: string
  name: string
  provider_id: string
  provider_name: string
  base_url: string // provider에서 상속(읽기 전용 표시)
  model_id: string
  kind: 'chat' | 'embedding'
  is_default: boolean
  params: Record<string, unknown>
  meta: Record<string, unknown> // models.dev 카탈로그 파생(context·modalities·cost·caps) — 스펙 047 #7
}
export const listModels = (kind?: 'chat' | 'embedding') =>
  j<Model[]>(`/models${kind ? `?kind=${kind}` : ''}`)
export const createModel = (body: unknown) => post('/models', body) as Promise<Model>
export const updateModel = (id: string, body: unknown) => put(`/models/${id}`, body) as Promise<Model>
export const deleteModel = (id: string) => del(`/models/${id}`)

/* ---------- 프로바이더 실모델 + 카탈로그 (통합 뷰 토글, 스펙 047 #7·#8) ---------- */
/** models.dev 매칭 메타(없으면 null). 정규화 형태는 catalog._to_meta 참조. */
export interface CatalogMeta {
  catalog_id?: string | null
  name?: string | null
  context?: number | null
  output_limit?: number | null
  modalities?: { input?: string[]; output?: string[] }
  cost?: { input?: number | null; output?: number | null }
  capabilities?: {
    reasoning?: boolean
    tool_call?: boolean
    structured_output?: boolean
    attachment?: boolean
  }
  release_date?: string | null
}
export interface AvailableModel {
  model_id: string // 프로바이더가 돌려준 raw id
  registered: boolean // 이 프로바이더+model_id로 모델이 이미 등록됐나
  registered_name: string | null // 등록돼 있으면 표시 이름
  registered_id: string | null // 등록돼 있으면 모델 id(토글 OFF용)
  catalog: CatalogMeta | null // models.dev 매칭(없으면 null — MLX 사설 모델 등 정상)
}
export interface AvailableModelsOut {
  reachable: boolean // base_url GET /models 도달 여부
  detail: string // 도달 실패 시 안내(비밀 미포함)
  models: AvailableModel[]
}
export const listAvailableModels = (providerId: string) =>
  j<AvailableModelsOut>(`/providers/${providerId}/available-models`)

/** 모델/프로바이더 연결 테스트 결과 (detail은 비밀 없는 안전 메시지). */
export interface ModelProbeResult {
  ok: boolean
  reachable: boolean
  modelAvailable: boolean
  latencyMs: number
  detail: string
  dims?: number | null
}
export const testModelConfig = (body: {
  provider_id: string
  model_id: string
  kind?: 'chat' | 'embedding'
}) => post('/models/test', body) as Promise<ModelProbeResult>
export const testSavedModel = (id: string) => post(`/models/${id}/test`) as Promise<ModelProbeResult>

/* ---------- 세션 / 승인 ---------- */
export interface SessionPage {
  items: Session[]
  total: number
  counts: Record<string, number> // 키 all|live|awaiting|error
}
// 서버 페이징·필터(스펙 034). status 버킷(all|live|awaiting|error) + limit/offset.
// agent_id(스펙 055): 외부 agent_id로 해당 에이전트 세션만 — Playground 세션 이어가기용.
export const listSessions = (params?: {
  status?: string
  agent_id?: string
  limit?: number
  offset?: number
}) => {
  const q = new URLSearchParams()
  if (params?.status) q.set('status', params.status)
  if (params?.agent_id) q.set('agent_id', params.agent_id)
  if (params?.limit != null) q.set('limit', String(params.limit))
  if (params?.offset != null) q.set('offset', String(params.offset))
  const qs = q.toString()
  return j<SessionPage>(`/sessions${qs ? `?${qs}` : ''}`)
}
// 대화에 쓰인 distinct user_id(이제 로그인 유저 UUID — 스펙 032), 최근 사용순.
// Playground 헤더 입력은 제거됐지만(032), 어드민 "유저 메모리" 조회(MemoryView)가 소비한다.
export const listUserIds = () => j<string[]>('/sessions/users')
// 유저 메모리 큐레이션용 — distinct user_id에 등록 유저 신원(email·display_name)을 보강(스펙 052).
// raw UUID만으론 누구인지 식별 불가라 별도 엔드포인트(users:manage 불요 — 메모리 화면 전용).
export interface MemoryUser {
  user_id: string
  email: string | null
  display_name: string | null
}
// 스펙 053 — 역할 기반 스코핑. 백엔드가 "타인 큐레이션 가능?"을 판정해 내린다(Casbin admin
// 역할은 클라이언트가 모르므로). 비-어드민: can_curate_others=false·users=[me]. 어드민: 전체.
export interface MemoryUserList {
  can_curate_others: boolean
  me: MemoryUser | null
  users: MemoryUser[]
}
export const listMemoryUsers = () => j<MemoryUserList>('/memory/users')
export interface SessionMessage {
  role: string
  content: string
  trace: Record<string, unknown> | null
}
export const getSessionMessages = (sessionId: string) =>
  j<SessionMessage[]>(`/sessions/${sessionId}/messages`)
export const listApprovals = (status?: string) =>
  j<Approval[]>(`/approvals${status ? `?status=${encodeURIComponent(status)}` : ''}`)
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
  // Playground "Proxy" 세션 한정 오버라이드(스펙 025). 변경된 키만 담긴 부분 객체 →
  // 비었으면 보내지 않아 서버는 저장된 에이전트 설정 그대로 실행(무회귀). 코드 에이전트는 서버가 무시.
  overrides?: Record<string, unknown>,
): Promise<void> {
  const callbacks: ChatCallbacks = typeof cb === 'function' ? { onToken: cb } : cb
  const hasOverrides = overrides != null && Object.keys(overrides).length > 0
  const res = await fetch(`${BASE}/agents/${agentId}/chat`, {
    method: 'POST',
    credentials: 'include',
    headers: authHeaders(true),
    // mem0 user_id 축은 서버가 인증 주체에서 도출한다(스펙 032) — 클라이언트는 보내지 않음.
    body: JSON.stringify({
      messages,
      sessionId,
      overrides: hasOverrides ? overrides : undefined,
    }),
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

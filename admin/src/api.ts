/* 어드민 백엔드 API 클라이언트 (007 Phase 3).
   타입은 admin/mockData.ts와 일원화 — 백엔드 출력이 동일 shape다. */
import type { Agent, Approval, BlockCategory, Session } from './admin/mockData'
import { httpError } from './httpError'

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
  if (!res.ok) throw await httpError(res, init?.method ?? 'GET', path)
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

/* 능력 부여(정책) — 스펙 177 P3. subject=역할명/유저id, object=`capability:{kind}[:{name}]`.
   백엔드가 capability: 경계·invoke 고정을 강제(임의 권한 상승 차단). */
export interface Policy {
  subject: string
  object: string
  action: string
}
export const listPolicies = () => j<Policy[]>('/admin/policies')
export const grantPolicy = (body: Policy) => post('/admin/policies', body) as Promise<Policy>
export const revokePolicy = (subject: string, object: string, action: string) =>
  del(
    `/admin/policies?subject=${encodeURIComponent(subject)}&object=${encodeURIComponent(object)}&action=${encodeURIComponent(action)}`,
  )

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

/* ---------- 앱 설정 (스펙 153) ---------- */
export const getAppSettings = () => j<Record<string, unknown>>('/admin/settings')
export const putAppSetting = (key: string, value: unknown) =>
  put(`/admin/settings/${encodeURIComponent(key)}`, { value }) as Promise<Record<string, unknown>>

/* ---------- SSRF allowlist (스펙 064) ---------- */
export interface AllowedHost {
  id: string
  host: string
  note: string | null
  created_at: string | null
}
export const listAllowedHosts = () => j<AllowedHost[]>('/admin/allowed-hosts')
export const addAllowedHost = (host: string, note?: string | null) =>
  post('/admin/allowed-hosts', { host, note: note ?? null }) as Promise<AllowedHost>
export const deleteAllowedHost = (id: string) =>
  del(`/admin/allowed-hosts/${encodeURIComponent(id)}`)

/* ---------- 빌딩 블록 ---------- */
export const getBlocks = () => j<Record<string, BlockCategory>>('/blocks')

/* MCP 서버 목록(스펙 200 — 능력 부여 카탈로그 선택용 최소 형태). */
export type McpServerLite = { id: string; name: string; alias?: string | null }
export const listMcpServers = () => j<McpServerLite[]>('/mcp-servers')
export const createMcp = (body: unknown) => post('/mcp-servers', body)
export const updateMcp = (id: string, body: unknown) => put(`/mcp-servers/${id}`, body)
/* 저장 전 라이브 도구 탐색(스펙 054 E) — url에 실제로 붙어 도구목록만 읽음(부작용 0). */
export type McpToolParam = { name: string; type?: string; required?: boolean }
export type McpToolInfo = {
  name: string
  description?: string
  params?: McpToolParam[]
  approval?: { required?: boolean } // 도구 승인 정책(스펙 177 P1) — 켜면 호출 전 승인
}
export type McpDiscoverResult = {
  ok: boolean
  reachable: boolean
  tools: string[]
  toolsDetail?: McpToolInfo[] // 도구 메타(스펙 151)
  latencyMs: number
  detail: string
}
export const discoverMcpTools = (body: { url: string; transport: string; auth?: string | null }) =>
  post('/mcp-servers/discover', body) as Promise<McpDiscoverResult>
export const deleteMcp = (id: string) => del(`/mcp-servers/${id}`)
/** 저장된 서버의 도구·메타 재탐색(스펙 151) — 자격증명은 백엔드가 복호해 사용. */
export const rediscoverMcp = (id: string) => post(`/mcp-servers/${id}/rediscover`)
export const publishMcp = (id: string, published: boolean) =>
  put(`/mcp-servers/${id}/publish`, { published })

/* 카테고리별 생성/수정/삭제 (BlocksView). resource: personas|memory-types|vector-tables */
export const createBlockItem = (resource: string, body: unknown) => post(`/${resource}`, body)
export const updateBlockItem = (resource: string, id: string, body: unknown) =>
  put(`/${resource}/${id}`, body)
export const deleteBlockItem = (resource: string, id: string) => del(`/${resource}/${id}`)

/* 페르소나 스냅샷 동기화 (스펙 161) — 복사본 유지 + 명시적 반영. */
export interface PersonaUsageAgent {
  id: string
  agentId: string
  name: string
  alias?: string | null
  stale: boolean // 이 에이전트 스냅샷이 현재 페르소나 본문과 다름
  canManage: boolean // 요청 주체가 이 에이전트를 갱신 가능
}
// 에이전트 쪽: 자기 페르소나 스냅샷을 현재 원본으로 갱신.
export const refreshAgentPersona = (id: string) =>
  post(`/agents/${id}/persona/refresh`) as Promise<Agent>
// 페르소나 쪽: 이 페르소나를 쓰는 에이전트 + 오래됨 상태.
export const listPersonaAgents = (personaId: string) =>
  j<PersonaUsageAgent[]>(`/personas/${personaId}/agents`)
// 페르소나 쪽: 선택 에이전트들에 최신 본문 반영.
export const applyPersona = (personaId: string, agentIds: string[]) =>
  post(`/personas/${personaId}/apply`, { agentIds }) as Promise<{ applied: string[]; skipped: string[] }>


/* ---------- RAG 컬렉션 + 문서 인제스트 (스펙 036) ---------- */
export interface Collection {
  id: string
  name: string // 식별 이름(규칙, 스펙 148)
  alias?: string | null // 별명(자유 표기, 스펙 148) — 표시 = alias ?? name
  kind?: 'document' | 'entity' // 종류 축(스펙 149) — 생성 후 불변
  entity_schema?: Record<string, unknown> | null // 엔티티 행 검증 JSON Schema(선택, 스펙 149)
  description: string
  embedding_model_id: string
  embedding_model_name: string
  dims: number
  chunk_size: number
  chunk_overlap: number
  doc_count: number
  chunk_count: number
  status: string // empty|ingesting|ready|error
  owner_id?: string | null // 소유자(스펙 112). null=공유/레거시
  can_manage?: boolean // 관리 가능(스펙 114) — false면 편집/삭제 숨김
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
export interface SearchHit {
  score: number // 1 - cosine_distance (1.0=동일 벡터), 내림차순
  filename: string
  text: string
  meta?: Record<string, unknown> | null // 엔티티 metadata(스펙 149) — 문서형은 null
}
export interface CollectionSearchOut {
  query: string
  top_k: number
  results: SearchHit[]
}
export const listCollections = () => j<Collection[]>('/collections')
export const createCollection = (body: {
  name: string
  alias?: string | null // 별명(스펙 148)
  kind?: 'document' | 'entity' // 종류 축(스펙 149)
  entity_schema?: Record<string, unknown> | null // 엔티티 행 검증 스키마(스펙 149)
  description?: string
  embedding_model_id: string
  chunk_size?: number
  chunk_overlap?: number
}) => post('/collections', body) as Promise<Collection>
export const updateCollection = (
  id: string,
  body: {
    alias?: string | null
    description?: string
    // 스펙 198: 청크 크기·겹침은 생성 후 불변 → 수정 payload에서 제거.
    entity_schema?: Record<string, unknown> | null
  },
) => put(`/collections/${id}`, body) as Promise<Collection>
export const deleteCollection = (id: string) => del(`/collections/${id}`)
export const collectionHealth = (id: string) =>
  j<CollectionHealth>(`/collections/${id}/health`)
/** retrieval 시험(스펙 072) — 인-챗 도구와 같은 코어를 타는 검색. 등록 직후 품질 즉석 확인. */
export const searchCollection = (id: string, query: string, topK: number) =>
  post(`/collections/${id}/search`, { query, top_k: topK }) as Promise<CollectionSearchOut>
/* 문서 페이지 목록(스펙 128) — 문서는 증가 축이라 서버 페이지네이션 + 파일명 부분일치(q). */
export interface DocumentPageOut {
  items: RagDocument[]
  total: number
}
export const listDocuments = (id: string, q = '', limit = 20, offset = 0) =>
  j<DocumentPageOut>(`/collections/${id}/documents${pageQS(q, limit, offset)}`)
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
  if (!res.ok) throw await httpError(res, 'POST', `/collections/${id}/documents`)
  return res.json() as Promise<RagDocument>
}

/* ---------- 에이전트 ---------- */
export const listAgents = () => j<Agent[]>('/agents')
/* 실행 방식 메타(스펙 206) — consumes: 이 impl이 읽는 설정 표면(null=미선언, 폼 전부 노출). */
export interface ImplMeta { key: string; consumes: string[] | null }
export const listAgentImpls = () => j<ImplMeta[]>('/agent-impls')
export const createAgent = (name: string, config: unknown, alias?: string | null) =>
  post('/agents', { name, alias: alias ?? null, config }) as Promise<Agent>
export const updateAgent = (id: string, name: string, config: unknown, alias?: string | null) =>
  // alias: undefined=미변경(백엔드 None), ''=비우기 — 폼은 항상 현재값을 보낸다(스펙 148)
  put(`/agents/${id}`, { name, alias: alias === undefined ? null : alias, config }) as Promise<Agent>
export const deleteAgent = (id: string) => del(`/agents/${id}`)
/* 복제 — 기존 설정을 새 ui 초안으로 복사(저마찰 재사용, 스펙 120). 복제자가 소유. */
export const cloneAgent = (id: string) => post(`/agents/${id}/clone`) as Promise<Agent>
/** 공개/비공개 전환(스펙 154 — 승격/강등). 강등 시 A2A 자동 off. */
export const setAgentVisibility = (id: string, isPublic: boolean) =>
  put(`/agents/${id}/visibility`, { public: isPublic }) as Promise<Agent>
export const activateVersion = (id: string, version: string) =>
  post(`/agents/${id}/activate`, { version }) as Promise<Agent>
export const revertVersion = (id: string, version: string) =>
  post(`/agents/${id}/revert`, { version }) as Promise<Agent>
export const forkVersion = (id: string) => post(`/agents/${id}/versions`) as Promise<Agent>
export const exposeAgent = (id: string, a2a: boolean) =>
  put(`/agents/${id}/expose`, { a2a }) as Promise<Agent>

/* A2A 카드의 광고 스킬(스펙 157) — 노출 에이전트가 외부에 광고하는 능력(chat+mcp+delegate+rag).
   카드는 공개(전역 인증 밖)라 자격증명 없이 GET. 미노출/부재면 404 → 호출측이 빈 배열 처리. */
export interface A2ASkill {
  id: string
  name: string
  description: string
  tags: string[]
}
export async function getA2ASkills(agentId: string): Promise<A2ASkill[]> {
  const res = await fetch(`${BASE}/agents/${agentId}/.well-known/agent-card.json`, {
    credentials: 'include',
  })
  if (!res.ok) return []
  const card = await res.json()
  return Array.isArray(card?.skills) ? (card.skills as A2ASkill[]) : []
}
/* 원격 에이전트 연결(스펙 057 — A2A 단일화) — URL 하나를 보내면 백엔드가 카드를 fetch·검증하고
   my-agents 확장 유무로 source(code=배포한 SDK / external=제3자)를 자동분류한다. 등록 진입점 단일.
   (구 registerCodeAgent `/agents/register`·registerExternalAgent `/agents/external`를 대체.) */
export const connectAgent = (url: string, token?: string) =>
  post('/agents/connect', { url, token: token || undefined }) as Promise<Agent>
export const resyncAgent = (id: string) => post(`/agents/${id}/resync`) as Promise<Agent>

/* ---------- 에이전트 전용 메모리 큐레이션 (스펙 029) ---------- */
export const addAgentMemory = (id: string, text: string) =>
  post(`/agents/${id}/memory`, { text })
export const updateAgentMemory = (id: string, memId: string, text: string) =>
  patch(`/agents/${id}/memory/${memId}`, { text })
export const deleteAgentMemory = (id: string, memId: string) =>
  del(`/agents/${id}/memory/${memId}`)

/* ---------- 유저 메모리 큐레이션 (스펙 030) — user_id 축, 교정 전용(add 없음) ---------- */
export const updateUserMemory = (userId: string, memId: string, text: string) =>
  patch(`/memory/user/${encodeURIComponent(userId)}/${encodeURIComponent(memId)}`, { text })
export const deleteUserMemory = (userId: string, memId: string) =>
  del(`/memory/user/${encodeURIComponent(userId)}/${encodeURIComponent(memId)}`)

/* ---------- 메모리 회상 시험 (스펙 084) — 챗과 같은 코어 memory.search 직접 호출 ---------- */
export interface MemoryHit {
  type: string
  text: string
  score: number // 내림차순(1.0=가장 관련)
  scope: string // 매치된 축(agent_id/user_id/run_id)
}
export interface MemorySearchDiag {
  configured: boolean // mem_cfg에 llm·embedder 둘 다
  backendReady: boolean // 백엔드 초기화 성공
  embedderModel: string | null
  llmModel: string | null
  error: string | null // 미설정/초기화실패/검색예외(정제·마스킹). 정상이면 null
  scope: string
  count: number
  stored?: number | null // 스코프 저장 건수(스펙 158) — 저장>0인데 회상 0이면 유사도/임베더 문제
}
export interface MemorySearchOut {
  query: string
  limit: number
  enabled: boolean // false=메모리 미구성/비활성(빈 results와 구분)
  results: MemoryHit[]
  diag?: MemorySearchDiag | null // 진단(스펙 125) — "왜 0건/실패인지"
}
export const searchAgentMemory = (id: string, query: string, limit: number) =>
  post(`/agents/${id}/memory/search`, { query, limit }) as Promise<MemorySearchOut>
export const searchUserMemory = (userId: string, query: string, limit: number) =>
  post(`/memory/user/${encodeURIComponent(userId)}/search`, { query, limit }) as Promise<MemorySearchOut>
/* 기억 페이지 목록(스펙 127) — 서버 페이지네이션 + 부분일치(q). enabled=false=미구성(0건과 구분). */
export interface MemoryPageItem {
  id: string
  text: string
  created_at: string | null
  updated_at: string | null
}
export interface MemoryPageOut {
  items: MemoryPageItem[]
  total: number // q 적용 후 전체 건수
  limit: number
  offset: number
  enabled: boolean
}
const pageQS = (q: string, limit: number, offset: number) =>
  `?limit=${limit}&offset=${offset}` + (q ? `&q=${encodeURIComponent(q)}` : '')
export const pageUserMemory = (userId: string, q: string, limit: number, offset: number) =>
  j<MemoryPageOut>(`/memory/user/${encodeURIComponent(userId)}/page${pageQS(q, limit, offset)}`)
export const pageAgentMemory = (id: string, q: string, limit: number, offset: number) =>
  j<MemoryPageOut>(`/agents/${id}/memory/page${pageQS(q, limit, offset)}`)

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
/** 기본 모델 지정(스펙 150) — 같은 kind의 기존 기본은 서버가 자동 해제. */
export const setDefaultModel = (id: string) => put(`/models/${id}/default`, {}) as Promise<Model>
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

/* ---------- 세션 / 승인 ---------- */
export interface SessionPage {
  items: Session[]
  total: number
  counts: Record<string, number> // 키 all|live|awaiting|error
}
// 서버 페이징·필터(스펙 034). status 버킷(all|live|awaiting|error) + limit/offset.
// agent_id(스펙 055): 외부 agent_id로 해당 에이전트 세션만 — Playground 세션 이어가기용.
// q(스펙 098): 메타데이터 검색 — session_id·user_id·agent_name 부분일치(서버측, status와 AND).
/* 세션 종료(스펙 129) — status→completed. 소유권은 서버 스코프(_own_scope)가 강제. 응답=갱신된 세션. */
export const endSession = (id: string) => post(`/sessions/${id}/end`) as Promise<Session>
export const listSessions = (params?: {
  status?: string
  agent_id?: string
  q?: string
  limit?: number
  offset?: number
}) => {
  const qp = new URLSearchParams()
  if (params?.status) qp.set('status', params.status)
  if (params?.agent_id) qp.set('agent_id', params.agent_id)
  if (params?.q?.trim()) qp.set('q', params.q.trim())
  if (params?.limit != null) qp.set('limit', String(params.limit))
  if (params?.offset != null) qp.set('offset', String(params.offset))
  const qs = qp.toString()
  return j<SessionPage>(`/sessions${qs ? `?${qs}` : ''}`)
}
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
export interface MessageFeedback {
  rating: 'up' | 'down'
  reason: string
}
export interface SessionMessage {
  id?: string // 스펙 209 — 피드백 부착 대상(구 응답엔 없을 수 있음)
  role: string
  content: string
  trace: Record<string, unknown> | null
  feedback?: MessageFeedback | null // 스펙 209 — 요청 사용자의 이 메시지 피드백
}
export const getSessionMessages = (sessionId: string) =>
  j<SessionMessage[]>(`/sessions/${sessionId}/messages`)
// 스펙 209 — 응답 피드백 upsert/취소(세션 소유자만·assistant 메시지만, 서버가 게이트).
export const setMessageFeedback = (sessionId: string, messageId: string, rating: 'up' | 'down', reason = '') =>
  put(`/sessions/${sessionId}/messages/${messageId}/feedback`, { rating, reason }) as Promise<MessageFeedback>
export const clearMessageFeedback = (sessionId: string, messageId: string) =>
  del(`/sessions/${sessionId}/messages/${messageId}/feedback`)
export const listApprovals = (status?: string) =>
  j<Approval[]>(`/approvals${status ? `?status=${encodeURIComponent(status)}` : ''}`)
export const resolveApproval = (id: string, decision: 'approve' | 'reject') =>
  post(`/approvals/${id}/resolve`, { decision }) as Promise<Approval>

/* ---------- 채팅 SSE ---------- */
export interface ChatFormField {
  key: string
  label?: string
  candidates?: string[]
  required?: boolean
}

export interface ChatFormFrame {
  fields: ChatFormField[]
  prefill: Record<string, string>
  note?: string
}

export interface ChatArtifact {
  kind: string
  data: Record<string, unknown>
  raw?: string | null
}

export interface ChatCallbacks {
  onToken: (t: string) => void
  onSession?: (sessionId: string) => void
  onTrace?: (trace: Record<string, unknown>) => void
  // 위험 도구가 그래프를 멈춰 승인 대기 프레임({text, approval, approver})이 오면 승인 id를 넘긴다(179).
  // 요청자 UI가 이 id로 승인 상태를 폴링해, 해소되면 재개 결과를 세션에서 불러온다(라이브 push 부재 보완).
  // approver(admin/self, 스펙 180)로 대화 내 인라인 승인 가능 여부를 판정한다.
  onApproval?: (approvalId: string, approver?: string) => void
  // 산출물형 폼 프레임(스펙 188) — 채팅에 폼을 렌더하고, 제출은 streamChat의 form 파라미터로.
  onForm?: (formId: string, form: ChatFormFrame) => void
  // 산출물 완성 프레임(스펙 188) — 임베드 시 JS 콜백이 받을 페이로드 그대로.
  onArtifact?: (artifact: ChatArtifact) => void
  // 저장된 assistant 메시지 id(스펙 209 P1.5) — 이 응답에 피드백(👍/👎)을 부착하기 위해.
  onMessageId?: (id: string) => void
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
    else if (event === 'message_id' && typeof parsed.id === 'string') cb.onMessageId?.(parsed.id)
    else if (typeof parsed.text === 'string') cb.onToken(parsed.text)
    else if (typeof parsed.session === 'string') cb.onSession?.(parsed.session)
    else if (typeof parsed.error === 'string') cb.onToken(`\n[오류] ${parsed.error}`)
    // 승인 대기 프레임은 text와 approval을 함께 실어 온다 — text는 위에서 토큰으로 표시하고,
    // approval id는 별도로 표면화(else-if 아님)해 요청자 폴링을 트리거한다(스펙 179).
    if (typeof parsed.approval === 'string')
      cb.onApproval?.(parsed.approval, typeof parsed.approver === 'string' ? parsed.approver : undefined)
    // 산출물형 프레임(스펙 188) — form(입력 요청)·artifact(완성 페이로드).
    if (parsed.form && typeof parsed.formId === 'string') cb.onForm?.(parsed.formId, parsed.form)
    if (parsed.artifact && typeof parsed.artifact.kind === 'string') cb.onArtifact?.(parsed.artifact)
  } catch {
    /* 비-JSON 프레임 무시 */
  }
  return false
}

/** A2A 서빙 프레임(스펙 155) 파서 — direct용 handleFrame과 형태가 달라 별도.
 * JSON-RPC message/stream: result.kind==="status-update" → status.message.parts[].text 델타,
 * final:true 또는 [DONE]에서 종료. error 프레임은 표면화. 세션/trace는 A2A가 안 준다(정직). */
function handleA2AFrame(frame: string, onToken: (t: string) => void): boolean {
  const dataLine = frame.split('\n').find((l) => l.startsWith('data: '))
  // 프레임에 `data:`가 없으면 SSE가 아니다 — 서버가 스트림 대신 평문 JSON-RPC error 바디를 준 경우
  // (루프 가드 -32000, 미지원 메서드 -32601 등은 dispatch 전에 평문으로 반환). 통째로 파싱해 표면화.
  const data = dataLine ? dataLine.slice(6) : frame.trim()
  if (!data) return false
  if (data === '[DONE]') return true
  try {
    const parsed = JSON.parse(data)
    const err = parsed.error
    if (err) {
      onToken(`\n[오류] ${typeof err === 'object' ? err.message ?? JSON.stringify(err) : err}`)
      return false
    }
    const result = parsed.result
    if (result && result.kind === 'status-update') {
      const parts = result.status?.message?.parts
      if (Array.isArray(parts)) {
        for (const p of parts) {
          if (p && p.kind === 'text' && typeof p.text === 'string' && p.text) onToken(p.text)
        }
      }
      if (result.final === true) return true
    }
  } catch {
    /* 비-JSON 프레임 무시 */
  }
  return false
}

/** A2A 경유 테스트(스펙 155) — 노출 에이전트(source∈{ui,code} + exposed.a2a)를 외부 소비자처럼
 * `/agents/{id}/a2a` JSON-RPC message/stream으로 호출한다. 단발 메시지 텍스트만 전달(세션/히스토리/
 * trace/오버라이드 없음 — 우리 A2A 서빙이 안 넘김). 인증은 direct와 동일(current_principal). */
export async function streamChatA2A(
  agentId: string,
  text: string,
  onToken: (t: string) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`${BASE}/agents/${agentId}/a2a`, {
    method: 'POST',
    credentials: 'include',
    headers: authHeaders(true),
    body: JSON.stringify({
      jsonrpc: '2.0',
      id: 1,
      method: 'message/stream',
      params: { message: { role: 'user', parts: [{ kind: 'text', text }] } },
    }),
    signal,
  })
  if (!res.ok) throw await httpError(res, 'POST', `/agents/${agentId}/a2a`)
  if (!res.body) throw new Error('A2A 테스트 실패: 응답 본문이 없습니다')

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
      if (handleA2AFrame(frame, onToken)) return
    }
  }
  if (buf.trim()) handleA2AFrame(buf, onToken)
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
  // 산출물형 폼 제출(스펙 188) — 대기 중 폼 프레임(formId)의 값. 텍스트 입력은 messages 그대로(이중 입력).
  form?: { formId: string; values: Record<string, string> },
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
      form,
    }),
    signal,
  })
  if (!res.ok) throw await httpError(res, 'POST', `/agents/${agentId}/chat`)
  if (!res.body) throw new Error('채팅 실패: 응답 본문이 없습니다')

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

/* ---------- 평가 (스펙 137, admin 전용) ---------- */
export interface EvalDataset {
  id: string
  name: string
  description: string | null
  kind: 'agent' | 'rag'
  collection_id?: string | null // 스펙 193 — RAG 문제집의 고정 컬렉션(실행 시 재선택 불필요)
  case_count: number
  can_manage?: boolean
  generating?: boolean // 스펙 193 — 문제 자동 생성 진행 중(스피너·Skeleton·폴링 신호)
}
export interface EvalAssert {
  type: 'trace_has' | 'trace_lacks' | 'output_contains' | 'no_error' | 'output_nonempty' | 'llm_judge' | 'rag_hits_gte' | 'rag_hits_lte' | 'rag_score_gte' | 'rag_score_lte' | 'rag_source_contains'
  arg?: string
}
export interface EvalCaseT {
  id: string
  dataset_id: string
  name: string
  input: string
  asserts: EvalAssert[]
  order_idx: number
}
export interface EvalRunT {
  id: string
  dataset_id: string
  dataset_name?: string | null
  agent_name: string | null
  model_name?: string | null
  group_id?: string | null
  status: 'running' | 'ok' | 'error'
  score: number | null
  passed: number
  total: number
  error: string | null
  started_at: string
  finished_at: string | null
  can_manage?: boolean
}
export interface EvalCaseResultT {
  case_name: string
  case_passed: boolean
  details: [string, boolean][]
  obs: { output?: string; trace_nodes?: string[]; error?: boolean; detail?: string; judge?: Record<string, { pass: boolean; reason: string }>; rag?: { hits: { score: number; filename: string; text: string }[]; top_score: number | null } } | null
}
export interface EvalRunDetail extends EvalRunT {
  results: EvalCaseResultT[]
}
export interface EvalDatasetPage { items: EvalDataset[]; total: number; any_generating: boolean }
export const listEvalDatasets = (params?: { q?: string; limit?: number; offset?: number }) =>
  j<EvalDatasetPage>(`/eval/datasets${pageQS(params?.q ?? '', params?.limit ?? 20, params?.offset ?? 0)}`)
export const getEvalDataset = (id: string) => j<EvalDataset>(`/eval/datasets/${id}`)
export const createEvalDataset = (body: { name: string; description?: string | null; kind?: string; collection_id?: string | null }) =>
  post('/eval/datasets', body) as Promise<EvalDataset>
export const deleteEvalDataset = (id: string) => del(`/eval/datasets/${id}`)
export const listEvalCases = (datasetId: string) => j<EvalCaseT[]>(`/eval/datasets/${datasetId}/cases`)
export const createEvalCase = (datasetId: string, body: { name?: string; input: string; asserts: EvalAssert[]; order_idx?: number }) =>
  post(`/eval/datasets/${datasetId}/cases`, body) as Promise<EvalCaseT>
export const updateEvalCase = (caseId: string, body: { name?: string; input: string; asserts: EvalAssert[]; order_idx?: number }) =>
  patch(`/eval/cases/${caseId}`, body) as Promise<EvalCaseT>
export const deleteEvalCase = (caseId: string) => del(`/eval/cases/${caseId}`)
export const startEvalRun = (
  datasetId: string,
  target: { agentId?: string; collectionId?: string; models?: string[] }
) =>
  post(`/eval/datasets/${datasetId}/runs`, {
    agent_id: target.agentId ?? null,
    collection_id: target.collectionId ?? null,
    models: target.models ?? [],
  }) as Promise<EvalRunT>
export const getEvalHelperStatus = () =>
  j<{ available: boolean; reason: string | null }>('/eval/helper-status')
export const suggestEvalCases = (datasetId: string, body: { agent_id?: string; count: number }) =>
  post(`/eval/datasets/${datasetId}/suggest-cases`, body) as Promise<EvalDataset>
// 스펙 209 Phase 2 — 피드백 수확: 미수확 수 조회 + 수확 트리거(에이전트 소유자/admin만)
export const getHarvestCount = (agentId: string) =>
  j<{ available: number; dataset_id: string | null }>(`/eval/harvest-count?agent_id=${encodeURIComponent(agentId)}`)
export const harvestFeedback = (agentId: string) =>
  post('/eval/datasets/harvest', { agent_id: agentId }) as Promise<EvalDataset>
export const generateEvalDataset = (body: { collection_id: string; name: string; count: number }) =>
  post('/eval/generate-dataset', body) as Promise<EvalDataset>
export const listEvalRunsByGroup = (groupId: string) =>
  j<EvalRunT[]>(`/eval/runs?group_id=${groupId}`)
export const listEvalRuns = (datasetId?: string) =>
  j<EvalRunT[]>(`/eval/runs${datasetId ? `?dataset_id=${datasetId}` : ''}`)
export const getEvalRun = (runId: string) => j<EvalRunDetail>(`/eval/runs/${runId}`)

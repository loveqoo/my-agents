/* 어드민 백엔드 API 클라이언트 (007 Phase 3).
   타입은 admin/mockData.ts와 일원화 — 백엔드 출력이 동일 shape다. */
import type { Agent, Approval, Audit, BlockCategory, PipelineNode, Session } from './admin/mockData'
import { httpError } from './httpError'

// 기본은 same-origin 상대경로 `/api` — vite dev 프록시(vite.config.ts)가 127.0.0.1:8000으로 넘긴다.
// 브라우저는 API 호스트를 모르므로 tailscale 도메인/IP/scheme가 바뀌어도 무설정 동작(CORS·mixed-content·cert 회피).
// 별도 호스트로 직접 붙고 싶을 때만 VITE_API_BASE로 절대 URL을 준다.
const BASE = import.meta.env.VITE_API_BASE ?? '/api'
// 인증은 세션 쿠키(fastapi-users, 스펙 031)가 기본 — same-origin이라 쿠키가 자동 동행한다.
// VITE_API_TOKEN은 머신 Bearer 토큰 하위호환용(헤드리스/E2E). 있으면 함께 보낸다.
const TOKEN = import.meta.env.VITE_API_TOKEN ?? ''

export type { Agent, Approval, Audit, BlockCategory, Session }

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

/* 파일첨부(스펙 404, A안) — 추출 결과를 클라이언트가 들고 있다가 전송 시 되보낸다(무상태). */
export interface ChatAttachmentDraft {
  filename: string
  text: string
  chars: number
  truncated: boolean
}

export async function uploadChatAttachment(file: File): Promise<ChatAttachmentDraft> {
  const fd = new FormData()
  fd.append('file', file)
  // FormData는 브라우저가 boundary 포함 Content-Type을 정한다 — 수동 지정 금지(hasBody=false).
  const res = await fetch(`${BASE}/chat/attachments`, {
    method: 'POST',
    credentials: 'include',
    headers: authHeaders(false),
    body: fd,
  })
  if (!res.ok) throw await httpError(res, 'POST', '/chat/attachments')
  return res.json()
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

/* ---------- 배경 잡 이벤트(SSE, 스펙 335) ---------- */
export interface IngestEvent {
  type: 'ingest'
  status: 'ready' | 'error'
  filename: string
  collection: string
  document_id: string
  collection_id: string
  chunks?: number
  error?: string
}
/** 전역 이벤트 스트림 구독 — EventSource(쿠키 동행·자동 재연결). 반환값 호출=구독 해제.
 *  이벤트는 알림이지 진실이 아니다(끊긴 동안 발생분 유실 — 상태의 진실은 문서 status).
 *  경계(codex 335): EventSource는 Authorization 헤더를 못 실어 **VITE_API_TOKEN 단독 모드에선
 *  알림만 미동작**(쿠키 로그인 UI는 정상, 나머지 기능 무영향 — 세션 만료 시 브라우저가 재시도를
 *  멈추고 재로그인 후 AdminShell 재마운트가 새로 구독). */
export function openEventStream(onEvent: (ev: IngestEvent) => void): () => void {
  const es = new EventSource(`${BASE}/events`, { withCredentials: true })
  es.onmessage = (m) => {
    try {
      onEvent(JSON.parse(m.data) as IngestEvent)
    } catch {
      /* 형식 밖 프레임 무시(heartbeat는 comment라 onmessage에 안 온다) */
    }
  }
  return () => es.close()
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
  checkpoint_ttl_hours: number | null
  checkpoint_cleanup_cron: string | null
  token_cleanup_cron: string | null
  approval_retention_days: number | null
  approval_cleanup_cron: string | null
  history_retention_days: number | null
  history_cleanup_cron: string | null
  memory_orphan_grace_days: number | null
  memory_cleanup_cron: string | null
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
export interface SchedulerStatus {
  mode: string
  leader: boolean
  jobs: { name: string; next_run_time: string | null }[]
  last_runs?: Record<string, string | null>
}
/** 배치 스케줄러 가동 상태(스펙 348) — 안 돌고 있으면 화면이 그렇게 말해야 한다(조용한 무동작 금지). */
export const getSchedulerStatus = () => j<SchedulerStatus>('/admin/batch/scheduler')
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
export type McpServerLite = { id: string; name: string; description?: string | null }
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
/* 도구 시험(스펙 326) — 등록 도구를 인자 넣어 실호출. 실행 경로=채팅과 동일(build_mcp_tools)이라
   결과/실패 사유가 채팅 표면과 같은 규칙(마스킹+캡, 스펙 320). 승인 정책 도구는 confirm 필수. */
export interface McpToolTestResult {
  ok: boolean
  ms: number
  result?: string | null
  error?: string | null
}
export const testMcpTool = (id: string, body: { tool: string; args: Record<string, unknown>; confirm?: boolean }) =>
  post(`/mcp-servers/${id}/test-tool`, body) as Promise<McpToolTestResult>
export const publishMcp = (id: string, published: boolean) =>
  put(`/mcp-servers/${id}/publish`, { published })

/* 카테고리별 생성/수정/삭제 (BlocksView). resource: prompts|memory-types|vector-tables */
export const createBlockItem = (resource: string, body: unknown) => post(`/${resource}`, body)
export const updateBlockItem = (resource: string, id: string, body: unknown) =>
  put(`/${resource}/${id}`, body)
export const deleteBlockItem = (resource: string, id: string) => del(`/${resource}/${id}`)

/* 프롬프트 스냅샷 동기화 (스펙 161) — 복사본 유지 + 명시적 반영. */
export interface PromptUsageAgent {
  id: string
  agentId: string
  name: string
  description?: string | null
  stale: boolean // 이 에이전트 스냅샷이 현재 프롬프트 본문과 다름
  canManage: boolean // 요청 주체가 이 에이전트를 갱신 가능
}
// 프롬프트 쪽: 이 프롬프트를 쓰는 에이전트 + 오래됨 상태.
export const listPromptAgents = (promptId: string) =>
  j<PromptUsageAgent[]>(`/prompts/${promptId}/agents`)
// 프롬프트 쪽: 선택 에이전트들에 최신 본문 반영.
export const applyPrompt = (promptId: string, agentIds: string[]) =>
  post(`/prompts/${promptId}/apply`, { agentIds }) as Promise<{ applied: string[]; skipped: string[] }>

/* ---------- 블록 버전 이력 (스펙 369) — 5종 공유 폴리모픽, append-only 불변 ---------- */
export interface BlockVersionRow {
  id: string
  kind: string
  block_pk: string
  version: number
  payload: Record<string, unknown>
  created_at?: string
  created_by?: string
}
export const listBlockVersions = (kind: string, blockPk: string) =>
  j<BlockVersionRow[]>(`/block-versions/${kind}/${blockPk}`)


/* ---------- RAG 컬렉션 + 문서 인제스트 (스펙 036) ---------- */
export interface Collection extends Audit {
  id: string
  name: string // 식별 이름(규칙, 스펙 148)
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
export interface RagDocument extends Audit {
  id: string
  collection_id: string
  filename: string
  content_type: string | null
  byte_size: number
  chunk_count: number
  status: string // parsing|embedding|ready|error
  error: string | null
  editable?: boolean // 스펙 331 — 런타임 수정 가능(문서형·비PDF·원본 보존)
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
/** 재인덱싱(스펙 312) — 임베딩 모델 교체(같은 차원)와/또는 청크 크기·겹침 재청킹. 준 필드만 변경.
    재인덱싱 중 컬렉션은 배타 잠금(다른 접근 409). 평가 이력은 보존. 서버가 완료까지 동기 처리. */
export const reindexCollection = (
  id: string,
  body: { embedding_model_id?: string; chunk_size?: number; chunk_overlap?: number },
) => post(`/collections/${id}/reindex`, body) as Promise<Collection>
export interface ReindexEvent {
  id: string
  collection_id: string
  from_model_name: string | null
  to_model_name: string | null
  from_chunk_size: number | null
  from_chunk_overlap: number | null
  to_chunk_size: number | null
  to_chunk_overlap: number | null
  chunk_count: number
  status: string // ok | error
  error: string | null
  owner_id: string | null
  created_at: string
}
/** 재인덱싱 이력(최신순, 스펙 312) — 모델·청크 정책 계보. */
export const listReindexEvents = (id: string) =>
  j<ReindexEvent[]>(`/collections/${id}/reindex-events`)
/* 문서 페이지 목록(스펙 128) — 문서는 증가 축이라 서버 페이지네이션 + 파일명 부분일치(q). */
export interface DocumentPageOut {
  items: RagDocument[]
  total: number
  processing: number // 컬렉션 전체 처리 중(parsing/embedding) 문서 수(스펙 334 — 폴링 신호)
}
export const listDocuments = async (id: string, q = '', limit = 20, offset = 0) => {
  const out = await j<DocumentPageOut>(`/collections/${id}/documents${pageQS(q, limit, offset)}`)
  // PagedListShell extra 채널로 전역 처리 중 신호 전달(현재 페이지에 안 보여도 폴링이 서게).
  return { ...out, extra: { processing: out.processing } }
}
export const deleteDocument = (id: string, docId: string) =>
  del(`/collections/${id}/documents/${docId}`)
/* 문서 런타임 수정(스펙 331) — 원문 조회 + 저장(그 문서만 재청킹, 변경 청크만 재임베딩). */
export interface DocumentContent {
  id: string
  filename: string
  editable: boolean
  text: string | null
  reason: string | null // editable=false 사유
}
export interface DocumentEditResult {
  document: RagDocument
  chunks: number // 재청킹 결과 청크 수
  reembedded: number // 새로 임베딩(내용 변경분)
  reused: number // 기존 벡터 재사용(내용 동일)
}
export const getDocumentContent = (id: string, docId: string) =>
  j<DocumentContent>(`/collections/${id}/documents/${docId}/content`)
export const updateDocumentContent = (id: string, docId: string, text: string) =>
  put(`/collections/${id}/documents/${docId}/content`, { text }) as Promise<DocumentEditResult>
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

/* ---------- 노드 라이브러리 (스펙 316) — 노드형 파이프라인의 재사용 노드 ----------
   등록 노드는 (name, version) 단위 불변 — 수정=새 버전 발행(update 라우트 없음).
   에이전트 nodes[]가 {ref:{name,version}}으로 버전 핀 고정 참조. 참조 중인 버전 삭제는 409. */
export interface NodeTemplateGroup {
  name: string
  kind: string // "config"(폼 저작) | "code"(스펙 317 — 코드 배포로만 발행·삭제)
  description: string | null
  latestVersion: number
  versionCount: number
  usedByCount: number
}
export interface NodeTemplateVersion {
  id: string
  version: number
  kind: string
  description: string | null
  config: PipelineNode // 에이전트 노드와 동일 화이트리스트(_normalize_node)로 검증된 형태. 코드 노드(스펙 317)는 {impl, overridable}
  created_at: string | null
  usedBy: string[] // 이 버전을 참조하는 에이전트 이름들(요청 주체 가시 범위)
  usedByHidden: number // 가시 범위 밖 참조 에이전트 수(스펙 317) — 0 아니면 "외 N개(비공개)" 표기
}
export interface NodeTemplateDetail {
  name: string
  versions: NodeTemplateVersion[] // 최신 버전 먼저
}
export const listNodeTemplates = () => j<NodeTemplateGroup[]>('/node-templates')
export const getNodeTemplate = (name: string) =>
  j<NodeTemplateDetail>(`/node-templates/${encodeURIComponent(name)}`)
/** 새 이름이면 v1, 기존 이름이면 다음 버전 자동 발행. 검증 위반은 422(detail 한국어). */
export const createNodeTemplate = (body: { name: string; description?: string | null; config: PipelineNode }) =>
  post('/node-templates', body) as Promise<NodeTemplateVersion>
/** 참조 에이전트가 있으면 409 + detail에 에이전트 이름 목록. */
export const deleteNodeTemplateVersion = (name: string, version: number) =>
  del(`/node-templates/${encodeURIComponent(name)}/${version}`)

/* ---------- 에이전트 ---------- */
export const listAgents = () => j<Agent[]>('/agents')
// 버전 운영 집계(스펙 244) — 버전별 평가·자동 회귀·피드백.
export interface VersionOps { evalRuns: number; lastScore: number | null; lastRunAt: string | null; autoRuns: number; errorRuns: number; up: number; down: number }
export interface AgentOps { versions: Record<string, VersionOps>; unversionedUp: number; unversionedDown: number }
// 단건 상세(스펙 370) — stalePins(채택 배지)는 단건 GET만 계산(목록 무비용 유지).
export const getAgent = (id: string) => j<Agent>(`/agents/${id}`)
export const getAgentOps = (id: string) => j<AgentOps>(`/agents/${id}/ops`)
/* 실행 방식 메타(스펙 206) — consumes: 이 impl이 읽는 설정 표면(null=미선언, 폼 전부 노출). */
export interface ImplMeta { key: string; consumes: string[] | null }
export const listAgentImpls = () => j<ImplMeta[]>('/agent-impls')
export const createAgent = (name: string, config: unknown, description?: string | null) =>
  post('/agents', { name, description: description ?? null, config }) as Promise<Agent>
export const updateAgent = (id: string, name: string, config: unknown, description?: string | null) =>
  // description: undefined=미변경(백엔드 None), ''=비우기 — 폼은 항상 현재값을 보낸다(스펙 210)
  put(`/agents/${id}`, { name, description: description === undefined ? null : description, config }) as Promise<Agent>
export const deleteAgent = (id: string) => del(`/agents/${id}`)
/* 복제 — 기존 설정을 새 ui 초안으로 복사(저마찰 재사용, 스펙 120). 복제자가 소유. */
export const cloneAgent = (id: string) => post(`/agents/${id}/clone`) as Promise<Agent>
/** 공개/비공개 전환(스펙 154 — 승격/강등). 강등 시 A2A 자동 off. */
export const setAgentVisibility = (id: string, isPublic: boolean) =>
  put(`/agents/${id}/visibility`, { public: isPublic }) as Promise<Agent>
export const activateVersion = (id: string, version: string) =>
  post(`/agents/${id}/activate`, { version }) as Promise<Agent>
/* 블록 새 버전 채택(스펙 370) — 오픈 버전 config 그대로 pins만 head로 재freeze한 스크래치 생성. */
export const adoptAgent = (id: string) => post(`/agents/${id}/adopt`) as Promise<Agent>
export const exposeAgent = (id: string, a2a: boolean) =>
  put(`/agents/${id}/expose`, { a2a }) as Promise<Agent>

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
  // (스펙 324) type 필드 제거 — 백엔드가 항상 "semantic"만 실던 화석.
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
export interface Provider extends Audit {
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
export interface Model extends Audit {
  id: string
  name: string
  provider_id: string
  provider_name: string
  provider_kind: ProviderKind // provider.kind — mock 필터 등(스펙 218)
  base_url: string // provider에서 상속(읽기 전용 표시)
  model_id: string
  kind: 'chat' | 'embedding'
  is_default: boolean
  params: Record<string, unknown>
  capabilities?: Record<string, boolean> // 능력 선언(스펙 408) — streaming·thinking·vision
  meta: Record<string, unknown> // models.dev 카탈로그 파생(context·modalities·cost·caps) — 스펙 047 #7
}
export const listModels = (kind?: 'chat' | 'embedding') =>
  j<Model[]>(`/models${kind ? `?kind=${kind}` : ''}`)
/** 능력→설정 서술자(스펙 409·411 단일 정본) — 모델·에이전트·플그·노드 4화면이 이 목록으로 렌더.
 *  FE에 사본을 두지 않는다(FE/BE 드리프트 0 — 백엔드 agent.capabilities가 정본).
 *  스펙 411: 능력 사실(capabilities)과 파라미터(params, bool|number)를 분리 — params는 N-확장
 *  (temperature 등 숫자 파라미터도 여기 담긴다, kind로 렌더 분기). */
export interface CapabilityFact { cap: string; label: string; capDefault: boolean }
export interface ParamDescriptor {
  key: string; kind: 'bool' | 'number'; label: string; default: number | boolean
  wire: string; cap: string | null; min: number | null; max: number | null; step: number | null; isInt: boolean
  advanced: boolean // UI 고급 접기 축(스펙 412) — true면 Collapse 안(top_p·repetition_penalty 등).
}
export interface ModelDescriptors { capabilities: CapabilityFact[]; params: ParamDescriptor[] }
export const getCapabilityDescriptors = () => j<ModelDescriptors>('/models/capabilities/descriptors')
export const createModel = (body: unknown) => post('/models', body) as Promise<Model>
export const updateModel = (id: string, body: unknown) => put(`/models/${id}`, body) as Promise<Model> // 능력·설정 편집(스펙 408)
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
  counts: Record<string, number> // 키 all|live (스펙 324 — 죽은 버킷 awaiting/error 제거)
}
// 서버 페이징·필터(스펙 034). status 버킷(all|live) + limit/offset.
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
/** 승인 1건 조회(스펙 350) — 폴링을 O(전체 테이블)에서 O(1)로. 볼 수 없는 건 404(존재 비노출). */
export const getApproval = (approvalId: string) => j<Approval>(`/approvals/${approvalId}`)
export const listApprovals = (status?: string) =>
  j<Approval[]>(`/approvals${status ? `?status=${encodeURIComponent(status)}` : ''}`)
// 승인 페이지 목록(스펙 251) — {items,total}. status: pending=대기 큐, resolved=처리 내역.
export const listApprovalsPage = (status: 'pending' | 'resolved', q: string, limit: number, offset: number) =>
  j<{ items: Approval[]; total: number }>(
    `/approvals/page?status=${status}&q=${encodeURIComponent(q)}&limit=${limit}&offset=${offset}`,
  )
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
  // 사고 과정(reasoning_content, 스펙 410) — 본문과 분리된 side channel. 델타로 다회 누적.
  // node(스펙 413) — 노드형에서 어느 노드의 사고인지(langgraph_node). 노드별 ThoughtChain 분리에 사용.
  onReasoning?: (t: string, node?: string) => void
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
  // 턴 논리 완료([DONE]) — 스펙 314: 스트림은 이후에도 열려 있을 수 있어(백그라운드 기억 저장 완료
  // 이벤트 대기), 스피너 해제 등 '완료' 처리는 이 콜백으로 한다(스트림 종료가 아님).
  onDone?: () => void
  // 백그라운드 자동 기억 저장 완료(스펙 314) — done 뒤 트레일링. mid로 그 턴을 조용히 패치.
  onMemory?: (mid: string, memorySaved: unknown) => void
}

function handleFrame(frame: string, cb: ChatCallbacks): boolean {
  const lines = frame.split('\n')
  const event = lines.find((l) => l.startsWith('event: '))?.slice(7)
  const dataLine = lines.find((l) => l.startsWith('data: '))
  if (!dataLine) return false
  const data = dataLine.slice(6)
  // 스펙 314: [DONE]은 '턴 논리 완료'일 뿐 스트림 종료가 아니다 — 이후 트레일링 event: memory가 올 수
  // 있어 계속 읽는다(리더는 서버가 스트림을 닫을 때/abort 시 끝난다). 완료 처리는 onDone로.
  if (data === '[DONE]') {
    cb.onDone?.()
    return false
  }
  try {
    const parsed = JSON.parse(data)
    if (event === 'trace') cb.onTrace?.(parsed)
    else if (event === 'memory' && typeof parsed.mid === 'string') cb.onMemory?.(parsed.mid, parsed.memorySaved)
    else if (event === 'message_id' && typeof parsed.id === 'string') cb.onMessageId?.(parsed.id)
    else if (typeof parsed.text === 'string') cb.onToken(parsed.text)
    else if (typeof parsed.session === 'string') cb.onSession?.(parsed.session)
    else if (typeof parsed.error === 'string') cb.onToken(`\n[오류] ${parsed.error}`)
    // 사고 과정(스펙 410) — 독립 if(else-if 아님, codex 410 P2): 복합 프레임에서 reasoning이
    // text/session을 가리지 않도록. node(스펙 413)=노드형 사고의 출처 노드(langgraph_node).
    if (typeof parsed.reasoning === 'string')
      cb.onReasoning?.(parsed.reasoning, typeof parsed.node === 'string' ? parsed.node : undefined)
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
  // 버전 지정 실행(스펙 242/243) — 미지정=활성(서빙) 버전. 관리 권한 필요(서버 403).
  version?: string,
  // 파일첨부(스펙 404) — 서버가 마지막 user 메시지에 경계 블록으로 주입(1회성).
  attachments?: { filename: string; text: string }[],
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
      version,
      attachments: attachments && attachments.length > 0 ? attachments : undefined,
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
  source_agent_pk?: string | null // 스펙 209 P2 — 수확 문제집의 출처 에이전트(실행 대상 고정)
  case_count: number
  can_manage?: boolean
  generating?: boolean // 스펙 193 — 문제 자동 생성 진행 중(스피너·Skeleton·폴링 신호)
}
export interface EvalAssert {
  type: 'trace_has' | 'trace_lacks' | 'output_contains' | 'no_error' | 'output_nonempty' | 'llm_judge' | 'rag_hits_gte' | 'rag_hits_lte' | 'rag_score_gte' | 'rag_score_lte' | 'rag_source_contains' | 'rag_meta_contains'
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
  agent_version?: string | null // 실행 시점 활성 버전(스펙 240) — null=과거 런(미기록)
  env?: Record<string, unknown> | null // 경량 환경 기록(스펙 240, 진단용)
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
export const listEvalDatasets = (params?: { q?: string; kind?: 'agent' | 'rag'; limit?: number; offset?: number }) =>
  j<EvalDatasetPage>(
    `/eval/datasets${pageQS(params?.q ?? '', params?.limit ?? 20, params?.offset ?? 0)}${params?.kind ? `&kind=${params.kind}` : ''}`,
  )
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
  target: { agentId?: string; collectionId?: string; models?: string[]; agentVersion?: string }
) =>
  post(`/eval/datasets/${datasetId}/runs`, {
    agent_id: target.agentId ?? null,
    collection_id: target.collectionId ?? null,
    models: target.models ?? [],
    // 버전 지정 평가(스펙 242) — null=활성(서빙) 버전.
    agent_version: target.agentVersion ?? null,
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
export const listEvalRunsByGroup = (groupId: string) =>
  j<EvalRunT[]>(`/eval/runs?group_id=${groupId}`)
export const listEvalRuns = (datasetId?: string) =>
  j<EvalRunT[]>(`/eval/runs${datasetId ? `?dataset_id=${datasetId}` : ''}`)
export const getEvalRun = (runId: string) => j<EvalRunDetail>(`/eval/runs/${runId}`)

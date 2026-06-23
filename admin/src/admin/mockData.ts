/* Admin 콘솔 데모 데이터.
   handoff 번들 ui_kits/admin/adminData.js를 타입 포함해 그대로 이식.
   빌딩 블록(페르소나·메모리·벡터테이블·권한·MCP), 그 블록으로 조립한 에이전트,
   라이브 세션, 승인 큐, 각종 상태맵. 모두 mock(데모 데이터)이며 뷰에서 useState로
   복제해 조작한다. 실제 백엔드 연결은 이후 루프에서 점진적으로. */

/* ---------- 타입 ---------- */
export interface AgentConfig {
  model?: string
  persona?: string
  memories?: string[]
  historyDepth?: number
  persistHistory?: boolean
  vectorTables?: string[]
  permissions?: string[]
  mcps?: string[]
}
export interface VersionMeta {
  version: string
  status: 'draft' | 'active' | 'archived'
  createdAt: string
  note: string
  config?: AgentConfig
}
export interface BlockItem {
  id: string
  name: string
  usedBy: number
  updated: string
  body?: string
  /* persona */ tone?: string
  /* memory/permission */ scope?: string
  /* embedding */ model?: string
  source?: string
  dims?: number
  rows?: number
  status?: string
  /* permission */ approver?: string
  /* mcp */ transport?: string
  tools?: string[]
  enabledTools?: string[]
  published?: boolean
  endpoint?: string
  url?: string
  auth?: string
  activeVersion?: string
  versions?: VersionMeta[]
}
export interface BlockCategory {
  label: string
  icon: string
  color: string
  desc: string
  items: BlockItem[]
}
export interface Agent {
  id: string
  name: string
  agentId: string
  environments: string[]
  model: string
  status: 'online' | 'idle' | 'offline'
  persona: string
  memories: string[]
  historyDepth: number
  persistHistory?: boolean
  vectorTables: string[]
  permissions: string[]
  mcps: string[]
  exposed: { a2a: boolean }
  sessions: number
  created: string
  systemPrompt?: string
  activeVersion: string
  versions: VersionMeta[]
  /* ---- code-defined agent (source === 'code') ---- */
  source?: 'ui' | 'code'
  endpoint?: string
  token?: string
  runtime?: string
  repo?: string
  commit?: string
  registeredAt?: string
  lastSync?: string
}
export interface Session {
  id: string
  agentId: string
  agent: string
  channel: string
  status: 'active' | 'running' | 'awaiting' | 'draining' | 'idle' | 'error' | 'completed'
  turns: number
  started: string
  lastActivity: string
  tokens: number
  awaiting?: { permission: string; summary: string; checkpoint: string }
  error?: string
}
export interface Approval {
  id: string
  sessionId: string
  agentId: string
  agent: string
  permission: string
  action: string
  args: Record<string, unknown>
  summary: string
  requestedAt: string
  checkpoint: string
}
export interface StatusMeta {
  label: string
  color?: string
  tag: string
  icon?: string
  desc?: string
}

/* ---------- 빌딩 블록 ---------- */
export const BLOCKS: Record<string, BlockCategory> = {
  persona: {
    label: '페르소나', icon: 'smile', color: 'var(--magenta-6)',
    desc: '에이전트가 따르는 성격·말투 정의(재사용 가능).',
    items: [
      { id: 'ps-research', name: 'Methodical Researcher', tone: 'Rigorous · neutral', usedBy: 1, updated: '2d ago', body: 'Rigorous, source-driven, neutral. Prefer primary sources. Always cite. Lead with a one-line answer.' },
      { id: 'ps-senior', name: 'Strict Senior Engineer', tone: 'Direct · kind', usedBy: 1, updated: '5d ago', body: 'Direct, specific, kind. Flag correctness and security first, style last. Cite exact line numbers.' },
      { id: 'ps-sre', name: 'Calm SRE', tone: 'Unflappable', usedBy: 1, updated: '1w ago', body: 'Unflappable. Quantify before acting. Smallest safe step first. Confirm blast radius.' },
      { id: 'ps-secretary', name: 'Warm Secretary', tone: 'Friendly · proactive', usedBy: 1, updated: '3d ago', body: "Friendly, concise, proactive. Protect the user's time and focus. Confirm before sending." },
    ],
  },
  memory: {
    label: '메모리 타입', icon: 'bulb', color: 'var(--purple-6)',
    desc: '에이전트가 컨텍스트를 저장·검색하는 메모리 타입. 서로 배타적이지 않으며, 에이전트마다 여러 타입을 동시에 켤 수 있습니다.',
    items: [
      { id: 'mem-short', name: '단기(세션)', scope: 'Single session', usedBy: 4, updated: '1w ago', body: '현재 세션의 인-컨텍스트 윈도우. 세션이 끝나면 비워집니다. 영속성 없음.' },
      { id: 'mem-semantic', name: '장기·의미론적', scope: 'Cross-session', usedBy: 2, updated: '1w ago', body: '벡터 스토어. 매 턴 전에 의미적으로 유사한 메모리 top-k를 검색합니다. TTL 없음.' },
      { id: 'mem-episodic', name: '장기·일화적', scope: 'Rolling window', usedBy: 1, updated: '4d ago', body: '상호작용 이벤트 로그를 일 단위로 요약. 과거 대화·사건을 회상합니다.' },
      { id: 'mem-procedural', name: '절차적', scope: 'Cross-session', usedBy: 0, updated: '3d ago', body: '학습된 절차·선호·규칙을 누적. 반복 작업의 방법을 기억합니다.' },
    ],
  },
  embedding: {
    label: '벡터 테이블', icon: 'appstore', color: 'var(--cyan-7)',
    desc: '임베딩 모델로 특정 데이터를 벡터화해 만든 테이블(임베딩 데이터셋). 에이전트가 의미 검색으로 참조하는 지식 소스입니다. 에이전트마다 0개 이상 연결할 수 있습니다.',
    items: [
      { id: 'vt-product-titles', name: 'product_titles', model: 'text-embedding-3-large', source: 'products.title', dims: 3072, rows: 12840, status: 'synced', usedBy: 1, updated: '2h ago', body: '상품 테이블의 title 컬럼을 임베딩. 상품 의미 검색·추천에 사용.' },
      { id: 'vt-docs-kb', name: 'docs_kb', model: 'text-embedding-3-small', source: 'help_articles.body', dims: 1536, rows: 3204, status: 'synced', usedBy: 1, updated: '1d ago', body: '헬프센터 문서 본문을 청크 단위로 임베딩한 지식베이스. RAG 답변에 사용.' },
      { id: 'vt-tickets', name: 'support_tickets', model: 'voyage-3', source: 'tickets.summary', dims: 1024, rows: 58210, status: 'indexing', usedBy: 0, updated: '방금', body: '과거 지원 티켓 요약을 임베딩. 유사 사례 검색용. 현재 재색인 중.' },
      { id: 'vt-notes', name: 'team_notes', model: 'nomic-embed-text', source: 'notion.pages', dims: 768, rows: 941, status: 'stale', usedBy: 1, updated: '6d ago', body: '팀 노션 노트를 로컬 임베딩. 원본 변경분 미반영(stale) — 재동기화 필요.' },
    ],
  },
  permission: {
    label: '권한', icon: 'global', color: 'var(--geekblue-6)',
    desc: "에이전트에 부여되는 범위 한정 권한. 각 권한엔 승인자가 반드시 있습니다 — 사용자는 대화 중 인라인 확인, 관리자는 승인 큐로 라우팅(체크포인트에서 일시정지). 승인자를 지정하지 않으면 기본값은 '사용자' 승인입니다.",
    items: [
      { id: 'pm-web', name: 'web.search', scope: 'Network', approver: 'user', usedBy: 1, updated: '2w ago', body: 'Outbound web search via the configured provider.' },
      { id: 'pm-files-r', name: 'files.read', scope: 'Filesystem', approver: 'user', usedBy: 2, updated: '2w ago', body: 'Read-only access to whitelisted local paths.' },
      { id: 'pm-repo-r', name: 'repo.read', scope: 'Code', approver: 'user', usedBy: 1, updated: '1w ago', body: 'Read pull requests, files and diffs from connected repos.' },
      { id: 'pm-k8s-r', name: 'k8s.read', scope: 'Infra', approver: 'user', usedBy: 1, updated: '3d ago', body: 'Read-only cluster + workload inspection.' },
      { id: 'pm-cal-rw', name: 'calendar.rw', scope: 'Productivity', approver: 'user', usedBy: 1, updated: '3d ago', body: 'Read & write calendar events. Writes are confirmed inline by the user.' },
      { id: 'pm-mail-send', name: 'mail.send', scope: 'Productivity', approver: 'user', usedBy: 1, updated: '4d ago', body: "Send email on the user's behalf. Each send is confirmed inline by the user." },
      { id: 'pm-repo-merge', name: 'repo.merge', scope: 'Code', approver: 'admin', usedBy: 1, updated: '5d ago', body: 'Merge pull requests. Routed to an admin for approval before execution.' },
      { id: 'pm-k8s-write', name: 'k8s.write', scope: 'Infra', approver: 'admin', usedBy: 1, updated: '2d ago', body: 'Mutate cluster state (scale, restart, apply). Requires admin approval.' },
    ],
  },
  mcp: {
    label: 'MCP 서버', icon: 'thunderbolt', color: 'var(--cyan-7)',
    desc: 'Model Context Protocol 서버. 직접 운영하는 로컬 서버는 프로토콜로 공개할 수 있고, 외부에서 공개된 MCP는 URL로 등록할 수 있습니다.',
    items: [
      { id: 'mcp-tavily', name: 'tavily', transport: 'stdio', tools: ['search'], usedBy: 1, status: 'connected', updated: '1d ago', published: true, endpoint: 'mcp://my-agents.local/tavily' },
      { id: 'mcp-fs', name: 'filesystem', transport: 'stdio', tools: ['read', 'list'], usedBy: 2, status: 'connected', updated: '1d ago', published: false, endpoint: 'mcp://my-agents.local/filesystem' },
      { id: 'mcp-github', name: 'github', transport: 'http', tools: ['get_pr', 'get_file'], usedBy: 1, status: 'connected', updated: '2d ago', published: true, endpoint: 'mcp://my-agents.local/github' },
      { id: 'mcp-prom', name: 'prometheus', transport: 'http', tools: ['query'], usedBy: 1, status: 'connected', updated: '6h ago', published: false, endpoint: 'mcp://my-agents.local/prometheus' },
      { id: 'mcp-k8s', name: 'kubernetes', transport: 'http', tools: ['get'], usedBy: 1, status: 'degraded', updated: '6h ago', published: false, endpoint: 'mcp://my-agents.local/kubernetes' },
      { id: 'mcp-gcal', name: 'gcal', transport: 'http', tools: ['list', 'create'], usedBy: 1, status: 'connected', updated: '3d ago', published: false, endpoint: 'mcp://my-agents.local/gcal' },
      { id: 'mcp-gmail', name: 'gmail', transport: 'http', tools: ['search'], usedBy: 1, status: 'disconnected', updated: '3d ago', published: false, endpoint: 'mcp://my-agents.local/gmail' },
      { id: 'mcp-notion', name: 'notion', transport: 'http', tools: ['append'], usedBy: 1, status: 'connected', updated: '3d ago', published: true, endpoint: 'mcp://my-agents.local/notion' },
    ],
  },
}

/* ---------- 에이전트 ---------- */
export const ADMIN_AGENTS: Agent[] = [
  { id: 'research', name: 'Research Assistant', source: 'ui', agentId: 'agt_rsch_7f3a91', environments: ['sandbox', 'production'], model: 'claude-sonnet-4', status: 'online',
    persona: 'Methodical Researcher', memories: ['단기(세션)', '장기·의미론적'], historyDepth: 20, vectorTables: ['docs_kb', 'product_titles'],
    permissions: ['web.search', 'files.read'], mcps: ['tavily', 'filesystem'],
    exposed: { a2a: true }, sessions: 2, created: '2026-05-30',
    activeVersion: 'v3', versions: [
      { version: 'v3', status: 'active', createdAt: '2026-06-12', note: 'Tightened citation rules' },
      { version: 'v2', status: 'archived', createdAt: '2026-06-04', note: 'Added filesystem MCP' },
      { version: 'v1', status: 'archived', createdAt: '2026-05-30', note: 'Initial' },
    ] },
  { id: 'reviewer', name: 'Code Reviewer', source: 'ui', agentId: 'agt_rvw_2b91c4', environments: ['sandbox', 'production'], model: 'gpt-4o', status: 'online',
    persona: 'Strict Senior Engineer', memories: ['단기(세션)'], historyDepth: 10, vectorTables: [],
    permissions: ['repo.read', 'repo.merge'], mcps: ['github', 'filesystem'],
    exposed: { a2a: true }, sessions: 1, created: '2026-06-02',
    activeVersion: 'v2', versions: [
      { version: 'v3', status: 'draft', createdAt: '2026-06-19', note: 'Trial: auto-merge on green CI' },
      { version: 'v2', status: 'active', createdAt: '2026-06-09', note: 'Added repo.merge (admin-gated)' },
      { version: 'v1', status: 'archived', createdAt: '2026-06-02', note: 'Initial' },
    ] },
  { id: 'ops', name: 'Ops Copilot', source: 'ui', agentId: 'agt_ops_5c0833', environments: ['sandbox'], model: 'claude-haiku-4', status: 'idle',
    persona: 'Calm SRE', memories: [], historyDepth: 6, vectorTables: [],
    permissions: ['k8s.read', 'k8s.write'], mcps: ['prometheus', 'kubernetes'],
    exposed: { a2a: false }, sessions: 0, created: '2026-06-10',
    activeVersion: 'v1', versions: [
      { version: 'v1', status: 'active', createdAt: '2026-06-10', note: 'Initial' },
    ] },
  { id: 'secretary', name: 'Personal Secretary', source: 'ui', agentId: 'agt_sec_9d4417', environments: ['sandbox', 'production'], model: 'claude-sonnet-4', status: 'online',
    persona: 'Warm Secretary', memories: ['단기(세션)', '장기·일화적', '절차적'], historyDepth: 40, vectorTables: ['team_notes'],
    permissions: ['calendar.rw', 'mail.send'], mcps: ['gcal', 'gmail', 'notion'],
    exposed: { a2a: false }, sessions: 1, created: '2026-06-15',
    activeVersion: 'v2', versions: [
      { version: 'v2', status: 'active', createdAt: '2026-06-16', note: 'Warmer tone' },
      { version: 'v1', status: 'archived', createdAt: '2026-06-15', note: 'Initial' },
    ] },
  /* 코드 정의 에이전트 — SDK로 빌드해 코드베이스에서 배포한 뒤, 엔드포인트 URL + 토큰으로
     콘솔에 등록한다. 구성은 실행 중인 배포가 보고(REPORTED)하므로 여기서는 읽기 전용이며,
     버전은 git 배포(commit)다. */
  { id: 'translator', name: 'Doc Translator', source: 'code', agentId: 'agt_xlt_a17c33', environments: ['production'], model: 'claude-sonnet-4', status: 'online',
    persona: '코드 정의 (SDK)', memories: ['단기(세션)'], historyDepth: 10, vectorTables: [],
    permissions: ['web.search', 'files.read'], mcps: ['tavily'],
    exposed: { a2a: true }, sessions: 1, created: '2026-06-18',
    endpoint: 'https://agents.acme.dev/doc-translator', token: 'sk_live_a3f••••••••91c2',
    runtime: 'my-agents-sdk · Python 2.4.1', repo: 'acme/doc-translator', commit: 'f3a91c2',
    registeredAt: '2026-06-18', lastSync: '12분 전',
    activeVersion: 'f3a91c2', versions: [
      { version: 'f3a91c2', status: 'active', createdAt: '2026-06-18', note: 'Deploy · 용어집 조회 추가' },
      { version: '9b22d01', status: 'archived', createdAt: '2026-06-14', note: 'Deploy · 초기 배포' },
    ] },
]

/* ---------- 상태맵 ---------- */
export const VERSION_STATUS: Record<string, StatusMeta> = {
  draft: { label: '초안', tag: 'gold', color: 'var(--gold-6)', desc: '임시 — 게시 전 테스트' },
  active: { label: '활성', tag: 'green', color: 'var(--color-success)', desc: '현재 서빙 중' },
  archived: { label: '보관', tag: 'default', color: 'var(--gray-6)', desc: '이전 버전 · 롤백용 보관' },
}
export const MCP_STATUS: Record<string, StatusMeta> = {
  connected: { tag: 'green', label: 'Connected' },
  degraded: { tag: 'gold', label: 'Degraded' },
  disconnected: { tag: 'red', label: 'Disconnected' },
}
export const SESSION_STATUS: Record<string, StatusMeta> = {
  active: { label: '활성', color: 'var(--color-success)', tag: 'green' },
  running: { label: '실행 중', color: 'var(--color-primary)', tag: 'blue' },
  awaiting: { label: '승인 대기', color: 'var(--purple-6)', tag: 'purple' },
  draining: { label: '드레이닝', color: 'var(--volcano-6)', tag: 'volcano' },
  idle: { label: '유휴', color: 'var(--gold-6)', tag: 'gold' },
  error: { label: '오류', color: 'var(--color-error)', tag: 'red' },
  completed: { label: '완료', color: 'var(--gray-6)', tag: 'default' },
}
export const VECTOR_STATUS: Record<string, StatusMeta> = {
  synced: { label: '동기화됨', tag: 'green' },
  indexing: { label: '재색인 중', tag: 'blue' },
  stale: { label: '갱신 필요', tag: 'gold' },
}
export const APPROVER: Record<string, StatusMeta> = {
  user: { label: '사용자', tag: 'blue', icon: 'user', desc: '대화 중 사용자가 인라인 확인' },
  admin: { label: '관리자', tag: 'purple', icon: 'team', desc: '관리자 승인 큐로 라우팅' },
}
export const DEFAULT_APPROVER = 'user'
export const AGENT_STATUS: Record<string, StatusMeta> = {
  online: { label: '온라인', color: 'var(--color-success)', tag: 'green' },
  idle: { label: '유휴', color: 'var(--gold-6)', tag: 'gold' },
  offline: { label: '오프라인', color: 'var(--gray-6)', tag: 'default' },
}
/* 에이전트가 만들어진 출처. UI 구성(이 콘솔에서 블록으로 조립) vs Code 정의(SDK로 선언해
   코드베이스에서 배포, 엔드포인트로 등록). Code 에이전트는 여기서 읽기 전용 — 구성은 코드가 소유. */
export const AGENT_SOURCE: Record<string, StatusMeta> = {
  ui: { label: 'UI 구성', tag: 'default', icon: 'appstore', desc: '콘솔에서 빌딩 블록을 조합해 생성 · 편집 가능' },
  code: { label: 'Code', tag: 'geekblue', icon: 'code', desc: 'SDK로 정의해 코드베이스에서 배포 · 읽기 전용' },
}

/* ---------- 세션 ---------- */
export const ADMIN_SESSIONS: Session[] = [
  { id: 'sess-8f21', agentId: 'research', agent: 'Research Assistant', channel: 'debug-console', status: 'active', turns: 6, started: '14:02', lastActivity: 'just now', tokens: 18420 },
  { id: 'sess-7a05', agentId: 'research', agent: 'Research Assistant', channel: 'A2A · partner-x', status: 'idle', turns: 14, started: '11:40', lastActivity: '32m ago', tokens: 52110 },
  { id: 'sess-6c93', agentId: 'reviewer', agent: 'Code Reviewer', channel: 'github-webhook', status: 'awaiting', turns: 3, started: '13:55', lastActivity: 'paused 2m ago', tokens: 9240, awaiting: { permission: 'repo.merge', summary: 'Merge PR #482 into main', checkpoint: 'ckpt_6c93_07' } },
  { id: 'sess-5d77', agentId: 'secretary', agent: 'Personal Secretary', channel: 'web-chat', status: 'error', turns: 2, started: '09:18', lastActivity: '5h ago', tokens: 3110, error: 'gmail MCP disconnected' },
  { id: 'sess-4b10', agentId: 'research', agent: 'Research Assistant', channel: 'web-chat', status: 'completed', turns: 21, started: 'Yesterday', lastActivity: 'Yesterday', tokens: 74300 },
]

/* ---------- 승인 큐 ---------- */
export const ADMIN_APPROVALS: Approval[] = [
  { id: 'apr-3391', sessionId: 'sess-6c93', agentId: 'reviewer', agent: 'Code Reviewer', permission: 'repo.merge', action: 'github.merge_pr', args: { pr: 482, repo: 'my-agents', strategy: 'squash' }, summary: 'Merge PR #482 “Fix token refresh race” into main', requestedAt: '2m ago', checkpoint: 'ckpt_6c93_07' },
  { id: 'apr-3388', sessionId: 'sess-9d22', agentId: 'ops', agent: 'Ops Copilot', permission: 'k8s.write', action: 'kubernetes.scale', args: { deployment: 'api', replicas: 8, namespace: 'prod' }, summary: 'Scale prod/api from 5 → 8 replicas', requestedAt: '9m ago', checkpoint: 'ckpt_9d22_03' },
]

/* ---------- 후처리 (adminData.js의 IIFE들) ---------- */

/* source 기본값 보정 — 명시 안 된 에이전트는 UI 구성으로 간주. (스냅샷 루프보다 먼저) */
ADMIN_AGENTS.forEach((a) => {
  if (!a.source) a.source = 'ui'
})

/* 모든 에이전트 버전에 편집 가능한 config 스냅샷을 붙인다.
   에이전트의 top-level 필드 = 활성 버전의 config. 다른 버전은 복사본을 스냅샷한다. */
ADMIN_AGENTS.forEach((a) => {
  const snap: AgentConfig = {
    model: a.model, persona: a.persona, memories: [...a.memories], historyDepth: a.historyDepth,
    vectorTables: [...(a.vectorTables || [])], permissions: [...a.permissions], mcps: [...a.mcps],
  }
  a.versions.forEach((v) => {
    if (!v.config) v.config = { ...snap, permissions: [...(snap.permissions || [])], mcps: [...(snap.mcps || [])] }
  })
})
/* reviewer 초안에 실제 diff를 줘서 Test/Activate가 의미를 갖게. */
;(() => {
  const rev = ADMIN_AGENTS.find((a) => a.id === 'reviewer')
  const d = rev && rev.versions.find((v) => v.status === 'draft')
  if (d) d.config = { ...d.config, memories: ['단기(세션)', '장기·의미론적'], permissions: ['repo.read', 'repo.merge'] }
})()

/* MCP 서버는 draft/activate 아티팩트가 아니라 외부 연결 — enabledTools/source 기본값 부여. */
BLOCKS.mcp.items.forEach((m) => {
  if (!m.enabledTools) m.enabledTools = [...(m.tools || [])]
  if (!m.source) m.source = 'local'
})
BLOCKS.mcp.items.push(
  { id: 'mcp-ext-weather', name: 'acme-weather', source: 'external', transport: 'http', url: 'mcp://acme.io/weather', tools: ['forecast', 'current'], enabledTools: ['forecast', 'current'], usedBy: 0, status: 'connected', updated: '4h ago', auth: 'Bearer ****', published: false },
  { id: 'mcp-ext-crm', name: 'partner-crm', source: 'external', transport: 'http', url: 'mcp://partner.example.com/crm', tools: ['lookup', 'create_lead'], enabledTools: ['lookup'], usedBy: 1, status: 'degraded', updated: '1d ago', auth: 'OAuth', published: false },
)

/* 승인자 기본값 보정. */
BLOCKS.permission.items.forEach((p) => {
  if (!p.approver) p.approver = DEFAULT_APPROVER
})

/* 사이더 "승인" 배지 카운트. */
export const PENDING_APPROVALS = ADMIN_APPROVALS.length

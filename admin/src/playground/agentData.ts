/* my-agents — debug console data.
   Agents built in the service (persona + memory policy + permissions + MCP),
   each with a resolved system prompt. Conversation turns carry a full trace:
   the prompt used, retrieved memories, MCP tool calls, and the LangGraph path. */

export interface DebugAgent {
  id: string
  name: string
  model: string
  status: 'online' | 'idle' | 'offline'
  persona: string
  memories: string[]
  permissions: string[]
  mcps: string[]
  exposed: { a2a: boolean; mcp: boolean }
  systemPrompt: string
}

export interface Memory {
  type: 'semantic' | 'episodic' | 'procedural' | string
  text: string
  score: number
}

export interface McpCallT {
  server: string
  tool: string
  status: 'ok' | 'error' | string
  ms: number
  args: Record<string, unknown>
  result: string
}

export interface GraphNode {
  node: string
  ms: number
}

export interface Trace {
  latencyMs: number
  tokens: { in: number; out: number }
  promptRef: string
  memories: Memory[]
  mcp: McpCallT[]
  graph: GraphNode[]
  resumedFrom?: string
}

export interface A2UIComponent {
  id: string
  componentType: string
  title?: string
  text?: string
  variant?: string
  label?: string
  placeholder?: string
  icon?: string
  children?: string[]
  value?: { path: string }
  options?: { label: string; value: string }[]
  action?: { name: string }
}

export interface SurfaceCmd {
  createSurface?: { surfaceId: string }
  updateComponents?: { root: string; components: A2UIComponent[] }
  updateDataModel?: { contents: { op: string; path: string; value: unknown }[] }
}

export type ChatMsg =
  | { role: 'me'; text: string }
  | { role: 'ai'; text: string; trace?: Trace }
  | {
      role: 'approval'
      id: string
      approver: 'user' | 'admin'
      permission: string
      tool: string
      args: Record<string, unknown>
      summary: string
      checkpoint: string
      state: 'pending' | 'routed' | 'approved' | 'rejected'
    }
  | {
      role: 'a2ui'
      id: string
      surface: SurfaceCmd[]
      state: 'open' | 'submitted'
      submitted?: Record<string, unknown>
    }

export const AGENTS: DebugAgent[] = [
  {
    id: 'research',
    name: '리서치 어시스턴트',
    model: 'claude-sonnet-4',
    status: 'online',
    persona: '체계적인 리서처',
    memories: ['단기(세션)', '장기·의미론적'],
    permissions: ['web.search', 'files.read'],
    mcps: ['tavily', 'filesystem'],
    exposed: { a2a: true, mcp: false },
    systemPrompt: `당신은 체계적인 리서치 에이전트 '리서치 어시스턴트'입니다.

# 페르소나
엄격하고 출처 중심이며 중립적. 1차 자료를 선호하고 항상 인용합니다.

# 도구
- tavily.search(query): 웹 검색
- filesystem.read(path): 로컬 노트 읽기

# 메모리
의미론적 장기 메모리가 켜져 있습니다. 답하기 전 관련된 이전 조사 내용을
검색하세요. 절대 인용을 지어내지 마세요.

# 출력
한 줄 답변으로 시작해 근거, 그다음 열린 질문 순으로 제시합니다.`,
  },
  {
    id: 'reviewer',
    name: '코드 리뷰어',
    model: 'gpt-4o',
    status: 'online',
    persona: '까다로운 시니어 엔지니어',
    memories: ['단기(세션)'],
    permissions: ['repo.read', 'repo.merge'],
    mcps: ['github', 'filesystem'],
    exposed: { a2a: true, mcp: true },
    systemPrompt: `당신은 까다로운 시니어 엔지니어 '코드 리뷰어'입니다.

# 페르소나
직설적이고 구체적이며 친절합니다. 정확성과 보안을 먼저, 스타일은 마지막에 지적합니다.

# 도구
- github.get_pr(id), github.get_file(path)
- filesystem.read(path)

# 규칙
정확한 줄 번호를 인용하고 구체적인 diff를 제안하세요. 이유 없는 트질은
금물. 정확성·보안 문제일 때만 차단합니다.`,
  },
  {
    id: 'ops',
    name: '운영 코파일럿',
    model: 'claude-haiku-4',
    status: 'idle',
    persona: '침착한 SRE',
    memories: ['단기(세션)', '장기·일화적'],
    permissions: ['k8s.read', 'k8s.write'],
    mcps: ['prometheus', 'kubernetes'],
    exposed: { a2a: false, mcp: true },
    systemPrompt: `당신은 침착한 사이트 신뢰성 엔지니어 '운영 코파일럿'입니다.

# 페르소나
동요하지 않고, 행동 전 정량화합니다. 가장 안전한 최소 단계부터.

# 도구
- prometheus.query(promql)
- kubernetes.get(resource)

# 규칙
상태를 변경하는 제안 전에는 영향 범위를 확인하세요. 읽기 전용 진단을
우선하고, 실행한 쿼리를 항상 보여주세요.`,
  },
  {
    id: 'secretary',
    name: '개인 비서',
    model: 'claude-sonnet-4',
    status: 'online',
    persona: '따뜻하고 꼼꼼한',
    memories: ['단기(세션)', '장기·일화적', '절차적'],
    permissions: ['calendar.rw', 'mail.send'],
    mcps: ['gcal', 'gmail', 'notion'],
    exposed: { a2a: false, mcp: false },
    systemPrompt: `당신은 따뜻하고 꼼꼼한 조력자 '개인 비서'입니다.

# 페르소나
친근하고 간결하며 적극적. 사용자의 시간과 집중을 지켝니다.

# 도구
- gcal.list/create, gmail.search, notion.append

# 규칙
생성이나 발송 전에 항상 확인합니다. 충돌을 알려주고, 하루 요약을
메모리에 지속적으로 유지합니다.`,
  },
]

/* Seed conversation for the Research Assistant, with per-turn traces. */
export const AGENT_SEED: Record<string, ChatMsg[]> = {
  research: [
    { role: 'me', text: 'LLM 앱을 위한 스트리밍 UI 패턴의 현재 흐름은 어때?' },
    {
      role: 'ai',
      text: "토큰 단위 스트리밍 렌더링이 이제 표준이며, 세 가지 패턴이 주도적입니다: 타이핑 커서가 있는 점진적 텍스트, 점진적 도구 호출 카드, 그리고 지연된 '사고' 접기.\n\n근거:\n• 대부분의 주요 채팅 UI는 SSE로 부분 토큰을 렌더링합니다.\n• 에이전트 UI는 점점 더 도구 호출을 실행 중에 인라인으로 보여줍니다.\n\n열린 질문: 중간 추론을 기본적으로 얼마나 노출할 것인가?",
      trace: {
        latencyMs: 2140,
        tokens: { in: 1284, out: 196 },
        promptRef: 'research',
        memories: [
          { type: 'semantic', text: '사용자는 명확한 TL;DR과 출처가 달린 답변을 선호함.', score: 0.91 },
          { type: 'semantic', text: '이전 조사: SSE가 토큰 스트리밍의 주요 전송 방식임.', score: 0.78 },
          { type: 'episodic', text: '지난 세션에서 에이전트 도구 호출 시각화를 다룰.', score: 0.64 },
        ],
        mcp: [
          {
            server: 'tavily',
            tool: 'search',
            status: 'ok',
            ms: 980,
            args: { query: 'LLM streaming UI patterns 2026', max_results: 5 },
            result: "결과 5건 · 최상위: 'Designing streaming chat interfaces'",
          },
          {
            server: 'filesystem',
            tool: 'read',
            status: 'ok',
            ms: 38,
            args: { path: '~/notes/ui-patterns.md' },
            result: '2.1 KB · 이전 노트 48줄',
          },
        ],
        graph: [
          { node: '__start__', ms: 0 },
          { node: 'retrieve_memory', ms: 120 },
          { node: 'plan', ms: 240 },
          { node: 'tools', ms: 1020 },
          { node: 'call_model', ms: 740 },
          { node: '__end__', ms: 20 },
        ],
      },
    },
  ],
  reviewer: [],
  ops: [],
  secretary: [],
}

/* ----- Human-in-the-loop (HIL) ------------------------------------------------
   Some agents hold permissions whose approver is "user" or "admin". When a prompt
   would trigger such an action, the LangGraph run hits interrupt(): it pauses,
   saves a checkpoint, and surfaces an approval request. A "user" approver is
   resolved inline (Approve/Reject in chat); an "admin" approver is routed to the
   admin console's approvals queue and the session simply waits. */
interface HilEntry {
  permission: string
  approver: 'user' | 'admin'
  tool: string
  triggers: string[]
  makeArgs: (p: string) => Record<string, unknown>
  summarize: (p: string) => string
}

export const AGENT_HIL: Record<string, HilEntry> = {
  secretary: {
    permission: 'mail.send',
    approver: 'user',
    tool: 'gmail.send',
    triggers: ['email', 'send', '메일', '보내'],
    makeArgs: (p) => ({ to: 'team@acme.com', subject: 'Re: ' + p.slice(0, 28), body: '(초안)…' }),
    summarize: () => 'team@acme.com으로 이메일 발송',
  },
  reviewer: {
    permission: 'repo.merge',
    approver: 'admin',
    tool: 'github.merge_pr',
    triggers: ['merge', 'approve pr', '병합'],
    makeArgs: () => ({ pr: 482, repo: 'my-agents', strategy: 'squash' }),
    summarize: () => 'PR #482를 main에 병합',
  },
  ops: {
    permission: 'k8s.write',
    approver: 'admin',
    tool: 'kubernetes.scale',
    triggers: ['scale', 'restart', 'deploy', '배포'],
    makeArgs: () => ({ deployment: 'api', replicas: 8, namespace: 'prod' }),
    summarize: () => 'prod/api 레플리카 5 → 8로 증설',
  },
}

let __ckptN = 10
export function nextCheckpoint(agentId: string): string {
  __ckptN += 1
  return `ckpt_${agentId}_${String(__ckptN).padStart(2, '0')}`
}

/* Build an A2UI command stream — the agent replying with generative UI instead of
   text. Here: a "schedule a meeting" form bound to a live data model. */
export function buildScheduleSurface(): SurfaceCmd[] {
  return [
    { createSurface: { surfaceId: 'schedule' } },
    {
      updateComponents: {
        root: 'root',
        components: [
          { id: 'root', componentType: 'Card', title: '회의 일정 잡기', children: ['hint', 'title', 'date', 'time', 'attendees', 'remind', 'submit'] },
          { id: 'hint', componentType: 'Text', variant: 'caption', text: '요청하신 내용으로 초안을 만들었어요 — 조정하고 확인해 주세요.' },
          { id: 'title', componentType: 'Field', label: '제목', children: ['titleF'] },
          { id: 'titleF', componentType: 'TextField', placeholder: '회의 제목', value: { path: '/form/title' } },
          { id: 'date', componentType: 'Field', label: '날짜', children: ['dateF'] },
          { id: 'dateF', componentType: 'DateField', value: { path: '/form/date' } },
          { id: 'time', componentType: 'Field', label: '시간', children: ['timeF'] },
          {
            id: 'timeF',
            componentType: 'Select',
            value: { path: '/form/time' },
            options: [
              { label: '오전 10:00', value: '10:00' },
              { label: '오후 2:00', value: '14:00' },
              { label: '오후 4:00', value: '16:00' },
            ],
          },
          { id: 'attendees', componentType: 'Field', label: '참석자', children: ['attF'] },
          { id: 'attF', componentType: 'TextField', placeholder: '쉼표로 구분한 이메일', value: { path: '/form/attendees' } },
          { id: 'remind', componentType: 'Checkbox', label: '하루 전 리마인더 보내기', value: { path: '/form/remind' } },
          { id: 'submit', componentType: 'Button', label: '확인 및 컬린더에 추가', icon: 'calendar', action: { name: 'confirmSchedule' } },
        ],
      },
    },
    {
      updateDataModel: {
        contents: [
          { op: 'add', path: '/form/title', value: '팀 싱크' },
          { op: 'add', path: '/form/date', value: '2026-06-24' },
          { op: 'add', path: '/form/time', value: '14:00' },
          { op: 'add', path: '/form/attendees', value: 'team@acme.com' },
          { op: 'add', path: '/form/remind', value: true },
        ],
      },
    },
  ]
}

export type PlanResult =
  | { type: 'a2ui'; surface: SurfaceCmd[] }
  | {
      type: 'interrupt'
      approver: 'user' | 'admin'
      permission: string
      tool: string
      args: Record<string, unknown>
      summary: string
      checkpoint: string
    }
  | { type: 'reply'; text: string; trace: Trace }

/* Decide what an incoming prompt does: a normal reply, an A2UI surface, or an interrupt. */
export function planAgent(agent: DebugAgent, prompt: string): PlanResult {
  const hil = AGENT_HIL[agent.id]
  const p = (prompt || '').toLowerCase()
  const a2uiTriggers = ['schedule', 'meeting', 'calendar', 'book', 'reserve', 'form', '예약', '일정', '회의']
  if (a2uiTriggers.some((t) => p.includes(t))) {
    return { type: 'a2ui', surface: buildScheduleSurface() }
  }
  if (hil && hil.triggers.some((t) => p.includes(t))) {
    return {
      type: 'interrupt',
      approver: hil.approver,
      permission: hil.permission,
      tool: hil.tool,
      args: hil.makeArgs(prompt),
      summary: hil.summarize(prompt),
      checkpoint: nextCheckpoint(agent.id),
    }
  }
  const r = runAgent(agent, prompt)
  return { type: 'reply', text: r.text, trace: r.trace }
}

interface InterruptInfo {
  approver: 'user' | 'admin'
  permission: string
  tool: string
  args: Record<string, unknown>
  summary: string
  checkpoint: string
}

/* Build the reply + trace produced when a paused run resumes from its checkpoint. */
export function resumeAgent(
  agent: DebugAgent,
  interruptInfo: InterruptInfo,
  decision: 'approve' | 'reject',
): { text: string; trace: Trace } {
  const base = runAgent(agent, interruptInfo.summary)
  if (decision === 'reject') {
    base.text =
      "알겠습니다 — '" +
      interruptInfo.summary +
      "' 작업은 실행하지 않겠습니다. " +
      interruptInfo.checkpoint +
      ' 체크포인트에서 중단되었고, 아무것도 실행되지 않았습니다.'
  } else {
    base.text =
      '승인되었습니다. ' +
      interruptInfo.checkpoint +
      '에서 재개해 ' +
      interruptInfo.tool +
      "을(를) 실행했습니다. '" +
      interruptInfo.summary +
      "' — 완료."
    base.trace.mcp = [
      {
        server: interruptInfo.tool.split('.')[0],
        tool: interruptInfo.tool.split('.')[1] || 'call',
        status: 'ok',
        ms: 320,
        args: interruptInfo.args,
        result: 'ok',
      },
    ]
  }
  base.trace.graph = [
    { node: 'resume', ms: 0 },
    { node: 'checkpoint_load', ms: 24 },
    ...(decision === 'approve' ? [{ node: 'tools', ms: 320 }] : []),
    { node: 'call_model', ms: 540 + Math.round(Math.random() * 300) },
    { node: '__end__', ms: 14 },
  ]
  base.trace.resumedFrom = interruptInfo.checkpoint
  base.trace.latencyMs = base.trace.graph.reduce((a, c) => a + c.ms, 0)
  return base
}

/* Fake an agent run: returns { text, trace } derived from the agent's config. */
export function runAgent(agent: DebugAgent, prompt: string): { text: string; trace: Trace } {
  const p = (prompt || '').toLowerCase()
  const memories: Memory[] = [
    { type: 'semantic', text: `"${prompt.slice(0, 36)}…"와 관련된 사용자 컨텍스트.`, score: 0.88 },
    { type: 'episodic', text: '이번 주의 관련 대화를 회상함.', score: 0.6 },
  ]
  const toolByServer: Record<string, string> = {
    tavily: 'search',
    filesystem: 'read',
    github: 'get_pr',
    prometheus: 'query',
    kubernetes: 'get',
    gcal: 'list',
    gmail: 'search',
    notion: 'append',
  }
  const mcp: McpCallT[] = (agent.mcps || []).slice(0, 2).map((server, i) => ({
    server,
    tool: toolByServer[server] || 'call',
    status: 'ok',
    ms: 120 + i * 260 + Math.round(Math.random() * 300),
    args:
      server === 'tavily'
        ? { query: prompt.slice(0, 40), max_results: 5 }
        : server === 'prometheus'
        ? { promql: 'rate(http_requests_total[5m])' }
        : { ref: prompt.slice(0, 24) },
    result: server === 'tavily' ? '5 results' : server === 'prometheus' ? '12 series' : 'ok',
  }))
  const graph: GraphNode[] = [
    { node: '__start__', ms: 0 },
    { node: 'retrieve_memory', ms: 90 + Math.round(Math.random() * 80) },
    ...(mcp.length ? [{ node: 'tools', ms: mcp.reduce((a, c) => a + c.ms, 0) }] : []),
    { node: 'call_model', ms: 600 + Math.round(Math.random() * 500) },
    { node: '__end__', ms: 15 },
  ]
  const text =
    p.includes('error') || p.includes('debug') || p.includes('오류') || p.includes('디버')
      ? '추적해 볼게요. 관련 컨텍스트를 검색하고 아래 도구를 호출했습니다 — 실패는 모델 호출 이전 단계일 가능성이 높아요. 정확한 경로는 인스펙터를 확인하세요.'
      : `오른쪽의 검색된 컨텍스트와 도구 결과를 근거로 한 제 의견입니다. 어느 단계든 더 파고들어달라고 하시면 펼쳐서 보여드릴게요.`
  return {
    text,
    trace: {
      latencyMs: graph.reduce((a, c) => a + c.ms, 0),
      tokens: { in: 800 + Math.round(Math.random() * 900), out: 120 + Math.round(Math.random() * 160) },
      promptRef: agent.id,
      memories,
      mcp,
      graph,
    },
  }
}

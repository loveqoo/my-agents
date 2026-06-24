/* my-agents — debug console shared types.
   The real backend streams chat tokens, a session id, and a final execution trace.
   These types describe the trace shape the Inspector renders, plus the simplified
   chat-message shape the playground keeps in state. (Mock data + the HIL/A2UI flows
   were removed when the console was wired to the real backend.) */

export interface Memory {
  type: 'semantic' | 'episodic' | 'procedural' | string
  text: string
  score: number
  // 이 기억이 회상된 스코프 축: 'user_id'(유저 장기) | 'run_id'(세션). 없으면 미상.
  scope?: 'user_id' | 'run_id' | string
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
  // 적용된 메모리 스코프(다층). None이 아닌 축만 담긴다: {user_id?, run_id?}.
  // user_id 있으면 유저 장기(세션 가로지름)+세션, 없으면 세션 한정.
  memoryScope?: { user_id?: string; run_id?: string }
}

export type ChatMsg = { role: 'me' | 'ai'; text: string; trace?: Trace }

/* my-agents — debug console shared types.
   The real backend streams chat tokens, a session id, and a final execution trace.
   These types describe the trace shape the Inspector renders, plus the simplified
   chat-message shape the playground keeps in state. (Mock data + the HIL/A2UI flows
   were removed when the console was wired to the real backend.) */

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

export type ChatMsg = { role: 'me' | 'ai'; text: string; trace?: Trace }

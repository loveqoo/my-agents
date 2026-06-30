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
  // RAG 검색 도구가 반환한 히트 수(server='rag'일 때). 스펙 079.
  hits?: number
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
  // 회상에 쓴 쿼리(=user_text 에코) — 0건 회상이어도 "조회 이력"을 인스펙터에 남긴다. 스펙 079.
  memoryQuery?: string
  // 이 턴에 구성된 RAG 컬렉션명(도구 호출 여부와 무관하게 노출). 스펙 037/079.
  ragCollections?: string[]
  // 요청됐으나 해석 실패한 컬렉션명(조용히 비는 footgun을 드러냄). 스펙 079.
  ragUnresolved?: string[]
}

export type ChatMsg = { role: 'me' | 'ai'; text: string; trace?: Trace }

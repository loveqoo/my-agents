const BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000'

export interface Agent {
  id: string
  name: string
  persona: string
  params: Record<string, unknown>
  created_at: string
}

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

export async function listAgents(): Promise<Agent[]> {
  const res = await fetch(`${BASE}/agents`)
  if (!res.ok) throw new Error(`목록 조회 실패: ${res.status}`)
  return res.json()
}

/** SSE 프레임 1개 처리. [DONE]이면 true 반환(종료 신호). */
function handleFrame(frame: string, onToken: (t: string) => void): boolean {
  const dataLine = frame.split('\n').find((l) => l.startsWith('data: '))
  if (!dataLine) return false
  const data = dataLine.slice(6)
  if (data === '[DONE]') return true
  try {
    const parsed = JSON.parse(data)
    if (typeof parsed.text === 'string') onToken(parsed.text)
  } catch {
    /* 비-JSON 프레임 무시 */
  }
  return false
}

/**
 * chat SSE 스트리밍. POST라 EventSource를 못 쓰므로 fetch + ReadableStream으로
 * `data: {"text": "..."}` 프레임을 파싱해 토큰마다 onToken을 호출한다.
 * signal로 도중 취소(에이전트 전환/언마운트) 가능.
 */
export async function streamChat(
  agentId: string,
  messages: ChatMessage[],
  onToken: (token: string) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`${BASE}/agents/${agentId}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ messages }),
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
      if (handleFrame(frame, onToken)) return
    }
  }
  // 마지막 프레임이 빈 줄로 안 끝났을 때 남은 버퍼 처리.
  if (buf.trim()) handleFrame(buf, onToken)
}

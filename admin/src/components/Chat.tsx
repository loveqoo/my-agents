import { useEffect, useRef, useState } from 'react'
import { Typography, Empty } from 'antd'
import { Bubble, Sender, ThoughtChain } from '@ant-design/x'
import { streamChat, type Agent, type ChatMessage } from '../api'

const PANE = {
  flex: 1,
  minWidth: 0,
  display: 'flex',
  flexDirection: 'column',
} as const

const SCROLL = {
  flex: 1,
  minHeight: 0, // flex 자식 내부 스크롤이 동작하려면 필요
  overflowY: 'auto',
  margin: '8px 0',
  padding: 12,
  border: '1px solid #f0f0f0',
  borderRadius: 8,
  background: '#fff',
} as const

export default function Chat({ agent }: { agent: Agent }) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [debugIndex, setDebugIndex] = useState<number | null>(null) // 프롬프트 노출 대상 응답
  const abortRef = useRef<AbortController | null>(null)
  const sendingRef = useRef(false) // setBusy 비동기성으로 인한 중복 전송 가드

  // 언마운트(에이전트 전환) 시 진행 중 스트림 취소.
  useEffect(() => () => abortRef.current?.abort(), [])

  // 채팅 버블: user 우측, assistant 좌측. assistant 응답엔 "프롬프트 보기" 링크.
  const bubbleItems = messages.map((m, i) => {
    const isAi = m.role !== 'user'
    return {
      key: i,
      role: isAi ? 'ai' : 'user',
      content: m.content,
      loading: busy && i === messages.length - 1 && isAi && m.content === '',
      footer:
        isAi && m.content ? (
          <Typography.Link onClick={() => setDebugIndex(i)}>프롬프트 보기</Typography.Link>
        ) : undefined,
    }
  })

  // 선택한 응답(debugIndex)의 전송 페이로드 = system(페르소나) + 그 응답 직전까지의 대화.
  const debugItems =
    debugIndex === null
      ? null
      : [{ role: 'system', content: agent.persona }, ...messages.slice(0, debugIndex)].map(
          (m, i) => ({
            key: String(i),
            title: m.role,
            status: 'success' as const,
            collapsible: true,
            content: (
              <Typography.Paragraph style={{ whiteSpace: 'pre-wrap', margin: 0 }}>
                {m.content}
              </Typography.Paragraph>
            ),
          }),
        )

  async function send(text: string) {
    const t = text.trim()
    if (!t || sendingRef.current) return
    sendingRef.current = true
    // 무상태 서버 — 브라우저가 히스토리를 보관·전달.
    const history: ChatMessage[] = [...messages, { role: 'user', content: t }]
    setMessages([...history, { role: 'assistant', content: '' }])
    setInput('')
    setBusy(true)

    const controller = new AbortController()
    abortRef.current = controller
    try {
      await streamChat(
        agent.id,
        history,
        (token) => {
          setMessages((prev) => {
            const next = [...prev]
            const last = next[next.length - 1]
            next[next.length - 1] = { ...last, content: last.content + token }
            return next
          })
        },
        controller.signal,
      )
    } catch (e) {
      if (controller.signal.aborted) return // 전환/언마운트 취소 — 무시
      setMessages((prev) => {
        const next = [...prev]
        next[next.length - 1] = { role: 'assistant', content: `[오류] ${String(e)}` }
        return next
      })
    } finally {
      sendingRef.current = false
      setBusy(false)
    }
  }

  return (
    <div style={{ display: 'flex', gap: 16, height: '68vh' }}>
      {/* 채팅 영역 */}
      <div style={PANE}>
        <Typography.Text type="secondary">채팅</Typography.Text>
        <div style={SCROLL}>
          <Bubble.List
            autoScroll
            role={{
              ai: { placement: 'start', variant: 'outlined' },
              user: { placement: 'end' },
            }}
            items={bubbleItems}
          />
        </div>
        <Sender
          value={input}
          onChange={(v) => setInput(v)}
          onSubmit={send}
          loading={busy}
          placeholder={`${agent.name}에게 말을 걸어보세요`}
          style={{ background: '#fff' }}
        />
      </div>

      {/* 디버깅 영역 — 선택한 응답의 전송 프롬프트만 (온디맨드, 읽기 전용) */}
      <div style={PANE}>
        <Typography.Text type="secondary">디버깅 — 응답별 전송 프롬프트 (읽기 전용)</Typography.Text>
        <div style={SCROLL}>
          {debugItems === null ? (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description="응답의 '프롬프트 보기'를 누르면 그 응답에 보낸 프롬프트가 여기 표시됩니다"
            />
          ) : (
            <ThoughtChain items={debugItems} />
          )}
        </div>
      </div>
    </div>
  )
}

import { useEffect, useRef, useState } from 'react'
import { Input, Button, List, Typography, Space } from 'antd'
import { streamChat, type Agent, type ChatMessage } from '../api'

const PANE: React.CSSProperties = {
  flex: 1,
  minWidth: 0,
  display: 'flex',
  flexDirection: 'column',
}

export default function Chat({ agent }: { agent: Agent }) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const abortRef = useRef<AbortController | null>(null)
  const sendingRef = useRef(false) // setBusy 비동기성으로 인한 중복 전송 가드
  const bottomRef = useRef<HTMLDivElement>(null)

  // 언마운트(에이전트 전환) 시 진행 중 스트림 취소.
  useEffect(() => () => abortRef.current?.abort(), [])
  // 새 메시지/토큰마다 채팅 영역 맨 아래로.
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // 모델로 실제 전송되는 메시지 = system(페르소나) + 대화.
  // (서버의 create_react_agent(prompt=persona)가 persona를 system으로 prepend)
  const transmit: { role: string; content: string }[] = [
    { role: 'system', content: agent.persona },
    ...messages,
  ]

  async function send() {
    const text = input.trim()
    if (!text || sendingRef.current) return
    sendingRef.current = true
    // 무상태 서버 — 브라우저가 히스토리를 보관·전달.
    const history: ChatMessage[] = [...messages, { role: 'user', content: text }]
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
    <div style={{ display: 'flex', gap: 16, alignItems: 'stretch' }}>
      {/* 채팅 영역 */}
      <div style={PANE}>
        <Typography.Text type="secondary">채팅</Typography.Text>
        <div
          style={{
            flex: 1,
            maxHeight: '64vh',
            overflowY: 'auto',
            border: '1px solid #f0f0f0',
            borderRadius: 8,
            padding: 8,
            margin: '8px 0',
          }}
        >
          <List
            split={false}
            dataSource={messages}
            locale={{ emptyText: `${agent.name}에게 말을 걸어보세요` }}
            renderItem={(m) => (
              <List.Item>
                <Typography.Text strong>{m.role === 'user' ? '나' : agent.name}: </Typography.Text>
                <Typography.Text style={{ whiteSpace: 'pre-wrap', marginLeft: 4 }}>
                  {m.content}
                </Typography.Text>
              </List.Item>
            )}
          />
          <div ref={bottomRef} />
        </div>
        <Space.Compact style={{ width: '100%' }}>
          <Input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onPressEnter={send}
            placeholder="메시지 입력"
            disabled={busy}
          />
          <Button type="primary" onClick={send} loading={busy}>
            보내기
          </Button>
        </Space.Compact>
      </div>

      {/* 디버깅 영역 (프롬프트 확인, 읽기 전용) */}
      <div style={PANE}>
        <Typography.Text type="secondary">디버깅 — 프롬프트 (읽기 전용)</Typography.Text>
        <div
          style={{
            flex: 1,
            maxHeight: '64vh',
            overflowY: 'auto',
            border: '1px solid #f0f0f0',
            borderRadius: 8,
            padding: 8,
            margin: '8px 0',
          }}
        >
          <Typography.Text type="secondary">페르소나 (system)</Typography.Text>
          <Typography.Paragraph style={{ whiteSpace: 'pre-wrap', marginTop: 4 }}>
            {agent.persona}
          </Typography.Paragraph>
          <Typography.Text type="secondary">모델 전송 메시지 (system + 대화)</Typography.Text>
          <List
            size="small"
            split={false}
            dataSource={transmit}
            renderItem={(m) => (
              <List.Item style={{ display: 'block' }}>
                <Typography.Text code>{m.role}</Typography.Text>
                <Typography.Paragraph style={{ whiteSpace: 'pre-wrap', margin: '4px 0 0' }}>
                  {m.content}
                </Typography.Paragraph>
              </List.Item>
            )}
          />
        </div>
      </div>
    </div>
  )
}

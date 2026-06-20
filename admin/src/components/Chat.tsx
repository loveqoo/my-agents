import { useEffect, useRef, useState } from 'react'
import { Input, Button, List, Typography, Space } from 'antd'
import { streamChat, type Agent, type ChatMessage } from '../api'

export default function Chat({ agent }: { agent: Agent }) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const abortRef = useRef<AbortController | null>(null)
  const sendingRef = useRef(false) // setBusy 비동기성으로 인한 중복 전송 가드

  // 언마운트(에이전트 전환) 시 진행 중 스트림 취소.
  useEffect(() => () => abortRef.current?.abort(), [])

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
    <Space direction="vertical" style={{ width: '100%' }} size="middle">
      <List
        bordered
        dataSource={messages}
        locale={{ emptyText: `${agent.name}에게 말을 걸어보세요` }}
        renderItem={(m) => (
          <List.Item>
            <Typography.Text strong>{m.role === 'user' ? '나' : agent.name}: </Typography.Text>
            <Typography.Text style={{ whiteSpace: 'pre-wrap' }}>{m.content}</Typography.Text>
          </List.Item>
        )}
      />
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
    </Space>
  )
}

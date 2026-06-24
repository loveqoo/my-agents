/* my-agents debug console — app shell. Loads real agents, drives the real
   streaming chat API, and links each assistant turn → the Inspector from the
   real execution trace. 3-pane: agent picker (in header) + debug chat + Inspector. */
import { useEffect, useRef, useState } from 'react'
import { message, Grid } from 'antd'
import { DebugChat } from './DebugChat'
import { Inspector } from './Inspector'
import type { ChatMsg, Trace } from './agentData'
import type { Agent } from '../admin/mockData'
import { listAgents, streamChat, type ChatMessage } from '../api'

export function Playground() {
  const [agents, setAgents] = useState<Agent[]>([])
  const [activeId, setActiveId] = useState('')
  const [convos, setConvos] = useState<Record<string, ChatMsg[]>>({})
  const [sessions, setSessions] = useState<Record<string, string>>({})
  const [streaming, setStreaming] = useState(false)
  const [showPrompt, setShowPrompt] = useState(false)
  const [selectedTurn, setSelectedTurn] = useState<number | null>(null)
  const [inspectorOpen, setInspectorOpen] = useState(false)
  const controllerRef = useRef<AbortController | null>(null)

  const screens = Grid.useBreakpoint()
  const isMobile = !screens.md

  const activeAgent = agents.find((a) => a.id === activeId) ?? null
  const messages = convos[activeId] || []

  // 마운트 시 실제 에이전트 목록 로드 — 첫 번째 에이전트를 활성으로.
  useEffect(() => {
    let cancelled = false
    listAgents()
      .then((list) => {
        if (cancelled) return
        setAgents(list)
        if (list.length) setActiveId(list[0].id)
      })
      .catch(() => {
        if (!cancelled) message.error('에이전트 목록을 불러오지 못했습니다.')
      })
    return () => {
      cancelled = true
    }
  }, [])

  // 언마운트 시 진행 중인 스트림 중단.
  useEffect(() => {
    return () => {
      controllerRef.current?.abort()
    }
  }, [])

  const stop = () => {
    controllerRef.current?.abort()
    controllerRef.current = null
    setStreaming(false)
  }

  const send = async (text: string) => {
    if (streaming) return
    const id = activeId
    if (!id) return

    // 직전 대화로 백엔드 메시지 배열 구성 — me→user, ai→assistant, 빈 텍스트 제외.
    const prior = convos[id] || []
    const apiMessages: ChatMessage[] = prior
      .filter((m) => m.text.trim())
      .map((m) => ({ role: m.role === 'me' ? 'user' : 'assistant', content: m.text }))
    apiMessages.push({ role: 'user', content: text })

    // 사용자 턴 + 빈 ai 플레이스홀더 추가.
    setConvos((c) => ({
      ...c,
      [id]: [...(c[id] || []), { role: 'me', text }, { role: 'ai', text: '' }],
    }))

    const appendToLastAi = (fn: (prev: ChatMsg) => ChatMsg) => {
      setConvos((c) => {
        const arr = (c[id] || []).slice()
        const last = arr[arr.length - 1]
        if (last && last.role === 'ai') arr[arr.length - 1] = fn(last)
        return { ...c, [id]: arr }
      })
    }

    const controller = new AbortController()
    controllerRef.current = controller
    setStreaming(true)
    try {
      await streamChat(
        id,
        apiMessages,
        {
          onToken: (t) => appendToLastAi((prev) => ({ ...prev, text: prev.text + t })),
          onSession: (sid) => setSessions((s) => ({ ...s, [id]: sid })),
          onTrace: (tr) => {
            const trace = tr as unknown as Trace
            setConvos((c) => {
              const arr = (c[id] || []).slice()
              const lastIdx = arr.length - 1
              const last = arr[lastIdx]
              if (last && last.role === 'ai') arr[lastIdx] = { ...last, trace }
              setSelectedTurn(lastIdx)
              return { ...c, [id]: arr }
            })
            setInspectorOpen(true)
          },
        },
        controller.signal,
        sessions[id],
      )
    } catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') {
        /* 사용자가 취소 — 무시 */
      } else {
        const msg = e instanceof Error ? e.message : String(e)
        appendToLastAi((prev) => ({ ...prev, text: prev.text + `\n[오류] ${msg}` }))
      }
    } finally {
      controllerRef.current = null
      setStreaming(false)
    }
  }

  const switchAgent = (id: string) => {
    stop()
    setActiveId(id)
    setShowPrompt(false)
  }

  // Clicking a turn's "인스펙터" chip opens the panel on that turn.
  const openInspector = (i: number) => {
    setSelectedTurn(i)
    setInspectorOpen(true)
  }

  const selectedMsg = selectedTurn != null ? messages[selectedTurn] : null

  return (
    <div style={{ flex: 1, minHeight: 0, display: 'flex', background: 'var(--color-bg-container)' }}>
      <DebugChat
        agent={activeAgent}
        agents={agents}
        onSwitchAgent={switchAgent}
        messages={messages}
        streaming={streaming}
        selectedTurn={inspectorOpen ? selectedTurn : null}
        onSelectTurn={openInspector}
        onSend={send}
        onStop={stop}
        showPrompt={showPrompt}
        onTogglePrompt={() => setShowPrompt((s) => !s)}
        inspectorOpen={inspectorOpen}
        onToggleInspector={() => setInspectorOpen((o) => !o)}
      />
      {inspectorOpen ? (
        isMobile ? (
          // 모바일: 인스펙터를 전체화면 오버레이로 — 채팅과 나란히 두면 양쪽이 짜부라진다.
          <div style={{ position: 'fixed', inset: 0, zIndex: 1200, background: 'var(--color-bg-container)' }}>
            <Inspector agent={activeAgent} turn={selectedMsg} turnIndex={selectedTurn || 0} onClose={() => setInspectorOpen(false)} fullWidth />
          </div>
        ) : (
          <Inspector agent={activeAgent} turn={selectedMsg} turnIndex={selectedTurn || 0} onClose={() => setInspectorOpen(false)} />
        )
      ) : null}
    </div>
  )
}

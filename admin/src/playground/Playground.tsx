/* my-agents debug console — app shell. Wires agent selection, conversation state,
   fake LangGraph runs with captured traces, and the turn → Inspector link.
   3-pane: agent picker (in header) + debug chat + right-side turn Inspector. */
import { useEffect, useRef, useState } from 'react'
import { DebugChat } from './DebugChat'
import { Inspector } from './Inspector'
import {
  AGENTS,
  AGENT_SEED,
  planAgent,
  resumeAgent,
  runAgent,
  type ChatMsg,
  type Trace,
} from './agentData'

export function Playground() {
  const agents = AGENTS
  const [activeId, setActiveId] = useState('research')
  const [convos, setConvos] = useState<Record<string, ChatMsg[]>>(AGENT_SEED)
  const [streaming, setStreaming] = useState(false)
  const [showPrompt, setShowPrompt] = useState(false)
  const [selectedTurn, setSelectedTurn] = useState<number | null>(null)
  const [inspectorOpen, setInspectorOpen] = useState(false)
  const timer = useRef<ReturnType<typeof setInterval> | null>(null)

  const agent = agents.find((a) => a.id === activeId) ?? agents[0]
  const messages = convos[activeId] || []

  // default-select the latest assistant turn with a trace
  useEffect(() => {
    const idx = [...messages]
      .map((m, i) => ({ m, i }))
      .reverse()
      .find((x) => x.m.role === 'ai' && x.m.trace)
    setSelectedTurn(idx ? idx.i : null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeId])

  // 언마운트 시 스트리밍 interval 정리 — 다른 뷰로 이동해도 setState가 호출되지 않도록.
  useEffect(() => {
    return () => {
      if (timer.current) clearInterval(timer.current)
    }
  }, [])

  const stop = () => {
    if (timer.current) {
      clearInterval(timer.current)
      timer.current = null
    }
    setStreaming(false)
  }

  const streamReply = (id: string, full: string, trace: Trace) => {
    setStreaming(true)
    setConvos((c) => ({ ...c, [id]: [...(c[id] || []), { role: 'ai', text: '' }] }))
    let i = 0
    const step = Math.max(2, Math.round(full.length / 80))
    timer.current = setInterval(() => {
      i += step
      const slice = full.slice(0, i)
      setConvos((c) => {
        const arr = (c[id] || []).slice()
        arr[arr.length - 1] = { role: 'ai', text: slice }
        return { ...c, [id]: arr }
      })
      if (i >= full.length) {
        if (timer.current) clearInterval(timer.current)
        timer.current = null
        setStreaming(false)
        setConvos((c) => {
          const arr = (c[id] || []).slice()
          arr[arr.length - 1] = { role: 'ai', text: full, trace }
          setSelectedTurn(arr.length - 1)
          return { ...c, [id]: arr }
        })
      }
    }, 38)
  }

  // User submitted an A2UI surface — the action + data model flow back to the agent.
  const onA2UIAction = (msgIndex: number, action: { name: string }, data: { form: Record<string, unknown> }) => {
    if (streaming) return
    const id = activeId
    setConvos((c) => {
      const arr = (c[id] || []).slice()
      const target = arr[msgIndex]
      if (target && target.role === 'a2ui') arr[msgIndex] = { ...target, state: 'submitted', submitted: data }
      return { ...c, [id]: arr }
    })
    const f = (data && data.form) || {}
    const base = runAgent(agent, 'confirm ' + (action && action.name))
    base.text =
      '완료 — "' +
      (String(f.title || '회의')) +
      '" 일정을 ' +
      (String(f.date || '')) +
      ' ' +
      (String(f.time || '')) +
      '에 ' +
      (String(f.attendees || '팀')) +
      '과(와) 잡았습니다' +
      (f.remind ? ', 하루 전 모두에게 리마인더도 보낼게요' : '') +
      '. A2UI 액션 ' +
      (action && action.name) +
      '이(가) 폼 데이터 모델과 함께 저에게 회신되었습니다.'
    setTimeout(() => streamReply(id, base.text, base.trace), 260)
  }

  const send = (text: string) => {
    if (streaming) return
    const id = activeId
    setConvos((c) => ({ ...c, [id]: [...(c[id] || []), { role: 'me', text }] }))
    const plan = planAgent(agent, text)
    if (plan.type === 'a2ui') {
      // Agent replies with generative UI (A2UI) instead of text.
      setTimeout(() => {
        setConvos((c) => ({
          ...c,
          [id]: [...(c[id] || []), { role: 'a2ui', id: 'srf-' + Date.now(), surface: plan.surface, state: 'open' }],
        }))
      }, 260)
      return
    }
    if (plan.type === 'interrupt') {
      // Run hit interrupt() — pause at a checkpoint and surface an approval request.
      setTimeout(() => {
        setConvos((c) => ({
          ...c,
          [id]: [
            ...(c[id] || []),
            {
              role: 'approval',
              id: 'apr-' + Date.now(),
              approver: plan.approver,
              permission: plan.permission,
              tool: plan.tool,
              args: plan.args,
              summary: plan.summary,
              checkpoint: plan.checkpoint,
              state: plan.approver === 'admin' ? 'routed' : 'pending',
            },
          ],
        }))
      }, 260)
      return
    }
    setTimeout(() => streamReply(id, plan.text, plan.trace), 260)
  }

  // Resolve an inline (user) approval, then resume the run from its checkpoint.
  const resolveApproval = (msgIndex: number, decision: 'approve' | 'reject') => {
    if (streaming) return
    const id = activeId
    const info = (convos[id] || [])[msgIndex]
    if (!info || info.role !== 'approval') return
    setConvos((c) => {
      const arr = (c[id] || []).slice()
      arr[msgIndex] = { ...info, state: decision === 'approve' ? 'approved' : 'rejected' }
      return { ...c, [id]: arr }
    })
    const resumed = resumeAgent(agent, info, decision)
    setTimeout(() => streamReply(id, resumed.text, resumed.trace), 260)
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
        agent={agent}
        agents={agents}
        onSwitchAgent={switchAgent}
        messages={messages}
        streaming={streaming}
        selectedTurn={inspectorOpen ? selectedTurn : null}
        onSelectTurn={openInspector}
        onSend={send}
        onResolveApproval={resolveApproval}
        onA2UIAction={onA2UIAction}
        onStop={stop}
        showPrompt={showPrompt}
        onTogglePrompt={() => setShowPrompt((s) => !s)}
        inspectorOpen={inspectorOpen}
        onToggleInspector={() => setInspectorOpen((o) => !o)}
      />
      {inspectorOpen ? (
        <Inspector agent={agent} turn={selectedMsg} turnIndex={selectedTurn || 0} onClose={() => setInspectorOpen(false)} />
      ) : null}
    </div>
  )
}

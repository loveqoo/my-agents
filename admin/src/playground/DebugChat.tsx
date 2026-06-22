/* my-agents debug console — center: chat with the selected agent.
   Header exposes the agent's config + a "System prompt" toggle. Each assistant
   turn is selectable (drives the Inspector) and shows trace chips. */
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Bubble, Sender, Welcome, Prompts } from '@ant-design/x'
import { Avatar, Button, Tag } from 'antd'
import { Icon } from '../admin/icons'
import { A2UISurface } from './A2UISurface'
import type { DebugAgent, ChatMsg, Trace } from './agentData'

const agentAvatar = (
  <Avatar style={{ background: 'var(--gray-12)', flex: 'none' }}>
    <Icon name="robot" />
  </Avatar>
)
const userAvatar = <Avatar style={{ background: 'var(--volcano-6)', flex: 'none' }}>U</Avatar>

const STATUS_DOT: Record<string, string> = {
  online: 'var(--color-success)',
  idle: 'var(--gold-6)',
  offline: 'var(--gray-6)',
}

interface DebugChatProps {
  agent: DebugAgent
  agents: DebugAgent[]
  onSwitchAgent: (id: string) => void
  messages: ChatMsg[]
  streaming: boolean
  selectedTurn: number | null
  onSelectTurn: (i: number) => void
  onSend: (text: string) => void
  onResolveApproval: (i: number, decision: 'approve' | 'reject') => void
  onA2UIAction: (i: number, action: { name: string }, data: { form: Record<string, unknown> }) => void
  onStop: () => void
  showPrompt: boolean
  onTogglePrompt: () => void
  inspectorOpen: boolean
  onToggleInspector: () => void
}

function ExposeBadges({ agent }: { agent: DebugAgent }) {
  return (
    <div style={{ display: 'flex', gap: 6 }}>
      {agent.exposed.a2a ? <Tag color="green">A2A</Tag> : null}
      {agent.exposed.mcp ? <Tag color="cyan">MCP 서버</Tag> : null}
    </div>
  )
}

/* Rich agent picker — replaces the left rail. Shows avatar, persona, model and
   MCP chips per agent in a dropdown. */
function AgentCombo({
  agent,
  agents,
  onSwitch,
}: {
  agent: DebugAgent
  agents: DebugAgent[]
  onSwitch: (id: string) => void
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [])
  return (
    <div ref={ref} style={{ position: 'relative', minWidth: 0 }}>
      <button
        onClick={() => setOpen((o) => !o)}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          padding: '6px 12px 6px 8px',
          borderRadius: 10,
          border: '1px solid ' + (open ? 'var(--color-primary-border)' : 'var(--color-border)'),
          background: open ? 'var(--color-primary-bg)' : 'var(--color-bg-container)',
          cursor: 'pointer',
          font: 'inherit',
          transition: 'all .2s',
          maxWidth: 360,
        }}
      >
        <span style={{ position: 'relative', flex: 'none' }}>
          {agentAvatar}
          <span
            style={{
              position: 'absolute',
              right: -1,
              bottom: -1,
              width: 9,
              height: 9,
              borderRadius: '50%',
              background: STATUS_DOT[agent.status],
              border: '2px solid #fff',
            }}
          />
        </span>
        <span style={{ minWidth: 0, textAlign: 'left' }}>
          <span
            style={{
              display: 'block',
              fontSize: 15,
              fontWeight: 600,
              color: 'var(--color-text-heading)',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {agent.name}
          </span>
          <span
            style={{
              display: 'block',
              fontSize: 12,
              color: 'var(--color-text-tertiary)',
              fontFamily: 'var(--font-family-code)',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {agent.model} · {agent.persona}
          </span>
        </span>
        <Icon
          name="down"
          size={12}
          style={{
            color: 'var(--color-text-tertiary)',
            flex: 'none',
            transform: open ? 'rotate(180deg)' : 'none',
            transition: 'transform .2s',
          }}
        />
      </button>
      {open ? (
        <div
          style={{
            position: 'absolute',
            top: 'calc(100% + 6px)',
            left: 0,
            zIndex: 1050,
            width: 360,
            background: 'var(--color-bg-elevated)',
            borderRadius: 12,
            boxShadow: 'var(--box-shadow)',
            padding: 6,
            maxHeight: 420,
            overflow: 'auto',
          }}
        >
          <div style={{ fontSize: 11, color: 'var(--color-text-tertiary)', padding: '6px 10px 4px' }}>에이전트 {agents.length}</div>
          {agents.map((a) => {
            const on = a.id === agent.id
            return (
              <button
                key={a.id}
                onClick={() => {
                  onSwitch(a.id)
                  setOpen(false)
                }}
                style={{
                  width: '100%',
                  display: 'flex',
                  gap: 10,
                  alignItems: 'flex-start',
                  padding: '9px 10px',
                  borderRadius: 8,
                  border: 'none',
                  cursor: 'pointer',
                  font: 'inherit',
                  textAlign: 'left',
                  background: on ? 'var(--color-primary-bg)' : 'transparent',
                  transition: 'background .15s',
                }}
                onMouseEnter={(e) => {
                  if (!on) e.currentTarget.style.background = 'var(--color-fill-tertiary)'
                }}
                onMouseLeave={(e) => {
                  if (!on) e.currentTarget.style.background = 'transparent'
                }}
              >
                <span style={{ position: 'relative', flex: 'none', marginTop: 1 }}>
                  <Avatar size="small" style={{ background: 'var(--gray-12)' }}>
                    <Icon name="robot" size={13} />
                  </Avatar>
                  <span
                    style={{
                      position: 'absolute',
                      right: -1,
                      bottom: -1,
                      width: 8,
                      height: 8,
                      borderRadius: '50%',
                      background: STATUS_DOT[a.status],
                      border: '2px solid var(--color-bg-elevated)',
                    }}
                  />
                </span>
                <span style={{ flex: 1, minWidth: 0 }}>
                  <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <span style={{ fontSize: 14, fontWeight: 500, color: 'var(--color-text-heading)' }}>{a.name}</span>
                    {on ? <Icon name="check" size={12} style={{ color: 'var(--color-primary)' }} /> : null}
                    <span style={{ flex: 1 }} />
                    <span style={{ fontSize: 11, color: 'var(--color-text-tertiary)', fontFamily: 'var(--font-family-code)' }}>{a.model}</span>
                  </span>
                  <span style={{ display: 'block', fontSize: 12, color: 'var(--color-text-secondary)', marginTop: 1 }}>{a.persona}</span>
                  <span style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 6 }}>
                    {a.exposed && a.exposed.a2a ? <Tag color="green">A2A</Tag> : null}
                    {a.mcps.map((m) => (
                      <Tag key={m} color="cyan">
                        {m}
                      </Tag>
                    ))}
                  </span>
                </span>
              </button>
            )
          })}
        </div>
      ) : null}
    </div>
  )
}

function ChatHeader({
  agent,
  agents,
  onSwitchAgent,
  showPrompt,
  onTogglePrompt,
  inspectorOpen,
  onToggleInspector,
}: {
  agent: DebugAgent
  agents: DebugAgent[]
  onSwitchAgent: (id: string) => void
  showPrompt: boolean
  onTogglePrompt: () => void
  inspectorOpen: boolean
  onToggleInspector: () => void
}) {
  return (
    <div style={{ flex: 'none', borderBottom: '1px solid var(--color-border-secondary)', background: 'var(--color-bg-container)' }}>
      <div style={{ height: 64, display: 'flex', alignItems: 'center', gap: 12, padding: '0 20px' }}>
        <AgentCombo agent={agent} agents={agents} onSwitch={onSwitchAgent} />
        <div style={{ flex: 1 }} />
        <ExposeBadges agent={agent} />
        <Button size="small" type={showPrompt ? 'primary' : 'default'} icon={<Icon name="file" />} onClick={onTogglePrompt}>
          시스템 프롬프트
        </Button>
        <Button size="small" type={inspectorOpen ? 'primary' : 'default'} icon={<Icon name="dashboard" />} onClick={onToggleInspector}>
          인스펙터
        </Button>
      </div>
      {showPrompt ? (
        <div style={{ padding: '0 20px 16px' }}>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 8 }}>
            {(agent.memories || []).map((m) => (
              <Tag key={m} color="purple">
                {m}
              </Tag>
            ))}
            {agent.permissions.map((p) => (
              <Tag key={p} color="geekblue">
                {p}
              </Tag>
            ))}
            {agent.mcps.map((m) => (
              <Tag key={m} color="cyan">
                {m}
              </Tag>
            ))}
          </div>
          <pre
            style={{
              fontFamily: 'var(--font-family-code)',
              fontSize: 12,
              lineHeight: 1.6,
              color: 'var(--color-text)',
              background: 'var(--gray-2)',
              border: '1px solid var(--color-border-secondary)',
              borderRadius: 8,
              padding: '12px 14px',
              margin: 0,
              whiteSpace: 'pre-wrap',
              maxHeight: 220,
              overflow: 'auto',
            }}
          >
            {agent.systemPrompt}
          </pre>
        </div>
      ) : null}
    </div>
  )
}

function Chip({ icon, color, n, label }: { icon: string; color: string; n?: number; label: string }) {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 12, color: 'var(--color-text-secondary)' }}>
      <Icon name={icon} size={12} style={{ color }} />
      {n != null ? n + ' ' : ''}
      {label}
    </span>
  )
}

function TraceChips({ trace, active, onClick }: { trace?: Trace; active: boolean; onClick: () => void }) {
  if (!trace) return null
  return (
    <div
      onClick={onClick}
      style={{
        display: 'inline-flex',
        gap: 10,
        alignItems: 'center',
        marginTop: 2,
        padding: '4px 10px',
        cursor: 'pointer',
        border: '1px solid ' + (active ? 'var(--color-primary-border)' : 'var(--color-border-secondary)'),
        background: active ? 'var(--color-primary-bg)' : 'var(--color-bg-container)',
        borderRadius: 100,
        transition: 'all .2s',
      }}
    >
      <Chip icon="bulb" color="var(--purple-6)" n={trace.memories.length} label="mem" />
      <Chip icon="thunderbolt" color="var(--cyan-7)" n={trace.mcp.length} label="mcp" />
      <Chip icon="clock-circle" color="var(--color-text-tertiary)" label={(trace.latencyMs / 1000).toFixed(2) + 's'} />
      <span style={{ fontSize: 12, color: 'var(--color-primary)', fontWeight: 500 }}>인스펙터{active ? ' ✓' : ''}</span>
    </div>
  )
}

/* HIL approval card rendered inline in the thread when a run hits interrupt(). */
function ApprovalCard({
  msg,
  disabled,
  onResolve,
}: {
  msg: Extract<ChatMsg, { role: 'approval' }>
  disabled: boolean
  onResolve: (decision: 'approve' | 'reject') => void
}) {
  const isAdmin = msg.approver === 'admin'
  const accent = isAdmin ? 'var(--purple-6)' : 'var(--color-primary)'
  const resolved = msg.state === 'approved' || msg.state === 'rejected'
  return (
    <div style={{ display: 'flex', gap: 12, alignSelf: 'flex-start', maxWidth: '100%' }}>
      <span
        style={{
          width: 32,
          height: 32,
          borderRadius: '50%',
          flex: 'none',
          background: accent,
          color: '#fff',
          display: 'inline-flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <Icon name="clock-circle" size={16} />
      </span>
      <div
        style={{
          border: '1px solid ' + accent,
          borderRadius: 12,
          overflow: 'hidden',
          flex: 1,
          minWidth: 0,
          background: isAdmin ? 'var(--purple-1)' : 'var(--color-primary-bg)',
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            padding: '10px 14px',
            borderBottom: '1px solid ' + (isAdmin ? 'var(--purple-3)' : 'var(--color-primary-border)'),
          }}
        >
          <Icon name="exclamation-circle" size={14} style={{ color: accent }} />
          <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--color-text-heading)' }}>승인 필요</span>
          <Tag color={isAdmin ? 'purple' : 'blue'} style={{ marginInlineStart: 'auto' }}>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
              <Icon name={isAdmin ? 'team' : 'user'} size={10} />
              {isAdmin ? '관리자' : '사용자'}
            </span>
          </Tag>
        </div>
        <div style={{ padding: '12px 14px' }}>
          <div style={{ fontSize: 14, color: 'var(--color-text-heading)', fontWeight: 500, marginBottom: 8 }}>{msg.summary}</div>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 10 }}>
            <Tag color="geekblue">{msg.permission}</Tag>
            <Tag color="cyan">
              <code style={{ fontFamily: 'var(--font-family-code)' }}>{msg.tool}</code>
            </Tag>
          </div>
          <pre
            style={{
              fontFamily: 'var(--font-family-code)',
              fontSize: 12,
              lineHeight: 1.5,
              color: 'var(--color-text)',
              background: 'var(--color-bg-container)',
              border: '1px solid var(--color-border-secondary)',
              borderRadius: 6,
              padding: '8px 10px',
              margin: 0,
              whiteSpace: 'pre-wrap',
            }}
          >
            {JSON.stringify(msg.args, null, 2)}
          </pre>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 10, fontSize: 12, color: 'var(--color-text-tertiary)' }}>
            <Icon name="clock-circle" size={12} />
            일시정지 지점{' '}
            <code style={{ fontFamily: 'var(--font-family-code)', color: 'var(--color-text-secondary)' }}>{msg.checkpoint}</code>
          </div>

          {isAdmin ? (
            <div style={{ marginTop: 12, fontSize: 13, color: 'var(--purple-7)', display: 'flex', alignItems: 'center', gap: 6 }}>
              <Icon name="share-alt" size={13} />
              관리자 승인 큐로 라우팅됨 — 관리자가 처리할 때까지 세션이 대기합니다.
            </div>
          ) : resolved ? (
            <div
              style={{
                marginTop: 12,
                fontSize: 13,
                fontWeight: 500,
                color: msg.state === 'approved' ? 'var(--color-success)' : 'var(--color-error)',
                display: 'inline-flex',
                alignItems: 'center',
                gap: 6,
              }}
            >
              <Icon name={msg.state === 'approved' ? 'check-circle' : 'close-circle'} size={14} />
              {msg.state === 'approved' ? '승인됨 — 체크포인트에서 재개' : '거부됨 — 실행 중단'}
            </div>
          ) : (
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 12 }}>
              <Button size="small" danger icon={<Icon name="close" />} disabled={disabled} onClick={() => onResolve('reject')}>
                거부
              </Button>
              <Button size="small" type="primary" icon={<Icon name="check" />} disabled={disabled} onClick={() => onResolve('approve')}>
                승인 및 재개
              </Button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

/* Generative-UI message: the agent replied with an A2UI surface. */
function A2UIMessage({
  msg,
  disabled,
  onAction,
}: {
  msg: Extract<ChatMsg, { role: 'a2ui' }>
  disabled: boolean
  onAction: (action: { name: string }, data: { form: Record<string, unknown> }) => void
}) {
  return (
    <div style={{ display: 'flex', gap: 12, alignSelf: 'flex-start', maxWidth: '100%' }}>
      <span
        style={{
          width: 32,
          height: 32,
          borderRadius: '50%',
          flex: 'none',
          background: 'var(--gray-12)',
          color: '#fff',
          display: 'inline-flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <Icon name="appstore" size={16} />
      </span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
          <Tag color="cyan">
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
              <Icon name="appstore" size={10} />
              A2UI 서페이스
            </span>
          </Tag>
          {msg.state === 'submitted' ? <Tag color="green">제출됨</Tag> : null}
        </div>
        <div
          style={{
            maxWidth: 380,
            pointerEvents: msg.state === 'submitted' || disabled ? 'none' : 'auto',
            opacity: msg.state === 'submitted' ? 0.7 : 1,
          }}
        >
          <A2UISurface messages={msg.surface} onAction={onAction} />
        </div>
      </div>
    </div>
  )
}

export function DebugChat({
  agent,
  agents,
  onSwitchAgent,
  messages,
  streaming,
  selectedTurn,
  onSelectTurn,
  onSend,
  onResolveApproval,
  onA2UIAction,
  onStop,
  showPrompt,
  onTogglePrompt,
  inspectorOpen,
  onToggleInspector,
}: DebugChatProps) {
  const scroller = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (scroller.current) scroller.current.scrollTop = scroller.current.scrollHeight
  }, [messages, streaming, showPrompt])

  const empty = messages.length === 0

  const hilDescription =
    agent.id === 'reviewer'
      ? 'PR #482를 main에 병합해줘'
      : agent.id === 'ops'
      ? 'prod api 배포를 증설해줘'
      : agent.id === 'secretary'
      ? '팀에 업데이트 이메일을 보내줘'
      : '마지막 실행이 왜 실패했는지 재현해줘'

  const promptItems = [
    { key: '1', icon: <Icon name="bulb" style={{ color: 'var(--purple-6)' }} />, label: '메모리 회상 테스트', description: '지난번에 무슨 얘기를 나눔지?' },
    { key: '2', icon: <Icon name="thunderbolt" style={{ color: 'var(--cyan-7)' }} />, label: '도구 호출 유도', description: '스트리밍 UI 최신 동향을 검색해줘' },
    { key: '3', icon: <Icon name="appstore" style={{ color: 'var(--cyan-7)' }} />, label: '생성형 UI (A2UI)', description: '팀과 회의 일정을 잡아줘' },
    { key: '4', icon: <Icon name="user" style={{ color: 'var(--color-primary)' }} />, label: 'HIL 승인 트리거', description: hilDescription },
  ]

  return (
    <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', background: 'var(--color-bg-container)' }}>
      <ChatHeader
        agent={agent}
        agents={agents}
        onSwitchAgent={onSwitchAgent}
        showPrompt={showPrompt}
        onTogglePrompt={onTogglePrompt}
        inspectorOpen={inspectorOpen}
        onToggleInspector={onToggleInspector}
      />

      <div ref={scroller} style={{ flex: 1, overflowY: 'auto' }}>
        {empty ? (
          <div style={{ maxWidth: 680, margin: '0 auto', width: '100%', padding: '7vh 24px 0', display: 'flex', flexDirection: 'column', gap: 24 }}>
            <Welcome
              icon={agentAvatar}
              title={`${agent.name} 디버깅`}
              description="메시지를 보내 에이전트를 실행하세요. 모든 턴은 프롬프트, 메모리 히트, MCP 호출, LangGraph 경로를 기록합니다 — 오른쪽에서 인스펙트하세요."
            />
            <Prompts
              title="디버그 프롬프트 체험"
              wrap
              items={promptItems}
              onItemClick={(info) => onSend((info.data as { description?: string }).description ?? '')}
            />
          </div>
        ) : (
          <div style={{ maxWidth: 680, margin: '0 auto', padding: 24, width: '100%', boxSizing: 'border-box' }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
              {messages.map((m, i) => {
                if (m.role === 'ai') {
                  const isLast = i === messages.length - 1
                  const footer: ReactNode =
                    m.trace && !(streaming && isLast) ? (
                      <TraceChips trace={m.trace} active={selectedTurn === i} onClick={() => onSelectTurn(i)} />
                    ) : null
                  return (
                    <Bubble
                      key={i}
                      placement="start"
                      avatar={agentAvatar}
                      header={agent.name}
                      content={m.text}
                      typing={streaming && isLast}
                      footer={footer}
                    />
                  )
                }
                if (m.role === 'approval') {
                  return <ApprovalCard key={i} msg={m} disabled={streaming} onResolve={(d) => onResolveApproval(i, d)} />
                }
                if (m.role === 'a2ui') {
                  return <A2UIMessage key={i} msg={m} disabled={streaming} onAction={(action, data) => onA2UIAction(i, action, data)} />
                }
                return <Bubble key={i} placement="end" variant="filled" avatar={userAvatar} content={m.text} />
              })}
            </div>
          </div>
        )}
      </div>

      <div style={{ flex: 'none', padding: '8px 24px 18px' }}>
        <div style={{ maxWidth: 680, margin: '0 auto' }}>
          <Sender
            placeholder={`${agent.name}에게 메시지…`}
            loading={streaming}
            onSubmit={onSend}
            onCancel={onStop}
            prefix={<Button type="text" icon={<Icon name="paper-clip" />} />}
            footer={() => (
              <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>LangGraph 에이전트 실행 · 턴마다 트레이스 기록</span>
            )}
          />
        </div>
      </div>
    </div>
  )
}

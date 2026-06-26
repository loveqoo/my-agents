/* my-agents debug console — center: chat with the selected agent.
   Header exposes the agent's config + a "System prompt" toggle. Each assistant
   turn is selectable (drives the Inspector) and shows trace chips. Data is real:
   agents come from the backend, turns/traces come from the streaming chat API. */
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Bubble, Sender, Prompts } from '@ant-design/x'
import { Avatar, Button, Tag, Grid, Tooltip } from 'antd'
import { Icon } from '../admin/icons'
import type { ChatMsg, Trace } from './agentData'
import type { Agent } from '../admin/mockData'

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
const statusDot = (status: string) => STATUS_DOT[status] ?? 'var(--gray-6)'

/* 모델 배지를 source별로 정직하게 (스펙 028). code 에이전트는 model 필드가 박혀 있어도
   로컬 모델로 돌지 않고 자기 원격 엔드포인트(dev=mock)로 bypass하므로 모델명을 띄우면
   거짓이다 → "코드 정의"(persona "코드 정의 (SDK)"·AgentsView 소스 표기와 일관).
   external은 A2A 원격 → "외부 A2A"(AGENT_SOURCE.external.label과 동일). ui만 실행 모델 맞아 모델명. */
function modelBadge(a: Agent): { text: string; remote: boolean; tip?: ReactNode } {
  if (a.source === 'code')
    return {
      text: '코드 정의',
      remote: true,
      tip: (
        <span style={{ whiteSpace: 'pre-line' }}>
          {['원격 엔드포인트에서 실행 — 로컬 모델 미사용', a.runtime, a.endpoint].filter(Boolean).join('\n')}
        </span>
      ),
    }
  if (a.source === 'external')
    return { text: '외부 A2A', remote: true, tip: a.card?.url ?? a.endpoint }
  return { text: a.model, remote: false }
}

/* size='header': 헤더 칩(pill). size='row': 피커 행의 작은 텍스트. remote면 primary 대신 중립색. */
function ModelBadge({ a, size }: { a: Agent; size: 'header' | 'row' }) {
  const b = modelBadge(a)
  const header = size === 'header'
  const chip = (
    <span
      style={{
        fontFamily: 'var(--font-family-code)',
        fontWeight: header ? 600 : 400,
        fontSize: header ? undefined : 11,
        color: b.remote ? 'var(--color-text-tertiary)' : header ? 'var(--color-primary)' : 'var(--color-text-tertiary)',
        ...(header
          ? {
              background: b.remote ? 'var(--color-fill-tertiary)' : 'var(--color-primary-bg)',
              border: '1px solid ' + (b.remote ? 'var(--color-border)' : 'var(--color-primary-border)'),
              borderRadius: 5,
              padding: '0 5px',
              marginInlineEnd: 6,
            }
          : {}),
      }}
    >
      {b.text}
    </span>
  )
  return b.tip ? <Tooltip title={b.tip}>{chip}</Tooltip> : chip
}

interface DebugChatProps {
  agent: Agent | null
  agents: Agent[]
  onSwitchAgent: (id: string) => void
  messages: ChatMsg[]
  streaming: boolean
  selectedTurn: number | null
  onSelectTurn: (i: number) => void
  onSend: (text: string) => void
  onStop: () => void
  canResetConversation: boolean
  onResetConversation: () => void
  showPrompt: boolean
  onTogglePrompt: () => void
  effectiveSystemPrompt?: string
  inspectorOpen: boolean
  onToggleInspector: () => void
  overrideActive: boolean
  onToggleOverrides: () => void
}

function ExposeBadges({ agent }: { agent: Agent }) {
  return <div style={{ display: 'flex', gap: 6 }}>{agent.exposed?.a2a ? <Tag color="green">A2A</Tag> : null}</div>
}

/* Rich agent picker — replaces the left rail. Shows avatar, persona, model and
   MCP chips per agent in a dropdown. */
function AgentCombo({
  agent,
  agents,
  onSwitch,
}: {
  agent: Agent
  agents: Agent[]
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
          // 슬롯이 좁아지면 버튼도 따라 줄고 안쪽 텍스트가 ellipsis 되도록 — 안 그러면
          // 콘텐츠 폭(~347px)을 고수해 슬롯 밖으로 넘쳐 옆 요소(userId)를 덮는다.
          width: '100%',
          minWidth: 0,
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
              background: statusDot(agent.status),
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
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {/* 실행 주체를 한눈에 — ui=모델명, code=코드 정의, external=외부 A2A (스펙 028). */}
            <ModelBadge a={agent} size="header" />
            {agent.persona}
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
                      background: statusDot(a.status),
                      border: '2px solid var(--color-bg-elevated)',
                    }}
                  />
                </span>
                <span style={{ flex: 1, minWidth: 0 }}>
                  <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <span style={{ fontSize: 14, fontWeight: 500, color: 'var(--color-text-heading)' }}>{a.name}</span>
                    {on ? <Icon name="check" size={12} style={{ color: 'var(--color-primary)' }} /> : null}
                    <span style={{ flex: 1 }} />
                    <ModelBadge a={a} size="row" />
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
  canResetConversation,
  onResetConversation,
  showPrompt,
  onTogglePrompt,
  effectiveSystemPrompt,
  inspectorOpen,
  onToggleInspector,
  overrideActive,
  onToggleOverrides,
}: {
  agent: Agent
  agents: Agent[]
  onSwitchAgent: (id: string) => void
  canResetConversation: boolean
  onResetConversation: () => void
  showPrompt: boolean
  onTogglePrompt: () => void
  effectiveSystemPrompt?: string
  inspectorOpen: boolean
  onToggleInspector: () => void
  overrideActive: boolean
  onToggleOverrides: () => void
}) {
  const screens = Grid.useBreakpoint()
  const isMobile = !screens.md
  // 좁은 데스크톱(lg 미만): 사이드바(232px) 탓에 헤더 가로가 빠듯해 AgentCombo가 아바타만 남게
  // 쭈그러든다. md만으로는 너무 늦으니 lg부터 컨트롤을 축소(A2A 숨김 + 버튼 아이콘만)해 공간 확보.
  // 또한 인스펙터가 나란히(side-by-side) 열려 있으면 채팅 컬럼이 384px만큼 더 줄어 라벨이 인스펙터로
  // 흘러넘친다(#9). 그래서 인스펙터가 열린 동안엔 폭과 무관하게 항상 compact로 둔다.
  const compact = !screens.lg || inspectorOpen
  return (
    <div style={{ flex: 'none', borderBottom: '1px solid var(--color-border-secondary)', background: 'var(--color-bg-container)' }}>
      {/* compact: 버튼 아이콘만(라벨 제거) + A2A 배지 숨김 — 한 줄에 안 들어가 겹치던 문제. */}
      <div style={{ height: 64, display: 'flex', alignItems: 'center', gap: isMobile ? 8 : 12, padding: isMobile ? '0 12px' : '0 20px' }}>
        <AgentCombo agent={agent} agents={agents} onSwitch={onSwitchAgent} />
        <div style={{ flex: 1 }} />
        {/* mem0 user_id 축은 서버가 로그인 유저에서 도출한다(스펙 032) — 수동 userId 입력은 제거.
            "새 대화"는 userId 잠금에서 분리된 일반 리셋: 진행 중인 대화가 있을 때만 노출. */}
        {canResetConversation && (
          <Button
            size="small"
            icon={<Icon name="plus" />}
            onClick={onResetConversation}
            title="새 대화 — 현재 대화를 비우고 처음부터 시작합니다."
          >
            {compact ? null : '새 대화'}
          </Button>
        )}
        {!compact && <ExposeBadges agent={agent} />}
        <Button
          size="small"
          type={overrideActive ? 'primary' : 'default'}
          icon={<Icon name="experiment" />}
          onClick={onToggleOverrides}
          title={overrideActive ? '런타임 오버라이드 (적용 중)' : '런타임 오버라이드'}
        >
          {compact ? null : overrideActive ? '오버라이드 ✓' : '오버라이드'}
        </Button>
        <Button
          size="small"
          type={showPrompt ? 'primary' : 'default'}
          icon={<Icon name="file" />}
          onClick={onTogglePrompt}
          title="시스템 프롬프트"
        >
          {compact ? null : '시스템 프롬프트'}
        </Button>
        <Button
          size="small"
          type={inspectorOpen ? 'primary' : 'default'}
          icon={<Icon name="dashboard" />}
          onClick={onToggleInspector}
          title="인스펙터"
        >
          {compact ? null : '인스펙터'}
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
            {effectiveSystemPrompt ?? agent.systemPrompt ?? ''}
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

export function DebugChat({
  agent,
  agents,
  onSwitchAgent,
  messages,
  streaming,
  selectedTurn,
  onSelectTurn,
  onSend,
  onStop,
  canResetConversation,
  onResetConversation,
  showPrompt,
  onTogglePrompt,
  effectiveSystemPrompt,
  inspectorOpen,
  onToggleInspector,
  overrideActive,
  onToggleOverrides,
}: DebugChatProps) {
  const scroller = useRef<HTMLDivElement>(null)
  // Sender는 submit 시 스스로 입력을 비우지 않는다(@ant-design/x 2.8 — triggerSend가
  // onSubmit만 호출, clear는 클리어 버튼에서만). 그래서 controlled로 두고 직접 비운다.
  const [draft, setDraft] = useState('')
  useEffect(() => {
    if (scroller.current) scroller.current.scrollTop = scroller.current.scrollHeight
  }, [messages, streaming, showPrompt])

  if (!agent) {
    return (
      <div
        style={{
          flex: 1,
          minWidth: 0,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: 'var(--color-text-tertiary)',
          background: 'var(--color-bg-container)',
        }}
      >
        에이전트를 불러오는 중…
      </div>
    )
  }

  const empty = messages.length === 0

  const promptItems = [
    { key: '1', icon: <Icon name="bulb" style={{ color: 'var(--purple-6)' }} />, label: '메모리 회상 테스트', description: '지난번에 무슨 얘기를 나눴지?' },
    { key: '2', icon: <Icon name="thunderbolt" style={{ color: 'var(--cyan-7)' }} />, label: '도구 호출 유도', description: '스트리밍 UI 최신 동향을 검색해줘' },
    { key: '3', icon: <Icon name="file" style={{ color: 'var(--color-primary)' }} />, label: '시스템 프롬프트 확인', description: '너의 역할과 규칙을 한 줄로 요약해줘' },
  ]

  return (
    <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', background: 'var(--color-bg-container)' }}>
      <ChatHeader
        agent={agent}
        agents={agents}
        onSwitchAgent={onSwitchAgent}
        canResetConversation={canResetConversation}
        onResetConversation={onResetConversation}
        showPrompt={showPrompt}
        onTogglePrompt={onTogglePrompt}
        effectiveSystemPrompt={effectiveSystemPrompt}
        inspectorOpen={inspectorOpen}
        onToggleInspector={onToggleInspector}
        overrideActive={overrideActive}
        onToggleOverrides={onToggleOverrides}
      />

      <div ref={scroller} style={{ flex: 1, overflowY: 'auto' }}>
        {empty ? (
          <div style={{ maxWidth: 680, margin: '0 auto', width: '100%', padding: '7vh 24px 0', display: 'flex', flexDirection: 'column', gap: 24 }}>
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
                      // 첫 토큰 도착 전(빈 content)에는 typing이 보일 게 없어 말풍선이 멈춘 듯
                      // 보인다 — 그 구간엔 loading 점 애니메이션을 띄운다(사용자 피드백).
                      loading={streaming && isLast && !m.text}
                      typing={streaming && isLast}
                      footer={footer}
                    />
                  )
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
            value={draft}
            onChange={(v) => setDraft(v)}
            placeholder={`${agent.name}에게 메시지…`}
            loading={streaming}
            onSubmit={(text) => {
              setDraft('')
              onSend(text)
            }}
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

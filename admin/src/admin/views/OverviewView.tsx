/* my-agents admin — Overview: at-a-glance counts + quick links. */
import { type CSSProperties, useEffect, useState } from 'react'
import { Tag, Button, Avatar, message } from 'antd'
import { Page, StatusPill, Panel } from '../shared'
import { Icon } from '../icons'
import { AGENT_STATUS, SESSION_STATUS } from '../mockData'
import { type Agent, type Session, type BlockCategory } from '../mockData'
import { listAgents, listSessions, getBlocks } from '../../api'

function StatTile({
  icon,
  color,
  label,
  value,
  onClick,
}: {
  icon: string
  color: string
  label: string
  value: number
  onClick?: () => void
}) {
  return (
    <button
      onClick={onClick}
      style={{
        flex: 1,
        textAlign: 'left',
        font: 'inherit',
        cursor: 'pointer',
        background: 'var(--color-bg-container)',
        border: '1px solid var(--color-border-secondary)',
        borderRadius: 'var(--radius-lg)',
        padding: 20,
        transition: 'box-shadow .2s, border-color .2s',
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.boxShadow = 'var(--box-shadow)'
        e.currentTarget.style.borderColor = 'transparent'
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.boxShadow = 'none'
        e.currentTarget.style.borderColor = 'var(--color-border-secondary)'
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <span style={{ color: 'var(--color-text-tertiary)', fontSize: 14 }}>{label}</span>
        <span
          style={{
            width: 36,
            height: 36,
            borderRadius: 9,
            background: color,
            color: '#fff',
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          <Icon name={icon} size={18} />
        </span>
      </div>
      <div style={{ fontSize: 30, fontWeight: 600, color: 'var(--color-text-heading)', marginTop: 10 }}>{value}</div>
    </button>
  )
}

export default function OverviewView({ onGo }: { onGo: (v: string) => void }) {
  const [agents, setAgents] = useState<Agent[]>([])
  const [sessions, setSessions] = useState<Session[]>([])
  const [blocks, setBlocks] = useState<Record<string, BlockCategory>>({})

  useEffect(() => {
    Promise.all([listAgents(), listSessions(), getBlocks()])
      .then(([a, s, b]) => {
        setAgents(a)
        setSessions(s)
        setBlocks(b)
      })
      .catch(() => message.error('개요 데이터를 불러오지 못했습니다'))
  }, [])

  const live = sessions.filter((s) => s.status === 'active' || s.status === 'running').length
  const blockCount = Object.values(blocks).reduce((a, b) => a + b.items.length, 0)
  const exposed = agents.filter((a) => a.exposed.a2a).length

  const headerRow: CSSProperties = {
    display: 'flex',
    alignItems: 'center',
    padding: '14px 18px',
    borderBottom: '1px solid var(--color-border-secondary)',
  }

  return (
    <Page title="개요" subtitle="에이전트 워크스페이스 한눈에 보기">
      <div style={{ display: 'flex', gap: 16, marginBottom: 24 }}>
        <StatTile icon="robot" color="var(--color-primary)" label="에이전트" value={agents.length} onClick={() => onGo('agents')} />
        <StatTile icon="appstore" color="var(--magenta-6)" label="빌딩 블록" value={blockCount} onClick={() => onGo('blocks')} />
        <StatTile icon="comment" color="var(--green-6)" label="라이브 세션" value={live} onClick={() => onGo('sessions')} />
        <StatTile icon="global" color="var(--cyan-7)" label="A2A 에이전트" value={exposed} onClick={() => onGo('agents')} />
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        <Panel style={{ padding: 0 }}>
          <div style={headerRow}>
            <span style={{ fontWeight: 600, flex: 1 }}>최근 에이전트</span>
            <Button type="link" size="small" onClick={() => onGo('agents')}>
              전체 보기
            </Button>
          </div>
          {agents.slice(0, 4).map((a: Agent) => {
            const st = AGENT_STATUS[a.status]
            const stColor = st?.color ?? 'var(--gray-6)'
            const stLabel = st?.label ?? a.status
            return (
              <div
                key={a.id}
                style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '11px 18px', borderTop: '1px solid var(--color-border-secondary)' }}
              >
                <Avatar size="small" style={{ background: 'var(--gray-12)' }}>
                  <Icon name="robot" size={13} />
                </Avatar>
                <div style={{ flex: 1 }}>
                  <div style={{ fontWeight: 500, fontSize: 14 }}>{a.name}</div>
                  <div style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>{a.persona}</div>
                </div>
                <StatusPill color={stColor} label={stLabel} />
              </div>
            )
          })}
        </Panel>

        <Panel style={{ padding: 0 }}>
          <div style={headerRow}>
            <span style={{ fontWeight: 600, flex: 1 }}>라이브 세션</span>
            <Button type="link" size="small" onClick={() => onGo('sessions')}>
              전체 보기
            </Button>
          </div>
          {sessions
            .filter((s) => s.status !== 'completed')
            .slice(0, 4)
            .map((s: Session) => {
              const st = SESSION_STATUS[s.status]
              const stColor = st?.color ?? 'var(--gray-6)'
              const stLabel = st?.label ?? s.status
              const stTag = st?.tag ?? 'default'
              return (
                <div
                  key={s.id}
                  style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '11px 18px', borderTop: '1px solid var(--color-border-secondary)' }}
                >
                  <span style={{ width: 8, height: 8, borderRadius: '50%', background: stColor, flex: 'none' }} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <code style={{ fontFamily: 'var(--font-family-code)', fontSize: 13 }}>{s.id}</code>
                    <div style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>
                      {s.agent} · {s.channel}
                    </div>
                  </div>
                  {stTag === 'default' ? <Tag>{stLabel}</Tag> : <Tag color={stTag}>{stLabel}</Tag>}
                </div>
              )
            })}
        </Panel>
      </div>
    </Page>
  )
}

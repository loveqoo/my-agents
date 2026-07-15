/* my-agents admin — Overview: at-a-glance counts + quick links. */
import { type CSSProperties, type ReactNode } from 'react'
import { Tag, Button, Avatar, Card, Statistic, Badge } from 'antd'
import { Page, StatusPill, Panel } from '../shared'
import { Icon } from '../icons'
import { AGENT_STATUS, SESSION_STATUS } from '../mockData'
import { type Agent, type Session, type BlockCategory } from '../mockData'
import { listAgents, listSessions, getBlocks } from '../../api'
import { useAsyncData } from '../../hooks'

// 목록 행(아바타+제목/설명+후행) — antd List.Item.Meta 대체(List는 v6 deprecated, 스펙 208).
// List.Item.Meta의 레이아웃(아바타 좌·제목/설명 스택·후행 우)을 Flex 프리미티브로 조립. 항목 간
// 구분선은 첫 행 제외 borderTop으로(List 기본 디바이더 동치).
function MetaRow({
  avatar,
  title,
  description,
  trailing,
  divider,
}: {
  avatar: ReactNode
  title: ReactNode
  description: ReactNode
  trailing: ReactNode
  divider: boolean
}) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 12,
        padding: '11px 18px',
        borderTop: divider ? '1px solid var(--color-split, rgba(5,5,5,0.06))' : undefined,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, minWidth: 0 }}>
        {avatar}
        <div style={{ minWidth: 0 }}>
          <div>{title}</div>
          <div style={{ marginTop: 2 }}>{description}</div>
        </div>
      </div>
      {trailing}
    </div>
  )
}

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
  // antd Card(hoverable)+Statistic으로 통일(스펙 204) — 수동 onMouseEnter/Leave hover 제거.
  return (
    <Card hoverable onClick={onClick} style={{ flex: 1, cursor: 'pointer' }} styles={{ body: { padding: 20 } }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <Statistic
          title={<span style={{ fontSize: 14 }}>{label}</span>}
          value={value}
          valueStyle={{ fontSize: 30, fontWeight: 600, color: 'var(--color-text-heading)' }}
        />
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
            flex: 'none',
          }}
        >
          <Icon name={icon} size={18} />
        </span>
      </div>
    </Card>
  )
}

export default function OverviewView({ onGo }: { onGo: (v: string) => void }) {
  // 라이브 세션 패널/카운트만 필요 → 서버 페이징(스펙 034)으로 live 버킷 상위 4건 + 전체 집계.
  const { data } = useAsyncData(
    () => Promise.all([listAgents(), listSessions({ status: 'live', limit: 4 }), getBlocks()]),
    [],
    { errorMsg: '개요 데이터를 불러오지 못했습니다' },
  )
  const [agents, sessionPage, blocks]: [Agent[], { items: Session[]; counts: Record<string, number> }, Record<string, BlockCategory>] =
    data ?? [[], { items: [], counts: {} }, {}]
  const sessions = sessionPage.items
  const live = sessionPage.counts.live ?? 0
  const blockCount = Object.values(blocks).reduce((a, b) => a + b.items.length, 0)
  // A2A 노출은 로컬(ui) 에이전트만 — source로 좁혀 정직(스펙 083 불변식: exposed.a2a ⟹ source=ui).
  const exposed = agents.filter((a) => a.source === 'ui' && a.exposed.a2a).length

  const headerRow: CSSProperties = {
    display: 'flex',
    alignItems: 'center',
    padding: '14px 18px',
    borderBottom: '1px solid var(--color-border-secondary)',
  }

  return (
    <Page title="개요" subtitle="에이전트 현황 한눈에 보기">
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 160px), 1fr))', gap: 16, marginBottom: 24 }}>
        <StatTile icon="robot" color="var(--color-primary)" label="에이전트" value={agents.length} onClick={() => onGo('agents')} />
        <StatTile icon="appstore" color="var(--magenta-6)" label="빌딩 블록" value={blockCount} onClick={() => onGo('blocks')} />
        <StatTile icon="comment" color="var(--green-6)" label="라이브 세션" value={live} onClick={() => onGo('sessions')} />
        <StatTile icon="global" color="var(--cyan-7)" label="A2A 에이전트" value={exposed} onClick={() => onGo('agents')} />
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 280px), 1fr))', gap: 16 }}>
        <Panel style={{ padding: 0 }}>
          <div style={headerRow}>
            <span style={{ fontWeight: 600, flex: 1 }}>최근 에이전트</span>
            <Button type="link" size="small" onClick={() => onGo('agents')}>
              전체 보기
            </Button>
          </div>
          {/* 행 스택 = Flex+MetaRow(List v6 deprecated, 스펙 208). */}
          {agents.slice(0, 4).map((a: Agent, i) => {
            const st = AGENT_STATUS[a.status]
            return (
              <MetaRow
                key={a.id}
                divider={i > 0}
                avatar={<Avatar size="small" style={{ background: 'var(--gray-12)' }}><Icon name="robot" size={13} /></Avatar>}
                title={<span style={{ fontWeight: 500, fontSize: 14 }}>{a.name}</span>}
                description={<span style={{ fontSize: 12 }}>{a.prompt}</span>}
                trailing={<StatusPill color={st?.color ?? 'var(--gray-6)'} label={st?.label ?? a.status} />}
              />
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
          {/* 행 스택 = Flex+MetaRow(상태 점은 Badge, 스펙 208). */}
          {sessions.filter((s) => s.status !== 'completed').slice(0, 4).map((s: Session, i) => {
            const st = SESSION_STATUS[s.status]
            const stTag = st?.tag ?? 'default'
            return (
              <MetaRow
                key={s.id}
                divider={i > 0}
                avatar={<Badge color={st?.color ?? 'var(--gray-6)'} />}
                title={<code style={{ fontFamily: 'var(--font-family-code)', fontSize: 13 }}>{s.id}</code>}
                description={<span style={{ fontSize: 12 }}>{s.agent} · {s.channel}</span>}
                trailing={stTag === 'default' ? <Tag>{st?.label ?? s.status}</Tag> : <Tag color={stTag}>{st?.label ?? s.status}</Tag>}
              />
            )
          })}
        </Panel>
      </div>
    </Page>
  )
}

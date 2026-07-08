/* 외부 A2A 에이전트 상세 — 풀페이지(스펙 246 후속, 소스별 상세 문법 통일).
   DetailPageShell + key/value bordered 표. 메타는 원격 A2A 카드가 소유(읽기 전용, 026). */
import { Tag, Button, Alert, Descriptions, Grid, Typography } from 'antd'
import { Icon } from '../../../icons'
import type { Agent } from '../../../mockData'
import { displayName } from '../../../naming'
import { DetailPageShell } from './DetailPageShell'

export function ExternalAgentDetailPage({
  agent,
  onBack,
  onDelete,
  onClone,
}: {
  agent: Agent
  onBack: () => void
  onDelete: (a: Agent) => void
  onClone: (a: Agent) => void
}) {
  const screens = Grid.useBreakpoint()
  const isMobile = !screens.md
  const card = agent.card
  const caps = Object.entries(card?.capabilities ?? {})
    .filter(([, v]) => v === true)
    .map(([k]) => k)
  const kv = { column: 1 as const, size: 'small' as const, bordered: true, layout: (isMobile ? 'vertical' : 'horizontal') as 'vertical' | 'horizontal', labelStyle: { width: 120 } }

  return (
    <DetailPageShell
      onBack={onBack}
      avatar={<Icon name="robot" />}
      name={displayName(agent)}
      agentId={agent.agentId}
      badges={
        <>
          <Tag color="purple" style={{ margin: 0 }}>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
              <Icon name="robot" size={11} /> 외부 A2A
            </span>
          </Tag>
          {card?.version ? <Tag style={{ margin: 0 }}>v{card.version}</Tag> : null}
        </>
      }
      actions={
        <>
          <Button icon={<Icon name="copy" />} onClick={() => onClone(agent)}>
            복제
          </Button>
          {agent.can_manage === false ? (
            <span style={{ color: 'var(--color-text-tertiary)', alignSelf: 'center' }}>다른 사용자 소유 — 관리 권한 없음</span>
          ) : (
            <Button danger icon={<Icon name="delete" />} onClick={() => onDelete(agent)}>
              등록 해제
            </Button>
          )}
        </>
      }
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
        <Alert
          type="info"
          showIcon
          title="A2A 카드로 등록한 외부 에이전트입니다. 구성은 원격 서비스가 소유하므로 콘솔에서는 읽기 전용입니다."
        />
        {card?.description ? (
          <div style={{ fontSize: 13, color: 'var(--color-text-secondary)' }}>{card.description}</div>
        ) : null}

        <div>
          <SectionTitle>A2A 카드</SectionTitle>
          <Descriptions
            {...kv}
            items={[
              {
                key: 'endpoint',
                label: 'Endpoint',
                children: (card?.url || agent.endpoint) ? (
                  <Typography.Text code copyable={{ text: card?.url || agent.endpoint || '', tooltips: ['복사', '복사됨'] }} ellipsis style={{ fontFamily: 'var(--font-family-code)', fontSize: 12, maxWidth: '100%' }}>
                    {card?.url || agent.endpoint}
                  </Typography.Text>
                ) : '—',
              },
              { key: 'provider', label: '제공자', children: card?.provider?.organization || '—' },
              ...(caps.length
                ? [{
                    key: 'caps',
                    label: '기능',
                    children: (
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                        {caps.map((c) => <Tag key={c} color="blue">{c}</Tag>)}
                      </div>
                    ),
                  }]
                : []),
              { key: 'registered', label: '등록일', children: agent.registeredAt || '—' },
            ]}
          />
        </div>

        {card?.skills?.length ? (
          <div>
            <SectionTitle>스킬 (skills)</SectionTitle>
            <div style={{ border: '1px solid var(--color-border-secondary)', borderRadius: 'var(--radius-lg)', overflow: 'hidden' }}>
              {card.skills.map((s, i) => (
                <div key={s.id ?? i} style={{ padding: '10px 14px', borderTop: i ? '1px solid var(--color-border-secondary)' : 'none' }}>
                  <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--color-text)' }}>{s.name ?? s.id}</div>
                  {s.description ? (
                    <div style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>{s.description}</div>
                  ) : null}
                  {s.tags?.length ? (
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 4 }}>
                      {s.tags.map((t) => <Tag key={t} color="cyan">{t}</Tag>)}
                    </div>
                  ) : null}
                </div>
              ))}
            </div>
          </div>
        ) : null}
      </div>
    </DetailPageShell>
  )
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--color-text-heading)', marginBottom: 10, paddingBottom: 6, borderBottom: '1px solid var(--color-border-secondary)' }}>
      {children}
    </div>
  )
}

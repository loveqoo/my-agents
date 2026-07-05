import { Tag, Button, Avatar, Alert, Descriptions } from 'antd'
import { Drawer } from '../../../shared'
import { Icon } from '../../../icons'
import type { Agent } from '../../../mockData'
import { displayName } from '../../../naming'
import { IdRow } from '../primitives'

/* ---- External A2A agent detail (read-only; meta owned by the remote A2A card, 026) ---- */
export function ExternalAgentDetail({
  agent,
  onClose,
  onDelete,
  onClone,
}: {
  agent: Agent
  onClose: () => void
  onDelete: (a: Agent) => void
  onClone: (a: Agent) => void
}) {
  const card = agent.card
  const caps = Object.entries(card?.capabilities ?? {})
    .filter(([, v]) => v === true)
    .map(([k]) => k)
  return (
    <Drawer
      open={!!agent}
      title={displayName(agent)}
      width={480}
      onClose={onClose}
      footer={
        // 복제(스펙 120)는 관리 권한 불요 — 외부 A2A 에이전트의 행위 설정도 내 ui 초안으로 복사 가능.
        <>
          <Button icon={<Icon name="copy" />} onClick={() => onClone(agent)}>
            복제
          </Button>
          {agent.can_manage === false ? (
            <span style={{ color: 'var(--color-text-tertiary)', marginLeft: 8 }}>다른 사용자 소유 — 관리 권한 없음</span>
          ) : (
            <Button danger icon={<Icon name="delete" />} onClick={() => onDelete(agent)}>
              등록 해제
            </Button>
          )}
        </>
      }
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
        <Avatar size="large" style={{ background: 'var(--purple-1)', color: 'var(--purple-7)' }}>
          <Icon name="robot" />
        </Avatar>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 16, fontWeight: 600, display: 'flex', alignItems: 'center', gap: 8 }}>
            {displayName(agent)}
            <Tag color="purple">
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                <Icon name="robot" size={11} />
                외부 A2A
              </span>
            </Tag>
            {card?.version ? <Tag>v{card.version}</Tag> : null}
          </div>
          <code style={{ fontSize: 11, color: 'var(--color-text-tertiary)', fontFamily: 'var(--font-family-code)' }}>
            {agent.agentId}
          </code>
        </div>
      </div>

      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 14 }}
        message="A2A 카드로 등록한 외부 에이전트입니다. 구성은 원격 서비스가 소유하므로 콘솔에서는 읽기 전용입니다. 실제 호출 기능은 준비 중 — 지금은 등록 정보 확인만 가능합니다."
      />

      {card?.description ? (
        <div style={{ fontSize: 13, color: 'var(--color-text-secondary)', marginBottom: 14 }}>{card.description}</div>
      ) : null}

      <div
        style={{
          padding: 14,
          border: '1px solid var(--purple-3)',
          background: 'var(--purple-1)',
          borderRadius: 'var(--radius-lg)',
        }}
      >
        <div
          style={{
            fontSize: 12,
            color: 'var(--color-text-tertiary)',
            marginBottom: 8,
            display: 'flex',
            alignItems: 'center',
            gap: 6,
          }}
        >
          <Icon name="global" size={12} style={{ color: 'var(--purple-7)' }} />
          A2A 카드
        </div>
        <IdRow label="Endpoint" value={card?.url || agent.endpoint || '—'} />
        <Descriptions
          column={1}
          size="small"
          items={[
            { key: 'provider', label: '제공자', children: card?.provider?.organization || '—' },
            ...(caps.length
              ? [
                  {
                    key: 'caps',
                    label: '기능',
                    children: (
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                        {caps.map((c) => (
                          <Tag key={c} color="blue">{c}</Tag>
                        ))}
                      </div>
                    ),
                  },
                ]
              : []),
            { key: 'registered', label: '등록일', children: agent.registeredAt || '—' },
          ]}
        />
      </div>

      {card?.skills?.length ? (
        <div style={{ marginTop: 16 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--color-text-heading)', marginBottom: 10 }}>
            스킬 (skills)
          </div>
          <div
            style={{
              border: '1px solid var(--color-border-secondary)',
              borderRadius: 'var(--radius-lg)',
              overflow: 'hidden',
            }}
          >
            {card.skills.map((s, i) => (
              <div
                key={s.id ?? i}
                style={{
                  padding: '10px 14px',
                  borderTop: i ? '1px solid var(--color-border-secondary)' : 'none',
                }}
              >
                <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--color-text)' }}>{s.name ?? s.id}</div>
                {s.description ? (
                  <div style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>{s.description}</div>
                ) : null}
                {s.tags?.length ? (
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 4 }}>
                    {s.tags.map((t) => (
                      <Tag key={t} color="cyan">{t}</Tag>
                    ))}
                  </div>
                ) : null}
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </Drawer>
  )
}

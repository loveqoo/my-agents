import { Tag, Button, Avatar, Alert, Modal, Descriptions } from 'antd'
import { Drawer, ExposeSwitch } from '../../../shared'
import { Icon } from '../../../icons'
import type { Agent } from '../../../mockData'
import { displayName } from '../../../naming'
import { IdRow } from '../primitives'
import { PersonaStaleNote } from '../PersonaStaleNote'

/* ---- 읽기 전용 구성 행(코드 에이전트 상세에서 사용) ---- */
export function ReadonlyConfig({ agent, onRefreshPersona }: { agent: Agent; onRefreshPersona: (a: Agent) => Promise<void> }) {
  return (
    <>
      <Descriptions
        column={1}
        size="small"
        items={[
          {
            key: 'model',
            label: '모델',
            children: <span style={{ fontFamily: 'var(--font-family-code)' }}>{agent.model}</span>,
          },
          { key: 'persona', label: '페르소나', children: agent.persona },
        ]}
      />
      <PersonaStaleNote agent={agent} onRefresh={onRefreshPersona} />
      <Descriptions
        column={1}
        size="small"
        items={[
          {
            key: 'memories',
            label: '메모리',
            children: (agent.memories || []).length ? (
              <span style={{ display: 'inline-flex', flexWrap: 'wrap', gap: 6 }}>
                {agent.memories.map((m) => (
                  <Tag key={m} color="purple">
                    {m}
                  </Tag>
                ))}
              </span>
            ) : (
              <span style={{ color: 'var(--color-text-tertiary)' }}>메모리 없음</span>
            ),
          },
          {
            key: 'history',
            label: '채팅 히스토리',
            children: agent.historyDepth ? `최근 ${agent.historyDepth}개 메시지` : '기억 안 함',
          },
          {
            key: 'mcps',
            label: 'MCP',
            children: (
              <span style={{ display: 'inline-flex', flexWrap: 'wrap', gap: 6 }}>
                {(agent.mcps || []).map((m) => (
                  <Tag key={m} color="cyan">
                    {m}
                  </Tag>
                ))}
              </span>
            ),
          },
          { key: 'sessions', label: '세션', children: <>활성 {agent.sessions}개</> },
        ]}
      />
    </>
  )
}

/* ---- Code-defined agent detail (read-only; config owned by the deployed code) ---- */
export function CodeAgentDetail({
  agent,
  onClose,
  onDelete,
  onClone,
  onResync,
  onToggleExpose,
  onSetVisibility,
  onRefreshPersona,
}: {
  agent: Agent
  onClose: () => void
  onDelete: (a: Agent) => void
  onClone: (a: Agent) => void
  onResync: (a: Agent) => void
  onToggleExpose: (a: Agent) => void
  onSetVisibility: (a: Agent, pub: boolean) => void
  onRefreshPersona: (a: Agent) => Promise<void>
}) {
  return (
    <Drawer
      open={!!agent}
      title={displayName(agent)}
      width={480}
      onClose={onClose}
      footer={
        // 복제(스펙 120)는 관리 권한 불요 — 원격 에이전트도 행위 설정을 내 ui 초안으로 복사 가능.
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
        <Avatar size="large" style={{ background: 'var(--geekblue-1)', color: 'var(--geekblue-7)' }}>
          <Icon name="code" />
        </Avatar>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 16, fontWeight: 600, display: 'flex', alignItems: 'center', gap: 8 }}>
            {displayName(agent)}
            <Tag color="geekblue">
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                <Icon name="code" size={11} />
                Code
              </span>
            </Tag>
          </div>
          <code style={{ fontSize: 11, color: 'var(--color-text-tertiary)', fontFamily: 'var(--font-family-code)' }}>
            {agent.agentId}
          </code>
        </div>
        <Tag color="green">
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
            서빙 중 <code style={{ fontFamily: 'var(--font-family-code)' }}>{agent.commit || agent.activeVersion}</code>
          </span>
        </Tag>
      </div>

      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 14 }}
        message="SDK로 코드 정의해 원격 엔드포인트에서 실행되는 에이전트입니다. 구성은 코드가 소유하므로 콘솔에서는 읽기 전용입니다 — 변경하려면 코드를 수정해 다시 배포한 뒤 동기화하세요."
      />

      <ReadonlyConfig agent={agent} onRefreshPersona={onRefreshPersona} />

      <div
        style={{
          marginTop: 16,
          padding: 14,
          border: '1px solid var(--geekblue-3)',
          background: 'var(--geekblue-1)',
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
          <Icon name="code" size={12} style={{ color: 'var(--geekblue-7)' }} />
          배포 / 연결
        </div>
        <IdRow label="Endpoint" value={agent.endpoint || '—'} />
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 0' }}>
          <span style={{ width: 84, flex: 'none', fontSize: 12, color: 'var(--color-text-tertiary)' }}>
            Access token
          </span>
          <code
            style={{
              flex: 1,
              minWidth: 0,
              fontFamily: 'var(--font-family-code)',
              fontSize: 12,
              color: 'var(--color-text)',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {agent.token || '—'}
          </code>
          <Icon name="key" size={13} style={{ color: 'var(--color-text-tertiary)', flex: 'none' }} />
        </div>
        <div style={{ fontSize: 11, color: 'var(--color-text-tertiary)', margin: '2px 0 8px 84px' }}>
          마스킹 표시 · 콘솔에 평문 저장 안 함
        </div>
        <Descriptions
          column={1}
          size="small"
          items={[
            {
              key: 'runtime',
              label: '런타임',
              children: <span style={{ fontFamily: 'var(--font-family-code)', fontSize: 13 }}>{agent.runtime || '—'}</span>,
            },
            {
              key: 'source',
              label: '소스',
              children: (
                <code style={{ fontFamily: 'var(--font-family-code)', fontSize: 13 }}>
                  {agent.repo}
                  {agent.commit ? '@' + agent.commit : ''}
                </code>
              ),
            },
            { key: 'registered', label: '등록일', children: agent.registeredAt || '—' },
          ]}
        />
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 12 }}>
          <span style={{ flex: 1, fontSize: 12, color: 'var(--color-text-tertiary)' }}>
            마지막 동기화 · {agent.lastSync || '—'}
          </span>
          <Button size="small" icon={<Icon name="sync" />} onClick={() => onResync(agent)}>
            재동기화
          </Button>
        </div>
      </div>

      <div style={{ marginTop: 18 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--color-text-heading)', marginBottom: 10 }}>
          배포 히스토리
        </div>
        <div
          style={{
            border: '1px solid var(--color-border-secondary)',
            borderRadius: 'var(--radius-lg)',
            overflow: 'hidden',
          }}
        >
          {(agent.versions || []).map((v, i) => (
            <div
              key={v.version}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 10,
                padding: '10px 14px',
                borderTop: i ? '1px solid var(--color-border-secondary)' : 'none',
                background: v.status === 'active' ? 'var(--color-success-bg)' : 'transparent',
              }}
            >
              <code
                style={{
                  fontFamily: 'var(--font-family-code)',
                  fontSize: 13,
                  fontWeight: 600,
                  color: 'var(--color-text-heading)',
                  width: 64,
                }}
              >
                {v.version}
              </code>
              {v.status === 'active' ? <Tag color="green">서빙 중</Tag> : <Tag>이전 배포</Tag>}
              <div style={{ flex: 1, minWidth: 0 }}>
                <div
                  style={{
                    fontSize: 13,
                    color: 'var(--color-text)',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {v.note}
                </div>
                <div style={{ fontSize: 11, color: 'var(--color-text-tertiary)' }}>{v.createdAt}</div>
              </div>
            </div>
          ))}
        </div>
        <div style={{ fontSize: 11, color: 'var(--color-text-tertiary)', marginTop: 8 }}>
          배포는 코드 푸시로 생성됩니다 — 콘솔에서 새 버전을 만들거나 활성화하지 않습니다.
        </div>
      </div>

      {/* 공개 범위 + A2A 중계 공개(스펙 154) — 직접 코딩(SDK 배포) 에이전트도 우리 A2A 주소로 공개.
          private는 A2A 불가(147)라 공개 전환이 선행 조건. 호출은 서버가 1홉 중계한다. */}
      {agent.can_manage !== false ? (
        <div
          style={{
            marginTop: 18, padding: '12px 14px', display: 'flex', alignItems: 'center', gap: 10,
            border: '1px solid var(--color-border-secondary)', borderRadius: 'var(--radius-lg)',
            background: 'var(--gray-2)',
          }}
        >
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 14, fontWeight: 500, color: 'var(--color-text-heading)' }}>공개 범위</div>
            <div style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>
              {agent.owner_id == null ? 'public · 모두 사용 가능(A2A 켜기 가능)' : 'private · 소유자만 사용(A2A 불가)'}
            </div>
          </div>
          <Button
            size="small"
            onClick={() =>
              Modal.confirm({
                title: agent.owner_id == null ? '비공개(private)로 전환할까요?' : '공개(public)로 전환할까요?',
                content:
                  agent.owner_id == null
                    ? 'private가 되면 소유자만 사용할 수 있고, 켜져 있던 A2A 공개는 자동으로 꺼집니다.'
                    : 'public이 되면 모든 사용자가 사용할 수 있고 A2A 공개(서버가 1홉 중계)도 켤 수 있습니다.',
                okText: '전환',
                cancelText: '취소',
                onOk: () => onSetVisibility(agent, agent.owner_id != null),
              })
            }
          >
            {agent.owner_id == null ? '비공개로 전환' : '공개로 전환'}
          </Button>
        </div>
      ) : null}
      <div style={{ marginTop: 10 }}>
        <ExposeSwitch
          on={!!agent.exposed.a2a}
          onChange={() => onToggleExpose(agent)}
          label="A2A로 공개 (중계)"
          onText="켬 · 우리 A2A 주소로 호출을 중계"
          offText="꺼짐 · 노출되지 않음"
        />
      </div>
    </Drawer>
  )
}
